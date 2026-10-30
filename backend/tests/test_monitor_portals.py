"""Local regression tests: isolated SQLite; no Gemini or MQTT network calls."""
import asyncio
import copy
import os
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory(prefix='smart-ward-tests-')
os.environ['WARD_DB_PATH'] = str(Path(TEMP.name) / 'test.db')
os.environ['WARD_INGEST_MODE'] = 'off'
os.environ['WARD_STAFF_PASSWORD'] = 'test-only-password'
os.environ['WARD_DASHBOARD_LLM'] = '0'
import sys
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import main
import patient_api
import auth
if auth.DB.resolve() != (Path(TEMP.name) / 'test.db').resolve() or main.INGEST_MODE != 'off':
    raise RuntimeError('Test isolation was overridden by environment configuration; refusing to touch any database')
from ai_models import monitor_model
from ai_models.trained_risk import assess_patient_risk
from monitor_service import MonitorWorker, patient_state, worker_status
from test_simulation import TestPatientSimulator, simulated_reading
from ml_pipeline.bidmc import KEYS, load_recordings, valid_values


class PortalTests(unittest.TestCase):
    def setUp(self):
        main.init_db()
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            for table in ('portal_accounts', 'care_messages', 'care_chat_messages', 'portal_sessions', 'login_attempts', 'monitor_results', 'monitor_worker', 'nurse_agent_steps', 'nurse_agent_runs', 'agent_scenario_runs', 'agent_alerts', 'agent_audit_logs', 'vital_logs'):
                conn.execute('DELETE FROM ' + table)
            conn.execute("UPDATE nurse_agent_runtime SET status='STARTING',processed_events=0,alert_proposals=0,last_error=NULL")
        self.staff = TestClient(main.app)
        self.patient = TestClient(patient_api.app)

    def tearDown(self):
        self.staff.close()
        self.patient.close()

    def patient_login(self, patient_id='A001'):
        return self.patient.post('/api/session/login', json={'patient_id': patient_id})

    def staff_login(self):
        return self.staff.post('/api/session/login', json={'password': 'test-only-password'})

    def test_staff_requires_authentication(self):
        self.assertEqual(self.staff.get('/api/monitor/patients').status_code, 401)
        self.assertEqual(self.staff.post('/api/session/login', json={'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.staff_login().status_code, 200)
        self.assertEqual(len(self.staff.get('/api/monitor/patients').json()['patients']), 60)

    def test_research_is_staff_only_and_never_a_patient_endpoint(self):
        self.assertEqual(self.staff.get('/api/research/sepsis/status').status_code, 401)
        self.patient_login()
        self.assertEqual(self.patient.get('/api/research/sepsis/status').status_code, 404)
        self.staff.cookies.update(self.patient.cookies)
        self.assertEqual(self.staff.get('/api/research/sepsis/status').status_code, 401)
        self.staff_login()
        result = self.staff.get('/api/research/sepsis/status')
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['live_enabled'])

    def test_research_rejects_training_and_live_ward_ids(self):
        self.staff_login()
        self.assertEqual(self.staff.post('/api/research/sepsis/train').status_code, 404)
        self.assertEqual(self.staff.get('/api/research/sepsis/cases?split=train').status_code, 422)
        self.assertEqual(self.staff.get('/api/research/sepsis/cases?limit=10000').status_code, 422)

    def test_research_real_artifact_and_text_export(self):
        self.staff_login()
        status = self.staff.get('/api/research/sepsis/status').json()
        if status['status'] != 'READY':
            self.skipTest('Download/train the optional research dataset first')
        self.assertEqual(self.staff.get('/api/research/sepsis/cases/A001').status_code, 404)
        listing = self.staff.get('/api/research/sepsis/cases?limit=1').json()
        self.assertEqual(listing['run_id'], status['run_id'])
        case_id = listing['cases'][0]['id']
        case = self.staff.get('/api/research/sepsis/cases/' + case_id).json()
        hour = case['timeline'][0]['hour']
        result = self.staff.get(f'/api/research/sepsis/cases/{case_id}/summary?hour={hour}')
        self.assertEqual(result.status_code, 200)
        self.assertIn(case_id, result.text)
        self.assertIn('attachment;', result.headers['content-disposition'])
        self.assertEqual(self.staff.get(f'/api/research/sepsis/cases/{case_id}/summary?hour=NaN').status_code, 422)
        self.assertEqual(self.staff.get('/api/research/sepsis/report').status_code, 200)

    def test_ward_text_report_is_grounded_not_registry_measurements(self):
        self.staff_login()
        result = self.staff.get('/api/patient/A001/report/text')
        self.assertEqual(result.status_code, 200)
        self.assertIn('Evidence-grounded', result.text)
        self.assertIn('ไม่มีข้อมูล', result.text)

    def test_patient_id_is_session_bound(self):
        self.assertEqual(self.patient_login('a001').status_code, 200)
        data = self.patient.get('/api/me?patient_id=B001').json()
        self.assertEqual(data['patient_id'], 'A001')
        self.assertEqual(data['monitor']['patient_id'], 'A001')
        self.assertNotIn('audit', data)
        for route in ('/api/patients', '/api/patient/B001/details', '/api/monitor/patients'):
            self.assertEqual(self.patient.get(route).status_code, 404)
        self.assertIn('A001', self.patient.get('/api/me/report').text)

    def test_invalid_id_rejected(self):
        self.assertEqual(self.patient_login('A021').status_code, 401)
        self.assertEqual(self.patient_login("A001' OR 1=1").status_code, 401)

    def test_patient_cookie_cannot_access_staff(self):
        self.patient_login()
        self.staff.cookies.update(self.patient.cookies)
        self.assertEqual(self.staff.get('/api/patients').status_code, 401)
        self.assertEqual(self.staff.patch('/api/alerts/1', json={'status': 'RESOLVED'}).status_code, 401)

    def test_cross_port_origin_rejected(self):
        self.staff_login()
        self.assertEqual(self.staff.get('/api/monitor/status', headers={'Origin': 'http://localhost:3001'}).status_code, 403)
        self.assertEqual(self.patient.post('/api/session/login', json={'patient_id': 'A001'}, headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_logout_and_expiry_revoke_session(self):
        self.patient_login()
        saved = dict(self.patient.cookies)
        self.assertEqual(self.patient.post('/api/session/logout').status_code, 200)
        self.patient.cookies.update(saved)
        self.assertEqual(self.patient.get('/api/me').status_code, 401)
        self.patient_login()
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            conn.execute('UPDATE portal_sessions SET expires=0')
        self.assertEqual(self.patient.get('/api/me').status_code, 401)

    def test_websocket_subject_and_authorization(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.staff.websocket_connect('/ws/vitals', headers={'origin': 'http://localhost:3000'}):
                pass
        self.patient_login()
        with self.patient.websocket_connect('/ws/me?patient_id=B001', headers={'origin': 'http://localhost:3001'}) as ws:
            self.assertEqual(ws.receive_json()['patient_id'], 'A001')

    def test_audit_actor_cannot_be_forged(self):
        self.staff_login()
        alert = main.persist_agent_alert({'patient_id': 'A001', 'timestamp': time.time(), 'severity': 'warning',
                                         'reason': 'test', 'recommended_next_step': 'review', 'vitals': {}})
        result = self.staff.patch('/api/alerts/' + str(alert['alert_id']), json={'status': 'ACKNOWLEDGED', 'actor': 'fake-doctor'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['alert']['assigned_to'], 'clinician')

    def test_episodes_dedup_and_require_note_and_fresh_workflow_version(self):
        self.staff_login()
        proposal = {'patient_id': 'A001', 'timestamp': time.time(), 'severity': 'critical',
                    'reason': 'SpO2 85 below threshold', 'recommended_next_step': 'review', 'vitals': {'spo2': 85}}
        first = main.persist_agent_alert(proposal)
        self.assertEqual(main.persist_agent_alert(proposal)['alert_id'], first['alert_id'])
        path = '/api/alerts/' + str(first['alert_id'])
        self.assertEqual(self.staff.patch(path, json={'status': 'ACKNOWLEDGED', 'expected_version': 1}).status_code, 200)
        self.assertEqual(self.staff.patch(path, json={'status': 'RESOLVED', 'expected_version': 1, 'note': 'Reviewed measurement'}).status_code, 409)
        self.assertEqual(self.staff.patch(path, json={'status': 'RESOLVED', 'expected_version': 2}).status_code, 422)
        self.assertEqual(self.staff.patch(path, json={'status': 'RESOLVED', 'expected_version': 2, 'note': 'Reviewed measurement'}).status_code, 200)

    def test_legacy_alerts_group_without_deleting_evidence(self):
        import alert_episodes
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            for n in range(3):
                conn.execute("INSERT INTO agent_alerts(patient_id,severity,reason,recommended_next_step,status,created_at) VALUES ('A001','critical','Heart rate 140','review','NEW',?)", (time.time() - n,))
        alert_episodes.init(str(auth.DB))
        self.assertEqual(len(main.get_workflow_alerts()), 1)
        self.assertEqual(main.get_workflow_alerts()[0]['occurrences'], 3)
        alert_episodes.init(str(auth.DB))
        with closing(sqlite3.connect(auth.DB)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM agent_alerts').fetchone()[0], 3)
        self.assertEqual(main.get_workflow_alerts()[0]['occurrences'], 3)

    def test_episode_recovers_only_after_fresh_measurement_without_auto_closure(self):
        from ai_models.agent_workflow import VitalEvent
        from ai_models.nurse_agent import NurseAgent
        now = time.time()
        main.persist_agent_alert({'patient_id': 'A001', 'timestamp': now - 20, 'severity': 'critical',
                                 'reason': 'SpO2 85 below threshold', 'recommended_next_step': 'review', 'vitals': {'spo2': 85}})
        agent = NurseAgent(str(auth.DB))
        event = dict(patient_id='A001', heart_rate=80, spo2=98, status='NORMAL', is_anomaly=False, risk_percent=None)
        agent.process(VitalEvent(**event, timestamp=now - 60), now=now)
        self.assertIsNone(main.get_workflow_alerts()[0]['recovered_at'])
        agent.process(VitalEvent(**event, timestamp=now), now=now)
        alert = main.get_workflow_alerts()[0]
        self.assertEqual(alert['status'], 'NEW')
        self.assertEqual(alert['recovered_at'], now)

    def test_zone_filter_applies_before_page_limit(self):
        for patient in ('A001', 'B001', 'C001'):
            main.persist_agent_alert({'patient_id': patient, 'timestamp': time.time(), 'severity': 'warning', 'reason': 'test', 'recommended_next_step': 'review', 'vitals': {}})
        self.assertEqual([a['patient_id'] for a in main.get_workflow_alerts(zone='A', limit=1)], ['A001'])

    def test_triage_uses_live_state_and_never_calls_missing_data_routine(self):
        import json
        old = time.time() - 100
        main.save_to_db('A001', 80, 98, 'NORMAL', old)
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            conn.execute('INSERT INTO monitor_results VALUES (?,?,?)', ('A001', json.dumps({'patient_id': 'A001', 'heart_rate': 140, 'spo2': 85, 'timestamp': time.time(), 'status': 'CRITICAL'}), time.time()))
        row = next(p for p in main.get_triage_snapshot() if p['patient_id'] == 'A001')
        self.assertEqual(row['latest']['heart_rate'], 140)
        self.assertEqual(row['triage_level'], 'CRITICAL')
        missing = next(p for p in main.get_triage_snapshot() if p['patient_id'] == 'A002')
        self.assertEqual(missing['triage_level'], 'ATTENTION')
        self.assertIsNone(missing['latest']['heart_rate'])

    def test_named_accounts_work_when_demo_login_disabled_and_password_reset_revokes_session(self):
        auth.set_account('staff', 'nurse.one', 'private-test-password')
        auth.set_account('patient', 'A001', 'private-test-password')
        with patch.dict(os.environ, {'WARD_DEMO_ID_LOGIN': '0'}):
            self.assertEqual(self.staff_login().status_code, 401)
            self.assertEqual(self.patient_login().status_code, 401)
            self.assertEqual(self.staff.post('/api/session/login', json={'username': 'nurse.one', 'password': 'private-test-password'}).status_code, 200)
            self.assertEqual(self.patient.post('/api/session/login', json={'patient_id': 'A001', 'password': 'private-test-password'}).status_code, 200)
            self.assertEqual(self.staff.get('/api/session').json()['subject'], 'nurse.one')
            auth.set_account('patient', 'A001', 'new-private-password')
            self.assertEqual(self.patient.get('/api/me').status_code, 401)

    def test_fixed_test_accounts_and_session_bound_two_way_chat(self):
        auth.ensure_test_accounts()
        doctor = self.staff.post('/api/session/login', json={'username': 'test_d', 'password': 'admin1234'})
        patient = self.patient.post('/api/session/login', json={'patient_id': 'test_p', 'password': 'admin4321'})
        self.assertEqual(doctor.status_code, 200)
        self.assertEqual(patient.status_code, 200)
        self.assertEqual(doctor.json()['display_name'], 'ธุวานนธ์ โต้ตอบ')
        self.assertEqual(patient.json()['display_name'], 'ธุวานนธ์ ตอบโต้')
        self.assertEqual(self.patient.get('/api/me').json()['profile']['name'], 'ธุวานนธ์ ตอบโต้')
        self.assertEqual([row['patient_id'] for row in self.staff.get('/api/monitor/patients').json()['patients']], ['TEST_P'])
        doctor_profile = self.staff.get('/api/session/profile').json()
        patient_profile = self.patient.get('/api/session/profile').json()
        self.assertEqual(doctor_profile['assigned_patients'][0]['patient_id'], 'TEST_P')
        self.assertEqual(patient_profile['care_team']['subject'], 'test_d')
        self.assertEqual(self.staff.get('/api/care-chat/B001').status_code, 403)

        sent = self.patient.post('/api/me/chat', json={
            'client_key': 'patient-message-0001', 'message': 'สวัสดีคุณหมอ ต้องการสอบถามการดูแลวันนี้'
        })
        self.assertEqual(sent.status_code, 201)
        self.assertEqual(self.staff.get('/api/care-chat/status').json()['unread'], 1)
        self.assertEqual(self.patient.get('/api/me/chat/status').json()['unread'], 0)
        listing = self.staff.get('/api/care-chat/conversations').json()['conversations']
        self.assertEqual(listing[0]['patient_id'], 'TEST_P')
        self.assertEqual(listing[0]['unread'], 1)
        room = self.staff.get('/api/care-chat/TEST_P').json()
        self.assertEqual(room['messages'][0]['sender_display_name'], 'ธุวานนธ์ ตอบโต้')
        self.assertEqual(self.staff.get('/api/care-chat/conversations').json()['conversations'][0]['unread'], 0)
        reply = self.staff.post('/api/care-chat/TEST_P', json={
            'client_key': 'doctor-message-00001', 'message': 'รับทราบแล้วครับ ทีมดูแลกำลังตรวจสอบข้อมูล'
        })
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(self.patient.get('/api/me/chat/status').json()['unread'], 1)
        own = self.patient.get('/api/me/chat').json()
        self.assertEqual(own['patient_id'], 'TEST_P')
        self.assertEqual(own['participants']['care_team']['subject'], 'test_d')
        self.assertEqual(own['messages'][-1]['sender_display_name'], 'ธุวานนธ์ โต้ตอบ')
        self.assertEqual(self.patient.get('/api/me/chat/status').json()['unread'], 0)
        self.assertEqual(self.patient.get('/api/care-chat/TEST_P').status_code, 404)
        with patch.dict(os.environ, {'WARD_ENABLE_TEST_ACCOUNTS': '0'}):
            auth.ensure_test_accounts()
        self.assertEqual(self.patient.get('/api/session').status_code, 401)
        self.assertEqual(self.staff.get('/api/session').status_code, 401)

    def test_assignment_scope_covers_clinical_data_counts_and_mutations(self):
        auth.ensure_test_accounts()
        self.staff.post('/api/session/login', json={'username': 'test_d', 'password': 'admin1234'})
        for path in ('/api/patient/A001/details', '/api/patient/A001/trends', '/api/patient/A001/timeline',
                     '/api/ml/patient/A001', '/api/care/patients/A001', '/api/care/patients/A001/profile',
                     '/api/care/patients/A001/daily', '/api/agent/runs?patient_id=A001', '/api/alerts?patient_id=A001'):
            with self.subTest(path=path):
                self.assertEqual(self.staff.get(path).status_code, 403)
        self.assertEqual(self.staff.post('/api/patient/A001/chat', json={'message': 'hello'}).status_code, 403)
        self.assertEqual(self.staff.post('/api/patient/A001/care-requests', json={'request_type': 'doctor'}).status_code, 403)
        for route in ('/api/patients', '/api/triage'):
            data = self.staff.get(route).json()
            self.assertEqual([row['patient_id'] for row in data['patients']], ['TEST_P'])
        self.assertEqual(self.staff.get('/api/dashboard/overview').json()['snapshot']['registered_patient_count'], 1)
        self.assertEqual(self.staff.get('/api/operations/status').json()['total_beds'], 1)
        # A guessed integer task/alert ID must not bypass the patient scope.
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            cursor = conn.execute("INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,created_at,created_by) VALUES ('A001','plan','check','clinician',0,0,0,'clinician')")
            plan_id = cursor.lastrowid
        self.assertEqual(self.staff.patch(f'/api/care/plans/{plan_id}', json={'version': 1, 'state': 'ACTIVE', 'demo_review_confirmed': True}).status_code, 403)

    def test_cloud_test_passwords_do_not_reset_or_expose_demo_prefill(self):
        password = 'cloud-test-secret-123'
        with patch.dict(os.environ, {'WARD_TEST_DOCTOR_PASSWORD': password, 'WARD_DEMO_ID_LOGIN': '0', 'WARD_ENABLE_TEST_ACCOUNTS': '1'}):
            auth.ensure_test_accounts()
            self.assertIsNone(self.staff.get('/api/session/config').json()['test_account'])
            self.assertEqual(self.staff.post('/api/session/login', json={'username': 'test_d', 'password': 'admin1234'}).status_code, 401)
            self.assertEqual(self.staff.post('/api/session/login', json={'username': 'test_d', 'password': password}).status_code, 200)
            auth.ensure_test_accounts()
            self.assertEqual(self.staff.get('/api/session').status_code, 200)
            with patch.dict(os.environ, {'WARD_TEST_DOCTOR_PASSWORD': 'rotated-cloud-test-456'}):
                auth.ensure_test_accounts()
            self.assertEqual(self.staff.get('/api/session').status_code, 401)
        auth.ensure_test_accounts()
        self.assertEqual(self.staff.post('/api/session/login', json={'username': 'test_d', 'password': 'admin1234'}).status_code, 401)
        self.assertEqual(self.staff.post('/api/session/login', json={'username': 'test_d', 'password': 'rotated-cloud-test-456'}).status_code, 200)

    def test_disabling_named_account_revokes_existing_session(self):
        auth.ensure_test_accounts()
        self.staff.post('/api/session/login', json={'username': 'test_d', 'password': 'admin1234'})
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            conn.execute("UPDATE portal_accounts SET enabled=0 WHERE subject='test_d'")
        self.assertEqual(self.staff.get('/api/session').status_code, 401)
        self.assertEqual(auth.staff_patient_scope('test_d'), ())
        self.assertEqual(auth.staff_patient_scope('missing-account'), ())

    def test_invalid_samples_do_not_break_valid_batch_or_mask_ward_failure(self):
        now = time.time()
        worker = MonitorWorker(str(auth.DB), main.PATIENT_PROFILES, 'mqtt')
        valid = {'patient_id': 'A001', 'timestamp': now, 'heart_rate': 80, 'spo2': 98, 'respiratory_rate': 18}
        invalid = [{**valid, 'heart_rate': float('nan')}, {**valid, 'timestamp': now + 60}, {**valid, 'spo2': 101}, {}, None]
        rows = worker.process([*invalid, valid], now)
        self.assertEqual([row['patient_id'] for row in rows], ['A001'])
        worker.failure(ValueError('test-only'))
        simulator = TestPatientSimulator(str(auth.DB), started_at=now)
        simulator.tick(now)
        status = worker_status(str(auth.DB))
        self.assertEqual(status['status'], 'ERROR')
        self.assertEqual(status['components']['test']['status'], 'RUNNING')

    def test_test_patient_simulation_is_labelled_realistic_and_excluded_from_bed_count(self):
        now = int(time.time())
        start = now - 151
        sample = simulated_reading(start + 151, start)
        self.assertEqual(sample['source'], 'TEST_SIMULATION')
        self.assertEqual(sample['simulation_state'], 'ช่วงออกซิเจนลดลงจำลอง')
        self.assertTrue(50 <= sample['heart_rate'] <= 130)
        self.assertTrue(90 <= sample['spo2'] <= 100)
        self.assertTrue(10 <= sample['respiratory_rate'] <= 30)
        simulator = TestPatientSimulator(str(auth.DB), started_at=start)
        for offset in range(152):
            simulator.tick(start + offset)
        state = patient_state(str(auth.DB), 'TEST_P')
        self.assertEqual(state['source'], 'TEST_SIMULATION')
        self.assertEqual(state['simulation_state'], 'ช่วงออกซิเจนลดลงจำลอง')
        self.assertEqual(state['status'], 'WARNING')
        self.assertEqual(worker_status(str(auth.DB))['fresh_beds'], 0)

    def test_patient_message_is_idempotent_scoped_and_human_acknowledged(self):
        self.patient_login()
        payload = {'request_key': 'request-1234567890', 'topic': 'device', 'message': 'Sensor disconnected'}
        first = self.patient.post('/api/me/messages', json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.patient.post('/api/me/messages', json=payload).json()['id'], first.json()['id'])
        self.assertEqual(self.patient.post('/api/me/messages', json={**payload, 'patient_id': 'B001'}).status_code, 422)
        self.assertEqual(self.patient.get('/api/care-messages').status_code, 404)
        self.staff_login()
        path = '/api/care-messages/' + str(first.json()['id'])
        self.assertEqual(self.staff.patch(path, json={'state': 'RESOLVED', 'reply': 'Responded'}).status_code, 409)
        self.assertEqual(self.staff.patch(path, json={'state': 'ACKNOWLEDGED'}).status_code, 200)
        self.assertEqual(self.staff.patch(path, json={'state': 'RESOLVED', 'reply': 'Staff checked the device'}).status_code, 200)
        messages = self.patient.get('/api/me/messages').json()['messages']
        self.assertEqual(messages[0]['state'], 'RESOLVED')
        self.assertNotIn('assigned_to', messages[0])
        self.patient_login('B001')
        self.assertEqual(self.patient.get('/api/me/messages').json()['messages'], [])

    def test_nurse_agent_trace_and_registry_are_staff_only(self):
        self.assertEqual(self.staff.get('/api/agent/status').status_code, 401)
        self.patient_login()
        self.assertEqual(self.patient.get('/api/agent/status').status_code, 404)
        self.staff_login()
        status = self.staff.get('/api/agent/status')
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()['policy']['cloud_llm_in_safety_loop'])
        self.assertEqual(self.staff.get('/api/agent/runs?patient_id=Z999').status_code, 404)

    def test_scenario_lab_is_staff_only_dry_run_and_never_creates_live_alert(self):
        self.assertEqual(self.staff.get('/api/agent/scenarios').status_code, 401)
        self.patient_login()
        self.assertEqual(self.patient.get('/api/agent/scenarios').status_code, 404)
        self.staff_login()
        catalog = self.staff.get('/api/agent/scenarios')
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(len(catalog.json()['scenarios']), 4)
        with closing(sqlite3.connect(auth.DB)) as conn:
            before = conn.execute('SELECT COUNT(*) FROM agent_alerts').fetchone()[0]
        result = self.staff.post('/api/agent/scenarios/desaturation')
        self.assertEqual(result.status_code, 201)
        payload = result.json()
        self.assertTrue(payload['passed'])
        self.assertTrue(payload['dry_run'])
        self.assertFalse(payload['training_data'])
        self.assertTrue(payload['actual']['would_alert'])
        self.assertEqual([stage['id'] for stage in payload['stages']],
                         ['input', 'quality', 'model', 'decision', 'action', 'ground_truth'])
        with closing(sqlite3.connect(auth.DB)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM agent_alerts').fetchone()[0], before)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM agent_scenario_runs').fetchone()[0], 1)
        self.assertEqual(self.staff.post('/api/agent/scenarios/not-a-case').status_code, 404)

    def test_no_automatic_gemini_call(self):
        self.staff_login()
        with patch.object(main, 'summarize_dashboard_section', side_effect=AssertionError('Network LLM not needed')):
            self.assertEqual(self.staff.get('/api/dashboard/overview').status_code, 200)

    def test_chat_receives_only_selected_id_model_context(self):
        self.staff_login()
        with patch.object(main, 'chat_with_patient_data', return_value='local test reply') as chat:
            response = self.staff.post('/api/patient/B003/chat', json={'message': 'สรุปผลโมเดล'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(chat.call_args.args[0], 'B003')
            self.assertEqual(chat.call_args.args[4]['patient_id'], 'B003')
            self.assertNotIn('patient_profile', chat.call_args.args[4])

    def test_worker_runs_without_login(self):
        async def check():
            worker = MonitorWorker(str(auth.DB), main.PATIENT_PROFILES)
            seen = asyncio.Event()
            async def publish(rows):
                if rows:
                    seen.set()
            task = asyncio.create_task(worker.run(publish))
            try:
                await asyncio.wait_for(seen.wait(), timeout=15)
                self.assertGreater(worker_status(auth.DB)['fresh_beds'], 0)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(check())
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM portal_sessions').fetchone()[0], 0)

    def test_worker_revokes_old_forecast_immediately_on_gap(self):
        worker = MonitorWorker(str(auth.DB), main.PATIENT_PROFILES)
        now = time.time()
        reading = {'patient_id': 'A001', 'timestamp': now, 'heart_rate': 80, 'spo2': 98, 'respiratory_rate': 18, 'source_segment': 'one'}
        worker.process([reading], now)
        worker.analysis['A001'] = {'status': 'READY', 'forecast': {'heart_rate': 80}, 'is_anomaly': True}
        result = worker.process([{**reading, 'timestamp': now + 3}], now + 3)[0]
        self.assertNotEqual(result['analysis']['status'], 'READY')
        self.assertIsNone(result['analysis']['forecast'])
        self.assertFalse(result['is_anomaly'])

    def test_account_deletion_and_disablement_revoke_sessions_even_in_demo_mode(self):
        auth.set_account('patient', 'A002', 'patient-pass-12345')
        res = self.patient.post('/api/session/login', json={'patient_id': 'A002', 'password': 'patient-pass-12345'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.patient.get('/api/me').status_code, 200)
        # Deleting the account row must invalidate the account-backed session even when WARD_DEMO_ID_LOGIN=1
        self.assertTrue(auth.delete_account('patient', 'A002'))
        self.assertEqual(self.patient.get('/api/me').status_code, 401)

        auth.set_account('patient', 'A003', 'patient-pass-67890')
        res2 = self.patient.post('/api/session/login', json={'patient_id': 'A003', 'password': 'patient-pass-67890'})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(self.patient.get('/api/me').status_code, 200)
        self.assertTrue(auth.disable_account('patient', 'A003'))
        self.assertEqual(self.patient.get('/api/me').status_code, 401)

    def test_sliding_session_renewal_extends_active_session_near_expiry(self):
        self.patient_login('A001')
        now = time.time()
        with closing(sqlite3.connect(auth.DB)) as conn, conn:
            conn.execute("UPDATE portal_sessions SET expires = ? WHERE audience = 'patient' AND subject = 'A001'", (now + 120,))
        self.assertEqual(self.patient.get('/api/me').status_code, 200)
        with closing(sqlite3.connect(auth.DB)) as conn:
            new_expires = conn.execute("SELECT expires FROM portal_sessions WHERE audience = 'patient' AND subject = 'A001'").fetchone()[0]
        self.assertGreater(new_expires, now + auth.TTL / 2)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records = load_recordings()  # includes SHA256 verification of every file
        cls.records = records
        cls.now = time.time()
        series = records['bidmc_04']
        for offset in range(len(series) - 60):
            values = series[offset:offset + 60, 1:]
            if valid_values(values):
                break
        cls.history = [{'timestamp': cls.now - 59 + i, **dict(zip(KEYS, row))} for i, row in enumerate(values)]

    def test_data_splits_disjoint(self):
        metadata = monitor_model.status()
        splits = [set(metadata['splits'][name]) for name in ('train', 'validation', 'test')]
        self.assertEqual(len(self.records), 53)
        self.assertFalse(splits[0] & splits[1] or splits[0] & splits[2] or splits[1] & splits[2])
        self.assertIsNone(metadata['anomaly_accuracy'])

    def test_forecast_contract_and_baseline(self):
        result = monitor_model.assess(self.history, self.now)
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['forecast']['spo2'], self.history[-1]['spo2'])
        self.assertEqual(result['prediction_at'], self.now + 30)
        self.assertIsInstance(result['is_anomaly'], bool)

    def test_batch_equals_individual(self):
        batch = monitor_model.assess_many([self.history] * 3, self.now)
        self.assertTrue(all(row == monitor_model.assess(self.history, self.now) for row in batch))

    def test_insufficient_stale_and_irregular_data(self):
        self.assertEqual(monitor_model.assess(self.history[:5], self.now)['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(monitor_model.assess(self.history, self.now + 31)['status'], 'STALE_DATA')
        bad = copy.deepcopy(self.history)
        bad[10]['timestamp'] += .8
        self.assertEqual(monitor_model.assess(bad, self.now)['status'], 'SAMPLING_MISMATCH')
        bad = copy.deepcopy(self.history)
        bad[0]['spo2'] = float('nan')
        self.assertEqual(monitor_model.assess(bad, self.now)['status'], 'INVALID_DATA')

    def test_replay_wrap_is_not_a_continuous_window(self):
        bad = copy.deepcopy(self.history)
        bad[-1]['source_segment'] = 'next-loop'
        self.assertEqual(monitor_model.assess(bad, self.now)['status'], 'INSUFFICIENT_DATA')

    def test_old_mortality_model_is_never_used_on_live_window(self):
        self.assertEqual(assess_patient_risk({}, self.history)['status'], 'UNSUPPORTED_CONTEXT')


if __name__ == '__main__':
    unittest.main()
