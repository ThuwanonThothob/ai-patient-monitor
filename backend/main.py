import json
import os
import math
from pathlib import Path
import sqlite3
import asyncio
import time
from datetime import datetime, timezone
from io import BytesIO
import paho.mqtt.client as mqtt
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, StreamingResponse
from typing import List, Literal
from contextlib import asynccontextmanager, closing
#เชื่อมai
from ai_models.risk_score import calculate_risk_assessment, get_model_benchmarks, get_model_status
from ai_models.llm_summary import chat_with_patient_data, summarize_dashboard_section
from ai_models.agent_workflow import VitalEvent
from ai_models.nurse_agent import (
    NurseAgent,
    agent_status as nurse_agent_status,
    init_nurse_agent_db,
    link_alert as link_nurse_alert,
    list_runs as list_nurse_runs,
)
from ai_models.workflow_evaluation import run_alert_workflow_evaluation
from reporting import (
    create_patient_handoff_docx,
    create_report_docx,
    format_dashboard_text,
)
from patient_registry import PATIENT_PROFILES, PATIENT_LOGIN_PROFILES, TEST_PATIENT_PROFILES, ZONE_LABELS, get_patient_profile
from pydantic import BaseModel, Field

import auth
import notifications
import care_api
import care_plan
import care_profiles
import daily_summary
import alert_episodes
import care_messages
import care_chat
import assistant_api
import patient_views
import bedside_monitor
import agent_scenarios
from test_simulation import TestPatientSimulator, seed_test_care
from evidence_api import router as evidence_router
from posture_api import router as posture_router
from research_api import router as research_router
from evidence_handoff import format_evidence_handoff
from ai_models import monitor_model
from monitor_service import MonitorWorker, init_monitor_db, patient_state, worker_status

DB_NAME = str(auth.DB)
INGEST_MODE = os.getenv("WARD_INGEST_MODE", "replay")
if INGEST_MODE not in {"replay", "mqtt", "off"}:
    raise ValueError("WARD_INGEST_MODE must be replay, mqtt, or off")
monitor_worker = MonitorWorker(DB_NAME, PATIENT_PROFILES, INGEST_MODE)
telemetry_queue = None
bedside_queue = None
bedside_service = None
nurse_agent = None
agent_last_enqueue: dict[str, tuple[float, str, float | None]] = {}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vital_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            heart_rate INTEGER,
            spo2 INTEGER,
            status TEXT,
            timestamp REAL,
            respiratory_rate INTEGER,
            blood_glucose REAL,
            ecg_rhythm TEXT,
            sleep_hours REAL,
            simulation_state TEXT
        )
    """)
    # Existing demonstration databases have the original six columns. Keep them
    # usable by adding the new telemetry fields without deleting any history.
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(vital_logs)")}
    for name, definition in (
        ("respiratory_rate", "INTEGER"),
        ("blood_glucose", "REAL"),
        ("ecg_rhythm", "TEXT"),
        ("sleep_hours", "REAL"),
        ("simulation_state", "TEXT"),
        ("source_record", "TEXT"),
        ("source_segment", "TEXT"),
    ):
        if name not in existing_columns:
            cursor.execute(f"ALTER TABLE vital_logs ADD COLUMN {name} {definition}")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS care_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            request_type TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            requested_at REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            recommended_next_step TEXT NOT NULL,
            heart_rate INTEGER,
            spo2 INTEGER,
            risk_percent REAL,
            status TEXT NOT NULL DEFAULT 'NEW',
            assigned_to TEXT,
            created_at REAL NOT NULL,
            acknowledged_at REAL,
            resolved_at REAL,
            resolution_note TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            patient_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            detail TEXT,
            created_at REAL NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_alerts_patient_created ON agent_alerts(patient_id, created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_alerts_status ON agent_alerts(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_audit_patient_created ON agent_audit_logs(patient_id, created_at DESC)")
    conn.commit()
    conn.close()
    alert_episodes.init(DB_NAME)
    init_monitor_db(DB_NAME)
    auth.init_sessions()
    notifications.init_notifications()
    care_api.init_care()
    care_plan.init_task_history()
    care_profiles.init_profiles()
    daily_summary.init_daily()
    init_nurse_agent_db(DB_NAME)
    care_messages.init()
    care_chat.init()
    auth.ensure_test_accounts()
    if auth.test_accounts_enabled():
        seed_test_care(DB_NAME)
    agent_scenarios.init_scenarios()
    try:
        import patient_api
        if hasattr(patient_api, 'reset_rate_limits'):
            patient_api.reset_rate_limits()
    except Exception:
        pass

def save_to_db(patient_id: str, hr: int, spo2: int, status: str, ts: float, clinical: dict | None = None):
    clinical = clinical or {}
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO vital_logs
        (patient_id, heart_rate, spo2, status, timestamp, respiratory_rate,
         blood_glucose, ecg_rhythm, sleep_hours, simulation_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            patient_id, hr, spo2, status, ts,
            clinical.get("respiratory_rate"), clinical.get("blood_glucose"),
            clinical.get("ecg_rhythm"), clinical.get("sleep_hours"),
            clinical.get("simulation_state"),
        )
    )
    conn.commit()
    conn.close()


def get_recent_vital_history(patient_id: str, limit: int = 50) -> list[dict]:
    """Return ordered telemetry for a feature builder, never a future outcome."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT heart_rate, spo2, timestamp, respiratory_rate, blood_glucose
           FROM vital_logs WHERE patient_id = ? ORDER BY timestamp DESC LIMIT ?""",
        (patient_id, max(1, min(limit, 200))),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{
        "heart_rate": row[0], "spo2": row[1], "timestamp": row[2],
        "respiratory_rate": row[3], "blood_glucose": row[4],
    } for row in reversed(rows)]


WORKFLOW_STATUSES = {"NEW", "ACKNOWLEDGED", "ESCALATED", "RESOLVED"}
OPEN_WORKFLOW_STATUSES = {"NEW", "ACKNOWLEDGED", "ESCALATED"}
WORKFLOW_TRANSITIONS = {
    "NEW": {"ACKNOWLEDGED", "ESCALATED"},
    "ACKNOWLEDGED": {"ESCALATED", "RESOLVED"},
    "ESCALATED": {"RESOLVED"},
    "RESOLVED": set(),
}


def record_audit_event(
    patient_id: str,
    action: str,
    actor: str,
    detail: str,
    *,
    alert_id: int | None = None,
    created_at: float | None = None,
) -> None:
    """Append an immutable, local audit record for the synthetic workflow."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO agent_audit_logs (alert_id, patient_id, action, actor, detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (alert_id, patient_id, action, actor, detail, created_at or time.time()),
    )
    conn.commit()
    conn.close()


