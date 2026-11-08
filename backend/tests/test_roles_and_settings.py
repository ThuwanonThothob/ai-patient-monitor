"""Tests for Change 1 (User Settings API) and Change 2 (Doctor / Patient / Central Role Separation,
1-Doctor-Per-Patient DB constraint, cross-access blocking, WebSocket scoping, and audit logging)."""
from __future__ import annotations

from contextlib import closing
import sqlite3
import time
import unittest

from fastapi.testclient import TestClient

import test_monitor_portals as isolation
import auth
import care_chat
import main
import patient_api


class RolesAndSettingsTests(unittest.TestCase):
    def setUp(self):
        main.init_db()
        patient_api.reset_rate_limits()
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            for table in (
                "care_chat_messages",
                "agent_audit_logs",
                "portal_sessions",
                "login_attempts",
                "user_settings",
            ):
                conn.execute("DELETE FROM " + table)
        auth.ensure_test_accounts()
        self.staff = TestClient(main.app)
        self.patient = TestClient(patient_api.app)

    def tearDown(self):
        patient_api.reset_rate_limits()
        self.staff.close()
        self.patient.close()

    def test_one_doctor_per_patient_database_constraint(self):
        """A patient has exactly one doctor, enforced by PRIMARY KEY(patient_id) in patient_doctor_assignments."""
        doc = auth.get_patient_doctor("A001")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["doctor_id"], "doctor5")

        # Re-assigning the same doctor is idempotent
        same = auth.assign_patient_doctor("A001", "doctor5", "นพ. วิชัย ใจดี")
        self.assertEqual(same["doctor_id"], "doctor5")

        # Attempting to assign a second doctor without overwrite raises sqlite3.IntegrityError
        with self.assertRaises(sqlite3.IntegrityError):
            auth.assign_patient_doctor("A001", "dr_napat", "พญ. ณภัทร สุขใจ", overwrite=False)

        # Raw SQL INSERT of a second row for the same patient also raises sqlite3.IntegrityError
        with closing(sqlite3.connect(auth.DB)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                with conn:
                    conn.execute(
                        "INSERT INTO patient_doctor_assignments(patient_id, doctor_id, doctor_display_name, assigned_at) VALUES (?,?,?,?)",
                        ("A001", "dr_anong", "พญ. อนงค์ รักษ์ดี", time.time()),
                    )

    def test_doctor5_is_assigned_exactly_five_patients_and_blocked_from_others(self):
        """Doctor role ('doctor5') sees and manages only their 5 assigned patients (A001-A004, B001)."""
        res = self.staff.post("/api/session/login", json={"username": "doctor5", "password": "doctor1234"})
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertEqual(payload["role_type"], "doctor")
        self.assertTrue(payload["chat_enabled"])

        expected_five = ["A001", "A002", "A003", "A004", "B001"]
        profile = self.staff.get("/api/session/profile").json()
        self.assertEqual([p["patient_id"] for p in profile["assigned_patients"]], expected_five)

        for route in ("/api/monitor/patients", "/api/patients", "/api/triage"):
            items = self.staff.get(route).json()["patients"]
            self.assertEqual(sorted(p["patient_id"] for p in items), expected_five)

        # Allowed access to own assigned patients
        self.assertEqual(self.staff.get("/api/patient/A001/details").status_code, 200)
        self.assertEqual(self.staff.get("/api/patient/B001/details").status_code, 200)

        # Cross-access attempts to unassigned patients must be blocked (403) and audit-logged
        for forbidden_pid in ("A005", "B002", "C001", "TEST_P"):
            for path in (
                f"/api/patient/{forbidden_pid}/details",
                f"/api/patient/{forbidden_pid}/trends",
                f"/api/patient/{forbidden_pid}/timeline",
                f"/api/care/patients/{forbidden_pid}",
                f"/api/care-chat/{forbidden_pid}",
            ):
                with self.subTest(pid=forbidden_pid, path=path):
                    self.assertEqual(self.staff.get(path).status_code, 403)
            self.assertEqual(
                self.staff.post(
                    f"/api/care-chat/{forbidden_pid}",
                    json={"client_key": f"forbid-key-{forbidden_pid}-0001", "message": "cross access"},
                ).status_code,
                403,
            )

        with closing(sqlite3.connect(auth.DB)) as conn:
            actions = [
                r[0]
                for r in conn.execute(
                    "SELECT action FROM agent_audit_logs WHERE actor='doctor5'"
                ).fetchall()
            ]
        self.assertIn("PATIENT_DATA_VIEWED", actions)
        self.assertIn("UNAUTHORIZED_PATIENT_ACCESS", actions)

    def test_bidirectional_chat_only_between_assigned_doctor_and_patient_pair(self):
        """Doctor5 <-> A001 bidirectional chat works; other doctors get 403 on A001 chat."""
        doc_login = self.staff.post("/api/session/login", json={"username": "doctor5", "password": "doctor1234"})
        self.assertEqual(doc_login.status_code, 200)
        pat_login = self.patient.post("/api/session/login", json={"patient_id": "A001"})
        self.assertEqual(pat_login.status_code, 200)

        # Verify A001 sees doctor5 as their single responsible doctor
        pat_profile = self.patient.get("/api/session/profile").json()
        self.assertEqual(pat_profile["care_team"]["subject"], "doctor5")
        self.assertIn("วิชัย", pat_profile["care_team"]["display_name"])

        # Doctor5 sees all 5 assigned patients in chat conversation list
        convs = self.staff.get("/api/care-chat/conversations").json()["conversations"]
        self.assertEqual(sorted(c["patient_id"] for c in convs), ["A001", "A002", "A003", "A004", "B001"])

        # Patient A001 sends message to doctor5
        p_send = self.patient.post(
            "/api/me/chat",
            json={"client_key": "a001-msg-to-doctor5-001", "message": "สวัสดีคุณหมอวิชัย วันนี้หายใจโล่งขึ้นครับ"},
        )
        self.assertEqual(p_send.status_code, 201)

        # Doctor5 reads and replies
        d_hist = self.staff.get("/api/care-chat/A001")
        self.assertEqual(d_hist.status_code, 200)
        self.assertEqual(len(d_hist.json()["messages"]), 1)

        d_send = self.staff.post(
            "/api/care-chat/A001",
            json={"client_key": "doctor5-reply-a001-001", "message": "ดีมากครับ เดี๋ยวหมอติดตามค่า SpO2 ต่อเนื่องนะครับ"},
        )
        self.assertEqual(d_send.status_code, 201)

        p_hist = self.patient.get("/api/me/chat").json()
        self.assertEqual(len(p_hist["messages"]), 2)
        self.assertEqual(p_hist["participants"]["care_team"]["subject"], "doctor5")

        # Another doctor (test_d or dr_napat) cannot read or send to A001's chat
        other_doc = TestClient(main.app)
        try:
            other_doc.post("/api/session/login", json={"username": "dr_napat", "password": "doctor1234"})
            self.assertEqual(other_doc.get("/api/care-chat/A001").status_code, 403)
            self.assertEqual(
                other_doc.post(
                    "/api/care-chat/A001",
                    json={"client_key": "napat-illegal-msg-0001", "message": "should fail"},
                ).status_code,
                403,
            )
        finally:
            other_doc.close()

        # Verify audit log captured both views and sends
        with closing(sqlite3.connect(auth.DB)) as conn:
            a001_actions = [
                r[0]
                for r in conn.execute(
                    "SELECT action FROM agent_audit_logs WHERE patient_id='A001'"
                ).fetchall()
            ]
        self.assertIn("PATIENT_CARE_CHAT_SENT", a001_actions)
        self.assertIn("CARE_CHAT_VIEWED", a001_actions)
        self.assertIn("CARE_CHAT_SENT", a001_actions)
        self.assertIn("PATIENT_CARE_CHAT_VIEWED", a001_actions)

    def test_central_role_sees_all_patients_and_doctors_but_has_no_chat_endpoints(self):
        """Central role ('central') sees all 60 beds and responsible doctors, and gets 403 on all chat endpoints."""
        res = self.staff.post("/api/session/login", json={"username": "central", "password": "central1234"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["role_type"], "central")
        self.assertFalse(body["chat_enabled"])

        directory = self.staff.get("/api/patients?page_size=100").json()
        self.assertEqual(directory["registered_patient_count"], 60)
        self.assertEqual(len(directory["patients"]), 60)
        for item in directory["patients"]:
            self.assertTrue(item.get("doctor"), f"Missing doctor name for {item['patient_id']}")
            self.assertTrue(item.get("assigned_staff_id"), f"Missing assigned_staff_id for {item['patient_id']}")

        triage = self.staff.get("/api/triage").json()
        self.assertEqual(triage["total"], 60)
        self.assertTrue(all(item.get("doctor") for item in triage["patients"]))

        ops = self.staff.get("/api/operations/status").json()
        self.assertFalse(ops["chat_enabled"])
        self.assertEqual(ops["chat_unread"], 0)
        self.assertEqual(ops["unclaimed_messages"], 0)
        self.assertEqual(ops["role_type"], "central")

        dash_res = self.staff.get("/api/dashboard/overview")
        self.assertEqual(dash_res.status_code, 200)

        # Every chat and messaging endpoint must return 403 for Central role
        for chat_path in (
            "/api/care-chat/conversations",
            "/api/care-chat/status",
            "/api/care-chat/unread-summary",
            "/api/care-chat/A001",
            "/api/care-chat/TEST_P",
            "/api/care-messages",
        ):
            with self.subTest(chat_path=chat_path):
                self.assertEqual(self.staff.get(chat_path).status_code, 403)

        self.assertEqual(
            self.staff.post(
                "/api/care-chat/A001",
                json={"client_key": "central-chat-attempt-001", "message": "central cannot chat"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.staff.post("/api/patient/A001/chat", json={"message": "central ai chat attempt"}).status_code,
            403,
        )
        self.assertEqual(
            self.staff.post("/api/assistant/ask", json={"message": "สรุปข้อมูล", "patient_id": "A001"}).status_code,
            403,
        )

    def test_user_settings_persistence_per_user(self):
        """Settings are saved and retrieved per user across sessions."""
        self.staff.post("/api/session/login", json={"username": "doctor5", "password": "doctor1234"})
        initial = self.staff.get("/api/session/settings").json()
        self.assertFalse(initial["settings"]["night_shift"])
        self.assertTrue(initial["settings"]["sound_enabled"])

        updated = self.staff.put(
            "/api/session/settings",
            json={
                "night_shift": True,
                "sound_enabled": False,
                "warning_sound_enabled": True,
                "ai_default_tab": "evidence",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertTrue(updated.json()["settings"]["night_shift"])
        self.assertFalse(updated.json()["settings"]["sound_enabled"])
        self.assertTrue(updated.json()["settings"]["warning_sound_enabled"])
        self.assertEqual(updated.json()["settings"]["ai_default_tab"], "evidence")

        # Another user ('central') still has default settings
        central_client = TestClient(main.app)
        try:
            central_client.post("/api/session/login", json={"username": "central", "password": "central1234"})
            central_settings = central_client.get("/api/session/settings").json()["settings"]
            self.assertFalse(central_settings["night_shift"])
            self.assertTrue(central_settings["sound_enabled"])
        finally:
            central_client.close()


if __name__ == "__main__":
    unittest.main()
