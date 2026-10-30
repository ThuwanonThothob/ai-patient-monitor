"""Read-only agent boundaries; no real DB, cloud LLM or medical actions."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException
from assistant_api import ask, Question


def request(audience='patient', subject='A001'):
    return SimpleNamespace(state=SimpleNamespace(audience=audience, subject=subject))


class AssistantTests(unittest.TestCase):
    def test_patient_cannot_override_own_identity(self):
        with patch('assistant_api.patient_state') as read:
            with self.assertRaises(HTTPException) as error:
                ask(Question(message='สรุป', patient_id='B001'), request())
            self.assertEqual(error.exception.status_code, 403)
            read.assert_not_called()

    def test_staff_scope_is_checked_before_tools(self):
        with patch('assistant_api.auth.can_access_patient', return_value=False), patch('assistant_api.patient_state') as read:
            with self.assertRaises(HTTPException) as error:
                ask(Question(message='สรุป', patient_id='B001'), request('staff', 'test_d'))
            self.assertEqual(error.exception.status_code, 403)
            read.assert_not_called()

    def test_stale_measurements_are_not_presented_as_current(self):
        with patch('assistant_api.patient_state', return_value={'status': 'STALE_DATA', 'heart_rate': 199}):
            result = ask(Question(message='ค่าล่าสุด'), request())
        self.assertNotIn('199', result['answer'])
        self.assertIn('เก่าแล้ว', result['answer'])

    def test_summary_selects_tools_and_exposes_trace_without_writing(self):
        with patch('assistant_api.patient_state', return_value={'status': 'NORMAL', 'source': 'TEST_SIMULATION', 'heart_rate': 80,
                'analysis': {'status': 'READY', 'is_anomaly': False}}), \
                patch('assistant_api.patient_views.trends', return_value={'sources': {}}) as trend, \
                patch('assistant_api.patient_views.care', return_value={'open_count': 2, 'done_today': 1}) as care:
            result = ask(Question(message='สรุป'), request())
            trend.assert_called_once_with('A001', 24)
            care.assert_called_once_with('A001')
            self.assertEqual(len(result['steps']), 5)
            self.assertIn('TEST_SIMULATION', result['answer'])
            self.assertIn('ไม่ได้ยืนยันว่าปลอดภัย', result['answer'])
            self.assertEqual(result['mode'], 'READ_ONLY_AGENT')

    def test_empty_question_and_unselected_staff_do_not_run_tools(self):
        with patch('assistant_api.patient_state') as read:
            self.assertEqual(ask(Question(message='สรุป'), request('staff', 'test_d'))['steps'], [])
            with self.assertRaises(HTTPException):
                ask(Question(message='   '), request())
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