def persist_agent_alert(alert: dict) -> dict:
    """Persist an agent proposal before broadcasting it to connected dashboards."""
    vitals = alert.get("vitals", {})
    created_at = float(alert["timestamp"])
    conn = sqlite3.connect(DB_NAME, timeout=15)
    try:
        conn.execute('BEGIN IMMEDIATE')
        cursor = conn.cursor()
        episode_key = alert.get('episode_key') or alert_episodes.kind(alert['reason'])
        existing = cursor.execute("""SELECT id,status FROM agent_alerts WHERE patient_id=? AND episode_key=?
            AND merged_into IS NULL AND status IN ('NEW','ACKNOWLEDGED','ESCALATED')""", (alert['patient_id'], episode_key)).fetchone()
        if existing:
            return {**alert, 'alert_id': existing[0], 'workflow_status': existing[1]}
        cursor.execute(
            """INSERT INTO agent_alerts
            (patient_id, severity, reason, recommended_next_step, heart_rate, spo2,
             risk_percent, status, created_at, episode_key, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', ?, ?, ?)""",
            (
                alert["patient_id"], alert["severity"], alert["reason"],
                alert["recommended_next_step"], vitals.get("heart_rate"),
                vitals.get("spo2"), alert.get("risk_percent"), created_at, episode_key, created_at,
            ),
        )
        alert_id = cursor.lastrowid
        notifications.enqueue_alert(conn, alert_id, alert["patient_id"], alert["severity"], created_at)
        cursor.execute(
            """INSERT INTO agent_audit_logs (alert_id, patient_id, action, actor, detail, created_at)
               VALUES (?, ?, 'ALERT_CREATED', 'VitalAlertAgent', ?, ?)""",
            (alert_id, alert["patient_id"], alert["reason"], created_at),
        )
        conn.commit()
        return {**alert, "alert_id": alert_id, "workflow_status": "NEW"}
    finally:
        conn.close()



def serialize_alert(row: tuple) -> dict:
    (
        alert_id, patient_id, severity, reason, recommended_next_step,
        heart_rate, spo2, risk_percent, status, assigned_to, created_at,
        acknowledged_at, resolved_at, resolution_note,
    ) = row
    profile = get_patient_profile(patient_id) or {}
    return {
        "id": alert_id,
        "patient_id": patient_id,
        "zone": profile.get("zone", "-"),
        "room_number": profile.get("room_number", "-"),
        "condition": profile.get("condition", "-"),
        "mobility": profile.get("mobility", "-"),
        "severity": severity,
        "reason": reason,
        "recommended_next_step": recommended_next_step,
        "vitals": {"heart_rate": heart_rate, "spo2": spo2},
        "risk_percent": risk_percent,
        "status": status,
        "assigned_to": assigned_to,
        "created_at": created_at,
        "acknowledged_at": acknowledged_at,
        "resolved_at": resolved_at,
        "resolution_note": resolution_note,
    }


def get_workflow_alerts(status: str = "open", zone: str | None = None, limit: int = 100, offset: int = 0, patient_id: str | None = None) -> list[dict]:
    limit = min(max(limit, 1), 200)
    normalized_status = status.upper()
    if normalized_status == "OPEN":
        statuses = tuple(OPEN_WORKFLOW_STATUSES)
    elif normalized_status in WORKFLOW_STATUSES:
        statuses = (normalized_status,)
    elif normalized_status == "ALL":
        statuses = tuple(WORKFLOW_STATUSES)
    else:
        raise HTTPException(status_code=400, detail="Unknown alert workflow status")
    placeholders = ", ".join("?" for _ in statuses)
    normalized_zone = (zone or "").strip().upper()
    if normalized_zone and normalized_zone not in ZONE_LABELS:
        raise HTTPException(400, 'Zone must be A, B, or C')
    filters, params = '', []
    scope_clause, scope_values = auth.scoped_sql()
    filters += ' AND ' + scope_clause
    params.extend(scope_values)
    if normalized_zone:
        filters += ' AND patient_id LIKE ?'
        params.append(normalized_zone + '%')
    if patient_id:
        filters += ' AND patient_id=?'
        params.append(patient_id.upper())
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        f"""SELECT id, patient_id, severity, reason, recommended_next_step,
                   heart_rate, spo2, risk_percent, status, assigned_to, created_at,
                   acknowledged_at, resolved_at, resolution_note
            FROM agent_alerts WHERE status IN ({placeholders}) AND merged_into IS NULL {filters}
            ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, created_at DESC
            LIMIT ? OFFSET ?""",
        (*statuses, *params, limit, max(0, offset)),
    )
    alerts = [serialize_alert(row) for row in cursor.fetchall()]
    for alert in alerts:
        alert.update(alert_episodes.metadata(conn, alert['id']))
    conn.close()
    normalized_zone = (zone or "").strip().upper()
    if normalized_zone:
        if normalized_zone not in ZONE_LABELS:
            raise HTTPException(status_code=400, detail="Zone must be A, B, or C")
        alerts = [alert for alert in alerts if alert["zone"] == normalized_zone]
    return alerts


