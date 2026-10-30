"""Corrupt/stale stored inference must fail closed, using an isolated database."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from monitor_service import init_monitor_db, patient_state


class StoredMonitorIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ward-monitor-integrity-')
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / 'test.db')
        init_monitor_db(self.database)

    def read(self, payload):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute('INSERT OR REPLACE INTO monitor_results VALUES (?,?,?)',
                         ('A001', json.dumps(payload), 1000))
        with patch('monitor_service.time.time', return_value=1000):
            return patient_state(self.database, 'A001')

    def test_malformed_analysis_is_invalid_not_a_server_error(self):
        for analysis in (None, [], 'READY'):
            with self.subTest(analysis=analysis):
                self.assertEqual(self.read({'timestamp': 1000, 'analysis': analysis})['status'], 'INVALID_DATA')

    def test_missing_or_invalid_inference_time_clears_anomaly_and_forecast(self):
        for evaluated in (None, 'now', True, float('nan'), 1001, 969):
            with self.subTest(evaluated=evaluated):
                result = self.read({'timestamp': 1000, 'status': 'NORMAL', 'is_anomaly': True,
                                    'risk_percent': 99, 'analysis': {'status': 'READY', 'evaluated_at': evaluated,
                                                                  'is_anomaly': True, 'forecast': [1]}})
                self.assertEqual(result['analysis']['status'], 'STALE_ANALYSIS')
                self.assertFalse(result['is_anomaly'])
                self.assertIsNone(result['risk_percent'])
                self.assertIsNone(result['analysis']['forecast'])

    def test_old_or_future_sample_revokes_stored_inference(self):
        for measured in (984, 1003):
            result = self.read({'timestamp': measured, 'is_anomaly': True, 'risk_percent': 99,
                                'analysis': {'status': 'READY', 'evaluated_at': 1000, 'forecast': [1]}})
            self.assertEqual(result['status'], 'STALE_DATA')
            self.assertFalse(result['is_anomaly'])
            self.assertIsNone(result['analysis']['forecast'])


if __name__ == '__main__':
    unittest.main()
