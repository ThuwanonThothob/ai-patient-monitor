"""AI demo regression: isolated DB, no cloud calls, no real push/contact."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import time
import unittest

import sys
TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import numpy as np
import joblib
from fastapi import HTTPException
from fastapi.testclient import TestClient
import test_monitor_portals as isolation  # establishes isolated DB before importing app
import care_api
import evidence_api
import posture_api
from ai_models import anomaly, monitor_model
from ai_models.anomaly import (
    check_vital_quality_gate,
    evaluate_forecast_error_bounds,
    check_temporal_and_flatline_gate,
)
from ml_pipeline.bidmc import features, WINDOW, KEYS
from ml_pipeline.train_posture import pressure_features, subject_splits, load_data


class EvidenceTests(unittest.TestCase):
    def rows(self):
        rows = np.tile([0., 80., 98., 18.], (100, 1))
        rows[:, 0] = np.arange(100)
        return rows

    def test_future_is_hidden_and_cannot_change_forecast(self):
        first = self.rows()
        future = first.copy(); future[60:, 1:] = [120, 90, 30]
        a = evidence_api.replay(first, 'test', 59, 59)
        b = evidence_api.replay(future, 'test', 59, 59)
        self.assertEqual(a, b)
        self.assertIsNone(a['comparison'])
        self.assertEqual(a['observed_after'], [])
        self.assertEqual(a['analysis']['status'], 'READY')
        before = evidence_api.replay(future, 'test', 59, 88)
        self.assertIsNone(before['comparison'])
        after = evidence_api.replay(future, 'test', 59, 89)
        self.assertEqual(after['analysis']['forecast'], a['analysis']['forecast'])
        self.assertEqual(after['comparison']['heart_rate']['actual'], 120)
        self.assertEqual(after['comparison']['heart_rate']['baseline_absolute_error'], 40)
        self.assertEqual(len(after['feature_evidence']), 7)

    def test_abstention_boundaries_and_invalid_target(self):
        rows = self.rows()
        self.assertEqual(evidence_api.replay(rows, 'test', 10, 10)['evaluation_status'], 'ABSTAIN')
        with self.assertRaises(HTTPException): evidence_api.replay(rows, 'test', 59, 90)
        with self.assertRaises(HTTPException): evidence_api.replay(rows, 'test', 59, 58)
        self.assertEqual(evidence_api.replay(rows, 'test', 80, 90)['evaluation_status'], 'TARGET_OUTSIDE_RECORD')
        rows[75, 2] = np.nan
        result = evidence_api.replay(rows, 'test', 59, 89)
        self.assertEqual(result['evaluation_status'], 'TARGET_WINDOW_INVALID')
        self.assertIsNone(result['comparison'])
        self.assertIsNone(result['observed_after'][15]['spo2'])
        json.dumps(result, allow_nan=False)
        rows[20, 1] = 0
        self.assertEqual(evidence_api.replay(rows, 'test', 59, 89)['evaluation_status'], 'ABSTAIN')

    def test_synthetic_patient_profile_does_not_contaminate_model_features(self):
        # 1. Feature extraction strictly requires (60, 3) and outputs exactly 21 dimensions
        clean_vitals = np.tile([75., 98., 16.], (WINDOW, 1))
        vector = features(clean_vitals)
        self.assertEqual(vector.shape, (21,))
        self.assertEqual(vector.dtype, np.float64)

        # 2. Simulated patient profile data from EHR / Registry
        synthetic_ehr = {
            'patient_id': 'A001',
            'condition': 'เบาหวานชนิดที่ 2 และภาวะหัวใจเต้นผิดจังหวะสังเคราะห์ (Atrial Fibrillation)',
            'diabetes': True,
            'cardiac_arrhythmia': 'AFib',
            'blood_group': 'O+',
            'cholesterol': 245,
            'fasting_glucose': 142,
            'age': 78,
            'mobility': 'BEDBOUND',
        }

        now = 1000.0
        # History containing vital metrics AND synthetic profile metadata
        history_with_profile = [
            {'timestamp': now - 59 + i, 'heart_rate': 75.0, 'spo2': 98.0, 'respiratory_rate': 16.0,
             'source_segment': 'bidmc_test:0', **synthetic_ehr}
            for i in range(WINDOW)
        ]
        prepared_with_profile = monitor_model.prepare(history_with_profile, now=now)
        self.assertEqual(prepared_with_profile['status'], 'READY')
        self.assertEqual(len(prepared_with_profile['_vector']), 21)

        # Alter synthetic conditions (toggle diabetes, change arrhythmia label, mutate age)
        modified_ehr = synthetic_ehr.copy()
        modified_ehr.update({
            'diabetes': False,
            'cardiac_arrhythmia': 'Sinus Rhythm',
            'condition': 'No chronic disease',
            'age': 25,
            'fasting_glucose': 85,
        })
        history_modified = [
            {'timestamp': now - 59 + i, 'heart_rate': 75.0, 'spo2': 98.0, 'respiratory_rate': 16.0,
             'source_segment': 'bidmc_test:0', **modified_ehr}
            for i in range(WINDOW)
        ]
        prepared_modified = monitor_model.prepare(history_modified, now=now)
        self.assertEqual(prepared_modified['status'], 'READY')
        self.assertEqual(len(prepared_modified['_vector']), 21)

        # Zero Synthetic Contamination: The extracted feature vector is completely identical
        np.testing.assert_array_equal(prepared_with_profile['_vector'], prepared_modified['_vector'])

        # 3. Model metadata confirms locked random seeds and disjoint recording splits (30 train, 11 val, 11 test)
        bundle = monitor_model.bundle()
        metadata = bundle['metadata']
        splits = metadata['splits']
        train_set, val_set, test_set = set(splits['train']), set(splits['validation']), set(splits['test'])
        self.assertEqual(len(train_set), 30)
        self.assertEqual(len(val_set), 11)
        self.assertEqual(len(test_set), 11)
        self.assertTrue(train_set.isdisjoint(val_set))
        self.assertTrue(train_set.isdisjoint(test_set))
        self.assertTrue(val_set.isdisjoint(test_set))
        self.assertEqual(metadata['feature_count'], 21)

    def test_abstention_on_extreme_sensor_artifact(self):
        # 1. Sensor detached / Zero readings -> Abstain, device fault, not a patient crisis
        zero_res = check_vital_quality_gate(hr=0, spo2=0)
        self.assertTrue(zero_res.abstain)
        self.assertTrue(zero_res.is_device_fault)
        self.assertFalse(zero_res.is_crisis)
        self.assertEqual(zero_res.reason, 'SENSOR_DETACHED_ZERO_READING')

        # 2. SpO2 < 50% (Probe detached / optical sensor artifact) -> Abstain, device fault
        low_spo2_res = check_vital_quality_gate(hr=80, spo2=45.0)
        self.assertTrue(low_spo2_res.abstain)
        self.assertTrue(low_spo2_res.is_device_fault)
        self.assertFalse(low_spo2_res.is_crisis)
        self.assertEqual(low_spo2_res.reason, 'SENSOR_DETACHED_LOW_SPO2')

        # 3. SpO2 > 100% (Physiologically impossible reading) -> Abstain, device fault
        high_spo2_res = check_vital_quality_gate(hr=80, spo2=104.0)
        self.assertTrue(high_spo2_res.abstain)
        self.assertTrue(high_spo2_res.is_device_fault)
        self.assertFalse(high_spo2_res.is_crisis)
        self.assertEqual(high_spo2_res.reason, 'PHYSIOLOGICALLY_IMPOSSIBLE_SPO2')

        # 4. Sudden noise: HR jump > 50 bpm within 1 second -> Abstain, device fault
        hr_jump_res = check_vital_quality_gate(hr=135.0, spo2=98.0, previous_hr=75.0, time_delta=1.0)
        self.assertTrue(hr_jump_res.abstain)
        self.assertTrue(hr_jump_res.is_device_fault)
        self.assertFalse(hr_jump_res.is_crisis)
        self.assertEqual(hr_jump_res.reason, 'EXTREME_HR_DELTA_ARTIFACT')

        # 5. Normal physiological values -> Pass quality gate
        normal_res = check_vital_quality_gate(hr=76.0, spo2=98.0, previous_hr=74.0, time_delta=1.0)
        self.assertFalse(normal_res.abstain)
        self.assertFalse(normal_res.is_device_fault)
        self.assertFalse(normal_res.is_crisis)
        self.assertEqual(normal_res.reason, 'QUALITY_PASS')

        # 6. Replay pipeline abstention: Injecting SpO2 < 50% or sudden HR jump causes evaluation_status == 'ABSTAIN'
        rows = self.rows()
        rows[25, 2] = 40.0  # SpO2 drops to 40% (sensor detached)
        replay_result = evidence_api.replay(rows, 'test', 59, 89)
        self.assertEqual(replay_result['evaluation_status'], 'ABSTAIN')
        self.assertIsNone(replay_result['comparison'])

    def test_pressure_features_validate_raw_counts_and_disjoint_subjects(self):
        high = np.full((32, 64), 3844.)
        self.assertEqual(pressure_features(high).shape, (128,))
        self.assertAlmostEqual(pressure_features(high).sum(), 1.)
        np.testing.assert_allclose(pressure_features(high), pressure_features(high * 2))
        for bad in (np.zeros((32, 64)), np.ones((64, 32)), np.full((32, 64), -1), np.full((32, 64), np.nan)):
            with self.assertRaises(ValueError): pressure_features(bad)
        split = subject_splits()
        self.assertEqual([len(split[k]) for k in ('train', 'validation', 'test')], [7, 3, 3])
        self.assertEqual(len(set(sum(split.values(), []))), 13)

    def test_posture_artifacts_reproduce_actual_inference_and_metrics(self):
        if not (posture_api.ROOT / 'current.json').exists(): self.skipTest('PMD not trained')
        report = posture_api.store.load()
        x, y, groups, entries, _, _, _ = load_data()
        folder = posture_api.ROOT / report['run_id']
        self.assertEqual(hashlib.sha256((folder / 'models.joblib').read_bytes()).hexdigest(), report['model_sha256'])
        bundle = joblib.load(folder / 'models.joblib')
        mask = np.isin(groups, report['splits']['test'])
        actual = bundle['models'][report['selected_model']].predict(x[mask])
        self.assertAlmostEqual(float((actual == y[mask]).mean()), report['metrics'][report['selected_model']]['test']['accuracy'])
        case = posture_api.store.case(report['cases'][0]['id'], report)
        inference = bundle['models'][report['selected_model']].predict(pressure_features(case['pressure_map'])[None, :])[0]
        self.assertEqual(case['prediction'], inference)
        self.assertFalse(report['live_enabled'])

    def test_posture_tamper_is_rejected(self):
        if not (posture_api.ROOT / 'current.json').exists(): self.skipTest('PMD not trained')
        report = posture_api.store.load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / report['run_id']; (run / 'cases').mkdir(parents=True)
            (run / 'cases' / (report['cases'][0]['id'] + '.json')).write_text('{}')
            with self.assertRaises(HTTPException) as error:
                posture_api.PostureStore(root).case(report['cases'][0]['id'], report)
            self.assertEqual(error.exception.status_code, 503)

    def test_evaluate_forecast_error_bounds_clinical_metrics(self):
        # 1. Normal valid evaluation metrics
        actuals = [70.0, 72.0, 75.0, 80.0]
        predictions = [71.0, 72.0, 80.0, 82.0]
        # abs errors: [1.0, 0.0, 5.0, 2.0] -> sum = 8.0, mae = 2.0
        # squared errors: [1.0, 0.0, 25.0, 4.0] -> sum = 30.0, mean = 7.5, rmse = sqrt(7.5) = 2.7386
        # tolerance = 3.0 -> errors > 3.0: [5.0] (1 of 4 points -> exceed_rate = 0.25)
        res = evaluate_forecast_error_bounds(actuals, predictions, clinical_tolerance=3.0)
        self.assertFalse(res['abstain'])
        self.assertAlmostEqual(res['mae'], 2.0)
        self.assertAlmostEqual(res['rmse'], np.sqrt(7.5))
        self.assertAlmostEqual(res['exceed_tolerance_rate'], 0.25)
        self.assertEqual(res['sample_count'], 4)
        self.assertAlmostEqual(res['clinical_tolerance'], 3.0)
        self.assertAlmostEqual(res['p95_abs_error'], float(np.percentile([1.0, 0.0, 5.0, 2.0], 95)))

        # 2. Tolerances matching clinical guidelines (HR: 5 bpm, SpO2: 2%, RR: 3 brpm)
        hr_eval = evaluate_forecast_error_bounds([80.0, 82.0], [84.0, 88.0], clinical_tolerance=5.0)
        self.assertFalse(hr_eval['abstain'])
        self.assertEqual(hr_eval['exceed_tolerance_rate'], 0.5)  # 6.0 > 5.0 exceeds

        spo2_eval = evaluate_forecast_error_bounds([98.0, 96.0], [97.0, 93.0], clinical_tolerance=2.0)
        self.assertFalse(spo2_eval['abstain'])
        self.assertEqual(spo2_eval['exceed_tolerance_rate'], 0.5)  # 3.0 > 2.0 exceeds

        rr_eval = evaluate_forecast_error_bounds([16.0, 18.0], [18.0, 22.0], clinical_tolerance=3.0)
        self.assertFalse(rr_eval['abstain'])
        self.assertEqual(rr_eval['exceed_tolerance_rate'], 0.5)  # 4.0 > 3.0 exceeds

        # 3. Guardrail / Abstention on invalid inputs
        # Empty inputs
        self.assertEqual(evaluate_forecast_error_bounds([], []), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})
        # Length mismatch
        self.assertEqual(evaluate_forecast_error_bounds([70.0, 72.0], [70.0]), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})
        # NaN in actuals or predictions
        self.assertEqual(evaluate_forecast_error_bounds([70.0, np.nan], [70.0, 72.0]), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})
        self.assertEqual(evaluate_forecast_error_bounds([70.0, 72.0], [70.0, np.nan]), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})
        # Inf in inputs
        self.assertEqual(evaluate_forecast_error_bounds([70.0, np.inf], [70.0, 72.0]), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})
        # None inputs
        self.assertEqual(evaluate_forecast_error_bounds(None, [70.0]), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})
        # Invalid clinical tolerance (< 0 or NaN)
        self.assertEqual(evaluate_forecast_error_bounds([70.0], [71.0], clinical_tolerance=-1.0), {'abstain': True, 'reason': 'INVALID_EVALUATION_INPUT'})

    def test_temporal_discontinuity_and_incomplete_window_gate(self):
        # 1. Incomplete window (< 60 points) -> Abstain, device fault
        short_window = [75.0] * 59
        short_res = check_temporal_and_flatline_gate(short_window, required_length=60)
        self.assertTrue(short_res.abstain)
        self.assertEqual(short_res.reason, 'INSUFFICIENT_WINDOW_LENGTH')
        self.assertTrue(short_res.is_device_fault)
        self.assertFalse(short_res.is_crisis)

        # None window -> Abstain
        none_res = check_temporal_and_flatline_gate(None)
        self.assertTrue(none_res.abstain)
        self.assertEqual(none_res.reason, 'INSUFFICIENT_WINDOW_LENGTH')

        # 2. Valid 60-second window with continuous monotonic timestamps -> Pass
        valid_window = [72.0 + (i % 3) for i in range(60)]
        valid_ts = [1000.0 + i for i in range(60)]
        pass_res = check_temporal_and_flatline_gate(valid_window, timestamps=valid_ts, required_length=60)
        self.assertFalse(pass_res.abstain)
        self.assertEqual(pass_res.reason, 'QUALITY_PASS')
        self.assertFalse(pass_res.is_device_fault)
        self.assertFalse(pass_res.is_crisis)

        # 3. Temporal discontinuity: Non-monotonic / reversed / duplicate timestamps (t[i] <= t[i-1])
        non_mono_ts = [1000.0 + i for i in range(59)] + [1058.0]  # duplicate 1058
        non_mono_res = check_temporal_and_flatline_gate(valid_window, timestamps=non_mono_ts)
        self.assertTrue(non_mono_res.abstain)
        self.assertEqual(non_mono_res.reason, 'TEMPORAL_DISCONTINUITY')
        self.assertTrue(non_mono_res.is_device_fault)
        self.assertFalse(non_mono_res.is_crisis)

        # 4. Temporal discontinuity: Time gap > 5 seconds (e.g. packet loss / disconnect)
        gap_ts = [1000.0 + i for i in range(30)] + [1036.0 + i for i in range(30)]  # gap of 7.0s between 1029 and 1036
        gap_res = check_temporal_and_flatline_gate(valid_window, timestamps=gap_ts)
        self.assertTrue(gap_res.abstain)
        self.assertEqual(gap_res.reason, 'TEMPORAL_DISCONTINUITY')
        self.assertTrue(gap_res.is_device_fault)
        self.assertFalse(gap_res.is_crisis)

        # 5. Timestamp count mismatch
        mismatch_res = check_temporal_and_flatline_gate(valid_window, timestamps=[1000.0, 1001.0])
        self.assertTrue(mismatch_res.abstain)
        self.assertEqual(mismatch_res.reason, 'TEMPORAL_DISCONTINUITY')

        # 6. Flatline detection when check_flatline=True
        flat_window = [70.0] * 60
        flat_res = check_temporal_and_flatline_gate(flat_window, timestamps=valid_ts, check_flatline=True)
        self.assertTrue(flat_res.abstain)
        self.assertEqual(flat_res.reason, 'FLATLINE_DETECTED')

    def test_clinical_validation_report_governance_and_disclaimers(self):
        report_path = BACKEND_DIR.parent / 'docs' / 'CLINICAL_VALIDATION_REPORT.md'
        self.assertTrue(report_path.exists(), 'CLINICAL_VALIDATION_REPORT.md must exist in docs/')
        content = report_path.read_text(encoding='utf-8')

        # Core safety boundaries & disclaimers
        self.assertIn('AI ไม่อยู่ใน Safety Loop ของการสั่งการรักษา', content)
        self.assertIn('ห้ามใช้คำว่า "Accuracy"', content)
        self.assertIn('Not Approved for Autonomous Clinical Care', content)

        # Clinical tolerance criteria documented
        self.assertIn('5.0 bpm', content)
        self.assertIn('2.0%', content)
        self.assertIn('3.0 brpm', content)

        # Stratified metrics documented
        self.assertIn('RMSE', content)
        self.assertIn('P95', content)
        self.assertIn('1.977', content)
        self.assertIn('0.292', content)
        self.assertIn('1.272', content)

        # Disjoint splits and Sepsis external cross-hospital reality
        self.assertIn('Recording-disjoint', content)
        self.assertIn('AUROC Illusion', content)
        self.assertIn('3.4%', content)
        self.assertIn('Human-in-the-Loop', content)


class CareApiTests(unittest.TestCase):
    def setUp(self):
        isolation.main.init_db()
        with closing(sqlite3.connect(isolation.auth.DB)) as conn, conn:
            for table in ('care_events', 'care_tasks', 'care_plans', 'portal_sessions', 'login_attempts'):
                conn.execute('DELETE FROM ' + table)
        self.client = TestClient(isolation.main.app)
        self.client.post('/api/session/login', json={'password': 'test-only-password'})

    def tearDown(self): self.client.close()

    def create(self, interval=0):
        response = self.client.post('/api/care/patients/A001/plans', json={
            'title': 'Check demo sensor', 'instructions': 'Verify demo connection', 'assigned_to': 'Demo team',
            'first_due': time.time() - 1, 'interval_minutes': interval})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def get(self): return self.client.get('/api/care/patients/A001').json()

    def activate(self, plan_id, version=1):
        response = self.client.patch(f'/api/care/plans/{plan_id}', json={'version': version, 'state': 'ACTIVE', 'demo_review_confirmed': True})
        self.assertEqual(response.status_code, 200, response.text)

    def test_all_new_endpoints_are_staff_only(self):
        paths = ['/api/evidence/status', '/api/research/posture/status', '/api/care/patients/A001']
        unused = TestClient(isolation.main.app)
        for path in paths: self.assertEqual(unused.get(path).status_code, 401)
        unused.close()
        patient = TestClient(isolation.patient_api.app)
        patient.post('/api/session/login', json={'patient_id': 'A001'})
        for path in paths: self.assertEqual(patient.get(path).status_code, 404)
        patient.close()

    def test_draft_confirmation_version_workflow_and_patient_isolation(self):
        plan_id = self.create()
        care_api.materialize()
        self.assertEqual(self.get()['tasks'], [])
        self.assertEqual(self.client.patch(f'/api/care/plans/{plan_id}', json={'version': 1, 'state': 'ACTIVE'}).status_code, 422)
        self.activate(plan_id)
        self.assertEqual(self.client.patch(f'/api/care/plans/{plan_id}', json={'version': 1, 'state': 'PAUSED'}).status_code, 409)
        task = self.get()['tasks'][0]
        self.assertEqual(self.client.get('/api/care/patients/B001').json()['tasks'], [])
        route = f"/api/care/tasks/{task['id']}"
        self.assertEqual(self.client.patch(route, json={'version': 1, 'state': 'DONE', 'note': 'not acknowledged'}).status_code, 409)
        self.assertEqual(self.client.patch(route, json={'version': 1, 'state': 'ACKNOWLEDGED'}).status_code, 200)
        self.assertEqual(self.client.patch(route, json={'version': 1, 'state': 'SKIPPED', 'note': 'stale'}).status_code, 409)
        self.assertEqual(self.client.patch(route, json={'version': 2, 'state': 'DONE', 'note': '  '}).status_code, 422)
        self.assertEqual(self.client.patch(route, json={'version': 2, 'state': 'DONE', 'note': 'Checked'}).status_code, 200)
        result = self.get()
        self.assertEqual(result['plans'][0]['state'], 'COMPLETED')
        self.assertEqual(result['events'][0]['action'], 'TASK_DONE')
        self.assertEqual(result['events'][0]['actor'], 'clinician')
        self.assertFalse(result['automatic_external_contact'])
        self.assertIn('Checked', self.client.get('/api/care/patients/A001/report').text)

    def test_pause_resume_and_recurrence_no_task_flood(self):
        plan_id = self.create(10); self.activate(plan_id)
        care_api.materialize(time.time() + 86400)
        self.assertEqual(len(self.get()['tasks']), 1)
        self.client.patch(f'/api/care/plans/{plan_id}', json={'version': 2, 'state': 'PAUSED'})
        self.assertEqual(self.get()['tasks'][0]['state'], 'CANCELLED')
        self.activate(plan_id, 3)
        task = self.get()['tasks'][0]
        self.assertEqual(len(self.get()['tasks']), 2)
        route = f"/api/care/tasks/{task['id']}"
        self.assertEqual(self.client.patch(route, json={'version': 1, 'state': 'SKIPPED', 'note': 'Demonstration'}).status_code, 200)
        care_api.materialize()
        self.assertEqual(len(self.get()['tasks']), 2)
        due = self.get()['plans'][0]['next_due']
        self.assertGreater(due, time.time() + 590)
        care_api.materialize(due + 1); care_api.materialize(due + 2)
        self.assertEqual(len(self.get()['tasks']), 3)

    def test_provenance_routes_hide_labels_and_reject_ward_ids(self):
        evidence = self.client.get('/api/evidence/status')
        if evidence.status_code == 200:
            data = evidence.json(); record = data['records'][0]['id']
            self.assertEqual(self.client.get('/api/evidence/records/A001').status_code, 404)
            train_id = data['metadata']['splits']['train'][0]
            self.assertEqual(self.client.get('/api/evidence/records/' + train_id).status_code, 404)
            text = self.client.get(f'/api/evidence/records/{record}/report').text
            self.assertIn('research only', text)
        status = self.client.get('/api/research/posture/status').json()
        if status['status'] == 'READY':
            hidden = self.client.get('/api/research/posture/cases/0').json()
            for key in ('label', 'position', 'source_file', 'id'): self.assertNotIn(key, hidden)
            revealed = self.client.get('/api/research/posture/cases/0?reveal=true').json()
            self.assertIn(revealed['label'], status['classes'])
            self.assertEqual(self.client.get('/api/research/posture/cases/-1').status_code, 404)
            self.assertNotIn('label', self.client.get('/api/research/posture/cases').text)
            self.assertEqual(self.client.get('/api/research/posture/report').status_code, 200)

    def test_input_validation(self):
        self.assertEqual(self.client.get('/api/care/patients/A999').status_code, 404)
        body = {'title': 'Test', 'instructions': 'Check', 'assigned_to': 'Demo', 'first_due': time.time(), 'interval_minutes': -2}
        self.assertEqual(self.client.post('/api/care/patients/A001/plans', json=body).status_code, 422)
        body['interval_minutes'] = 0; body['actor'] = 'forged'
        self.assertEqual(self.client.post('/api/care/patients/A001/plans', json=body).status_code, 422)

    def test_old_open_task_not_hidden_by_new_completed_history(self):
        plan_id = self.create(); self.activate(plan_id)
        with closing(care_api.connect()) as conn, conn:
            conn.executemany("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'DONE')",
                             [(plan_id, time.time() + i + 1) for i in range(110)])
        result = self.get()
        self.assertEqual(result['task_count'], 111)
        self.assertEqual(result['open_task_count'], 1)
        self.assertTrue(result['task_list_truncated'])
        self.assertEqual(len(result['tasks']), 100)
        self.assertEqual(result['tasks'][0]['state'], 'PENDING')
