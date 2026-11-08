"""Unit tests for deterministic Modified NEWS2 rule engine and unified quality/abstention gates."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import tempfile
import time
import unittest

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import numpy as np
import test_monitor_portals as isolation  # ensures isolated test DB before app imports

from ai_models import monitor_model
from ai_models.agent_workflow import VitalAlertAgent, VitalEvent
from ai_models.anomaly import check_temporal_and_flatline_gate, check_vital_quality_gate
from ai_models.news2 import (
    calculate_modified_news2,
    score_news2_hr,
    score_news2_rr,
    score_news2_spo2,
)
from ai_models.nurse_agent import NurseAgent
from monitor_service import MonitorWorker, init_monitor_db


class News2RuleEngineTests(unittest.TestCase):
    """Verify exact RCP NEWS2 Scale 1 boundary tables for RR, SpO2, and HR."""

    def test_score_news2_rr_boundaries(self):
        self.assertIsNone(score_news2_rr(None))
        self.assertIsNone(score_news2_rr(float("nan")))
        self.assertIsNone(score_news2_rr(float("inf")))
        self.assertIsNone(score_news2_rr(-1))
        self.assertIsNone(score_news2_rr(0))
        self.assertIsNone(score_news2_rr(61))

        self.assertEqual(score_news2_rr(1), 3)
        self.assertEqual(score_news2_rr(8), 3)
        self.assertEqual(score_news2_rr(9), 1)
        self.assertEqual(score_news2_rr(11), 1)
        self.assertEqual(score_news2_rr(12), 0)
        self.assertEqual(score_news2_rr(20), 0)
        self.assertEqual(score_news2_rr(21), 2)
        self.assertEqual(score_news2_rr(24), 2)
        self.assertEqual(score_news2_rr(25), 3)
        self.assertEqual(score_news2_rr(60), 3)

    def test_score_news2_spo2_boundaries(self):
        self.assertIsNone(score_news2_spo2(None))
        self.assertIsNone(score_news2_spo2(float("nan")))
        self.assertIsNone(score_news2_spo2(49))
        self.assertIsNone(score_news2_spo2(101))

        self.assertEqual(score_news2_spo2(50), 3)
        self.assertEqual(score_news2_spo2(91), 3)
        self.assertEqual(score_news2_spo2(92), 2)
        self.assertEqual(score_news2_spo2(93), 2)
        self.assertEqual(score_news2_spo2(94), 1)
        self.assertEqual(score_news2_spo2(95), 1)
        self.assertEqual(score_news2_spo2(96), 0)
        self.assertEqual(score_news2_spo2(100), 0)

    def test_score_news2_hr_boundaries(self):
        self.assertIsNone(score_news2_hr(None))
        self.assertIsNone(score_news2_hr(float("nan")))
        self.assertIsNone(score_news2_hr(29))
        self.assertIsNone(score_news2_hr(241))

        self.assertEqual(score_news2_hr(30), 3)
        self.assertEqual(score_news2_hr(40), 3)
        self.assertEqual(score_news2_hr(41), 1)
        self.assertEqual(score_news2_hr(50), 1)
        self.assertEqual(score_news2_hr(51), 0)
        self.assertEqual(score_news2_hr(90), 0)
        self.assertEqual(score_news2_hr(91), 1)
        self.assertEqual(score_news2_hr(110), 1)
        self.assertEqual(score_news2_hr(111), 2)
        self.assertEqual(score_news2_hr(130), 2)
        self.assertEqual(score_news2_hr(131), 3)
        self.assertEqual(score_news2_hr(240), 3)

    def test_calculate_modified_news2_risk_levels_and_abstention(self):
        # 1. LOW risk (3 parameters normal -> total 0)
        low = calculate_modified_news2(75, 98, 16)
        self.assertFalse(low["abstain"])
        self.assertEqual(low["total"], 0)
        self.assertEqual(low["level"], "LOW")
        self.assertFalse(low["has_single_red"])
        self.assertEqual(low["parameters_used"], 3)

        # 2. LOW risk with 2 parameters (rr=None -> parameters_used=2)
        low_2p = calculate_modified_news2(95, 95, None)
        self.assertFalse(low_2p["abstain"])
        self.assertEqual(low_2p["total"], 2)
        self.assertEqual(low_2p["level"], "LOW")
        self.assertEqual(low_2p["parameters_used"], 2)
        self.assertIsNone(low_2p["rr_score"])

        # 3. MEDIUM risk via single red score (+3 in a single parameter, total < 5)
        med_red = calculate_modified_news2(78, 98, 30)  # RR=30 -> +3
        self.assertFalse(med_red["abstain"])
        self.assertEqual(med_red["total"], 3)
        self.assertTrue(med_red["has_single_red"])
        self.assertEqual(med_red["level"], "MEDIUM")

        # 4. MEDIUM risk via aggregate total 5-6 without any single +3 red score
        med_total = calculate_modified_news2(115, 92, 9)  # HR:+2, SpO2:+2, RR:+1 -> total=5
        self.assertFalse(med_total["abstain"])
        self.assertEqual(med_total["total"], 5)
        self.assertFalse(med_total["has_single_red"])
        self.assertEqual(med_total["level"], "MEDIUM")

        # 5. HIGH risk via total >= 5 with single red score
        high_combo = calculate_modified_news2(115, 98, 28)  # HR:+2, SpO2:0, RR:+3 -> total=5 + red
        self.assertFalse(high_combo["abstain"])
        self.assertEqual(high_combo["total"], 5)
        self.assertTrue(high_combo["has_single_red"])
        self.assertEqual(high_combo["level"], "HIGH")

        # 6. HIGH risk via total >= 7
        high_total = calculate_modified_news2(135, 90, 26)  # HR:+3, SpO2:+3, RR:+3 -> total=9
        self.assertFalse(high_total["abstain"])
        self.assertEqual(high_total["total"], 9)
        self.assertEqual(high_total["level"], "HIGH")

        # 7. ABSTAIN on artifact inputs
        for bad_hr, bad_spo2, bad_rr in (
            (25, 98, 16),
            (250, 98, 16),
            (80, 45, 16),
            (80, 105, 16),
            (80, 98, 0),
            (80, 98, 65),
            (None, 98, 16),
        ):
            with self.subTest(hr=bad_hr, spo2=bad_spo2, rr=bad_rr):
                res = calculate_modified_news2(bad_hr, bad_spo2, bad_rr)
                self.assertTrue(res["abstain"])
                self.assertEqual(res["level"], "ABSTAIN")
                self.assertIsNone(res["total"])
                self.assertEqual(res["parameters_used"], 0)


class QualityGateAndAbstentionTests(unittest.TestCase):
    """Verify every abstention path in check_vital_quality_gate and check_temporal_and_flatline_gate."""

    def test_all_vital_quality_gate_abstention_paths(self):
        # 1. SENSOR_DISCONNECTED
        for hr, spo2 in ((None, 98), (80, None), (float("nan"), 98), (80, float("inf"))):
            res = check_vital_quality_gate(hr, spo2)
            self.assertTrue(res.abstain)
            self.assertTrue(res.is_device_fault)
            self.assertFalse(res.is_crisis)
            self.assertEqual(res.reason, "SENSOR_DISCONNECTED")

        # 2. SENSOR_DETACHED_ZERO_READING
        for hr, spo2 in ((0, 98), (80, 0), (-5, 98)):
            res = check_vital_quality_gate(hr, spo2)
            self.assertTrue(res.abstain)
            self.assertEqual(res.reason, "SENSOR_DETACHED_ZERO_READING")

        # 3. SENSOR_DETACHED_LOW_SPO2
        res_low_spo2 = check_vital_quality_gate(80, 49.5)
        self.assertTrue(res_low_spo2.abstain)
        self.assertEqual(res_low_spo2.reason, "SENSOR_DETACHED_LOW_SPO2")

        # 4. PHYSIOLOGICALLY_IMPOSSIBLE_SPO2
        res_high_spo2 = check_vital_quality_gate(80, 105.0)
        self.assertTrue(res_high_spo2.abstain)
        self.assertEqual(res_high_spo2.reason, "PHYSIOLOGICALLY_IMPOSSIBLE_SPO2")

        # 5. EXTREME_HR_DELTA_ARTIFACT
        res_delta = check_vital_quality_gate(140.0, 98.0, previous_hr=80.0, time_delta=1.0)
        self.assertTrue(res_delta.abstain)
        self.assertEqual(res_delta.reason, "EXTREME_HR_DELTA_ARTIFACT")

        # 6. PHYSIOLOGICALLY_IMPOSSIBLE_HR (hr < 30 or hr > 240)
        for bad_hr in (25, 29.9, 240.1, 245, 250):
            res_hr = check_vital_quality_gate(bad_hr, 98.0)
            self.assertTrue(res_hr.abstain)
            self.assertEqual(res_hr.reason, "PHYSIOLOGICALLY_IMPOSSIBLE_HR")

        # 7. RESPIRATORY_SENSOR_FAULT (rr <= 0 or rr > 60)
        for bad_rr in (0, -2, 60.5, 65, float("nan")):
            res_rr = check_vital_quality_gate(80.0, 98.0, respiratory_rate=bad_rr)
            self.assertTrue(res_rr.abstain)
            self.assertEqual(res_rr.reason, "RESPIRATORY_SENSOR_FAULT")

    def test_flatline_gate_1d_and_2d(self):
        ts = [1000.0 + i for i in range(60)]

        # 1D flatline
        flat_1d = [75.0] * 60
        res_1d = check_temporal_and_flatline_gate(flat_1d, timestamps=ts, check_flatline=True)
        self.assertTrue(res_1d.abstain)
        self.assertEqual(res_1d.reason, "FLATLINE_DETECTED")

        # 2D multi-channel flatline (HR=75, SpO2=98, RR=16 constant across all 60 seconds)
        flat_2d = np.tile([75.0, 98.0, 16.0], (60, 1))
        res_2d = check_temporal_and_flatline_gate(flat_2d, timestamps=ts, check_flatline=True)
        self.assertTrue(res_2d.abstain)
        self.assertEqual(res_2d.reason, "FLATLINE_DETECTED")


class PipelineIntegrationTests(unittest.TestCase):
    """Verify MonitorWorker, monitor_model.prepare, NurseAgent, and VitalAlertAgent."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="news2-pipeline-tests-")
        self.db = str(Path(self.temp.name) / "test.db")
        init_monitor_db(self.db)
        with sqlite3_conn(self.db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS vital_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id TEXT, heart_rate INTEGER, spo2 INTEGER,
                    status TEXT, timestamp REAL, respiratory_rate INTEGER,
                    simulation_state TEXT, source_record TEXT, source_segment TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id TEXT NOT NULL, severity TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '', recommended_next_step TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'NEW', created_at REAL NOT NULL,
                    episode_key TEXT, merged_into INTEGER, last_seen_at REAL,
                    occurrences INTEGER NOT NULL DEFAULT 1, recovered_at REAL,
                    version INTEGER NOT NULL DEFAULT 1, heart_rate INTEGER, spo2 INTEGER
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS care_plans (
                    id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL,
                    state TEXT NOT NULL, reviewed_at REAL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS care_tasks (
                    id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL,
                    state TEXT NOT NULL, scheduled_at REAL NOT NULL
                )"""
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_monitor_model_prepare_flatline_and_news2(self):
        now = 2000.0
        # Flatline window must abstain with FLATLINE_DETECTED
        flat_history = [
            {
                "timestamp": now - 59 + i,
                "heart_rate": 75.0,
                "spo2": 98.0,
                "respiratory_rate": 16.0,
                "source_segment": "live_sensor:0",
            }
            for i in range(60)
        ]
        flat_res = monitor_model.prepare(flat_history, now=now)
        self.assertEqual(flat_res["status"], "INVALID_DATA")
        self.assertTrue(flat_res["abstain"])
        self.assertEqual(flat_res["abstain_reason"], "FLATLINE_DETECTED")

        # Valid dynamic window includes modified_news2 and abstain=False
        dynamic_history = [
            {
                "timestamp": now - 59 + i,
                "heart_rate": 75.0 + (i % 3),
                "spo2": 98.0,
                "respiratory_rate": 16.0 + (i % 2),
                "source_segment": "live_sensor:0",
            }
            for i in range(60)
        ]
        ready_res = monitor_model.prepare(dynamic_history, now=now)
        self.assertEqual(ready_res["status"], "READY")
        self.assertFalse(ready_res["abstain"])
        self.assertIn("modified_news2", ready_res)
        self.assertEqual(ready_res["modified_news2"]["level"], "LOW")

    def test_monitor_worker_tachypnea_bradypnea_and_artifacts(self):
        now = time.time()
        worker = MonitorWorker(self.db, {"A001": {"name": "Test"}}, "mqtt")

        # Severe tachypnea (RR=30) with normal HR=80, SpO2=98 -> CRITICAL
        tachy = worker.process(
            [{"patient_id": "A001", "timestamp": now, "heart_rate": 80, "spo2": 98, "respiratory_rate": 30}],
            now,
        )
        self.assertEqual(len(tachy), 1)
        self.assertEqual(tachy[0]["status"], "CRITICAL")
        self.assertEqual(tachy[0]["modified_news2"]["rr_score"], 3)

        # Severe bradypnea (RR=6) with normal HR=80, SpO2=98 -> CRITICAL
        brady = worker.process(
            [{"patient_id": "A001", "timestamp": now + 1, "heart_rate": 80, "spo2": 98, "respiratory_rate": 6}],
            now + 1,
        )
        self.assertEqual(len(brady), 1)
        self.assertEqual(brady[0]["status"], "CRITICAL")
        self.assertEqual(brady[0]["modified_news2"]["rr_score"], 3)

        # Artifacts (SpO2=105, HR=250, HR=25, RR=0, RR=65) -> rejected by quality bounds
        artifacts = [
            {"patient_id": "A001", "timestamp": now + 2, "heart_rate": 80, "spo2": 105, "respiratory_rate": 16},
            {"patient_id": "A001", "timestamp": now + 3, "heart_rate": 250, "spo2": 98, "respiratory_rate": 16},
            {"patient_id": "A001", "timestamp": now + 4, "heart_rate": 25, "spo2": 98, "respiratory_rate": 16},
            {"patient_id": "A001", "timestamp": now + 5, "heart_rate": 80, "spo2": 98, "respiratory_rate": 0},
            {"patient_id": "A001", "timestamp": now + 6, "heart_rate": 80, "spo2": 98, "respiratory_rate": 65},
        ]
        self.assertEqual(worker.process(artifacts, now + 6), [])

    def test_nurse_agent_and_vital_alert_agent_rr_and_artifacts(self):
        nurse = NurseAgent(self.db)
        alert_agent = VitalAlertAgent(cooldown_seconds=0)
        now = time.time()

        # 1. Severe tachypnea (RR=30) and bradypnea (RR=6) -> CRITICAL
        for rr in (30, 6):
            self.assertEqual(nurse.triage_vital_signs("A001", 80, 98, rr=rr), "CRITICAL")
            check_res = alert_agent.check_and_alert("A001", 80, 98, rr=rr)
            self.assertTrue(check_res["alert"])
            self.assertFalse(check_res["abstain"])
            self.assertEqual(check_res["status"], "CRITICAL")
            self.assertEqual(check_res["modified_news2"]["rr_score"], 3)

            proc_res = nurse.process(
                VitalEvent(
                    patient_id=f"P_RR_{rr}",
                    heart_rate=80,
                    spo2=98,
                    respiratory_rate=rr,
                    timestamp=now,
                    status="CRITICAL",
                    is_anomaly=False,
                    risk_percent=None,
                ),
                now=now,
            )
            self.assertEqual(proc_res["decision"], "PROPOSE_HUMAN_REVIEW")
            self.assertEqual(proc_res["alert"]["severity"], "critical")

        # 2. Artifacts (SpO2=105, HR=250, HR=25, RR=0, RR=65) -> ABSTAIN without fake alerts
        for hr, spo2, rr in ((80, 105, 16), (250, 98, 16), (25, 98, 16), (80, 98, 0), (80, 98, 65)):
            self.assertEqual(nurse.triage_vital_signs("A001", hr, spo2, rr=rr), "ABSTAIN_INVALID_DATA")
            check_res = alert_agent.check_and_alert("A001", hr, spo2, rr=rr)
            self.assertFalse(check_res["alert"])
            self.assertTrue(check_res["abstain"])
            self.assertEqual(check_res["status"], "INVALID_DATA")

            proc_res = nurse.process(
                VitalEvent(
                    patient_id="A001",
                    heart_rate=hr,
                    spo2=spo2,
                    respiratory_rate=rr,
                    timestamp=now,
                    status="NORMAL",
                    is_anomaly=False,
                    risk_percent=None,
                ),
                now=now,
            )
            self.assertEqual(proc_res["decision"], "ABSTAIN_INVALID_DATA")
            self.assertIsNone(proc_res["alert"])


def sqlite3_conn(db_path: str):
    import sqlite3
    return sqlite3.connect(db_path)


if __name__ == "__main__":
    unittest.main()
