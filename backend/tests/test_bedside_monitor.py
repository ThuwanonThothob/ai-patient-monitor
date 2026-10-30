"""Deterministic bedside-monitor tests; no MQTT broker, network, or real patient data."""
from pathlib import Path
import base64
import json
import sys
import tempfile
import time
import unittest
import zlib

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from bedside_monitor import BedsideService, PostureRuntime


class FakePostureRuntime:
    def __init__(self, prediction='supine', confidence=.91):
        self.model = object()
        self.model_version = 'posture-test-v1'
        self.error = None
        self.prediction = prediction
        self.confidence = confidence

    def load(self):
        return None

    def assess(self, pressure_map):
        frame = np.asarray(pressure_map, dtype=float)
        if frame.shape != (32, 64) or not np.isfinite(frame).all() or frame.sum() <= 0:
            raise ValueError('invalid test pressure map')
        features = np.ones(128, dtype=float) / 128
        return {'prediction': self.prediction, 'confidence': self.confidence, 'features': features,
                'model_version': self.model_version, 'reason': 'ACCEPTED'}


class BedsideMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bedside-tests-')
        self.database = str(Path(self.temp.name) / 'bedside.db')
        self.service = BedsideService(self.database, {'A001': {}}, stale_seconds=30, turn_seconds=30,
                                      posture_runtime=FakePostureRuntime(),
                                      dataset_export_key='test-export-key-123456789')
        self.now = time.time()

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, kind='vital', **changes):
        payload = {'message_type': 'device_health', 'patient_id': 'A001',
                   'device_id': f'A001-{kind}', 'kind': kind, 'timestamp': self.now,
                   'battery_percent': 80, 'signal_quality': .9, 'sensor_attached': True,
                   'calibration_due_at': self.now + 86400, 'source': 'TEST'}
        payload.update(changes)
        return payload

    def test_device_health_detects_fault_and_recovers(self):
        healthy = self.service.process_device(self.payload())
        self.assertEqual(healthy['status'], 'OK')
        self.assertIsNone(healthy['alert'])
        fault = self.service.process_device(self.payload(timestamp=self.now + 1, battery_percent=5, signal_quality=.1))
        self.assertEqual(fault['status'], 'CRITICAL')
        self.assertIn('BATTERY_CRITICAL', fault['issues'])
        self.assertEqual(fault['alert']['episode_key'], 'device_vital')
        current = self.service.patient('A001')['devices'][0]
        self.assertEqual(current['status'], 'CRITICAL')

    def test_missing_heartbeat_alerts_once_until_new_state(self):
        self.service.process_device(self.payload())
        first = self.service.evaluate_stale(self.now + 31)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]['episode_key'], 'device_vital')
        self.assertEqual(self.service.evaluate_stale(self.now + 60), [])
        self.assertEqual(self.service.patient('A001')['devices'][0]['status'], 'STALE')

    def test_pressure_posture_dwell_alert_and_human_label_export(self):
        pressure = np.ones((32, 64)).tolist()
        first = self.service.process_pressure(self.payload('pressure_mat', message_type='pressure_map',
            timestamp=self.now - 40, pressure_map=pressure))
        second = self.service.process_pressure(self.payload('pressure_mat', message_type='pressure_map',
            pressure_map=pressure))
        self.assertEqual(first['prediction'], 'supine')
        self.assertGreaterEqual(second['dwell_seconds'], 39)
        self.assertIn('posture_turn_due', [item['episode_key'] for item in second['alerts']])
        blinded = self.service.patient('A001')['posture']
        self.assertTrue(blinded['model_output_blinded'])
        self.assertEqual(blinded['prediction'], 'HIDDEN_PENDING_GROUND_TRUTH')
        truth = self.service.record_truth(request_key='truth-A001-000001', patient_id='A001',
            observation_id=second['observation_id'], label_type='posture', label='left', notes='checked visually',
            actor='nurse.test', observed_at=self.now)
        duplicate = self.service.record_truth(request_key='truth-A001-000001', patient_id='A001',
            observation_id=second['observation_id'], label_type='posture', label='left', notes='checked visually',
            actor='nurse.test', observed_at=self.now)
        self.assertEqual(truth['id'], duplicate['id'])
        revealed = self.service.patient('A001')['posture']
        self.assertFalse(revealed['model_output_blinded'])
        self.assertEqual(revealed['prediction'], 'supine')
        exported = json.loads(self.service.dataset_jsonl())
        self.assertEqual(exported['label'], 'left')
        self.assertEqual(len(exported['features']), 128)
        self.assertIn('subject_key', exported)
        self.assertNotIn('patient_id', exported)
        self.assertNotIn('recorded_by', exported)

    def test_rejects_bad_identity_values_and_cross_patient_label(self):
        with self.assertRaises(ValueError):
            self.service.process_device(self.payload(patient_id='Z999'))
        with self.assertRaises(ValueError):
            self.service.process_device(self.payload(battery_percent=float('nan')))
        with self.assertRaises(ValueError):
            self.service.process_pressure(self.payload('pressure_mat', message_type='pressure_map', pressure_map=[[1]]))
        with self.assertRaises(ValueError):
            self.service.record_truth(request_key='truth-invalid-001', patient_id='A001', observation_id=999,
                label_type='posture', label='supine', notes='', actor='nurse.test')

    def test_accepts_bounded_compressed_pressure_and_rejects_corruption(self):
        pressure = np.ones((32, 64)).tolist()
        packed = base64.b64encode(zlib.compress(json.dumps(pressure).encode())).decode()
        payload = self.payload('pressure_mat', message_type='pressure_map',
            pressure_encoding='zlib+base64+json', pressure_shape=[32, 64], pressure_data=packed)
        self.assertEqual(self.service.process_pressure(payload)['prediction'], 'supine')
        payload['pressure_data'] = 'not-valid-base64!'
        with self.assertRaises(ValueError):
            self.service.process_pressure(payload)

    def test_export_is_disabled_without_pseudonym_key(self):
        service = BedsideService(str(Path(self.temp.name) / 'no-export.db'), {'A001': {}},
                                 posture_runtime=FakePostureRuntime())
        with self.assertRaises(RuntimeError):
            service.dataset_jsonl()

    def test_real_posture_artifact_is_verified_when_present(self):
        runtime = PostureRuntime()
        runtime.load()
        pointer = runtime.root / 'current.json'
        if not pointer.exists():
            self.skipTest('optional PMD posture model has not been trained')
        self.assertIsNotNone(runtime.model, runtime.error)
        run = json.loads(pointer.read_text())['run_id']
        case_path = next((runtime.root / run / 'cases').glob('*.json'))
        result = runtime.assess(json.loads(case_path.read_text())['pressure_map'])
        self.assertIn(result['prediction'], {'left', 'right', 'supine', 'ABSTAIN'})
        self.assertEqual(len(result['features']), 128)


if __name__ == '__main__':
    unittest.main()
