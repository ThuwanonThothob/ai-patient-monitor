"""Personal care + daily drafts: isolated database, no network or clinical actions."""
from contextlib import closing
from datetime import date, datetime, timedelta
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import HTTPException
import test_monitor_portals as isolation
import care_plan
import care_profiles as profiles
import daily_summary as daily
import care_chat
import patient_api
from monitor_service import MonitorWorker


class PersonalCareTests(unittest.TestCase):
    def setUp(self):
        isolation.main.init_db()
        patient_api.reset_rate_limits()
        with closing(profiles.connect()) as conn, conn:
            for table in ('daily_summary_reviews', 'daily_summary_cache', 'care_profile_versions', 'care_events',
                          'care_task_history', 'care_chat_messages',
                          'care_tasks', 'care_plans', 'agent_alerts', 'agent_audit_logs', 'monitor_results',
                          'monitor_analysis_logs', 'vital_logs', 'portal_sessions', 'login_attempts'):
                conn.execute('DELETE FROM ' + table)
        self.client = TestClient(isolation.main.app)
        self.client.post('/api/session/login', json={'password': 'test-only-password'})
        self.day = date(2026, 9, 28)
        self.start = datetime(2026, 9, 28, tzinfo=daily.TZ).timestamp()
        self.now = self.start + 3600

    def tearDown(self):
        patient_api.reset_rate_limits()
        self.client.close()

    def insert_vital(self, at, hr=80, spo2=98, rr=18, source='BIDMC_REPLAY', segment='bidmc_04:0', patient='A001'):
        with closing(profiles.connect()) as conn, conn:
            return conn.execute('''INSERT INTO vital_logs(patient_id,timestamp,heart_rate,spo2,respiratory_rate,simulation_state,source_record,source_segment)
                VALUES (?,?,?,?,?,?,?,?)''', (patient, at, hr, spo2, rr, source, 'bidmc_04', segment)).lastrowid

    def draft(self, version=0, content=None):
        body = {'expected_version': version, 'content': content or {'conditions': 'Demo condition', 'ranges': {'heart_rate': {'low': 70, 'high': 100}}}}
        with patch.object(profiles.time, 'time', return_value=self.now - 10):
            return self.client.post('/api/care/patients/A001/profile', json=body)

    def approve(self, version=1, now=None):
        with patch.object(profiles.time, 'time', return_value=now or self.now):
            return self.client.patch('/api/care/patients/A001/profile/review', json={'expected_version': version, 'action': 'APPROVE', 'confirmed': True})

    def test_profile_requires_review_and_drafts_do_not_replace_active(self):
        self.assertEqual(self.draft().status_code, 201)
        self.assertIsNone(self.client.get('/api/care/patients/A001/profile').json()['active'])
        bad = self.client.patch('/api/care/patients/A001/profile/review', json={'expected_version': 1, 'action': 'APPROVE'})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.approve().status_code, 200)
        self.assertEqual(self.draft(version=0).status_code, 409)
        self.assertEqual(self.draft(version=1, content={'conditions': 'New draft'}).status_code, 201)
        result = self.client.get('/api/care/patients/A001/profile').json()
        self.assertEqual(result['active']['version'], 1)
        self.assertEqual(result['latest']['state'], 'DRAFT')
        self.assertEqual(self.approve(version=1).status_code, 409)
        self.assertEqual(self.approve(version=2, now=self.now + 10).status_code, 200)
        with closing(profiles.connect()) as conn:
            old = profiles.active_profile(conn, 'A001', self.now + 5)
        self.assertEqual(old['version'], 1)
        self.assertEqual(old['state'], 'ACTIVE')
        self.assertIsNone(old['retired_at'])
        self.assertEqual(result['active']['reviewed_by'], 'clinician')

    def test_profile_validation_and_no_cross_patient_or_public_access(self):
        self.assertEqual(self.draft(content={'ranges': {'spo2': {'low': 90, 'high': 110}}}).status_code, 422)
        self.assertEqual(self.draft(content={'ranges': {'heart_rate': {'low': 100, 'high': 70}}}).status_code, 422)
        self.assertEqual(self.draft(content={'actor': 'forged'}).status_code, 422)
        self.assertEqual(self.client.get('/api/care/patients/A999/profile').status_code, 404)
        anonymous = TestClient(isolation.main.app)
        self.assertEqual(anonymous.get('/api/care/patients/A001/profile').status_code, 401)
        anonymous.close()
        patient = TestClient(isolation.patient_api.app)
        patient.post('/api/session/login', json={'patient_id': 'A001'})
        self.assertEqual(patient.get('/api/care/patients/A001/profile').status_code, 404)
        self.assertEqual(patient.get('/api/care/patients/A001/daily').status_code, 404)
        patient.close()
        self.draft(); self.approve()
        self.assertIsNone(self.client.get('/api/care/patients/B001/profile').json()['active'])

    def test_reference_is_frozen_disjoint_and_expires_without_changing_alerts(self):
        for i in range(60): self.insert_vital(self.now - 300 + i * 5)
        self.draft(content={'use_reference': True, 'reference_minutes': 5, 'ranges': {'heart_rate': {'low': 70, 'high': 100}}})
        result = self.approve().json()
        active = result['active']
        self.assertEqual(active['reference']['status'], 'READY')
        self.assertEqual(active['reference']['statistics']['heart_rate']['median'], 80)
        sample = {'heart_rate': 110, 'spo2': 97, 'respiratory_rate': 19, 'timestamp': self.now + 5, 'source': 'BIDMC_REPLAY', 'source_segment': 'bidmc_04:0'}
        c = profiles.compare(active, sample, self.now + 6)
        self.assertEqual(c['reference']['heart_rate']['difference'], 30)
        self.assertTrue(c['ranges']['heart_rate']['outside'])
        self.assertFalse(c['changes_live_alerts'])
        self.assertEqual(active['reference']['statistics']['heart_rate']['median'], 80)
        self.assertEqual(profiles.compare(active, sample, self.now + 100)['status'], 'STALE_READING')
        sample['timestamp'] = self.now + 86401
        self.assertEqual(profiles.compare(active, sample, sample['timestamp'])['reference_status'], 'EXPIRED')
        sample['timestamp'] = self.now + 10; sample['source_segment'] = 'bidmc_04:1'
        self.assertEqual(profiles.compare(active, sample, sample['timestamp'])['reference_status'], 'SOURCE_CHANGED')
        with closing(profiles.connect()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM agent_alerts').fetchone()[0], 0)

    def test_reference_gap_mixed_source_and_no_data_abstain(self):
        with closing(profiles.connect()) as conn:
            self.assertEqual(profiles.make_reference(conn, 'A001', 5, self.now)['status'], 'INSUFFICIENT_DATA')
        for i in range(60): self.insert_vital(self.now - 300 + i * 5, source='MQTT' if i == 59 else 'BIDMC_REPLAY')
        with closing(profiles.connect()) as conn, conn:
            self.assertEqual(profiles.make_reference(conn, 'A001', 5, self.now)['status'], 'SOURCE_MIXED_OR_UNKNOWN')
            conn.execute("UPDATE vital_logs SET simulation_state='BIDMC_REPLAY',source_segment=NULL")
            self.assertEqual(profiles.make_reference(conn, 'A001', 5, self.now)['status'], 'REPLAY_SEGMENT_CHANGED')
            conn.execute("UPDATE vital_logs SET source_segment='bidmc_04:0'")
            self.assertEqual(profiles.make_reference(conn, 'A001', 10, self.now)['status'], 'DATA_GAPS')

    def test_pause_removes_comparison_but_preserves_history(self):
        self.draft(); self.approve()
        result = self.client.patch('/api/care/patients/A001/profile/review', json={'expected_version': 1, 'action': 'PAUSE', 'confirmed': True})
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()['active'])
        self.assertEqual(result.json()['history'][0]['state'], 'PAUSED')
        self.assertEqual(result.json()['comparison']['status'], 'NO_REVIEWED_PROFILE')

    def test_reference_rejects_overlapping_source_and_bursts(self):
        for i in range(60): self.insert_vital(self.now - 300 + i * 5, source='MQTT')
        self.insert_vital(self.now - 5, source='BIDMC_REPLAY')
        self.insert_vital(self.now - 5, source='MQTT')
        with closing(profiles.connect()) as conn, conn:
            self.assertEqual(profiles.make_reference(conn, 'A001', 5, self.now)['status'], 'SOURCE_MIXED_OR_UNKNOWN')
            conn.execute('DELETE FROM vital_logs')
        # Sixty unique points do not imply five minutes of coverage when clustered.
        for i in range(20):
            for offset in (0, .1, .2): self.insert_vital(self.now - 300 + i * 15 + offset, source='MQTT')
        self.insert_vital(self.now - 5, source='MQTT')
        with closing(profiles.connect()) as conn:
            self.assertEqual(profiles.make_reference(conn, 'A001', 5, self.now)['status'], 'DATA_GAPS')

    def test_bangkok_day_boundaries_and_future_measurements_excluded(self):
        self.assertEqual(datetime.fromtimestamp(self.start, daily.TZ).hour, 0)
        self.insert_vital(self.start - 1, hr=240)
        self.insert_vital(self.start, hr=80)
        self.insert_vital(self.now - 5, hr=90)
        self.insert_vital(self.now, hr=230)
        self.insert_vital(self.now + 30, hr=220)
        result = daily.assemble('A001', self.day, self.now)
        m = result['sources']['BIDMC_REPLAY']['measurements']['heart_rate']
        self.assertEqual(m['mean'], 85)
        self.assertEqual(m['change'], 10)
        self.assertTrue(result['partial_day'])
        self.assertLess(result['overall_recording']['estimated_percent'], 1)
        self.assertNotIn('230', result['text'])
        with self.assertRaises(HTTPException): daily.period(self.day + timedelta(days=1), self.now)

    def test_sources_and_missing_values_are_not_filled_from_registry(self):
        self.insert_vital(self.start + 10, hr=80)
        self.insert_vital(self.start + 20, hr=100, rr=None, source='MQTT')
        self.insert_vital(self.start + 7200, hr=84)
        result = daily.assemble('A001', self.day, self.start + 8000)
        self.assertEqual(result['sources']['BIDMC_REPLAY']['measurements']['heart_rate']['mean'], 82)
        self.assertEqual(result['sources']['MQTT']['measurements']['heart_rate']['mean'], 100)
        self.assertIsNone(result['sources']['MQTT']['measurements']['respiratory_rate'])
        self.assertIsNone(result['sources']['BIDMC_REPLAY']['hourly'][1]['heart_rate'])
        self.assertEqual(result['sources']['MQTT']['invalid_snapshot_count'], 1)
        empty = daily.assemble('B001', self.day, self.now)
        self.assertEqual(empty['sources'], {})
        self.assertIn('ไม่มีข้อมูลการวัด', empty['text'])
        self.assertEqual(empty['overall_recording']['estimated_percent'], 0)
        self.assertEqual(empty['ml'], {})

    def test_alert_and_task_states_use_cutoff_not_later_completion(self):
        with closing(profiles.connect()) as conn, conn:
            conn.execute('''INSERT INTO agent_alerts(patient_id,severity,reason,recommended_next_step,created_at,resolved_at,status)
                VALUES ('A001','warning','demo','review',?,?,'RESOLVED')''', (self.start + 50, self.now + 10))
            plan = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,created_at,created_by)
                VALUES ('A001','demo task','check','team',0,?,?,'clinician')''', (self.start + 30, self.start + 10)).lastrowid
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,completed_at,note) VALUES (?,?,'DONE',?,'FUTURE SECRET NOTE')", (plan, self.start + 30, self.now + 10))
        result = daily.assemble('A001', self.day, self.now)
        self.assertEqual(result['alerts']['open_as_of_count'], 1)
        self.assertEqual(result['alerts']['resolved_count'], 0)
        self.assertEqual(result['care']['open_due_as_of_count'], 1)
        self.assertEqual(result['care']['done_in_period'], 0)
        self.assertNotIn('FUTURE SECRET NOTE', json.dumps(result))

    def test_review_copy_is_immutable_and_stale_draft_rejected(self):
        self.insert_vital(self.now - 10)
        daily.refresh('A001', self.day, self.now)
        path = '/api/care/patients/A001/daily'
        original = self.client.get(f'{path}?day={self.day}').json()
        body = {'day': str(self.day), 'digest': original['digest'], 'confirmed': True, 'note': 'Reviewed demo'}
        first = self.client.post(path + '/review', json=body)
        self.assertEqual(first.status_code, 201, first.text)
        review_id = first.json()['id']
        self.assertTrue(self.client.post(path + '/review', json=body).json()['already_reviewed'])
        export_before = self.client.get(f'{path}/reviews/{review_id}/report').text
        self.insert_vital(self.now + 5, hr=150)
        daily.refresh('A001', self.day, self.now + 10)
        self.assertEqual(self.client.post(path + '/review', json=body).status_code, 409)
        self.assertEqual(self.client.get(f'{path}/report?day={self.day}&digest={original["digest"]}').status_code, 409)
        self.assertEqual(self.client.get(f'{path}/reviews/{review_id}/report').text, export_before)
        self.assertEqual(self.client.get(f'/api/care/patients/B001/daily/reviews/{review_id}/report').status_code, 404)
        self.assertIn('clinician', export_before)

    def test_worker_logs_actual_model_evaluations_and_record_provenance(self):
        worker = MonitorWorker(str(isolation.auth.DB), isolation.main.PATIENT_PROFILES)
        for i in range(61):
            worker.process([{'patient_id': 'A001', 'timestamp': self.start + i, 'heart_rate': 80, 'spo2': 98,
                             'respiratory_rate': 18, 'source_record': 'bidmc_04', 'source_segment': 'bidmc_04:0'}], self.start + i)
        result = daily.assemble('A001', self.day, self.start + 65)
        self.assertEqual(result['ml']['BIDMC_REPLAY']['evaluations'], 7)
        self.assertEqual(result['ml']['BIDMC_REPLAY']['ready'], 1)
        with closing(profiles.connect()) as conn:
            self.assertEqual(conn.execute('SELECT source_record FROM vital_logs LIMIT 1').fetchone()[0], 'bidmc_04')

    def test_background_generation_works_without_login_and_no_cloud(self):
        current = time.time()
        self.insert_vital(current - 5)
        self.client.post('/api/session/logout')
        with patch('daily_summary.time.time', return_value=current): daily.refresh_all()
        with closing(profiles.connect()) as conn:
            cached = conn.execute('SELECT payload FROM daily_summary_cache WHERE patient_id=? AND day=?', ('A001', daily.datetime.fromtimestamp(current, daily.TZ).date().isoformat())).fetchone()
        self.assertIsNotNone(cached)
        self.assertFalse(json.loads(cached[0])['is_llm_generated'])

    def test_overdue_care_summary_counts_overdue_and_upcoming_tasks(self):
        with closing(profiles.connect()) as conn, conn:
            plan_a = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,state,created_at,created_by)
                VALUES ('A001','check vitals','observe','nurse-a',60,?,'ACTIVE',?,'clinician')''', (self.now, self.start)).lastrowid
            plan_b = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,state,created_at,created_by)
                VALUES ('B001','turn patient','reposition','nurse-b',120,?,'ACTIVE',?,'clinician')''', (self.now, self.start)).lastrowid
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'PENDING')", (plan_a, self.now - 60))
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,acknowledged_at) VALUES (?,?,'ACKNOWLEDGED',?)", (plan_a, self.now, self.now - 10))
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'PENDING')", (plan_a, self.now + 120))
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,completed_at,note) VALUES (?,?,'DONE',?,'done')", (plan_a, self.now - 120, self.now - 30))
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state,completed_at,note) VALUES (?,?,'SKIPPED',?,'skip')", (plan_a, self.now + 60, self.now - 20))
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'PENDING')", (plan_b, self.now + 300))

        summary_a = care_plan.overdue_care_summary(patient_id='A001', now=self.now)
        self.assertEqual(summary_a, {'overdue_count': 2, 'upcoming_count': 1, 'total_open': 3})

        summary_b = care_plan.overdue_care_summary(patient_id='B001', now=self.now)
        self.assertEqual(summary_b, {'overdue_count': 0, 'upcoming_count': 1, 'total_open': 1})

        summary_all = care_plan.overdue_care_summary(now=self.now)
        self.assertEqual(summary_all, {'overdue_count': 2, 'upcoming_count': 2, 'total_open': 4})

    def test_unread_chat_summary_function_and_api(self):
        with closing(care_chat.connect()) as conn, conn:
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at)
                VALUES ('A001', 'patient', 'A001', 'Patient A', 'msg-1', 'hello doc', ?)''', (self.now,))
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at)
                VALUES ('A001', 'patient', 'A001', 'Patient A', 'msg-2', 'second msg', ?)''', (self.now + 1,))
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at)
                VALUES ('B001', 'patient', 'B001', 'Patient B', 'msg-3', 'from patient B', ?)''', (self.now + 2,))
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at, read_by_patient_at)
                VALUES ('A001', 'staff', 'clinician', 'Doctor', 'msg-4', 'reply doc', ?, NULL)''', (self.now + 3,))

        summary = care_chat.count_unread_by_patient()
        self.assertEqual(summary.get('A001'), 2)
        self.assertEqual(summary.get('B001'), 1)

        res = self.client.get('/api/care-chat/unread-summary')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['summary']['A001'], 2)
        self.assertEqual(data['summary']['B001'], 1)
        self.assertEqual(data['total_unread'], 3)

        anon = TestClient(isolation.main.app)
        self.assertEqual(anon.get('/api/care-chat/unread-summary').status_code, 401)
        anon.close()

    def test_care_plan_status_transitions_audit_trail_and_history_api(self):
        plan_now = time.time()
        res_plan = self.client.post('/api/care/patients/A001/plans', json={
            'title': 'Reposition patient',
            'instructions': 'Turn every 2 hours',
            'assigned_to': 'nurse-one',
            'interval_minutes': 0,
            'first_due': plan_now,
        })
        self.assertEqual(res_plan.status_code, 201)
        plan_id = res_plan.json()['id']

        res_act = self.client.patch(f'/api/care/plans/{plan_id}', json={
            'version': 1,
            'state': 'ACTIVE',
            'demo_review_confirmed': True,
        })
        self.assertEqual(res_act.status_code, 200)

        with closing(profiles.connect()) as conn:
            task = conn.execute('SELECT id, state, version FROM care_tasks WHERE plan_id=?', (plan_id,)).fetchone()
        self.assertIsNotNone(task)
        task_id = task['id']
        self.assertEqual(task['state'], 'PENDING')

        res_ack = self.client.patch(f'/api/care/tasks/{task_id}', json={
            'version': task['version'],
            'state': 'ACKNOWLEDGED',
            'note': 'Received and acknowledged',
        })
        self.assertEqual(res_ack.status_code, 200)

        res_skip = self.client.patch(f'/api/care/tasks/{task_id}', json={
            'version': task['version'] + 1,
            'state': 'SKIPPED',
            'note': 'Patient sleeping soundly',
        })
        self.assertEqual(res_skip.status_code, 200)

        res_hist = self.client.get(f'/api/care/tasks/{task_id}/history')
        self.assertEqual(res_hist.status_code, 200)
        data = res_hist.json()
        self.assertEqual(data['task_id'], task_id)
        self.assertEqual(data['patient_id'], 'A001')
        history = data['history']
        self.assertEqual(len(history), 2)

        self.assertEqual(history[0]['previous_state'], 'PENDING')
        self.assertEqual(history[0]['new_state'], 'ACKNOWLEDGED')
        self.assertEqual(history[0]['actor'], 'clinician')
        self.assertIsNone(history[0]['skip_reason'])

        self.assertEqual(history[1]['previous_state'], 'ACKNOWLEDGED')
        self.assertEqual(history[1]['new_state'], 'SKIPPED')
        self.assertEqual(history[1]['actor'], 'clinician')
        self.assertEqual(history[1]['skip_reason'], 'Patient sleeping soundly')

        self.assertEqual(self.client.get('/api/care/tasks/999999/history').status_code, 404)

    def test_patient_api_rate_limiting(self):
        patient_api.reset_rate_limits()
        client = TestClient(patient_api.app)

        for i in range(5):
            res = client.post('/api/session/login', json={'patient_id': 'A001'})
            self.assertIn(res.status_code, (200, 401), f'Request {i+1} failed with {res.status_code}')

        res_limited = client.post('/api/session/login', json={'patient_id': 'A001'})
        self.assertEqual(res_limited.status_code, 429)
        self.assertIn('Retry-After', res_limited.headers)
        self.assertGreater(int(res_limited.headers['Retry-After']), 0)

        patient_api.reset_rate_limits()
        for i in range(60):
            res = client.get('/health')
            self.assertEqual(res.status_code, 200, f'General request {i+1} failed with {res.status_code}')

        res_gen_limited = client.get('/health')
        self.assertEqual(res_gen_limited.status_code, 429)
        self.assertIn('Retry-After', res_gen_limited.headers)
        self.assertGreater(int(res_gen_limited.headers['Retry-After']), 0)

        patient_api.reset_rate_limits()
        client.close()

    def test_overdue_care_summary_endpoint(self):
        anon = TestClient(isolation.main.app)
        self.assertEqual(anon.get('/api/care/overdue-summary').status_code, 401)
        anon.close()

        with closing(profiles.connect()) as conn, conn:
            plan_a = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,state,created_at,created_by)
                VALUES ('A001','task a','instructions','nurse',60,?,'ACTIVE',?,'clinician')''', (time.time(), time.time())).lastrowid
            plan_b = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,state,created_at,created_by)
                VALUES ('B001','task b','instructions','nurse',60,?,'ACTIVE',?,'clinician')''', (time.time(), time.time())).lastrowid
            # A001 overdue task
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'PENDING')", (plan_a, time.time() - 300))
            # A001 upcoming task
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'ACKNOWLEDGED')", (plan_a, time.time() + 600))
            # B001 upcoming task
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'PENDING')", (plan_b, time.time() + 300))

        res_a = self.client.get('/api/care/overdue-summary?patient_id=A001')
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.json()
        self.assertEqual(data_a['overdue_count'], 1)
        self.assertEqual(data_a['upcoming_count'], 1)
        self.assertEqual(data_a['total_open'], 2)

        res_b = self.client.get('/api/care/overdue-summary?patient_id=B001')
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.json()
        self.assertEqual(data_b['overdue_count'], 0)
        self.assertEqual(data_b['upcoming_count'], 1)
        self.assertEqual(data_b['total_open'], 1)

        res_all = self.client.get('/api/care/overdue-summary')
        self.assertEqual(res_all.status_code, 200)
        data_all = res_all.json()
        self.assertEqual(data_all['overdue_count'], 1)
        self.assertEqual(data_all['upcoming_count'], 2)
        self.assertEqual(data_all['total_open'], 3)

    def test_shift_handoff_snapshot_api(self):
        anon = TestClient(isolation.main.app)
        self.assertEqual(anon.get('/api/operations/shift-handoff').status_code, 401)
        anon.close()

        with closing(profiles.connect()) as conn, conn:
            plan_id = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,next_due,state,created_at,created_by)
                VALUES ('A001','task handoff','instructions','nurse',0,?,'ACTIVE',?,'clinician')''', (time.time(), time.time())).lastrowid
            conn.execute("INSERT INTO care_tasks(plan_id,scheduled_at,state) VALUES (?,?,'PENDING')", (plan_id, time.time() - 100))
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at)
                VALUES ('A001', 'patient', 'A001', 'Patient A', 'msg-handoff-1', 'need help', ?)''', (time.time(),))
            conn.execute('''INSERT INTO agent_alerts(patient_id,severity,reason,recommended_next_step,status,created_at)
                VALUES ('A001','critical','SpO2 drop','check oxygen','NEW',?)''', (time.time(),))
            conn.execute('''INSERT INTO agent_alerts(patient_id,severity,reason,recommended_next_step,status,created_at,resolved_at)
                VALUES ('A001','warning','Resolved earlier','review','RESOLVED',?,?)''', (time.time() - 200, time.time() - 100))

        res = self.client.get('/api/operations/shift-handoff')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('generated_at', data)
        self.assertGreater(data['generated_at'], 0)
        self.assertEqual(data['care_summary']['overdue_count'], 1)
        self.assertEqual(data['care_summary']['total_open'], 1)
        self.assertGreaterEqual(data['chat_summary']['total_unread'], 1)
        self.assertEqual(data['chat_summary']['unread_by_patient'].get('A001'), 1)
        self.assertEqual(data['open_alerts_count'], 1)

    def test_care_chat_conversations_filtering(self):
        with closing(care_chat.connect()) as conn, conn:
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at)
                VALUES ('A001', 'patient', 'A001', 'Patient A', 'msg-c1', 'unread message from A', ?)''', (self.now,))
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id, sender_audience, sender_subject, sender_display_name, client_key, message, created_at, read_by_staff_at)
                VALUES ('B001', 'patient', 'B001', 'Patient B', 'msg-c2', 'read message from B', ?, ?)''', (self.now + 10, self.now + 20))

        # Default query (no filters)
        res = self.client.get('/api/care-chat/conversations')
        self.assertEqual(res.status_code, 200)
        convs = res.json()['conversations']
        pids = [c['patient_id'] for c in convs]
        self.assertIn('A001', pids)
        self.assertIn('B001', pids)

        # unread_only=true
        res_unread = self.client.get('/api/care-chat/conversations?unread_only=true')
        self.assertEqual(res_unread.status_code, 200)
        unread_convs = res_unread.json()['conversations']
        unread_pids = [c['patient_id'] for c in unread_convs]
        self.assertIn('A001', unread_pids)
        self.assertNotIn('B001', unread_pids)
        for c in unread_convs:
            self.assertGreater(c['unread'], 0)

        # Query search by patient_id (case-insensitive)
        res_qa = self.client.get('/api/care-chat/conversations?q=a001')
        self.assertEqual(res_qa.status_code, 200)
        qa_pids = [c['patient_id'] for c in res_qa.json()['conversations']]
        self.assertIn('A001', qa_pids)
        self.assertNotIn('B001', qa_pids)

        # Query search by display name
        res_q_name = self.client.get('/api/care-chat/conversations?q=Synthetic Patient A001')
        self.assertEqual(res_q_name.status_code, 200)
        q_name_pids = [c['patient_id'] for c in res_q_name.json()['conversations']]
        self.assertIn('A001', q_name_pids)
        self.assertNotIn('B001', q_name_pids)

        # Query nonexistent
        res_none = self.client.get('/api/care-chat/conversations?q=nonexistent-query-xyz')
        self.assertEqual(res_none.status_code, 200)
        self.assertEqual(len(res_none.json()['conversations']), 0)


