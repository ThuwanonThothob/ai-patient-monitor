"""Side-effect-free scenario lab for explaining the agent workflow.

The fixtures exercise routing and safety behaviour only.  They never create a
live alert, enqueue a push message, write a vital sign, or become training data.
Stored runs live in their own table so demo evidence cannot be confused with
patient observations or clinician-labelled ground truth.
"""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

import auth
from ai_models.agent_workflow import VitalAlertAgent, VitalEvent


router = APIRouter(prefix="/api/agent/scenarios", tags=["agent-scenario-lab"])

SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {
        "title": "ผู้ป่วยอยู่ในช่วงติดตาม",
        "description": "ข้อมูลใหม่ คุณภาพผ่าน และไม่เข้าเงื่อนไขเสนอ Alert",
        "kind": "vitals",
        "input": {"heart_rate": 78, "spo2": 98, "respiratory_rate": 17, "age_seconds": 1,
                  "sensor_attached": True, "signal_quality": 94},
        "model": {"dataset": "BIDMC PPG and Respiration v1.0.0", "version": "bidmc-monitor-v1",
                  "status": "READY", "is_anomaly": False, "risk_percent": 12,
                  "forecast": {"heart_rate": 79.2, "spo2": 98.0, "respiratory_rate": 17.4}},
        "expected": {"decision": "CONTINUE_MONITORING", "severity": "info", "would_alert": False},
        "ground_truth": "ไม่ควรสร้าง Alert ใน fixture นี้",
    },
    "desaturation": {
        "title": "SpO₂ ลดต่อเนื่อง",
        "description": "สัญญาณผ่านคุณภาพแต่ SpO₂ ต่ำกว่าเกณฑ์สาธิต",
        "kind": "vitals",
        "input": {"heart_rate": 108, "spo2": 87, "respiratory_rate": 24, "age_seconds": 1,
                  "sensor_attached": True, "signal_quality": 91},
        "model": {"dataset": "BIDMC PPG and Respiration v1.0.0", "version": "bidmc-monitor-v1",
                  "status": "READY", "is_anomaly": False, "risk_percent": 80,
                  "forecast": {"heart_rate": 110.1, "spo2": 87.0, "respiratory_rate": 24.6}},
        "expected": {"decision": "PROPOSE_HUMAN_REVIEW", "severity": "critical", "would_alert": True},
        "ground_truth": "ควรสร้างตัวอย่างงานเร่งด่วนให้บุคลากรตรวจวัดซ้ำ",
    },
    "sensor_disconnected": {
        "title": "เซนเซอร์หลุด",
        "description": "Device Health ต้องแยกอุปกรณ์ผิดปกติออกจากผู้ป่วยผิดปกติ",
        "kind": "device",
        "input": {"heart_rate": 0, "spo2": 0, "respiratory_rate": 0, "age_seconds": 2,
                  "sensor_attached": False, "signal_quality": 0},
        "model": {"dataset": None, "version": None, "status": "SKIPPED_QUALITY_GATE"},
        "expected": {"decision": "ABSTAIN_DEVICE_FAULT", "severity": "warning", "would_alert": True},
        "ground_truth": "ต้องแจ้งตรวจอุปกรณ์และห้ามตีความค่า 0 เป็นภาวะผู้ป่วย",
    },
    "prolonged_posture": {
        "title": "อยู่ท่าเดิมเกินกำหนด",
        "description": "Pressure map ระบุท่าหงายต่อเนื่องเกินเวลาสาธิต",
        "kind": "posture",
        "input": {"posture": "SUPINE", "dwell_seconds": 7800, "turn_limit_seconds": 7200,
                  "sensor_attached": True, "signal_quality": 89},
        "model": {"dataset": "PhysioNet PMD v1.0.0", "version": "posture-shadow-v1",
                  "status": "READY_SHADOW", "predicted_posture": "SUPINE", "confidence": 0.91},
        "expected": {"decision": "PROPOSE_POSTURE_REVIEW", "severity": "warning", "would_alert": True},
        "ground_truth": "ควรเสนอให้ผู้ดูแลตรวจท่า แต่ไม่ยืนยันแผลกดทับ",
    },
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(auth.DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_scenarios() -> None:
    with closing(connect()) as conn, conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_scenario_runs (
            id INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL,
            expected_decision TEXT NOT NULL, actual_decision TEXT NOT NULL,
            passed INTEGER NOT NULL, actor TEXT NOT NULL,
            payload TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_scenario_runs_created
            ON agent_scenario_runs(created_at DESC);
        """)


def scenario_catalog() -> list[dict[str, Any]]:
    return [{"id": key, "title": value["title"], "description": value["description"],
             "kind": value["kind"], "expected": value["expected"]}
            for key, value in SCENARIOS.items()]


def _vital_decision(case: dict[str, Any], now: float) -> tuple[str, str, bool, str]:
    values, model = case["input"], case["model"]
    proposal = VitalAlertAgent(cooldown_seconds=0).assess(VitalEvent(
        patient_id="SCENARIO",
        heart_rate=values["heart_rate"], spo2=values["spo2"],
        respiratory_rate=values["respiratory_rate"], timestamp=now - values["age_seconds"],
        status="NORMAL", is_anomaly=model["is_anomaly"], risk_percent=model["risk_percent"],
        analysis_status=model["status"], evaluated_at=now, model_version=model["version"],
        forecast=model.get("forecast"),
    ))
    if proposal:
        return "PROPOSE_HUMAN_REVIEW", proposal["severity"], True, proposal["reason"]
    return "CONTINUE_MONITORING", "info", False, "ไม่เข้าเงื่อนไขสร้างงานใหม่ในรอบนี้"


def evaluate_scenario(scenario_id: str, *, now: float | None = None) -> dict[str, Any]:
    case = SCENARIOS.get(scenario_id)
    if case is None:
        raise KeyError(scenario_id)
    now = time.time() if now is None else now
    values, model = case["input"], case["model"]
    sensor_ok = bool(values.get("sensor_attached", True)) and float(values.get("signal_quality", 0)) >= 20
    fresh = float(values.get("age_seconds", 0)) <= 15
    valid = sensor_ok and fresh

    if not sensor_ok:
        decision, severity, would_alert = "ABSTAIN_DEVICE_FAULT", "warning", True
        reason = "หยุดการแปลผลทางสรีรวิทยาและเสนอให้ตรวจเซนเซอร์"
    elif case["kind"] == "posture":
        overdue = values["dwell_seconds"] > values["turn_limit_seconds"]
        decision = "PROPOSE_POSTURE_REVIEW" if overdue else "CONTINUE_MONITORING"
        severity, would_alert = ("warning", True) if overdue else ("info", False)
        reason = "ท่าเดิมเกินเวลาที่กำหนด จึงเสนอให้ผู้ดูแลตรวจสอบ" if overdue else "ยังไม่ถึงเวลาตรวจท่า"
    elif not fresh:
        decision, severity, would_alert = "ABSTAIN_STALE_DATA", "info", False
        reason = "ข้อมูลเก่าเกินสัญญาคุณภาพ"
    else:
        decision, severity, would_alert, reason = _vital_decision(case, now)

    expected = case["expected"]
    passed = (decision == expected["decision"] and severity == expected["severity"]
              and would_alert == expected["would_alert"])
    model_skipped = not valid
    stages = [
        {"id": "input", "agent_id": "telemetry_agent", "title": "ข้อมูลเข้า",
         "status": "RECEIVED", "evidence": values,
         "explanation": "Fixture สังเคราะห์สำหรับทดสอบระบบ ไม่ใช่ข้อมูลผู้ป่วย"},
        {"id": "quality", "agent_id": "data_quality_agent", "title": "ตรวจคุณภาพ",
         "status": "PASS" if valid else "ABSTAIN", "evidence": {"sensor_ok": sensor_ok, "fresh": fresh,
         "signal_quality": values.get("signal_quality")},
         "explanation": "ผ่านและส่งต่อให้โมเดล" if valid else "หยุดการตีความค่าผู้ป่วยและส่งต่อ Device Health"},
        {"id": "model", "agent_id": "monitoring_agent" if case["kind"] == "vitals" else "device_health_agent",
         "title": "Dataset และ Model", "status": "SKIPPED" if model_skipped else model["status"],
         "evidence": model, "explanation": "ผลโมเดลเป็น fixture ที่กำหนดไว้เพื่อทดสอบ routing ไม่ใช่การวัด accuracy"},
        {"id": "decision", "agent_id": "safety_supervisor", "title": "Agent ตัดสินใจ",
         "status": decision, "evidence": {"decision": decision, "severity": severity, "reason": reason},
         "explanation": "Safety Supervisor บังคับ policy และไม่อนุญาตการรักษาอัตโนมัติ"},
        {"id": "action", "agent_id": "notification_agent", "title": "การกระทำของระบบ",
         "status": "DRY_RUN_ALERT" if would_alert else "AUDIT_ONLY",
         "evidence": {"would_create_alert": would_alert, "would_enqueue_push": would_alert,
                      "live_side_effects": False},
         "explanation": "แสดงผลลัพธ์จำลองเท่านั้น ไม่สร้าง Alert หรือ Web Push จริง"},
        {"id": "ground_truth", "agent_id": "documentation_agent", "title": "Ground Truth",
         "status": "MATCH" if passed else "MISMATCH",
         "evidence": {"label_source": "controlled_scenario_fixture", "expected": expected,
                      "actual": {"decision": decision, "severity": severity, "would_alert": would_alert}},
         "explanation": case["ground_truth"]},
    ]
    return {"scenario_id": scenario_id, "title": case["title"], "description": case["description"],
            "synthetic": True, "dry_run": True, "clinical_validation": False,
            "training_data": False, "created_at": now, "passed": passed,
            "expected": expected, "actual": {"decision": decision, "severity": severity,
                                               "would_alert": would_alert},
            "stages": stages,
            "notice": "ทดสอบ software workflow เท่านั้น ไม่วัดความแม่นยำทางคลินิกและไม่กระทบข้อมูลสด"}


def save_run(result: dict[str, Any], actor: str) -> int:
    with closing(connect()) as conn, conn:
        cursor = conn.execute("""INSERT INTO agent_scenario_runs
            (scenario_id,expected_decision,actual_decision,passed,actor,payload,created_at)
            VALUES (?,?,?,?,?,?,?)""", (
            result["scenario_id"], result["expected"]["decision"], result["actual"]["decision"],
            int(result["passed"]), actor, json.dumps(result, ensure_ascii=False, allow_nan=False),
            result["created_at"],
        ))
        conn.execute("""DELETE FROM agent_scenario_runs WHERE id IN
            (SELECT id FROM agent_scenario_runs ORDER BY id DESC LIMIT -1 OFFSET 200)""")
        return int(cursor.lastrowid)


@router.get("")
def list_scenarios() -> dict[str, Any]:
    init_scenarios()
    with closing(connect()) as conn:
        recent = [dict(row) for row in conn.execute("""SELECT id,scenario_id,expected_decision,
            actual_decision,passed,actor,created_at FROM agent_scenario_runs
            ORDER BY id DESC LIMIT 20""")]
    for row in recent:
        row["passed"] = bool(row["passed"])
    return {"scenarios": scenario_catalog(), "recent_runs": recent,
            "dry_run": True, "live_side_effects": False, "training_data": False}


@router.post("/{scenario_id}", status_code=201)
def run_scenario(scenario_id: str, request: Request) -> dict[str, Any]:
    init_scenarios()
    try:
        result = evaluate_scenario(scenario_id)
    except KeyError as error:
        raise HTTPException(404, "Unknown controlled scenario") from error
    run_id = save_run(result, request.state.subject)
    return {**result, "run_id": run_id}
