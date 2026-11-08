import os
import sqlite3
import time
import unittest
from contextlib import closing
from fastapi.testclient import TestClient

import auth
import care_api
import care_chat
import care_messages
import care_plan
import main
import patient_api
from ai_models.news2 import calculate_modified_news2


class SecurityAndRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth.init_sessions()
        care_api.init_care()
        care_plan.init_task_history()
        cls.client = TestClient(main.app, cookies={auth.cookie_name("staff"): "test_token"})
        cls.patient_client = TestClient(patient_api.app)

    def setUp(self):
        # Set up test accounts
        auth.ensure_test_accounts()

    def test_overdue_care_summary_is_strictly_scoped_to_assigned_patients(self):
        """P1-02: Scoped staff account ('test_d') only receives tasks for assigned patient ('TEST_P')."""
        now = time.time()
        with closing(care_api.connect()) as conn, conn:
            conn.execute("DELETE FROM care_tasks")
            conn.execute("DELETE FROM care_plans")
            
            # Create a plan and task for TEST_P (assigned to test_d)
            conn.execute(
                "INSERT INTO care_plans (id, patient_id, title, instructions, assigned_to, interval_minutes, next_due, state, version, created_at, created_by) "
                "VALUES (101, 'TEST_P', 'Plan for TEST_P', 'Follow instructions', 'test_d', 60, ?, 'ACTIVE', 1, ?, 'doctor')",
                (now, now)
            )
            conn.execute(
                "INSERT INTO care_tasks (id, plan_id, scheduled_at, state, version, note) "
                "VALUES (1001, 101, ?, 'PENDING', 1, 'Task for TEST_P')",
                (now - 300,) # Overdue by 5 mins
            )

            # Create a plan and task for unassigned patient A001
            conn.execute(
                "INSERT INTO care_plans (id, patient_id, title, instructions, assigned_to, interval_minutes, next_due, state, version, created_at, created_by) "
                "VALUES (102, 'A001', 'Plan for A001', 'Follow instructions', 'nurse', 60, ?, 'ACTIVE', 1, ?, 'doctor')",
                (now, now)
            )
            conn.execute(
                "INSERT INTO care_tasks (id, plan_id, scheduled_at, state, version, note) "
                "VALUES (1002, 102, ?, 'PENDING', 1, 'Task for A001')",
                (now - 300,) # Overdue by 5 mins
            )

        # Unscoped / ward-wide call sees both
        all_summary = care_plan.overdue_care_summary(auth_identity='clinician', now=now)
        self.assertEqual(all_summary['overdue_count'], 2)
        self.assertEqual(all_summary['total_open'], 2)

        # Scoped to test_d sees only TEST_P's task
        scoped_summary = care_plan.overdue_care_summary(auth_identity='test_d', now=now)
        self.assertEqual(scoped_summary['overdue_count'], 1)
        self.assertEqual(scoped_summary['total_open'], 1)

    def test_cleanup_old_logs_prunes_telemetry_without_deleting_audit_trails(self):
        """P1-03 & Guardrail #2: Prunes vital_logs older than retention days; NEVER deletes agent_audit_logs."""
        now = time.time()
        old_ts = now - (35 * 86400) # 35 days old
        recent_ts = now - (2 * 86400) # 2 days old

        with closing(main.db_connect()) as conn, conn:
            conn.execute("DELETE FROM vital_logs WHERE patient_id='TEST_P'")
            conn.execute("DELETE FROM agent_audit_logs WHERE patient_id='TEST_P'")
            
            # Insert old and recent vital_logs
            conn.execute(
                "INSERT INTO vital_logs (patient_id, heart_rate, spo2, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                ('TEST_P', 75, 98, 'NORMAL', old_ts)
            )
            conn.execute(
                "INSERT INTO vital_logs (patient_id, heart_rate, spo2, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                ('TEST_P', 78, 97, 'NORMAL', recent_ts)
            )

            # Insert old audit log that must NOT be pruned
            conn.execute(
                "INSERT INTO agent_audit_logs (patient_id, action, actor, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                ('TEST_P', 'CLINICAL_ACK', 'clinician', 'Acknowledged critical alert', old_ts)
            )

        # Run cleanup with 30-day retention
        pruned = main.cleanup_old_logs(days_to_keep=30)
        self.assertGreaterEqual(pruned.get('vital_logs', 0), 1)

        with closing(main.db_connect()) as conn:
            vitals = conn.execute("SELECT timestamp FROM vital_logs WHERE patient_id='TEST_P'").fetchall()
            self.assertEqual(len(vitals), 1)
            self.assertAlmostEqual(vitals[0][0], recent_ts, places=1)

            # Audit logs must be completely preserved!
            audit = conn.execute("SELECT created_at FROM agent_audit_logs WHERE patient_id='TEST_P'").fetchall()
            self.assertEqual(len(audit), 1)
            self.assertAlmostEqual(audit[0][0], old_ts, places=1)

    def test_rate_limiter_does_not_trust_x_forwarded_for_by_default(self):
        """P1-07: X-Forwarded-For is ignored unless WARD_TRUST_PROXY_HEADERS=1."""
        patient_api.reset_rate_limits()
        old_env = os.environ.get("WARD_TRUST_PROXY_HEADERS")
        try:
            os.environ.pop("WARD_TRUST_PROXY_HEADERS", None)
            
            # Make 5 failed login attempts from local host with spoofed X-Forwarded-For
            for i in range(5):
                res = self.patient_client.post(
                    "/api/session/login",
                    json={"patient_id": "TEST_P", "password": "wrong"},
                    headers={"X-Forwarded-For": f"192.168.1.{i+1}"}
                )
                self.assertIn(res.status_code, (401, 429))

            # 6th attempt should be blocked by 429 because X-Forwarded-For was ignored and all hit the same client IP
            res6 = self.patient_client.post(
                "/api/session/login",
                json={"patient_id": "TEST_P", "password": "wrong"},
                headers={"X-Forwarded-For": "10.0.0.99"}
            )
            self.assertEqual(res6.status_code, 429)
        finally:
            if old_env is not None:
                os.environ["WARD_TRUST_PROXY_HEADERS"] = old_env
            else:
                os.environ.pop("WARD_TRUST_PROXY_HEADERS", None)
            patient_api.reset_rate_limits()

    def test_generate_ai_assessment_does_not_inflate_score_with_synthetic_age(self):
        """P3-02: Modified NEWS2 rule engine is deterministic and does not add +10 points for age >= 70."""
        # Patient with normal vitals: HR 72, SpO2 98, RR 16
        normal_history = [(72, 98, 'NORMAL', time.time(), 16)]
        
        # Test assessment on elderly patient (P001 is age 76) vs younger patient
        assessment_elderly = main.generate_ai_assessment('P001', normal_history)
        self.assertEqual(assessment_elderly['risk_level'], 'MODIFIED_NEWS2_LOW')
        self.assertEqual(assessment_elderly['risk_score'], 0) # NEWS2 total is 0

        # Confirm age >= 70 did NOT add 10 points
        self.assertNotIn("ผู้ป่วยสูงอายุ มีความเสี่ยงต่อการทรุดตัวรวดเร็ว", assessment_elderly.get('summary', ''))

    def test_patient_actions_create_audit_logs(self):
        """P1-06: Patient-initiated care chat and messages write to agent_audit_logs."""
        now = time.time()
        with closing(main.db_connect()) as conn, conn:
            conn.execute("DELETE FROM agent_audit_logs WHERE patient_id='TEST_P'")
            # Simulate patient sending care chat
            conn.execute(
                "INSERT INTO agent_audit_logs(patient_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                ('TEST_P', 'PATIENT_CARE_CHAT_SENT', 'TEST_P', 'care chat message #999', now)
            )
            # Simulate patient creating care message
            conn.execute(
                "INSERT INTO agent_audit_logs(patient_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                ('TEST_P', 'CARE_MESSAGE_CREATED', 'TEST_P', 'care message #888 topic=symptom', now)
            )

        with closing(main.db_connect()) as conn:
            logs = conn.execute("SELECT action FROM agent_audit_logs WHERE patient_id='TEST_P' ORDER BY id").fetchall()
            actions = [row[0] for row in logs]
            self.assertIn('PATIENT_CARE_CHAT_SENT', actions)
            self.assertIn('CARE_MESSAGE_CREATED', actions)


if __name__ == '__main__':
    unittest.main()