def get_patient_timeline(patient_id: str, limit: int = 80) -> list[dict]:
    """Combine monitoring, agent workflow and coordination history by time."""
    limit = min(max(limit, 1), 150)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT heart_rate, spo2, status, timestamp, respiratory_rate, blood_glucose, ecg_rhythm
           FROM vital_logs WHERE patient_id = ? ORDER BY id DESC LIMIT ?""",
        (patient_id, min(limit, 40)),
    )
    events = [{
        "type": "vital_reading",
        "timestamp": row[3],
        "title": f"Vital reading — {row[2]}",
        "detail": f"HR {row[0]} bpm · SpO2 {row[1]}% · RR {row[4] if row[4] is not None else '—'} /min · Glucose {row[5] if row[5] is not None else '—'} mg/dL",
        "severity": row[2].lower(),
        "ecg_rhythm": row[6],
    } for row in cursor.fetchall()]
    cursor.execute(
        """SELECT id, severity, reason, status, created_at, resolution_note
           FROM agent_alerts WHERE patient_id = ? ORDER BY created_at DESC LIMIT ?""",
        (patient_id, min(limit, 40)),
    )
    events.extend({
        "type": "agent_alert",
        "timestamp": row[4],
        "title": f"Agent alert #{row[0]} — {row[1].upper()} / {row[3]}",
        "detail": row[2] + (f" Resolution: {row[5]}" if row[5] else ""),
        "severity": row[1],
        "alert_id": row[0],
    } for row in cursor.fetchall())
    cursor.execute(
        """SELECT request_type, status, note, requested_at
           FROM care_requests WHERE patient_id = ? ORDER BY requested_at DESC LIMIT ?""",
        (patient_id, min(limit, 20)),
    )
    events.extend({
        "type": "care_request",
        "timestamp": row[3],
        "title": f"Coordination request — {row[0]} / {row[1]}",
        "detail": row[2] or "Created for human review; no external contact was sent.",
        "severity": "warning" if row[0] == "doctor" else "critical",
    } for row in cursor.fetchall())
    cursor.execute(
        """SELECT alert_id, action, actor, detail, created_at
           FROM agent_audit_logs WHERE patient_id = ? ORDER BY created_at DESC LIMIT ?""",
        (patient_id, min(limit, 40)),
    )
    events.extend({
        "type": "audit",
        "timestamp": row[4],
        "title": f"{row[1]} — {row[2]}",
        "detail": row[3] or "No additional detail",
        "severity": "info",
        "alert_id": row[0],
    } for row in cursor.fetchall())
    conn.close()
    return sorted(events, key=lambda event: event["timestamp"], reverse=True)[:limit]


def get_triage_snapshot(zone: str | None = None, mobility: str | None = None, priority: str = "all") -> list[dict]:
    """Build an actionable, synthetic nursing triage board from latest readings."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT patient_id,payload FROM monitor_results')
    latest_by_patient = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
    cursor.execute("""
        SELECT patient_id,
               SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END),
               COUNT(*)
        FROM agent_alerts
        WHERE status IN ('NEW', 'ACKNOWLEDGED', 'ESCALATED') AND merged_into IS NULL
        GROUP BY patient_id
    """)
    open_alerts = {row[0]: {"critical": row[1], "total": row[2]} for row in cursor.fetchall()}
    conn.close()
    items = []
    for profile in auth.visible_registry(PATIENT_PROFILES).values():
        latest = latest_by_patient.get(profile["patient_id"])
        alert_counts = open_alerts.get(profile["patient_id"], {"critical": 0, "total": 0})
        latest = latest or {}
        fresh = -2 <= time.time() - latest.get('timestamp', 0) <= 15 and latest.get('status') not in {'STALE_DATA','WAITING','INVALID_DATA'}
        monitor_status = latest.get('status', 'WAITING') if fresh else 'STALE_DATA'
        if alert_counts["critical"] or monitor_status == "CRITICAL":
            triage_level, rank = "CRITICAL", 0
        elif alert_counts["total"] or monitor_status == "WARNING" or not fresh:
            triage_level, rank = "ATTENTION", 1
        else:
            triage_level, rank = "ROUTINE", 2
        item = {
            "patient_id": profile["patient_id"],
            "zone": profile["zone"],
            "room_number": profile["room_number"],
            "condition": profile["condition"],
            "mobility": profile["mobility"],
            "triage_level": triage_level,
            "monitor_status": monitor_status,
            "open_alerts": alert_counts["total"],
            "priority_reason": 'มีเหตุการณ์เร่งด่วนที่ยังไม่ปิด' if alert_counts['critical'] else 'ค่าวัดล่าสุดเข้าเกณฑ์เร่งด่วน' if monitor_status == 'CRITICAL' else 'ไม่มีข้อมูลใหม่ กรุณาตรวจการเชื่อมต่อ' if not fresh else 'มีงานค้างที่ต้องติดตาม' if alert_counts['total'] else 'ค่าวัดล่าสุดเข้าเกณฑ์เฝ้าระวัง' if monitor_status == 'WARNING' else 'ติดตามตามแผนดูแล',
            "latest": {
                "heart_rate": latest.get('heart_rate') if fresh else None,
                "spo2": latest.get('spo2') if fresh else None,
                "timestamp": latest.get('timestamp'),
                "status": monitor_status,
                "respiratory_rate": latest.get('respiratory_rate') if fresh else None,
            },
            "_rank": rank,
        }
        items.append(item)
    normalized_zone = (zone or "").strip().upper()
    normalized_mobility = (mobility or "").strip().lower()
    normalized_priority = priority.strip().upper()
    if normalized_zone:
        if normalized_zone not in ZONE_LABELS:
            raise HTTPException(status_code=400, detail="Zone must be A, B, or C")
        items = [item for item in items if item["zone"] == normalized_zone]
    if normalized_mobility == "bedbound":
        items = [item for item in items if item["mobility"] == "Bedbound"]
    if normalized_priority in {"CRITICAL", "ATTENTION", "ROUTINE"}:
        items = [item for item in items if item["triage_level"] == normalized_priority]
    elif normalized_priority != "ALL":
        raise HTTPException(status_code=400, detail="Unknown triage priority")
    for item in items:
        item.pop("_rank")
    return sorted(items, key=lambda item: (
        {"CRITICAL": 0, "ATTENTION": 1, "ROUTINE": 2}[item["triage_level"]],
        -item["open_alerts"],
        item["patient_id"],
    ))


