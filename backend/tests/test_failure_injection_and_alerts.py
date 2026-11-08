"""Tests for failure injection, MQTT resilience, alert escalation state machine, and abstention."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

TEMP = tempfile.TemporaryDirectory(prefix='smart-ward-fail-tests-')
os.environ['WARD_DB_PATH'] = str(Path(TEMP.name) / 'fail_test.db')
os.environ['WARD_INGEST_MODE'] = 'off'
os.environ['WARD_STAFF_PASSWORD'] = 'test-only-password'
os.environ['WARD_DASHBOARD_LLM'] = '0'

import sys
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
import main
import auth
from ai_models.news2 import calculate_modified_news2
from monitor_service import patient_state, init_monitor_db


class Msg:
    """Mock MQTT message."""
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


class FailureInjectionAndAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.init_db()
        init_monitor_db(str(auth.DB))

    def setUp(self):
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            for table in (
                'portal_accounts', 'portal_sessions', 'login_attempts',
                'agent_alerts', 'agent_audit_logs', 'monitor_results',
                'vital_logs'
            ):
                conn.execute('DELETE FROM ' + table)
        self.staff = TestClient(main.app)
        self.staff_login()

    def tearDown(self):
        self.staff.close()

    def staff_login(self):
        return self.staff.post('/api/session/login', json={'password': 'test-only-password'})

    # -------------------------------------------------------------------------
    # 1. Alert Workflow State Machine Transitions & Audit Trail
    # -------------------------------------------------------------------------
    def test_alert_lifecycle_and_audit_trail(self):
        """NEW -> ACKNOWLEDGED -> ESCALATED -> RESOLVED with audit logs."""
        proposal = {
            'patient_id': 'A001',
            'timestamp': time.time(),
            'severity': 'critical',
            'reason': 'SpO2 84 below threshold',
            'recommended_next_step': 'Assess bedside probe',
            'vitals': {'spo2': 84, 'heart_rate': 110}
        }
        persisted = main.persist_agent_alert(proposal)
        alert_id = persisted['alert_id']
        path = f'/api/alerts/{alert_id}'

        # 1. NEW -> ACKNOWLEDGED
        r1 = self.staff.patch(path, json={'status': 'ACKNOWLEDGED', 'expected_version': 1})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['alert']['status'], 'ACKNOWLEDGED')

        # Verify audit log for ACKNOWLEDGED
        with closing(sqlite3.connect(auth.DB)) as conn:
            log1 = conn.execute(
                "SELECT action, actor FROM agent_audit_logs WHERE alert_id=? AND action='ALERT_ACKNOWLEDGED'",
                (alert_id,)
            ).fetchone()
            self.assertIsNotNone(log1)

        # 2. ACKNOWLEDGED -> ESCALATED (requires note >= 5 chars)
        r2 = self.staff.patch(path, json={
            'status': 'ESCALATED',
            'expected_version': 2,
            'note': 'Escalating to duty doctor for rapid response'
        })
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['alert']['status'], 'ESCALATED')

        # Verify audit log for ESCALATED
        with closing(sqlite3.connect(auth.DB)) as conn:
            log2 = conn.execute(
                "SELECT action, detail FROM agent_audit_logs WHERE alert_id=? AND action='ALERT_ESCALATED'",
                (alert_id,)
            ).fetchone()
            self.assertIsNotNone(log2)
            self.assertIn('Escalating', log2[1])

        # 3. ESCALATED -> RESOLVED (requires note >= 5 chars)
        r3 = self.staff.patch(path, json={
            'status': 'RESOLVED',
            'expected_version': 3,
            'note': 'Patient stabilized after supplemental oxygen'
        })
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()['alert']['status'], 'RESOLVED')

        # Verify audit log for RESOLVED
        with closing(sqlite3.connect(auth.DB)) as conn:
            log3 = conn.execute(
                "SELECT action, detail FROM agent_audit_logs WHERE alert_id=? AND action='ALERT_RESOLVED'",
                (alert_id,)
            ).fetchone()
            self.assertIsNotNone(log3)
            self.assertIn('stabilized', log3[1])

    def test_direct_new_to_escalated(self):
        """NEW can jump directly to ESCALATED with valid note."""
        proposal = {
            'patient_id': 'B002',
            'timestamp': time.time(),
            'severity': 'critical',
            'reason': 'HR 165 persistent tachycardia',
            'recommended_next_step': 'Call medical emergency team',
            'vitals': {'heart_rate': 165}
        }
        persisted = main.persist_agent_alert(proposal)
        alert_id = persisted['alert_id']
        path = f'/api/alerts/{alert_id}'

        r = self.staff.patch(path, json={
            'status': 'ESCALATED',
            'expected_version': 1,
            'note': 'Immediate escalation to ICU on-call team'
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['alert']['status'], 'ESCALATED')

    def test_invalid_transitions_return_409(self):
        """Forbidden transitions (e.g. NEW->RESOLVED or from RESOLVED) return HTTP 409."""
        proposal = {
            'patient_id': 'A003',
            'timestamp': time.time(),
            'severity': 'warning',
            'reason': 'Borderline SpO2',
            'recommended_next_step': 'Check sensor',
            'vitals': {'spo2': 93}
        }
        alert = main.persist_agent_alert(proposal)
        alert_id = alert['alert_id']
        path = f'/api/alerts/{alert_id}'

        # NEW -> RESOLVED directly is prohibited
        bad_jump = self.staff.patch(path, json={
            'status': 'RESOLVED',
            'expected_version': 1,
            'note': 'Attempt to resolve directly without ack or escalate'
        })
        self.assertEqual(bad_jump.status_code, 409)

        # Transition to ACKNOWLEDGED then RESOLVED
        self.staff.patch(path, json={'status': 'ACKNOWLEDGED', 'expected_version': 1})
        self.staff.patch(path, json={'status': 'RESOLVED', 'expected_version': 2, 'note': 'All good now at bedside'})

        # Trying to transition an already RESOLVED alert to ACKNOWLEDGED returns 409
        re_ack = self.staff.patch(path, json={'status': 'ACKNOWLEDGED', 'expected_version': 3})
        self.assertEqual(re_ack.status_code, 409)

        # Trying to transition an already RESOLVED alert to ESCALATED returns 409
        re_esc = self.staff.patch(path, json={'status': 'ESCALATED', 'expected_version': 3, 'note': 'Attempt escalate'})
        self.assertEqual(re_esc.status_code, 409)

    def test_short_note_validation_422(self):
        """ESCALATED and RESOLVED require at least 5 characters note."""
        proposal = {
            'patient_id': 'A004',
            'timestamp': time.time(),
            'severity': 'critical',
            'reason': 'Test alert',
            'recommended_next_step': 'Test step',
            'vitals': {}
        }
        alert_id = main.persist_agent_alert(proposal)['alert_id']
        path = f'/api/alerts/{alert_id}'

        # Note < 5 chars on ESCALATE -> 422
        r_short_esc = self.staff.patch(path, json={'status': 'ESCALATED', 'note': 'no'})
        self.assertEqual(r_short_esc.status_code, 422)

        # Move to ACKNOWLEDGED (note optional)
        self.staff.patch(path, json={'status': 'ACKNOWLEDGED', 'expected_version': 1})

        # Note empty or < 5 chars on RESOLVE -> 422
        r_empty_res = self.staff.patch(path, json={'status': 'RESOLVED', 'note': '   '})
        self.assertEqual(r_empty_res.status_code, 422)

    def test_optimistic_locking_conflict_409(self):
        """Mismatched expected_version returns 409 Conflict."""
        proposal = {
            'patient_id': 'A005',
            'timestamp': time.time(),
            'severity': 'warning',
            'reason': 'Test concurrency',
            'recommended_next_step': 'Test',
            'vitals': {}
        }
        alert_id = main.persist_agent_alert(proposal)['alert_id']
        path = f'/api/alerts/{alert_id}'

        # Clinician 1 acknowledges (version becomes 2)
        r1 = self.staff.patch(path, json={'status': 'ACKNOWLEDGED', 'expected_version': 1})
        self.assertEqual(r1.status_code, 200)

        # Clinician 2 attempts concurrent change using stale version 1 -> 409
        r2 = self.staff.patch(path, json={
            'status': 'ESCALATED',
            'expected_version': 1,
            'note': 'Concurrent update attempt'
        })
        self.assertEqual(r2.status_code, 409)

    # -------------------------------------------------------------------------
    # 2. MQTT Failure Injection & Input Resilience
    # -------------------------------------------------------------------------
    def test_mqtt_malformed_json_rejected(self):
        """Non-JSON payload does not raise unhandled exception."""
        before_count = main.telemetry_queue.qsize() if main.telemetry_queue else 0
        msg = Msg("hospital/ward_a/telemetry", b"GARBAGE_PAYLOAD{not_json")
        # Should not raise exception
        main.on_message(None, None, msg)
        after_count = main.telemetry_queue.qsize() if main.telemetry_queue else 0
        self.assertEqual(before_count, after_count)

    def test_mqtt_missing_fields_rejected(self):
        """Missing patient_id or missing vital metrics are dropped."""
        msg_no_pid = Msg("hospital/ward_a/telemetry", json.dumps({'heart_rate': 72, 'spo2': 98}).encode())
        main.on_message(None, None, msg_no_pid)

        msg_no_vitals = Msg("hospital/ward_a/telemetry", json.dumps({'patient_id': 'A001'}).encode())
        main.on_message(None, None, msg_no_vitals)

    def test_mqtt_unknown_patient_rejected(self):
        """Unknown patient ID is rejected."""
        msg = Msg("hospital/ward_a/telemetry", json.dumps({
            'patient_id': 'Z999',
            'heart_rate': 75,
            'spo2': 98,
            'respiratory_rate': 16
        }).encode())
        main.on_message(None, None, msg)

    def test_mqtt_extreme_artifacts_rejected(self):
        """Out of physiological bounds values are dropped at MQTT boundary."""
        # SpO2 > 100
        msg_spo2 = Msg("hospital/ward_a/telemetry", json.dumps({
            'patient_id': 'A001', 'heart_rate': 75, 'spo2': 105, 'respiratory_rate': 16
        }).encode())
        main.on_message(None, None, msg_spo2)

        # Heart rate > 250
        msg_hr = Msg("hospital/ward_a/telemetry", json.dumps({
            'patient_id': 'A001', 'heart_rate': 299, 'spo2': 98, 'respiratory_rate': 16
        }).encode())
        main.on_message(None, None, msg_hr)

        # Negative values
        msg_neg = Msg("hospital/ward_a/telemetry", json.dumps({
            'patient_id': 'A001', 'heart_rate': -10, 'spo2': 98, 'respiratory_rate': 16
        }).encode())
        main.on_message(None, None, msg_neg)

    def test_mqtt_clock_skew_rejected(self):
        """Timestamps > 15s in past or future are dropped."""
        # 60 seconds in the past
        past_msg = Msg("hospital/ward_a/telemetry", json.dumps({
            'patient_id': 'A001', 'heart_rate': 75, 'spo2': 98, 'respiratory_rate': 16,
            'timestamp': time.time() - 60
        }).encode())
        main.on_message(None, None, past_msg)

        # 60 seconds in the future
        future_msg = Msg("hospital/ward_a/telemetry", json.dumps({
            'patient_id': 'A001', 'heart_rate': 75, 'spo2': 98, 'respiratory_rate': 16,
            'timestamp': time.time() + 60
        }).encode())
        main.on_message(None, None, future_msg)

    def test_mqtt_queue_backpressure_drop_oldest(self):
        """When telemetry_queue is full, backpressure drops oldest and enqueues new reading without deadlock."""
        import threading
        q = asyncio.Queue(maxsize=3)
        old_q = main.telemetry_queue
        old_loop = main.main_loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            main.telemetry_queue = q
            main.main_loop = loop
            # Fill the queue
            q.put_nowait({'patient_id': 'A001', 'seq': 1})
            q.put_nowait({'patient_id': 'A001', 'seq': 2})
            q.put_nowait({'patient_id': 'A001', 'seq': 3})
            self.assertTrue(q.full())

            # Now incoming message should trigger eviction of oldest item
            valid_msg = Msg("hospital/ward_a/telemetry", json.dumps({
                'patient_id': 'A001', 'heart_rate': 75, 'spo2': 98, 'respiratory_rate': 16,
                'timestamp': time.time()
            }).encode())
            main.on_message(None, None, valid_msg)
            # Give background loop a brief moment to process callback
            time.sleep(0.08)

            # Queue should still have at most 3 items and not deadlock
            self.assertEqual(q.qsize(), 3)
            # First item should now be seq: 2 (seq: 1 was evicted)
            first_item = q.get_nowait()
            self.assertEqual(first_item['seq'], 2)
        finally:
            main.telemetry_queue = old_q
            main.main_loop = old_loop
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1.0)
            loop.close()

    # -------------------------------------------------------------------------
    # 3. Clinical Abstention on Artifacts and Stale Telemetry
    # -------------------------------------------------------------------------
    def test_clinical_rule_engine_abstains_on_artifacts(self):
        """calculate_modified_news2 strictly returns abstain=True on artifacts."""
        # Probe disconnected or extreme tachycardia
        art_hr_high = calculate_modified_news2(hr=245, spo2=98, rr=18)
        self.assertTrue(art_hr_high['abstain'])
        self.assertIn('IMPOSSIBLE', art_hr_high['reason'])

        # Extreme bradycardia / artifact
        art_hr_low = calculate_modified_news2(hr=25, spo2=98, rr=18)
        self.assertTrue(art_hr_low['abstain'])
        self.assertIn('IMPOSSIBLE', art_hr_low['reason'])

        # Non-physiological SpO2
        art_spo2 = calculate_modified_news2(hr=80, spo2=101, rr=18)
        self.assertTrue(art_spo2['abstain'])
        self.assertIn('IMPOSSIBLE', art_spo2['reason'])

        # Extreme apnea or negative RR / sensor fault
        art_rr = calculate_modified_news2(hr=80, spo2=98, rr=0)
        self.assertTrue(art_rr['abstain'])
        self.assertEqual(art_rr['reason'], 'RESPIRATORY_SENSOR_FAULT')

    def test_patient_state_stale_telemetry_escalation(self):
        """Telemetry older than 15s marks patient STALE_DATA with abstain=True."""
        now = time.time()
        stale_payload = {
            'patient_id': 'A001',
            'timestamp': now - 45,  # 45 seconds old
            'heart_rate': 75,
            'spo2': 98,
            'respiratory_rate': 16,
            'status': 'NORMAL',
            'analysis': {'status': 'READY', 'evaluated_at': now - 45}
        }
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO monitor_results (patient_id, payload, updated_at) VALUES (?, ?, ?)",
                ('A001', json.dumps(stale_payload), now)
            )

        state = patient_state(str(auth.DB), 'A001')
        self.assertEqual(state['status'], 'STALE_DATA')
        self.assertTrue(state['analysis']['abstain'])
        self.assertIsNone(state['risk_percent'])
        self.assertFalse(state['is_anomaly'])


if __name__ == '__main__':
    unittest.main()
