"""Bounded Nurse Agent tests use a disposable SQLite database and no network."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from ai_models.agent_workflow import VitalEvent
from ai_models.nurse_agent import NurseAgent, agent_status, evidence_catalog, link_alert, list_runs


class NurseAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nurse-agent-tests-")
        self.database = str(Path(self.temp.name) / "agent.db")
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executescript("""
            CREATE TABLE agent_alerts (
                id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, severity TEXT NOT NULL,
                status TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE care_plans (
                id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, state TEXT NOT NULL,
                reviewed_at REAL);
            CREATE TABLE care_tasks (
                id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, state TEXT NOT NULL,
                scheduled_at REAL NOT NULL);
            """)
        self.agent = NurseAgent(self.database, trace_interval_seconds=600, alert_cooldown_seconds=300)
        self.now = time.time()

    def tearDown(self):
        self.temp.cleanup()

    def event(self, patient_id="A001", **changes):
        values = dict(patient_id=patient_id, heart_rate=82, spo2=98,
                      respiratory_rate=18, timestamp=self.now, status="NORMAL",
                      is_anomaly=False, risk_percent=None, source="BIDMC_REPLAY",
                      source_record="bidmc_42", analysis_status="READY",
                      evaluated_at=self.now, model_version="bidmc-monitor-v1")
        values.update(changes)
        return VitalEvent(**values)

    def test_normal_run_uses_tools_without_claiming_safety(self):
        result = self.agent.process(self.event(), now=self.now)
        self.assertEqual(result["decision"], "CONTINUE_MONITORING")
        self.assertIsNone(result["alert"])
        runs = list_runs(self.database, patient_id="A001")
        self.assertEqual(len(runs), 1)
        self.assertEqual([step["tool_name"] for step in runs[0]["steps"]], [
            "observe_vitals", "validate_data_contract", "read_trained_model",
            "read_reviewed_care_context", "apply_guarded_alert_policy", "document_decision",
        ])
        self.assertEqual([step["agent_id"] for step in runs[0]["steps"]], [
            "telemetry_agent", "data_quality_agent", "monitoring_agent",
            "care_coordinator_agent", "safety_supervisor", "documentation_agent",
        ])
        self.assertIn("ไม่ได้หมายความว่าผู้ป่วยปลอดภัย", runs[0]["summary"])

    def test_critical_value_proposes_human_review_and_can_link_alert(self):
        result = self.agent.process(self.event(patient_id="B001", spo2=87), now=self.now)
        self.assertEqual(result["decision"], "PROPOSE_HUMAN_REVIEW")
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(result["alert"]["severity"], "critical")
        link_alert(self.database, result["run_id"], 44)
        self.assertEqual(list_runs(self.database, patient_id="B001")[0]["alert_id"], 44)

    def test_restart_safe_persistent_dedup_suppresses_recent_open_alert(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO agent_alerts VALUES (1,'C001','critical','NEW',?)", (self.now - 30,))
        restarted = NurseAgent(self.database, trace_interval_seconds=600, alert_cooldown_seconds=300)
        result = restarted.process(self.event(patient_id="C001", heart_rate=140), now=self.now)
        self.assertEqual(result["decision"], "SUPPRESS_DUPLICATE_ALERT")
        self.assertIsNone(result["alert"])

    def test_stale_data_abstains_even_when_value_crosses_threshold(self):
        result = self.agent.process(self.event(patient_id="A002", spo2=80, timestamp=self.now - 60), now=self.now)
        self.assertEqual(result["decision"], "ABSTAIN_STALE_DATA")
        self.assertIsNone(result["alert"])

    def test_stale_model_cannot_create_anomaly_alert(self):
        result = self.agent.process(self.event(is_anomaly=True, evaluated_at=self.now - 120), now=self.now)
        self.assertIsNone(result['alert'])
        self.assertEqual(result['decision'], 'ABSTAIN_STALE_MODEL')

    def test_decision_transition_is_traced_without_waiting_for_interval(self):
        patient = 'B003'
        first = self.agent.process(self.event(patient_id=patient, analysis_status='INSUFFICIENT_DATA',
            evaluated_at=None), now=self.now)
        second = self.agent.process(self.event(patient_id=patient), now=self.now + 10)
        self.assertEqual(first['decision'], 'WAIT_FOR_MODEL_WINDOW')
        self.assertEqual(second['decision'], 'CONTINUE_MONITORING')
        runs = list_runs(self.database, patient_id=patient)
        self.assertEqual([run['decision'] for run in runs], ['CONTINUE_MONITORING', 'WAIT_FOR_MODEL_WINDOW'])

    def test_reads_only_human_reviewed_care_context(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO care_plans VALUES (1,'A003','ACTIVE',?)", (self.now - 100,))
            conn.execute("INSERT INTO care_plans VALUES (2,'A003','DRAFT',NULL)")
            conn.execute("INSERT INTO care_tasks VALUES (1,1,'PENDING',?)", (self.now - 20,))
            conn.execute("INSERT INTO care_tasks VALUES (2,2,'PENDING',?)", (self.now - 20,))
        result = self.agent.process(self.event(patient_id="A003"), now=self.now)
        run = list_runs(self.database, patient_id="A003")[0]
        care = next(step for step in run["steps"] if step["tool_name"] == "read_reviewed_care_context")
        self.assertEqual(care["output"], {"active_plans": 1, "open_tasks": 1, "overdue_tasks": 1})
        self.assertEqual(result["decision"], "CONTINUE_MONITORING")

    def test_registry_separates_active_from_research_models(self):
        catalog = evidence_catalog()
        active = [model for model in catalog["models"] if model["status"] == "ACTIVE"]
        self.assertEqual([model["dataset_id"] for model in active], ["bidmc"])
        self.assertTrue(all(dataset["role"] != "ACTIVE_MONITOR" for dataset in catalog["datasets"] if dataset["id"] != "bidmc"))
        status = agent_status(self.database)
        self.assertFalse(status["policy"]["cloud_llm_in_safety_loop"])
        self.assertIn("treatment_change", status["policy"]["human_required"])
        self.assertEqual(status["team"]["version"], "care-agent-team-v1")
        self.assertGreaterEqual(len(status["team"]["roles"]), 7)
        self.assertTrue(status["team"]["safety_contract"]["human_approval_for_clinical_action"])


if __name__ == "__main__":
    unittest.main()