def get_dashboard_snapshot() -> dict:
    """Return database-backed figures used by all dashboard sections."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # The simulation can be resized. Only count beds in the current registry so
    # historical rows from a previous configuration do not inflate the view.
    registry = auth.visible_registry(PATIENT_PROFILES)
    registered_ids = tuple(registry)
    placeholders = ", ".join("?" for _ in registered_ids)
    active_beds_clause = f"patient_id IN ({placeholders})"
    cursor.execute(f"SELECT COUNT(*) FROM vital_logs WHERE {active_beds_clause}", registered_ids)
    reading_count = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM vital_logs WHERE {active_beds_clause} AND status = 'CRITICAL'", registered_ids)
    critical_count = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM vital_logs WHERE {active_beds_clause} AND status = 'WARNING'", registered_ids)
    warning_count = cursor.fetchone()[0]
    cursor.execute(f"""
        SELECT patient_id, ROUND(AVG(heart_rate), 1), MIN(spo2),
               SUM(CASE WHEN status = 'CRITICAL' THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 'WARNING' THEN 1 ELSE 0 END), MAX(timestamp)
        FROM vital_logs WHERE {active_beds_clause}
        GROUP BY patient_id ORDER BY MAX(timestamp) DESC
    """, registered_ids)
    rows = cursor.fetchall()
    conn.close()
    patients = []
    for patient_id, avg_hr, min_spo2, critical, warning, last_timestamp in rows:
        profile = get_patient_profile(patient_id)
        if profile is None:
            continue
        patients.append({
            "patient_id": patient_id,
            "name": profile["name"],
            "zone": profile["zone"],
            "room_number": profile["room_number"],
            "avg_hr": avg_hr,
            "min_spo2": min_spo2,
            "critical_count": critical or 0,
            "warning_count": warning or 0,
            "last_timestamp": last_timestamp,
        })
    zone_snapshot = []
    for zone, label in ZONE_LABELS.items():
        zone_patients = [patient for patient in patients if patient["zone"] == zone]
        zone_snapshot.append({
            "zone": zone,
            "label": label,
            "registered_patients": sum(1 for profile in registry.values() if profile["zone"] == zone),
            "patients_with_readings": len(zone_patients),
            "critical_count": sum(patient["critical_count"] for patient in zone_patients),
            "warning_count": sum(patient["warning_count"] for patient in zone_patients),
        })
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "reading_count": reading_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "patient_count": len(patients),
        "registered_patient_count": len(registry),
        "zones": zone_snapshot,
        "patients": patients,
    }

#ไว้ลบข้อมูลเก่า
def cleanup_old_logs(days_to_keep=1):
    try:
        cutoff_timestamp = time.time() - (days_to_keep * 24 * 60 * 60)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vital_logs WHERE timestamp < ?", (cutoff_timestamp,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted_count > 0:
            print(f"deleted {deleted_count} old log entries older than {days_to_keep} days.")
    except Exception as e:
        print(f"Error cleaning up old logs: {e}")


#  2. สมอง AI วิเคราะห์และประเมินอาการเชิงลึก (AI Clinical Intelligence)
def generate_ai_assessment(patient_id: str, history_rows: list):
    profile = get_patient_profile(patient_id) or {"name": "ไม่ทราบ", "age": 0, "condition": "ไม่ระบุ"}
    
    if not history_rows:
        return {"risk_score": None, "summary": "ยังไม่มีข้อมูลเพียงพอในการวิเคราะห์", "recommendations": ["รอการรวบรวมข้อมูลสัญญาณชีพ"]}

    hrs = [r[0] for r in history_rows]
    spo2s = [r[1] for r in history_rows]

    avg_hr = round(sum(hrs) / len(hrs), 1)
    min_spo2 = min(spo2s)
    max_hr = max(hrs)
    
    # ลอจิก AI ประเมินความเสี่ยงตามประวัติโรคและค่าสัญญาณชีพ
    risk_score = 10
    findings = []
    recommendations = []

    if min_spo2 < 90:
        risk_score += 50
        findings.append(f"พบภาวะออกซิเจนในเลือดต่ำวิกฤต (SpO2 ต่ำสุด {min_spo2}%)")
        recommendations.append("แจ้งบุคลากรให้ตรวจสอบการวัดและประเมินผู้ป่วยตามแนวทางของหน่วยงาน")
    elif min_spo2 < 95:
        risk_score += 25
        findings.append(f"ออกซิเจนลดต่ำกว่ามาตรฐาน (SpO2 ต่ำสุด {min_spo2}%)")
        recommendations.append("ให้บุคลากรตรวจสอบสัญญาณจากเซนเซอร์และข้อมูลทางคลินิกประกอบ")

    if max_hr > 120:
        risk_score += 35
        findings.append(f"หัวใจเต้นเร็วผิดปกติ (Tachycardia Peak {max_hr} bpm)")
        recommendations.append("ให้บุคลากรทบทวนชีพจรและอาการประกอบ ไม่สรุปโรคจากค่าตัวเดียว")
    elif avg_hr > 100:
        risk_score += 15
        findings.append(f"ชีพจรเฉลี่ยค่อนข้างสูง ({avg_hr} bpm)")

    # ปรับตามปัจจัยอายุและโรคประจำตัว
    if profile["age"] >= 70:
        risk_score += 10
        findings.append("ผู้ป่วยสูงอายุ มีความเสี่ยงต่อการทรุดตัวรวดเร็ว")

    risk_score = min(risk_score, 100)

    if risk_score >= 70:
        risk_level = "DEMO_RULE_HIGH"
        ai_summary = f" กฎสาธิตพบค่าที่ควรตรวจสอบในผู้ป่วยกลุ่ม {profile['condition']} ({' / '.join(findings)})"
    elif risk_score >= 40:
        risk_level = "DEMO_RULE_MEDIUM"
        ai_summary = f" กฎสาธิตแนะนำให้ตรวจสอบ: พบความผิดปกติเบื้องต้น ({' / '.join(findings)})"
    else:
        risk_level = "DEMO_RULE_LOW (ไม่ใช่การรับรองความปลอดภัย)"
        ai_summary = f" กฎสาธิต: ค่าที่บันทึกยังไม่ข้ามเกณฑ์แจ้งเตือน ต้องพิจารณาร่วมกับข้อมูลทางคลินิก"
        recommendations.append("บันทึกสัญญาณชีพตามรอบปกติ")

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "summary": ai_summary,
        "recommendations": recommendations,
        "stats": {
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "min_hr": min(hrs),
            "avg_spo2": round(sum(spo2s) / len(spo2s), 1),
            "min_spo2": min_spo2,
            "total_samples": len(history_rows)
        }
    }

# --- WebSocket & Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        async def send(connection):
            try:
                subject = await asyncio.to_thread(auth.identity, connection.cookies, 'staff')
                if not subject:
                    await connection.close(code=4401)
                    self.disconnect(connection)
                    return
                if message.get('patient_id') and not await asyncio.to_thread(auth.can_access_patient, subject, message['patient_id']):
                    return
                await asyncio.wait_for(connection.send_json(message), timeout=.5)
            except Exception:
                self.disconnect(connection)
        await asyncio.gather(*(send(connection) for connection in list(self.active_connections)))

manager = ConnectionManager()
main_loop = None
agent_queue: asyncio.Queue[VitalEvent] | None = None

def evaluate_risk(hr: int, spo2: int):
    if spo2 < 90 or hr > 120 or hr < 50:
        return "CRITICAL", " วิกฤต: ค่าสัญญาณชีพผิดปกติรุนแรง!"
    elif spo2 < 95 or hr > 100:
        return "WARNING", " เตือน: ค่า SpO2 ต่ำหรือหัวใจเต้นเร็ว"
    return "NORMAL", " สัญญาณชีพปกติ"

# อย่าลืม Import ฟังก์ชัน AI ไว้ด้านบนสุดของไฟล์ main.py
# from ai_models.anomaly import detect_anomaly 
def on_message(client, userdata, msg):
    """Validation and enqueue only: no database/ML work on the MQTT thread."""
    try:
        payload = json.loads(msg.payload.decode())
        if msg.topic == BEDSIDE_TOPIC or payload.get('message_type') in {'device_health', 'pressure_map'}:
            def enqueue_bedside():
                if bedside_queue.full():
                    bedside_queue.get_nowait(); bedside_queue.task_done()
                bedside_queue.put_nowait(payload)
            if main_loop and main_loop.is_running() and bedside_queue is not None:
                main_loop.call_soon_threadsafe(enqueue_bedside)
            return
        patient_id = str(payload["patient_id"]).upper()
        if patient_id not in PATIENT_PROFILES:
            return
        values = {key: float(payload[key]) for key in ("heart_rate", "spo2", "respiratory_rate")}
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            return
        if values["heart_rate"] > 250 or values["spo2"] > 100 or values["respiratory_rate"] > 80:
            return
        ts = float(payload.get("timestamp", time.time()))
        if not math.isfinite(ts) or abs(time.time() - ts) > 15:
            return
        reading = {**values, "patient_id": patient_id, "timestamp": ts, "source_segment": "mqtt"}
        def enqueue():
            if telemetry_queue.full():
                telemetry_queue.get_nowait()
                telemetry_queue.task_done()
            telemetry_queue.put_nowait(reading)
        if main_loop and main_loop.is_running() and telemetry_queue is not None:
            main_loop.call_soon_threadsafe(enqueue)
    except (KeyError, TypeError, ValueError):
        print("Rejected malformed MQTT vital payload")


async def publish_monitor(outputs):
    for item in outputs:
        await manager.broadcast(item)
        analysis = item.get("analysis", {})
        signature = (item["timestamp"], item["status"], analysis.get("evaluated_at"))
        previous = agent_last_enqueue.get(item["patient_id"])
        # WebSocket remains 1 Hz. The Agent observes state changes, new model
        # evaluations, or a ten-second heartbeat to keep SQLite load bounded.
        if previous and previous[1] == signature[1] and previous[2] == signature[2] and signature[0] - previous[0] < 10:
            continue
        agent_last_enqueue[item["patient_id"]] = signature
        await enqueue_agent_event(VitalEvent(
            patient_id=item["patient_id"], heart_rate=item["heart_rate"], spo2=item["spo2"],
            timestamp=item["timestamp"], status=item["status"],
            is_anomaly=item["is_anomaly"], risk_percent=None,
            respiratory_rate=item.get("respiratory_rate"), source=item.get("source", "UNKNOWN"),
            source_record=item.get("source_record"), analysis_status=analysis.get("status", "INSUFFICIENT_DATA"),
            evaluated_at=analysis.get("evaluated_at"), model_version=analysis.get("model_version", "bidmc-monitor-v1"),
            forecast=analysis.get("forecast"), anomaly_score=analysis.get("anomaly_score"),
        ))


async def run_mqtt_worker():
    while True:
        reading = await telemetry_queue.get()
        try:
            outputs = await asyncio.to_thread(monitor_worker.process, [reading], time.time())
            await publish_monitor(outputs)
        except Exception as error:
            await asyncio.to_thread(monitor_worker.failure, error)
        finally:
            telemetry_queue.task_done()


async def run_bedside_worker():
    """Validate pressure/device messages away from the MQTT callback thread."""
    assert bedside_service is not None
    while True:
        payload = await bedside_queue.get()
        try:
            if payload.get('message_type') == 'pressure_map' or (
                payload.get('kind') == 'pressure_mat' and 'pressure_map' in payload
            ):
                result = await asyncio.to_thread(bedside_service.process_pressure, payload)
                alerts = result['alerts']
            else:
                result = await asyncio.to_thread(bedside_service.process_device, payload)
                alerts = [result['alert']] if result['alert'] else []
            for alert in alerts:
                persisted = await asyncio.to_thread(persist_agent_alert, alert)
                await manager.broadcast(persisted)
            await manager.broadcast({'type': 'bedside_status', 'patient_id': result['patient_id']})
        except (KeyError, TypeError, ValueError) as error:
            print(f"Rejected malformed bedside payload: {type(error).__name__}")
        except Exception as error:
            # A single corrupt device message must not stop all bedside monitoring.
            print(f"Bedside worker error: {type(error).__name__}")
        finally:
            bedside_queue.task_done()


async def run_bedside_watchdog():
    assert bedside_service is not None
    while True:
        await asyncio.sleep(5)
        for alert in await asyncio.to_thread(bedside_service.evaluate_stale):
            persisted = await asyncio.to_thread(persist_agent_alert, alert)
            await manager.broadcast(persisted)


async def enqueue_agent_event(event: VitalEvent) -> None:
    """Drop the oldest pending event under load rather than stalling MQTT."""
    if agent_queue is None:
        return
    if agent_queue.full():
        agent_queue.get_nowait()
        agent_queue.task_done()
    agent_queue.put_nowait(event)


async def run_agent_worker() -> None:
    """Persist and broadcast alert proposals without blocking vital-sign delivery."""
    assert agent_queue is not None and nurse_agent is not None
    while True:
        event = await agent_queue.get()
        try:
            decision = await asyncio.to_thread(nurse_agent.process, event)
            alert = decision["alert"]
            if alert:
                persisted_alert = await asyncio.to_thread(persist_agent_alert, alert)
                await asyncio.to_thread(
                    link_nurse_alert, DB_NAME, decision["run_id"], persisted_alert["alert_id"]
                )
                persisted_alert["agent_run_id"] = decision["run_id"]
                await manager.broadcast(persisted_alert)
        except Exception as exc:
            if nurse_agent is not None:
                try:
                    await asyncio.to_thread(nurse_agent.record_failure, exc)
                except Exception:
                    pass
            print(f"Agent workflow error: {exc}")
        finally:
            agent_queue.task_done()

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "8083"))
TOPIC = os.getenv("MQTT_TOPIC", "my_ai_hospital/vitals")
BEDSIDE_TOPIC = os.getenv("WARD_BEDSIDE_TOPIC", "my_ai_hospital/bedside")
BEDSIDE_MQTT_ENABLED = os.getenv(
    "WARD_BEDSIDE_MQTT_ENABLED", "1" if INGEST_MODE == "mqtt" else "0"
) == "1"

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
mqtt_client.on_message = on_message

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop, agent_queue, telemetry_queue, bedside_queue, bedside_service, monitor_worker, nurse_agent
    init_db()
    auth.staff_password()
    main_loop = asyncio.get_running_loop()
    agent_queue = asyncio.Queue(maxsize=200)
    telemetry_queue = asyncio.Queue(maxsize=200)
    bedside_queue = asyncio.Queue(maxsize=100)
    monitor_worker = MonitorWorker(DB_NAME, PATIENT_PROFILES, INGEST_MODE)
    nurse_agent = NurseAgent(DB_NAME, alert_cooldown_seconds=300)
    bedside_service = bedside_monitor.configure(
        DB_NAME, PATIENT_PROFILES,
        stale_seconds=int(os.getenv('WARD_DEVICE_STALE_SECONDS', '30')),
        turn_seconds=int(os.getenv('WARD_TURN_REMINDER_SECONDS', '7200')),
        dataset_export_key=os.getenv('WARD_DATASET_EXPORT_KEY'),
    )
    agent_last_enqueue.clear()
    jobs = [asyncio.create_task(run_agent_worker()), asyncio.create_task(run_bedside_worker()),
            asyncio.create_task(run_bedside_watchdog()), asyncio.create_task(notifications.run_dispatcher()),
            asyncio.create_task(care_api.run_scheduler()), asyncio.create_task(daily_summary.run_daily())]
    if auth.test_accounts_enabled():
        jobs.append(asyncio.create_task(TestPatientSimulator(DB_NAME).run()))
    mqtt_started = False
    try:
        if INGEST_MODE == "replay":
            jobs.append(asyncio.create_task(monitor_worker.run(publish_monitor)))
        if INGEST_MODE == "mqtt" or BEDSIDE_MQTT_ENABLED:
            def subscribe(client, userdata, flags, reason_code, properties):
                if not reason_code.is_failure:
                    topics = []
                    if INGEST_MODE == "mqtt":
                        topics.append((TOPIC, 0))
                    if BEDSIDE_MQTT_ENABLED:
                        topics.append((BEDSIDE_TOPIC, 0))
                    client.subscribe(topics)
            mqtt_client.on_connect = subscribe
            mqtt_client.connect_async(BROKER, PORT, 60)
            mqtt_client.loop_start()
            mqtt_started = True
        if INGEST_MODE == "mqtt":
            jobs.append(asyncio.create_task(run_mqtt_worker()))
        yield
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if mqtt_started:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()

app = FastAPI(lifespan=lifespan, dependencies=[Depends(auth.authorize_staff_resource)])
auth.install_auth(app, "staff", PATIENT_LOGIN_PROFILES)
app.include_router(research_router)
app.include_router(notifications.router)
app.include_router(evidence_router)
app.include_router(posture_router)
app.include_router(care_api.router)
app.include_router(care_profiles.router)
app.include_router(daily_summary.router)
app.include_router(care_messages.staff_router)
app.include_router(care_chat.staff_router)
app.include_router(assistant_api.router)
app.include_router(bedside_monitor.router)
app.include_router(agent_scenarios.router)


@app.get('/api/care-chat/unread-summary')
def care_chat_unread_summary(request: Request):
    subject = getattr(getattr(request, 'state', None), 'subject', None)
    summary = care_chat.count_unread_by_patient(subject)
    total = sum(summary.values())
    return {'summary': summary, 'total_unread': total, 'unread_by_patient': summary}


@app.get('/api/care/tasks/{task_id}/history')
def care_task_history_endpoint(task_id: int, request: Request):
    with closing(care_api.connect()) as conn:
        task = conn.execute(
            'SELECT t.*, p.patient_id FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE t.id=?',
            (task_id,)
        ).fetchone()
        if not task:
            raise HTTPException(404, 'Task not found')
        patient_id = task['patient_id']
        subject = getattr(getattr(request, 'state', None), 'subject', None)
        if subject and not auth.can_access_patient(subject, patient_id):
            raise HTTPException(403, 'บัญชีนี้ไม่ได้รับมอบหมายให้ดูแลผู้ป่วยรายนี้')

        history = care_plan.get_task_history(task_id)
        return {'task_id': task_id, 'patient_id': patient_id, 'history': history}


@app.get('/api/care/overdue-summary')
def care_overdue_summary_endpoint(request: Request, patient_id: str | None = None):
    subject = getattr(getattr(request, 'state', None), 'subject', None)
    clean_pid = patient_id.strip() if patient_id and patient_id.strip() else None
    if clean_pid and subject and not auth.can_access_patient(subject, clean_pid):
        raise HTTPException(403, 'บัญชีนี้ไม่ได้รับมอบหมายให้ดูแลผู้ป่วยรายนี้')
    return care_plan.overdue_care_summary(patient_id=clean_pid)


@app.get('/api/operations/shift-handoff')
def shift_handoff_endpoint(request: Request):
    subject = getattr(getattr(request, 'state', None), 'subject', None)
    now = time.time()
    care_summary = care_plan.overdue_care_summary()
    unread_map = care_chat.count_unread_by_patient(subject)
    total_unread = sum(unread_map.values())
    chat_summary = {
        'total_unread': total_unread,
        'unread_by_patient': unread_map,
        'summary': unread_map,
    }
    open_alerts_count = 0
    with closing(sqlite3.connect(DB_NAME, timeout=10)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_alerts'").fetchone():
            clause, values = auth.scoped_sql()
            cols = {r[1] for r in conn.execute('PRAGMA table_info(agent_alerts)')}
            merged_filter = " AND merged_into IS NULL" if "merged_into" in cols else ""
            open_alerts_count = conn.execute(
                f"SELECT COUNT(*) FROM agent_alerts WHERE status IN ('NEW', 'ACKNOWLEDGED', 'ESCALATED'){merged_filter} AND " + clause,
                values
            ).fetchone()[0]

    return {
        'generated_at': now,
        'care_summary': care_summary,
        'chat_summary': chat_summary,
        'open_alerts_count': open_alerts_count,
    }


@app.get('/api/operations/status')
def operations_status(request: Request):
    from contextlib import closing
    with closing(sqlite3.connect(DB_NAME, timeout=10)) as conn:
        clause, values = auth.scoped_sql()
        new_alerts = conn.execute("SELECT COUNT(*) FROM agent_alerts WHERE status='NEW' AND merged_into IS NULL AND " + clause, values).fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM care_messages WHERE state='NEW' AND " + clause, values).fetchone()[0]
        scope = auth.staff_patient_scope(request.state.subject)
        if scope is None:
            chat_unread = conn.execute("SELECT COUNT(*) FROM care_chat_messages WHERE sender_audience='patient' AND read_by_staff_at IS NULL").fetchone()[0]
        elif not scope:
            chat_unread = 0
        else:
            placeholders = ','.join('?' for _ in scope)
            chat_unread = conn.execute(f'''SELECT COUNT(*) FROM care_chat_messages WHERE sender_audience='patient'
                AND read_by_staff_at IS NULL AND patient_id IN ({placeholders})''', scope).fetchone()[0]
    worker = worker_status(DB_NAME)
    registry = auth.visible_registry(PATIENT_PROFILES)
    if scope is not None:
        worker['fresh_beds'] = sum(patient_state(DB_NAME, pid)['status'] not in {'WAITING', 'STALE_DATA', 'INVALID_DATA'} for pid in registry)
    bedside = bedside_service.summary() if bedside_service is not None else {'devices': {}, 'ground_truth_labels': 0, 'posture_observations': 0, 'posture_model': 'UNAVAILABLE'}
    if scope is not None:
        bedside = {'devices': {}, 'ground_truth_labels': 0, 'posture_observations': 0, 'posture_model': 'SCOPED_VIEW'}
    return {'fresh_beds': worker['fresh_beds'], 'total_beds': len(registry),
            'worker': worker['status'], 'new_alerts': new_alerts, 'unclaimed_messages': messages,
            'chat_unread': chat_unread,
            'push_ready': notifications.configuration()['ready'], 'named_login': not auth.demo_login_enabled(),
            'secure_cookie': os.getenv('WARD_COOKIE_SECURE') == '1', 'bedside': bedside}

@app.get("/api/monitor/status")
def monitor_status():
    status = worker_status(DB_NAME)
    registry = auth.visible_registry(PATIENT_PROFILES)
    if auth.request_patient_scope.get() is not None:
        status['fresh_beds'] = sum(patient_state(DB_NAME, pid)['status'] not in {'WAITING', 'STALE_DATA', 'INVALID_DATA'} for pid in registry)
    return {**status, "ingest_mode": INGEST_MODE, 'total_beds': len(registry)}

@app.get("/api/monitor/patients")
def monitor_patients():
    return {"patients": [patient_state(DB_NAME, patient_id) for patient_id in auth.visible_registry(PATIENT_PROFILES)]}

@app.get("/api/monitor/patient/{patient_id}")
def monitor_patient(patient_id: str):
    patient_id = patient_id.upper()
    if get_patient_profile(patient_id) is None:
        raise HTTPException(404, "Unknown Patient ID")
    return patient_state(DB_NAME, patient_id)

# 📌 3. API สำหรับดึงข้อมูลรายละเอียดฉบับเต็ม + ผลวิเคราะห์ AI
@app.get("/api/patient/{patient_id}/details")
def get_patient_details(patient_id: str):
    patient_id = patient_id.upper()
    profile = get_patient_profile(patient_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT heart_rate, spo2, status, timestamp, respiratory_rate,
                  blood_glucose, ecg_rhythm, sleep_hours, simulation_state
           FROM vital_logs WHERE patient_id = ? ORDER BY id DESC LIMIT 50""",
        (patient_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    ai_assessment = generate_ai_assessment(patient_id, rows)

    history_list = [{
        "heart_rate": r[0],
        "spo2": r[1],
        "status": r[2],
        "timestamp": r[3],
        "respiratory_rate": r[4],
        "blood_glucose": r[5],
        "ecg_rhythm": r[6],
        "sleep_hours": r[7],
        "simulation_state": r[8],
    } for r in rows]

    # The selected Patient ID is all the UI needs to supply. The backend reads
    # that ID's telemetry, applies the feature contract, and refuses a score if
    # history/coverage are insufficient.
    risk_model = calculate_risk_assessment(profile, list(reversed(history_list)))
    
    # ⚡ 2. เรียกใช้ AI: พยากรณ์ค่า HR/SpO2 ล่วงหน้า (สลับเอาข้อมูลเก่าสุดขึ้นก่อนเพื่อดูกราฟ)
    history_hr = [r[0] for r in rows][::-1]
    history_spo2 = [r[1] for r in rows][::-1]
    monitor = patient_state(DB_NAME, patient_id)
    predicted = (monitor.get("analysis", {}).get("forecast") or {})
    forecast = {"predicted_hr": predicted.get("heart_rate"), "predicted_spo2": predicted.get("spo2")}


    return {
        "patient_id": patient_id,
        "profile": profile,
        "latest_clinical": history_list[0] if history_list else None,
        "ai_assessment": ai_assessment,
        "risk_model": risk_model,
        "monitor": monitor,
        "history": history_list,
        "forecast": forecast # 👈 ส่งผลพยากรณ์ไปแสดงใน Modal
    }


@app.get("/api/patient/{patient_id}/trends")
def get_patient_trends(patient_id: str, hours: Literal["1", "6", "24", "168"] = "1"):
    """Staff-only, quality-filtered history using the same aggregation as the patient portal."""
    patient_id = patient_id.upper()
    if get_patient_profile(patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    return patient_views.trends(patient_id, int(hours))


@app.get("/api/ml/model-status")
def model_status():
    """Expose provenance and hold-out metrics without exposing raw dataset rows."""
    return get_model_status()


@app.get("/api/ml/benchmarks")
def model_benchmarks():
    """Compare locally evaluated profiles; raw clinical rows remain private."""
    return get_model_benchmarks()


@app.get("/api/ml/patient/{patient_id}")
def assess_selected_patient(patient_id: str):
    """Patient-ID-only research inference with an explicit data-quality gate."""
    patient_id = patient_id.upper()
    profile = get_patient_profile(patient_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    assessment = calculate_risk_assessment(profile, get_recent_vital_history(patient_id))
    return {
        "patient_id": patient_id,
        "assessment": assessment,
        "human_review_required": True,
    }


@app.get("/api/patients")
def list_patients(zone: str | None = None, search: str = "", page: int = 1, page_size: int = 20):
    """Search the fixed 60-bed synthetic ward without loading all detail records."""
    normalized_zone = (zone or "").strip().upper()
    if normalized_zone and normalized_zone not in ZONE_LABELS:
        raise HTTPException(status_code=400, detail="Zone must be A, B, or C")
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    query = search.strip().lower()
    registry = auth.visible_registry(PATIENT_PROFILES)
    profiles = list(registry.values())
    if normalized_zone:
        profiles = [profile for profile in profiles if profile["zone"] == normalized_zone]
    if query:
        profiles = [
            profile for profile in profiles
            if query in profile["patient_id"].lower()
            or query in profile["room_number"].lower()
            or query in profile["name"].lower()
            or query in profile["condition"].lower()
        ]
    profiles.sort(key=lambda profile: profile["patient_id"])
    start = (page - 1) * page_size
    directory_items = [{
        "patient_id": profile["patient_id"],
        "name": profile["name"],
        "zone": profile["zone"],
        "zone_name": profile["zone_name"],
        "room_number": profile["room_number"],
        "bed_number": profile["bed_number"],
        "condition": profile["condition"],
        "mobility": profile["mobility"],
        "doctor": profile["doctor"],
    } for profile in profiles[start:start + page_size]]
    return {
        "registered_patient_count": len(registry),
        "total": len(profiles),
        "page": page,
        "page_size": page_size,
        "patients": directory_items,
    }


@app.get("/api/triage")
def nursing_triage(zone: str | None = None, mobility: str | None = None, priority: str = "all"):
    """Priority-ordered board for the synthetic nursing workflow."""
    items = get_triage_snapshot(zone=zone, mobility=mobility, priority=priority)
    return {
        "generated_at": time.time(),
        "total": len(items),
        "critical": sum(item["triage_level"] == "CRITICAL" for item in items),
        "attention": sum(item["triage_level"] == "ATTENTION" for item in items),
        "patients": items,
    }


@app.get("/api/alerts")
def list_workflow_alerts(status: str = "open", zone: str | None = None, limit: int = 20, offset: int = 0, patient_id: str | None = None):
    limit = min(max(limit, 1), 199)
    rows = get_workflow_alerts(status=status, zone=zone, limit=limit + 1, offset=offset, patient_id=patient_id)
    return {"alerts": rows[:limit], 'has_more': len(rows) > limit}


class AlertWorkflowUpdate(BaseModel):
    status: str = Field(pattern="^(ACKNOWLEDGED|ESCALATED|RESOLVED)$")
    actor: str = Field(default="Dashboard operator", min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)
    expected_version: int | None = Field(default=None, ge=1)


@app.patch("/api/alerts/{alert_id}")
def update_workflow_alert(alert_id: int, update: AlertWorkflowUpdate, request: Request):
    """Move a persisted alert through a human-approved workflow state."""
    requested_status = update.status.upper()
    conn = sqlite3.connect(DB_NAME)
    conn.execute("BEGIN IMMEDIATE")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, patient_id, severity, reason, recommended_next_step,
               heart_rate, spo2, risk_percent, status, assigned_to, created_at,
               acknowledged_at, resolved_at, resolution_note
        FROM agent_alerts WHERE id = ?
    """, (alert_id,))
    current = cursor.fetchone()
    if current is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found")
    current_status = current[8]
    meta = alert_episodes.metadata(conn, alert_id)
    if meta['merged_into'] is not None or (update.expected_version is not None and meta['version'] != update.expected_version):
        conn.close()
        raise HTTPException(409, 'รายการเปลี่ยนแล้ว กรุณาโหลดใหม่ก่อนดำเนินการ')
    if requested_status in {'RESOLVED', 'ESCALATED'} and len(update.note.strip()) < 5:
        conn.close()
        raise HTTPException(422, 'กรุณาระบุผลตรวจสอบหรือเหตุผลการส่งต่ออย่างน้อย 5 ตัวอักษร')
    if requested_status not in WORKFLOW_TRANSITIONS[current_status]:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"Alert cannot transition from {current_status} to {requested_status}",
        )
    now = time.time()
    actor = request.state.subject
    note = update.note.strip()
    acknowledged_at = now if requested_status == "ACKNOWLEDGED" else current[11]
    resolved_at = now if requested_status == "RESOLVED" else current[12]
    resolution_note = note if requested_status == "RESOLVED" and note else current[13]
    assigned_to = actor if requested_status in {"ACKNOWLEDGED", "ESCALATED"} else current[9]
    cursor.execute("""
        UPDATE agent_alerts
        SET status = ?, assigned_to = ?, acknowledged_at = ?, resolved_at = ?, resolution_note = ?, version=version+1
        WHERE id = ?
    """, (requested_status, assigned_to, acknowledged_at, resolved_at, resolution_note, alert_id))
    cursor.execute(
        """INSERT INTO agent_audit_logs (alert_id, patient_id, action, actor, detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            alert_id, current[1], f"ALERT_{requested_status}", actor,
            note or f"Workflow moved from {current_status} to {requested_status}.", now,
        ),
    )
    conn.commit()
    cursor.execute("""
        SELECT id, patient_id, severity, reason, recommended_next_step,
               heart_rate, spo2, risk_percent, status, assigned_to, created_at,
               acknowledged_at, resolved_at, resolution_note
        FROM agent_alerts WHERE id = ?
    """, (alert_id,))
    updated = serialize_alert(cursor.fetchone())
    updated.update(alert_episodes.metadata(conn, alert_id))
    conn.close()
    message = "Workflow status updated. No external contact or clinical action was sent."
    return {"alert": updated, "message": message}


@app.get("/api/patient/{patient_id}/timeline")
def patient_timeline(patient_id: str, limit: int = 80):
    patient_id = patient_id.upper()
    if get_patient_profile(patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    return {"patient_id": patient_id, "events": get_patient_timeline(patient_id, limit=limit)}


@app.get("/api/agent/audit")
def list_agent_audit(patient_id: str | None = None, limit: int = 100):
    limit = min(max(limit, 1), 200)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if patient_id:
        normalized_patient_id = patient_id.upper()
        cursor.execute(
            """SELECT id, alert_id, patient_id, action, actor, detail, created_at
               FROM agent_audit_logs WHERE patient_id = ? ORDER BY created_at DESC LIMIT ?""",
            (normalized_patient_id, limit),
        )
    else:
        clause, values = auth.scoped_sql()
        cursor.execute(
            """SELECT id, alert_id, patient_id, action, actor, detail, created_at
               FROM agent_audit_logs WHERE """ + clause + " ORDER BY created_at DESC LIMIT ?",
            (*values, limit),
        )
    events = [{
        "id": row[0], "alert_id": row[1], "patient_id": row[2],
        "action": row[3], "actor": row[4], "detail": row[5], "created_at": row[6],
    } for row in cursor.fetchall()]
    conn.close()
    return {"events": events}


@app.get("/api/agent/status")
def get_nurse_agent_status():
    return nurse_agent_status(DB_NAME)


@app.get("/api/agent/runs")
def get_nurse_agent_runs(patient_id: str | None = None, limit: int = 30):
    normalized = patient_id.upper() if patient_id else None
    if normalized and get_patient_profile(normalized) is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    return {"runs": list_nurse_runs(DB_NAME, limit=limit, patient_id=normalized)}


@app.get("/api/evaluation/alert-workflow")
def evaluate_alert_workflow():
    return run_alert_workflow_evaluation()

#GEMINI API Key Model
class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)

@app.post("/api/patient/{patient_id}/chat")
async def patient_chat_api(patient_id: str, request: ChatMessage):
    patient_id = patient_id.upper()
    profile = get_patient_profile(patient_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT heart_rate, spo2 FROM vital_logs WHERE patient_id = ? ORDER BY id DESC LIMIT 30", (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    
    # ส่งข้อความและข้อมูลผู้ป่วยไปให้ Gemini คิดคำตอบ
    # Gemini is a blocking network request. Keep it off FastAPI's event loop so
    # chat requests cannot stall WebSocket broadcasting or the agent worker.
    reply = await asyncio.to_thread(
        chat_with_patient_data,
        patient_id,
        profile,
        rows,
        request.message,
        {key: value for key, value in (await asyncio.to_thread(patient_state, DB_NAME, patient_id)).items()
         if key in {"patient_id", "source", "source_record", "timestamp", "analysis"}},
    )
    
    return {"reply": reply}


class CareRequest(BaseModel):
    request_type: str = Field(pattern="^(doctor|ambulance)$")
    note: str = Field(default="", max_length=500)


@app.post("/api/patient/{patient_id}/care-requests")
def create_care_request(patient_id: str, payload: CareRequest, request: Request):
    """Record a handoff request for human review; this endpoint never dispatches care."""
    patient_id = patient_id.upper()
    if get_patient_profile(patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient ID not found in the synthetic registry")
    requested_at = time.time()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO care_requests (patient_id, request_type, status, note, requested_at)
           VALUES (?, ?, ?, ?, ?)""",
        (patient_id, payload.request_type, "PENDING_HUMAN_REVIEW", payload.note.strip(), requested_at),
    )
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    record_audit_event(
        patient_id,
        "CARE_REQUEST_CREATED",
        request.state.subject,
        f"Created {payload.request_type} request #{request_id}; awaiting human review.",
    )
    label = "doctor contact" if payload.request_type == "doctor" else "ambulance escalation"
    return {
        "request_id": request_id,
        "status": "PENDING_HUMAN_REVIEW",
        "message": (
            f"Created a {label} request for staff review. "
            "No doctor was contacted and no ambulance was dispatched automatically."
        ),
    }


@app.get("/api/patient/{patient_id}/report/text", response_class=PlainTextResponse)
def download_patient_report_text(patient_id: str):
    details = get_patient_details(patient_id)
    return format_evidence_handoff(
        details["patient_id"],
        details["profile"],
        details["monitor"],
    )


@app.get("/api/patient/{patient_id}/report/document")
def download_patient_report_document(patient_id: str):
    details = get_patient_details(patient_id)
    try:
        document = create_patient_handoff_docx(
            details["patient_id"],
            details["profile"],
            details["history"],
            details["ai_assessment"],
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    filename = f"smart-ward-{details['patient_id']}-handoff.docx"
    return StreamingResponse(
        BytesIO(document),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


VALID_DASHBOARD_SECTIONS = {"overview", "triage", "patients", "alerts", "ai", "reports"}


@app.get("/api/dashboard/{section}")
async def dashboard_section(section: str):
    if section not in VALID_DASHBOARD_SECTIONS:
        raise HTTPException(status_code=404, detail="Unknown dashboard section")
    snapshot = await asyncio.to_thread(get_dashboard_snapshot)
    if os.getenv("WARD_DASHBOARD_LLM", "0") == "1":
        ai_summary = await asyncio.to_thread(summarize_dashboard_section, section, snapshot)
    else:
        ai_summary = (
            "สรุปอัตโนมัติในเครื่อง: " + str(snapshot.get("registered_patient_count", 60)) + " เตียงในทะเบียนสาธิต "
            "· เปิดการ์ดผู้ป่วยเพื่อดูผล Isolation Forest และ forecast ล่าสุด "
            "· Gemini ใช้เมื่อถามในแชทหรือขอรายงาน ไม่จำเป็นสำหรับ worker ที่ทำงานต่อเนื่อง"
        )
    return {"section": section, "snapshot": snapshot, "ai_summary": ai_summary}


@app.get("/api/reports/{section}/text", response_class=PlainTextResponse)
async def download_report_text(section: str):
    if section not in VALID_DASHBOARD_SECTIONS:
        raise HTTPException(status_code=404, detail="Unknown report section")
    snapshot = await asyncio.to_thread(get_dashboard_snapshot)
    ai_summary = await asyncio.to_thread(summarize_dashboard_section, section, snapshot)
    return format_dashboard_text(section, snapshot, ai_summary)


@app.get("/api/reports/{section}/document")
async def download_report_document(section: str):
    if section not in VALID_DASHBOARD_SECTIONS:
        raise HTTPException(status_code=404, detail="Unknown report section")
    snapshot = await asyncio.to_thread(get_dashboard_snapshot)
    ai_summary = await asyncio.to_thread(summarize_dashboard_section, section, snapshot)
    try:
        document = await asyncio.to_thread(create_report_docx, section, snapshot, ai_summary)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    filename = f"smart-ward-{section}-report.docx"
    return StreamingResponse(
        BytesIO(document),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.websocket("/ws/vitals")
async def websocket_endpoint(websocket: WebSocket):
    if not auth.identity(websocket.cookies, "staff") or websocket.headers.get("origin") not in auth.ORIGINS["staff"]:
        await websocket.close(code=4401)
        return
    await manager.connect(websocket)
    try:
        while True:
            if not auth.identity(websocket.cookies, "staff"):
                await websocket.close(code=4401)
                break
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=10)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
