"""Session-bound patient views, privacy projections and truthful history."""
from contextlib import closing
from datetime import datetime, timedelta
import json
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_monitor_portals as isolation
import daily_summary
import patient_views
from care_profiles import ProfileContent, connect


class PatientWorkspaceTests(unittest.TestCase):
    def setUp(self):
        isolation.main.init_db()
        with closing(connect()) as conn, conn:
            for table in ('daily_summary_reviews', 'daily_summary_cache', 'care_profile_versions', 'care_events',
                          'care_tasks', 'care_plans', 'agent_alerts', 'agent_audit_logs', 'monitor_results',
                          'monitor_analysis_logs', 'vital_logs', 'portal_sessions', 'login_attempts'):
                conn.execute('DELETE FROM ' + table)
        self.patient = TestClient(isolation.patient_api.app)
        self.staff = TestClient(isolation.main.app)
        self.patient.post('/api/session/login', json={'patient_id': 'A001'})
        self.staff.post('/api/session/login', json={'password': 'test-only-password'})
        self.now = time.time()

    def tearDown(self):
        self.patient.close(); self.staff.close()

    def vital(self, at, hr=80, rr=18, source='MQTT', patient='A001'):
        with closing(connect()) as conn, conn:
            conn.execute('''INSERT INTO vital_logs(patient_id,timestamp,heart_rate,spo2,respiratory_rate,simulation_state)
                VALUES (?,?,?,98,?,?)''', (patient, at, hr, rr, source))

    def plan(self, patient='A001', state='ACTIVE', title='Approved demo task'):
        with closing(connect()) as conn, conn:
            return conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,
                state,created_at,created_by,reviewed_at,reviewed_by) VALUES (?,?,?,'PRIVATE_ACTOR',0,?,?,?,'PRIVATE_ACTOR',?,'PRIVATE_ACTOR')''',
                (patient, title, 'Demonstration instructions', self.now - 30, state, self.now - 60,
                 None if state == 'DRAFT' else self.now - 45)).lastrowid

    def test_session_bound_for_every_new_route_and_download(self):
        self.vital(self.now - 20, hr=80)
        self.vital(self.now - 20, hr=240, patient='B001')
        self.plan('B001', title='B001_PRIVATE_TASK')
        for path in ('/api/me', '/api/me/trends?hours=24', '/api/me/care', '/api/me/daily'):
            result = self.patient.get(path + ('&' if '?' in path else '?') + 'patient_id=B001')
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['patient_id'], 'A001')
            self.assertNotIn('B001_PRIVATE_TASK', result.text)
        trends = self.patient.get('/api/me/trends').json()
        self.assertEqual(trends['sources']['MQTT']['statistics']['heart_rate']['max'], 80)
        for path in ('/api/me/report', '/api/me/daily/report'):
            result = self.patient.get(path + '?patient_id=B001')
            self.assertIn('Patient ID: A001', result.text)
            self.assertNotIn('B001', result.text)
            self.assertIn('attachment', result.headers['content-disposition'])

    def test_new_routes_require_patient_session_and_valid_origin(self):
        anonymous = TestClient(isolation.patient_api.app)
        for path in ('/api/me/trends', '/api/me/care', '/api/me/daily', '/api/me/daily/report'):
            self.assertEqual(anonymous.get(path).status_code, 401)
        anonymous.cookies.update(self.staff.cookies)
        self.assertEqual(anonymous.get('/api/me/care').status_code, 401)
        anonymous.close()
        self.assertEqual(self.patient.get('/api/me/care', headers={'Origin': 'http://localhost:3000'}).status_code, 403)
        self.assertEqual(self.patient.get('/api/me/care', headers={'Origin': 'http://localhost:3001'}).status_code, 200)

    def test_patient_cannot_write_plans_profiles_or_review_reports(self):
        plan = self.plan()
        for path, method in (('/api/me/care', 'POST'), ('/api/me/daily/review', 'POST'),
                             (f'/api/care/plans/{plan}', 'PATCH'), ('/api/care/patients/A001/profile', 'POST')):
            self.assertIn(self.patient.request(method, path, json={}).status_code, (404, 405))
        for path in ('/api/patients', '/api/care/patients/B001', '/api/care/patients/A001/daily', '/api/alerts'):
            self.assertEqual(self.patient.get(path).status_code, 404)

    def test_trends_boundaries_missing_data_duplicates_and_source_separation(self):
        start = self.now - 3600
        self.vital(start - 1, hr=240)
        self.vital(start, hr=80)
        self.vital(start + 5, hr=100)
        self.vital(start + 5, hr=100)  # duplicate is not an independent sample
        self.vital(start + 5, hr=60, rr=None, source='BIDMC_REPLAY')
        self.vital(self.now, hr=230)
        self.vital(self.now + 30, hr=220)
        result = patient_views.trends('A001', 1, self.now)
        mqtt = result['sources']['MQTT']
        self.assertEqual(mqtt['snapshot_count'], 2)
        self.assertEqual(mqtt['statistics']['heart_rate']['mean'], 90)
        self.assertEqual(len(mqtt['points']), 60)
        self.assertIsNone(mqtt['points'][1]['heart_rate'])
        self.assertIsNone(result['sources']['BIDMC_REPLAY']['statistics']['respiratory_rate'])
        self.assertEqual(result['sources']['BIDMC_REPLAY']['statistics']['heart_rate']['mean'], 60)
        self.assertLess(mqtt['coverage']['estimated_percent'], 1)

    def test_staff_history_route_uses_same_quality_filtered_aggregation(self):
        self.vital(self.now - 20, hr=81)
        self.vital(self.now - 10, hr=83)
        result = self.staff.get('/api/patient/A001/trends?hours=1')
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data['patient_id'], 'A001')
        self.assertEqual(data['sources']['MQTT']['statistics']['heart_rate']['mean'], 82)
        self.assertEqual(self.staff.get('/api/patient/Z999/trends?hours=1').status_code, 404)
        self.assertEqual(self.staff.get('/api/patient/A001/trends?hours=2').status_code, 422)
        self.assertEqual(self.patient.get('/api/patient/A001/trends?hours=1').status_code, 404)

    def test_interval_and_date_validation_and_empty_states(self):
        for hours in ('1', '6', '24', '168'):
            response = self.patient.get('/api/me/trends?hours=' + hours)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['sources'], {})
        for hours in ('0', '-1', '2', '169', '100000', 'NaN'):
            self.assertEqual(self.patient.get('/api/me/trends?hours=' + hours).status_code, 422)
        tomorrow = (datetime.now(daily_summary.TZ).date() + timedelta(days=1)).isoformat()
        for day in (tomorrow, 'bad-date', '1999-01-01'):
            self.assertEqual(self.patient.get('/api/me/daily?day=' + day).status_code, 422)
        report = self.patient.get('/api/me/daily').json()
        self.assertEqual(report['sources'], {})
        self.assertIn('ไม่มีข้อมูลการวัด', report['text'])
        self.assertEqual(report['ml'], {})

    def test_care_only_reviewed_profiles_and_plans_without_internal_notes(self):
        active = self.plan()
        self.plan(state='DRAFT', title='PRIVATE_DRAFT_PLAN')
        with closing(connect()) as conn, conn:
            content = ProfileContent(conditions='Approved demo context', care_notes='PRIVATE_PROFILE_NOTE').model_dump_json()
            conn.execute("INSERT INTO care_profile_versions VALUES ('A001',1,'ACTIVE',?,NULL,?,'PRIVATE_ACTOR',?,'PRIVATE_ACTOR',NULL)", (content, self.now - 90, self.now - 60))
            draft = ProfileContent(conditions='PRIVATE_DRAFT_PROFILE').model_dump_json()
            conn.execute("INSERT INTO care_profile_versions VALUES ('A001',2,'DRAFT',?,NULL,?,'PRIVATE_ACTOR',NULL,NULL,NULL)", (draft, self.now - 10))
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,note) VALUES (?,?,'PENDING','PRIVATE_TASK_NOTE')", (active, self.now - 30))
            conn.execute("INSERT INTO care_events(patient_id,action,actor,detail,created_at) VALUES ('A001','TEST','PRIVATE_ACTOR','PRIVATE_AUDIT',?)", (self.now,))
        result = self.patient.get('/api/me/care')
        self.assertNotIn('PRIVATE_', result.text)
        data = result.json()
        self.assertEqual(data['profile']['version'], 1)
        self.assertEqual(data['profile']['conditions'], 'Approved demo context')
        self.assertEqual(data['plan_count'], 1)
        self.assertTrue(data['tasks'][0]['overdue'])
        with closing(connect()) as conn, conn:
            conn.execute("UPDATE care_profile_versions SET state='PAUSED' WHERE version=1")
        self.assertIsNone(self.patient.get('/api/me/care').json()['profile'])

    def test_open_tasks_are_not_hidden_behind_completed_history(self):
        plan = self.plan()
        with closing(connect()) as conn, conn:
            oldest = conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at) VALUES (?,?)", (plan, self.now - 1000)).lastrowid
            for i in range(55):
                conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,completed_at) VALUES (?,?,'DONE',?)", (plan, self.now - 900 + i, self.now - 60))
        result = self.patient.get('/api/me/care').json()
        self.assertEqual(result['tasks'][0]['id'], oldest)
        self.assertEqual(result['open_count'], 1)
        self.assertTrue(result['tasks_truncated'])
        self.assertEqual(len(result['tasks']), 50)

    def test_daily_json_and_text_hide_all_internal_fields_and_reject_changed_digest(self):
        self.vital(self.now - 20)
        plan = self.plan()
        with closing(connect()) as conn, conn:
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,completed_at,note) VALUES (?,?,'DONE',?,'PRIVATE_FINISH_NOTE')", (plan, self.now - 30, self.now - 10))
            conn.execute("INSERT INTO agent_alerts(patient_id,severity,reason,recommended_next_step,created_at) VALUES ('A001','warning','PRIVATE_REASON','PRIVATE_STEP',?)", (self.now - 5,))
        result = self.patient.get('/api/me/daily')
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('PRIVATE_', result.text)
        self.assertNotIn('evidence_ids', result.text)
        self.assertNotIn('reviewed_by', result.text)
        data = result.json()
        exported = self.patient.get('/api/me/daily/report?digest=' + data['digest'])
        self.assertEqual(exported.status_code, 200)
        self.assertNotIn('PRIVATE_', exported.text)
        daily_summary.refresh('A001', datetime.now(daily_summary.TZ).date(), self.now + 1)
        self.assertEqual(self.patient.get('/api/me/daily/report?digest=' + data['digest']).status_code, 409)

    def test_latest_download_withholds_stale_vitals_and_me_does_not_run_extra_inference(self):
        payload = {'patient_id': 'A001', 'timestamp': self.now - 120, 'heart_rate': 123, 'spo2': 98,
                   'respiratory_rate': 18, 'status': 'NORMAL', 'patient_profile': {'simulation': 'PRIVATE_SIMULATION'},
                   'analysis': {'status': 'READY', 'evaluated_at': self.now - 120, 'summary': 'PRIVATE_OLD_SUMMARY'}}
        with closing(connect()) as conn, conn:
            conn.execute('INSERT INTO monitor_results VALUES (?,?,?)', ('A001', json.dumps(payload), self.now - 120))
        with patch.object(isolation.main, 'get_patient_details', side_effect=AssertionError('Patient poll must not trigger assessment')):
            result = self.patient.get('/api/me')
            self.assertEqual(result.status_code, 200)
            self.assertNotIn('PRIVATE_SIMULATION', result.text)
            self.assertNotIn('blood_glucose', result.text)
        report = self.patient.get('/api/me/report')
        self.assertIn('ไม่มีข้อมูลใหม่', report.text)
        self.assertNotIn('123', report.text)
        self.assertNotIn('PRIVATE_OLD_SUMMARY', report.text)
