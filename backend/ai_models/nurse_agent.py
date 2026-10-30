"""Bounded local nurse agent with auditable tool steps.

The agent observes validated monitor events, reads only approved local context,
and may propose a review alert.  It never diagnoses, changes treatment, closes
care tasks, contacts a person, or calls a cloud model.  Gemini remains an
optional, on-demand explanation layer outside this safety loop.
"""

from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

from .agent_workflow import VitalAlertAgent, VitalEvent
from .care_team import owner_for_step, team_manifest


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
OPEN_ALERTS = ("NEW", "ACKNOWLEDGED", "ESCALATED")


def connect(database: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_nurse_agent_db(database: str) -> None:
    with closing(connect(database)) as conn, conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS nurse_agent_runtime (
            id INTEGER PRIMARY KEY CHECK(id=1), started_at REAL NOT NULL,
            heartbeat REAL NOT NULL, status TEXT NOT NULL,
            processed_events INTEGER NOT NULL DEFAULT 0,
            alert_proposals INTEGER NOT NULL DEFAULT 0,
            last_error TEXT, model_version TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS nurse_agent_runs (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, trigger TEXT NOT NULL,
            decision TEXT NOT NULL, severity TEXT NOT NULL,
            requires_human_review INTEGER NOT NULL, model_version TEXT NOT NULL,
            source TEXT NOT NULL, summary TEXT NOT NULL, alert_id INTEGER,
            created_at REAL NOT NULL, completed_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS nurse_agent_steps (
            id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, sequence INTEGER NOT NULL,
            agent_id TEXT NOT NULL DEFAULT 'legacy_agent',
            tool_name TEXT NOT NULL, status TEXT NOT NULL,
            input_json TEXT NOT NULL, output_json TEXT NOT NULL, created_at REAL NOT NULL,
            UNIQUE(run_id, sequence));
        CREATE INDEX IF NOT EXISTS idx_nurse_runs_created
            ON nurse_agent_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nurse_runs_patient_created
            ON nurse_agent_runs(patient_id, created_at DESC);
        """)
        step_columns = {row[1] for row in conn.execute("PRAGMA table_info(nurse_agent_steps)")}
        if "agent_id" not in step_columns:
            conn.execute("ALTER TABLE nurse_agent_steps ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'legacy_agent'")
        now = time.time()
        conn.execute("""INSERT OR IGNORE INTO nurse_agent_runtime
            (id,started_at,heartbeat,status,model_version) VALUES (1,?,?,?,?)""",
            (now, now, "STARTING", "care-agent-team-v1"))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _care_context(conn: sqlite3.Connection, patient_id: str) -> dict[str, int]:
    # Read only human-reviewed plans and their current tasks.  Absence of a plan
    # is not interpreted as absence of care needs.
    row = conn.execute("""SELECT
        COUNT(DISTINCT CASE WHEN p.state='ACTIVE' THEN p.id END) AS active_plans,
        COUNT(DISTINCT CASE WHEN t.state IN ('PENDING','ACKNOWLEDGED') THEN t.id END) AS open_tasks,
        COUNT(DISTINCT CASE WHEN t.state IN ('PENDING','ACKNOWLEDGED') AND t.scheduled_at<? THEN t.id END) AS overdue_tasks
        FROM care_plans p LEFT JOIN care_tasks t ON t.plan_id=p.id
        WHERE p.patient_id=? AND p.reviewed_at IS NOT NULL""", (time.time(), patient_id)).fetchone()
    return {key: int(row[key] or 0) for key in ("active_plans", "open_tasks", "overdue_tasks")}


def _recent_open_alert(conn: sqlite3.Connection, patient_id: str, severity: str, since: float, episode_key: str | None = None) -> bool:
    if 'episode_key' in {r[1] for r in conn.execute('PRAGMA table_info(agent_alerts)')}:
        return conn.execute("""SELECT 1 FROM agent_alerts WHERE patient_id=? AND episode_key=?
            AND merged_into IS NULL AND (status IN ('NEW','ACKNOWLEDGED','ESCALATED') OR created_at>=?) LIMIT 1""",
            (patient_id, episode_key, since)).fetchone() is not None
    marks = ",".join("?" for _ in OPEN_ALERTS)
    row = conn.execute(f"""SELECT 1 FROM agent_alerts
        WHERE patient_id=? AND severity=? AND (status IN ({marks}) OR created_at>=?)
        LIMIT 1""", (patient_id, severity, *OPEN_ALERTS, since)).fetchone()
    return row is not None


class NurseAgent:
    """Tool-using state machine for continuous, non-clinical workflow support."""

    def __init__(self, database: str, *, trace_interval_seconds: int = 600,
                 alert_cooldown_seconds: int = 60) -> None:
        self.database = database
        self.trace_interval_seconds = max(10, trace_interval_seconds)
        self.alert_cooldown_seconds = max(1, alert_cooldown_seconds)
        # Persistent SQLite episode/cooldown state below is the single source of
        # truth. Disable the helper's process-local cooldown so every suppression
        # is visible as SUPPRESS_DUPLICATE_ALERT in the audit trace.
        self.alert_agent = VitalAlertAgent(cooldown_seconds=0)
        self._last_trace: dict[str, float] = {}
        self._last_decision: dict[str, str] = {}
        init_nurse_agent_db(database)
        with closing(connect(database)) as conn, conn:
            now = time.time()
            conn.execute("""UPDATE nurse_agent_runtime SET started_at=?,heartbeat=?,status='STARTING',
                processed_events=0,alert_proposals=0,last_error=NULL,model_version='care-agent-team-v1' WHERE id=1""",
                (now, now))

    def process(self, event: VitalEvent, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        age = now - event.timestamp if _finite(event.timestamp) else math.inf
        valid = (_finite(event.heart_rate) and _finite(event.spo2)
                 and 20 <= event.heart_rate <= 250 and 1 <= event.spo2 <= 100)
        fresh = -5 <= age <= 15
        model_fresh = (event.analysis_status == "READY" and _finite(event.evaluated_at)
                       and -5 <= now - float(event.evaluated_at) <= 30)

        # A stale anomaly must never create a new clinical review proposal.
        from dataclasses import replace
        from alert_episodes import observe
        safe_event = event if model_fresh else replace(event, is_anomaly=False, model_requests_review=False, risk_percent=None)
        proposal = self.alert_agent.assess(safe_event) if valid and fresh else None
        duplicate = False
        with closing(connect(self.database)) as conn, conn:
            if valid and fresh:
                observe(conn, event, model_fresh)
            if proposal:
                duplicate = _recent_open_alert(
                    conn, event.patient_id, proposal["severity"],
                    now - self.alert_cooldown_seconds,
                    proposal.get('episode_key'),
                )
                if duplicate:
                    proposal = None

            if not valid:
                decision, severity, summary = "ABSTAIN_INVALID_DATA", "info", "ข้อมูลไม่ผ่านสัญญาคุณภาพ จึงไม่เสนอการดำเนินการ"
            elif not fresh:
                decision, severity, summary = "ABSTAIN_STALE_DATA", "info", "ข้อมูลเก่าหรือมาจากอนาคต จึงระงับผลและรอข้อมูลใหม่"
            elif duplicate:
                decision, severity, summary = "SUPPRESS_DUPLICATE_ALERT", "info", "มีข้อเสนอเปิดระดับเดียวกันอยู่แล้ว จึงไม่สร้างงานซ้ำ"
            elif proposal:
                decision = "PROPOSE_HUMAN_REVIEW"
                severity = proposal["severity"]
                summary = "Agent เสนอให้บุคลากรตรวจสอบ โดยไม่มีการวินิจฉัยหรือติดต่อภายนอกอัตโนมัติ"
            elif event.analysis_status != "READY":
                decision, severity, summary = "WAIT_FOR_MODEL_WINDOW", "info", "ค่าวัดยังไม่เข้าเกณฑ์เตือน แต่โมเดลยังมีข้อมูลต่อเนื่องไม่พอ"
            elif not model_fresh:
                decision, severity, summary = "ABSTAIN_STALE_MODEL", "info", "ผลโมเดลไม่ใหม่พอ จึงใช้เพียงการตรวจข้อมูลและรอประเมินรอบใหม่"
            else:
                decision, severity, summary = "CONTINUE_MONITORING", "info", "ประเมินรอบนี้แล้ว ไม่มีข้อเสนอ Alert ใหม่ ไม่ได้หมายความว่าผู้ป่วยปลอดภัย"

            state_changed = self._last_decision.get(event.patient_id) != decision
            should_trace = bool(proposal or duplicate or state_changed
                                or now - self._last_trace.get(event.patient_id, 0) >= self.trace_interval_seconds)
            care = _care_context(conn, event.patient_id) if should_trace else None

            run_id = None
            if should_trace:
                steps = [
                    ("observe_vitals", "OK", {"patient_id": event.patient_id, "source": event.source},
                     {"heart_rate": event.heart_rate, "spo2": event.spo2, "respiratory_rate": event.respiratory_rate, "age_seconds": round(age, 2) if math.isfinite(age) else None}),
                    ("validate_data_contract", "OK" if valid and fresh else "ABSTAIN",
                     {"max_age_seconds": 15, "future_tolerance_seconds": 5}, {"valid": valid, "fresh": fresh}),
                    ("read_trained_model", "OK" if model_fresh else "NOT_READY",
                     {"expected_model": event.model_version or "bidmc-monitor-v1"},
                     {"analysis_status": event.analysis_status, "evaluated_at": event.evaluated_at,
                      "is_anomaly": bool(event.is_anomaly) if model_fresh else False,
                      "anomaly_score": event.anomaly_score if model_fresh else None,
                      "forecast": event.forecast if model_fresh else None}),
                    ("read_reviewed_care_context", "OK", {"patient_id": event.patient_id}, care or {}),
                    ("apply_guarded_alert_policy", "PROPOSE" if proposal else "NO_ACTION",
                     {"automatic_treatment": False, "automatic_external_contact": False},
                     {"decision": decision, "severity": severity, "requires_human_review": bool(proposal)}),
                    ("document_decision", "OK",
                     {"patient_id": event.patient_id, "decision": decision},
                     {"audit_trace": True, "clinical_document_signed": False,
                      "summary": summary}),
                ]
                cursor = conn.execute("""INSERT INTO nurse_agent_runs
                    (patient_id,trigger,decision,severity,requires_human_review,model_version,source,summary,created_at,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                    event.patient_id, "vital_event", decision, severity, int(bool(proposal)),
                    event.model_version or "bidmc-monitor-v1", event.source or "UNKNOWN",
                    summary, now, time.time(),
                ))
                run_id = int(cursor.lastrowid)
                conn.executemany("""INSERT INTO nurse_agent_steps
                    (run_id,sequence,agent_id,tool_name,status,input_json,output_json,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""", [
                    (run_id, index, owner_for_step(name), name, status, _json(tool_input), _json(output), now)
                    for index, (name, status, tool_input, output) in enumerate(steps, start=1)
                ])
                self._last_trace[event.patient_id] = now
                self._last_decision[event.patient_id] = decision
                # Bounded retention avoids unlimited telemetry-derived trace growth.
                conn.execute("""DELETE FROM nurse_agent_steps WHERE run_id IN
                    (SELECT id FROM nurse_agent_runs ORDER BY id DESC LIMIT -1 OFFSET 5000)""")
                conn.execute("""DELETE FROM nurse_agent_runs WHERE id IN
                    (SELECT id FROM nurse_agent_runs ORDER BY id DESC LIMIT -1 OFFSET 5000)""")

            conn.execute("""UPDATE nurse_agent_runtime SET heartbeat=?,status='RUNNING',
                processed_events=processed_events+1,
                alert_proposals=alert_proposals+?,last_error=NULL WHERE id=1""",
                (now, int(bool(proposal))))

        return {"run_id": run_id, "decision": decision, "summary": summary,
                "alert": proposal, "requires_human_review": bool(proposal)}

    def record_failure(self, error: Exception) -> None:
        with closing(connect(self.database)) as conn, conn:
            conn.execute("""UPDATE nurse_agent_runtime SET heartbeat=?,status='ERROR',last_error=? WHERE id=1""",
                         (time.time(), str(error)[:500]))


def link_alert(database: str, run_id: int | None, alert_id: int) -> None:
    if run_id is None:
        return
    with closing(connect(database)) as conn, conn:
        conn.execute("UPDATE nurse_agent_runs SET alert_id=? WHERE id=?", (alert_id, run_id))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _current_report(group: str) -> dict[str, Any] | None:
    pointer = _read_json(MODELS / group / "current.json") or {}
    run_id = pointer.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        return None
    return _read_json(MODELS / group / run_id / "report.json")


def evidence_catalog() -> dict[str, list[dict[str, Any]]]:
    """Return a JSON-only registry; never load model pickle files here."""
    bidmc = _read_json(MODELS / "bidmc_monitor_v1_metadata.json") or {}
    icu = _read_json(MODELS / "physionet2012_ward_core_v1_metadata.json") or {}
    sepsis = _current_report("sepsis2019") or {}
    posture = _current_report("posture") or {}
    datasets = [
        {"id": "bidmc", "name": bidmc.get("dataset", "BIDMC PPG and Respiration Dataset v1.0.0"), "role": "ACTIVE_MONITOR", "access": "open", "source": bidmc.get("source", "https://physionet.org/content/bidmc/1.0.0/"), "fit": "HR/SpO2/RR forecasting and unusual-pattern research; not disease labels"},
        {"id": "pmd", "name": posture.get("dataset", "A Pressure Map Dataset for In-bed Posture Classification v1.0.0"), "role": "RESEARCH_ONLY", "access": "open", "source": posture.get("source", "https://physionet.org/content/pmd/1.0.0/"), "fit": "Three standard bed postures; no pressure-ulcer or elderly-home labels"},
        {"id": "sepsis2019", "name": sepsis.get("dataset", "PhysioNet Challenge 2019 v1.0.0"), "role": "RESEARCH_ONLY", "access": "open", "source": sepsis.get("source", "https://physionet.org/content/challenge-2019/1.0.0/"), "fit": "ICU sepsis benchmark; deliberately disabled for live ward scoring"},
        {"id": "physionet2012", "name": icu.get("dataset", "PhysioNet/CinC Challenge 2012 v1.0.0"), "role": "HISTORICAL_RESEARCH", "access": "open", "source": "https://physionet.org/content/challenge-2012/1.0.0/", "fit": "48-hour ICU mortality endpoint; incompatible with short home-monitor windows"},
    ]
    models = [
        {"id": bidmc.get("model_version", "bidmc-monitor-v1"), "status": "ACTIVE", "dataset_id": "bidmc", "methods": bidmc.get("models", []), "metric": "30-second hold-out MAE", "result": bidmc.get("test_selected_mae", {}), "limitation": "Selected RF does not beat persistence on the held-out test for every signal; anomaly has no labelled accuracy."},
        {"id": "posture-" + str(posture.get("run_id", "not-installed")), "status": "RESEARCH_ONLY", "dataset_id": "pmd", "methods": [posture.get("selected_model", "not installed")], "metric": "subject-split test macro-F1", "result": ((posture.get("metrics") or {}).get(posture.get("selected_model", ""), {}).get("test", {}) or {}).get("macro_f1"), "limitation": "Exploratory test contains three young-adult subjects; runtime accepts compatible maps in shadow mode but has not been validated with real hardware."},
        {"id": "sepsis-" + str(sepsis.get("run_id", "not-installed")), "status": "RESEARCH_ONLY", "dataset_id": "sepsis2019", "methods": [sepsis.get("selected_model", "not installed")], "metric": "external event recall", "result": (((sepsis.get("metrics") or {}).get(sepsis.get("selected_model", ""), {}).get("external_B", {}) or {}).get("event_sensitivity")), "limitation": "Misses most labelled events under the frozen protocol; live scoring is disabled."},
        {"id": icu.get("model_version", "physionet2012-not-installed"), "status": "HISTORICAL_RESEARCH", "dataset_id": "physionet2012", "methods": [icu.get("selected_estimator", "not installed")], "metric": "hold-out ROC-AUC", "result": (icu.get("holdout_test_metrics") or {}).get("roc_auc"), "limitation": "Requires first 48 hours of ICU data and must abstain for the live monitor context."},
    ]
    return {"datasets": datasets, "models": models}


def agent_status(database: str) -> dict[str, Any]:
    import auth
    clause, values = auth.scoped_sql()
    with closing(connect(database)) as conn:
        runtime = conn.execute("SELECT * FROM nurse_agent_runtime WHERE id=1").fetchone()
        hour_ago = time.time() - 3600
        recent = conn.execute("""SELECT COUNT(*) AS runs,
            COALESCE(SUM(requires_human_review),0) AS proposals,
            COALESCE(SUM(decision LIKE 'ABSTAIN%'),0) AS abstentions,
            COALESCE(SUM(decision='CONTINUE_MONITORING'),0) AS model_completed,
            COALESCE(SUM(decision='WAIT_FOR_MODEL_WINDOW'),0) AS waiting_for_window,
            COALESCE(SUM(decision='SUPPRESS_DUPLICATE_ALERT'),0) AS duplicates_suppressed
            FROM nurse_agent_runs WHERE created_at>=? AND """ + clause, (hour_ago, *values)).fetchone()
    data = dict(runtime) if runtime else {"status": "NOT_INITIALIZED"}
    if auth.request_patient_scope.get() is not None:
        data = {key: value for key, value in data.items() if key in {'status', 'heartbeat', 'last_error'}}
    if data.get("heartbeat") and time.time() - data["heartbeat"] > 20:
        data["status"] = "STALE"
    return {
        "runtime": data,
        "last_hour": dict(recent),
        "policy": {
            "automatic_actions": ["validate_data", "read_trained_model", "read_reviewed_care_context", "propose_alert", "enqueue_configured_staff_notification", "write_audit_trace"],
            "human_required": ["diagnosis", "treatment_change", "medication_change", "doctor_or_emergency_dispatch", "close_alert"],
            "cloud_llm_in_safety_loop": False,
        },
        "team": team_manifest(),
        **evidence_catalog(),
    }


def list_runs(database: str, *, limit: int = 30, patient_id: str | None = None) -> list[dict[str, Any]]:
    import auth
    limit = min(max(int(limit), 1), 100)
    with closing(connect(database)) as conn:
        if patient_id:
            rows = conn.execute("SELECT * FROM nurse_agent_runs WHERE patient_id=? ORDER BY id DESC LIMIT ?", (patient_id, limit)).fetchall()
        else:
            clause, values = auth.scoped_sql()
            rows = conn.execute("SELECT * FROM nurse_agent_runs WHERE " + clause + " ORDER BY id DESC LIMIT ?", (*values, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["requires_human_review"] = bool(item["requires_human_review"])
            item["steps"] = [{**dict(step), "input": json.loads(step["input_json"]), "output": json.loads(step["output_json"])}
                             for step in conn.execute("SELECT * FROM nurse_agent_steps WHERE run_id=? ORDER BY sequence", (row["id"],)).fetchall()]
            for step in item["steps"]:
                step.pop("input_json", None)
                step.pop("output_json", None)
            result.append(item)
    return result
