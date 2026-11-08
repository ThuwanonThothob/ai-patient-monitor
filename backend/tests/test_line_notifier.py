"""Unit tests for multi-channel mobile notification service (LINE Messaging API & Telegram).

Verifies:
- Bed Isolation (alerts restricted to specified bed only)
- AI Family-Friendly Presentation (plain Thai, reassuring tone, explicit bed label)
- Staff Alert Presentation (Modified NEWS2, clinical actions)
- Cooldown throttling
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import line_notifier


class LineNotifierTests(unittest.TestCase):
    def setUp(self):
        line_notifier._last_sent.clear()
        line_notifier._target_bed_override = None
        line_notifier._audience_override = None

    def test_not_configured_when_env_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(line_notifier.is_configured())

    def test_configured_when_line_bot_token_set(self):
        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "mock_channel_token"}):
            self.assertTrue(line_notifier.is_configured())

    def test_configured_when_telegram_set(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123", "TELEGRAM_CHAT_ID": "chat456"}):
            self.assertTrue(line_notifier.is_configured())

    def test_bed_isolation_and_filtering(self):
        line_notifier.set_target_bed("A001")
        self.assertTrue(line_notifier.is_bed_allowed("A001"))
        self.assertTrue(line_notifier.is_bed_allowed("a001"))
        self.assertFalse(line_notifier.is_bed_allowed("A002"))
        self.assertFalse(line_notifier.is_bed_allowed("B005"))

        # Multi-bed subscription
        line_notifier.set_target_bed("A001,A002")
        self.assertTrue(line_notifier.is_bed_allowed("A001"))
        self.assertTrue(line_notifier.is_bed_allowed("A002"))
        self.assertFalse(line_notifier.is_bed_allowed("A003"))

        # ALL beds allowed
        line_notifier.set_target_bed("ALL")
        self.assertTrue(line_notifier.is_bed_allowed("A001"))
        self.assertTrue(line_notifier.is_bed_allowed("C020"))

    def test_format_family_vital_message(self):
        msg = line_notifier.format_family_vital_message(
            patient_id="A001",
            severity="critical",
            reason="ระดับออกซิเจนในเลือดลดลงชั่วคราว",
            recommended_next_step="ตรวจวัดซ้ำและให้ออกซิเจน",
            vitals={"heart_rate": 110, "spo2": 88, "respiratory_rate": 22},
            news2_score=7,
        )
        self.assertIn("เตียง A001", msg)
        self.assertIn("รายงานสถานะผู้ป่วยสำหรับญาติ", msg)
        self.assertIn("SpO₂", msg)
        self.assertIn("88%", msg)
        self.assertIn("AI วิเคราะห์และสรุปข้อมูล", msg)
        self.assertIn("การดูแลของทีมพยาบาล", msg)
        self.assertIn("คำแนะนำสำหรับญาติ", msg)
        self.assertIn("ไม่ต้องตื่นตระหนก", msg)

    def test_translate_posture_and_anatomical_hotspots(self):
        self.assertEqual(line_notifier.translate_posture("supine"), "นอนหงาย")
        self.assertEqual(line_notifier.translate_posture("left"), "นอนตะแคงซ้าย")
        self.assertEqual(line_notifier.translate_posture("right"), "นอนตะแคงขวา")
        self.assertEqual(line_notifier.translate_posture("นอนหงาย"), "นอนหงาย")

        left_hotspot, left_tilt = line_notifier.get_anatomical_hotspot("left")
        self.assertIn("ปุ่มกระดูกสะโพกซ้าย", left_hotspot)
        self.assertIn("30 องศา (30° Lateral Tilt)", left_tilt)

        right_hotspot, right_tilt = line_notifier.get_anatomical_hotspot("right")
        self.assertIn("ปุ่มกระดูกสะโพกขวา", right_hotspot)

        supine_hotspot, supine_tilt = line_notifier.get_anatomical_hotspot("supine")
        self.assertIn("ก้นกบ (Sacrum", supine_hotspot)

    def test_format_family_posture_alert_message(self):
        # Pass raw English model output "left" to verify Thai translation and hotspot matching
        msg = line_notifier.format_family_posture_alert_message(
            patient_id="A001",
            posture="left",
            dwell_minutes=120,
            hotspot="ก้นกบ (Sacrum) > 42 mmHg",
            braden_score=11,
        )
        self.assertIn("เตียง A001", msg)
        self.assertIn("แจ้งเตือนรอบการดูแลสำหรับญาติ", msg)
        self.assertIn("นอนตะแคงซ้าย", msg)
        self.assertNotIn("left", msg.lower().split("30° lateral tilt")[0])
        self.assertIn("ปุ่มกระดูกสะโพกซ้าย", msg)
        self.assertIn("2 ชั่วโมง", msg)
        self.assertIn("AI วิเคราะห์และสรุปข้อมูล", msg)
        self.assertIn("30 องศา (30° Lateral Tilt)", msg)
        self.assertIn("คำแนะนำสำหรับญาติ", msg)

    def test_format_family_test_message(self):
        msg = line_notifier.format_family_test_message("A001")
        self.assertIn("เตียง A001", msg)
        self.assertIn("ทดสอบระบบแจ้งเตือนสำหรับญาติผู้ป่วย", msg)
        self.assertIn("การจัดระเบียบแยกเตียง (Bed Isolation)", msg)
        self.assertIn("เตียง A001", msg)
        self.assertIn("AI จัดการข้อมูลสำหรับญาติ", msg)

    def test_format_staff_vital_alert_message(self):
        msg = line_notifier.format_vital_alert_message(
            patient_id="A001",
            severity="critical",
            reason="SpO₂ ต่ำผิดปกติ",
            recommended_next_step="ตรวจวัดซ้ำและให้ออกซิเจน",
            vitals={"heart_rate": 115, "spo2": 88, "respiratory_rate": 24},
            news2_score=7,
        )
        self.assertIn("A001", msg)
        self.assertIn("วิกฤต", msg)
        self.assertIn("SpO₂ 88%", msg)
        self.assertIn("Modified NEWS2 Score: 7", msg)

    def test_format_staff_posture_alert_message(self):
        msg = line_notifier.format_posture_alert_message(
            patient_id="A003",
            posture="นอนหงาย",
            dwell_minutes=120,
            hotspot="ก้นกบ (Sacrum) > 42 mmHg",
            braden_score=11,
        )
        self.assertIn("A003", msg)
        self.assertIn("ถึงกำหนดพลิกตัวทันที", msg)
        self.assertIn("ก้นกบ (Sacrum)", msg)
        self.assertIn("Braden Scale 11/23", msg)
        self.assertIn("30° Lateral Tilt", msg)

    @patch("urllib.request.urlopen")
    def test_send_line_messaging_api_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "valid_token"}):
            success, body = line_notifier.send_line_messaging_api("ทดสอบ")
            self.assertTrue(success)
            self.assertIn("Broadcast", body)

    @patch("urllib.request.urlopen")
    def test_send_telegram_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123", "TELEGRAM_CHAT_ID": "chat456"}):
            success, body = line_notifier.send_telegram("ทดสอบ Telegram")
            self.assertTrue(success)
            self.assertIn("Telegram", body)

    @patch("urllib.request.urlopen")
    def test_dispatch_alert_bed_isolation_and_cooldown(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        line_notifier.set_target_bed("A001")
        line_notifier.set_audience_mode("family")

        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "valid_token"}):
            # Other bed (A002) should be filtered out to protect relative privacy
            res_other = line_notifier.dispatch_alert("A002", "critical", "SpO2 drop", "check patient")
            self.assertFalse(res_other)

            # Target bed (A001) should succeed
            res1 = line_notifier.dispatch_alert("A001", "critical", "SpO2 drop", "check patient")
            self.assertTrue(res1)

            # Immediate second send of the same alert should be throttled by cooldown
            res2 = line_notifier.dispatch_alert("A001", "critical", "SpO2 drop", "check patient")
            self.assertFalse(res2)


if __name__ == "__main__":
    unittest.main()
