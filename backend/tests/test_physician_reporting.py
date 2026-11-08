"""Unit tests for Physician SBAR Clinical Reporting System.

Verifies:
- Deterministic SBAR generation with RCP Modified NEWS2, Braden score, and EPUAP turning metrics.
- Accurate Braden Scale subscales & risk stratification (Bedbound = 11/23 High Risk).
- Text & DOCX report export integrity.
- Authenticated FastAPI endpoints for physician reporting.
"""

from io import BytesIO
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import auth
import main
import reporting


class PhysicianReportingTests(unittest.TestCase):
    def test_braden_score_calculation(self):
        bedbound = reporting.calculate_braden_score("Bedbound", "Bedbound frailty")
        self.assertEqual(bedbound["total"], 11)
        self.assertEqual(bedbound["tier"], "HIGH_RISK")
        self.assertIn("High Risk", bedbound["label_th"])
        self.assertEqual(len(bedbound["subscales"]), 6)
        self.assertEqual(bedbound["subscales"]["activity"]["score"], 1)

        mobile = reporting.calculate_braden_score("Assisted mobility", "Hypertension")
        self.assertEqual(mobile["total"], 16)
        self.assertEqual(mobile["tier"], "MILD_RISK")

    def test_generate_physician_sbar_report_structure(self):
        sbar = reporting.generate_physician_sbar_report("A001")
        self.assertIn("metadata", sbar)
        self.assertIn("situation", sbar)
        self.assertIn("background", sbar)
        self.assertIn("assessment", sbar)
        self.assertIn("recommendation", sbar)

        self.assertEqual(sbar["metadata"]["patient_id"], "A001")
        self.assertIn("Safety Disclaimer", sbar["metadata"]["safety_note"])

        # Situation
        sit = sbar["situation"]
        self.assertIn("acuity_label", sit)
        self.assertIn("news2_total", sit)
        self.assertIn("news2_scores", sit)
        self.assertIn("current_posture", sit)

        # Background
        bg = sbar["background"]
        self.assertIn("baseline_vitals", bg)
        self.assertIn("braden_scale", bg)
        self.assertEqual(bg["braden_scale"]["max"], 23)

        # Assessment
        asm = sbar["assessment"]
        self.assertIn("latest_vitals", asm)
        self.assertIn("vital_statistics_24h", asm)
        self.assertIn("turning_compliance", asm)
        self.assertIn("ai_anomaly_detection", asm)

        # Recommendation
        rec = sbar["recommendation"]
        self.assertTrue(len(rec["clinical_actions"]) >= 2)
        self.assertTrue(any("EPUAP" in act or "พลิกตัว" in act for act in rec["clinical_actions"]))

    def test_format_physician_sbar_text(self):
        sbar = reporting.generate_physician_sbar_report("A001")
        text = reporting.format_physician_sbar_text(sbar)
        self.assertIn("SMART WARD · PHYSICIAN CLINICAL SBAR HANDOFF & CARE REPORT", text)
        self.assertIn("[S — SITUATION:", text)
        self.assertIn("[B — BACKGROUND:", text)
        self.assertIn("[A — ASSESSMENT:", text)
        self.assertIn("[R — RECOMMENDATION:", text)
        self.assertIn("Modified NEWS2", text)
        self.assertIn("Braden Scale", text)
        self.assertIn("EPUAP", text)
        self.assertIn("Safety Disclaimer", text)

    def test_create_physician_sbar_docx(self):
        sbar = reporting.generate_physician_sbar_report("A001")
        docx_bytes = reporting.create_physician_sbar_docx(sbar)
        self.assertTrue(isinstance(docx_bytes, bytes))
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))
        self.assertGreater(len(docx_bytes), 15000)

    def test_backward_compatibility_handoff(self):
        profile = {"name": "Test Patient", "condition": "COPD", "mobility": "Bedbound"}
        history = [{"heart_rate": 88, "spo2": 95, "respiratory_rate": 20, "timestamp": 1700000000}]
        assessment = {"stats": {"avg_hr": 88, "avg_spo2": 95}}

        text = reporting.format_patient_handoff_text("A001", profile, history, assessment)
        self.assertIn("SBAR", text)
        self.assertIn("A001", text)

        docx_bytes = reporting.create_patient_handoff_docx("A001", profile, history, assessment)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))

    def test_doctor_report_endpoints_with_auth(self):
        client = TestClient(main.app)
        try:
            # 1. Unauthenticated request must be rejected with 401
            unauth = client.get("/api/patient/A001/doctor-report")
            self.assertEqual(unauth.status_code, 401)

            # 2. Authenticate as staff
            login_res = client.post("/api/session/login", json={"username": "central", "password": "central1234"})
            self.assertEqual(login_res.status_code, 200)

            # 3. GET JSON Doctor Report
            res = client.get("/api/patient/A001/doctor-report")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["metadata"]["patient_id"], "A001")
            self.assertIn("situation", data)
            self.assertIn("recommendation", data)

            # 4. GET Plain Text Doctor Report
            res_txt = client.get("/api/patient/A001/doctor-report/text")
            self.assertEqual(res_txt.status_code, 200)
            self.assertIn("text/plain", res_txt.headers.get("content-type", ""))
            self.assertIn("PHYSICIAN CLINICAL SBAR HANDOFF", res_txt.text)

            # 5. GET DOCX Document Doctor Report
            res_doc = client.get("/api/patient/A001/doctor-report/document")
            self.assertEqual(res_doc.status_code, 200)
            self.assertEqual(
                res_doc.headers.get("content-type"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            self.assertTrue(res_doc.content.startswith(b"PK\x03\x04"))

            # 6. Non-existent patient returns 404
            not_found = client.get("/api/patient/NONEXISTENT999/doctor-report")
            self.assertEqual(not_found.status_code, 404)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
