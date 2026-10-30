"""Push tests use temporary DBs and fake providers. Never contact a real phone."""
import base64
import asyncio
from contextlib import closing
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sys
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import auth
import notifications as push
import care_chat


class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ward-push-test-')
        self.db = patch.object(auth, 'DB', Path(self.temp.name) / 'push.db')
        self.db.start()
        self.env = patch.dict(os.environ, {'WARD_WEB_PUSH_ENABLED': '1', 'WARD_STAFF_PASSWORD': 'push-test-only'})
        self.env.start()
        self.ready = patch.object(push, 'configuration', return_value={'ready': True, 'enabled': True, 'status': 'READY', 'public_key': 'public-test-key'})
        self.ready.start()
        auth.init_sessions()
        push.init_notifications()
        care_chat.init()
        with closing(push.connection()) as conn, conn:
            conn.execute('CREATE TABLE agent_alerts(id INTEGER PRIMARY KEY, patient_id TEXT, severity TEXT, status TEXT, merged_into INTEGER)')
        app = FastAPI()
        auth.install_auth(app, 'staff', {})
        app.include_router(push.router)
        self.client = TestClient(app)
        self.client.post('/api/session/login', json={'password': 'push-test-only'})
        self.now = time.time()
        self.digest = hashlib.sha256(self.client.cookies.get(auth.cookie_name('staff')).encode()).hexdigest()

    def tearDown(self):
        self.client.close()
        self.ready.stop()
        self.env.stop()
        self.db.stop()
        self.temp.cleanup()

    def subscribe(self, zone='ALL', warning=False, client=None, endpoint='test-only'):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        payload = {'endpoint': 'https://fcm.googleapis.com/fcm/send/' + endpoint,
                   'keys': {'p256dh': base64.urlsafe_b64encode(key).rstrip(b'=').decode(),
                            'auth': base64.urlsafe_b64encode(b'0123456789abcdef').rstrip(b'=').decode()},
                   'zone': zone, 'include_warning': warning}
        result = (client or self.client).post('/api/notifications/subscriptions', json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['id']

    def alert(self, identifier=1, patient='A001', severity='critical', now=None):
        with closing(push.connection()) as conn, conn:
            conn.execute('INSERT OR IGNORE INTO agent_alerts(id,patient_id,severity,status) VALUES (?,?,?,?)', (identifier, patient, severity, 'NEW'))

            push.enqueue_alert(conn, identifier, patient, severity, now or self.now)

    def test_patient_push_chat_targeting_read_cancellation_and_logout(self):
        app = FastAPI()
        auth.install_auth(app, 'patient', {'A001': {}, 'B001': {}})
        app.include_router(push.router)
        with TestClient(app) as patient, TestClient(app) as unrelated:
            patient.post('/api/session/login', json={'patient_id': 'A001'})
            unrelated.post('/api/session/login', json={'patient_id': 'B001'})
            device = self.subscribe(client=patient, endpoint='patient-a')
            self.subscribe(client=unrelated, endpoint='patient-b')
            self.subscribe()
            with closing(push.connection()) as conn, conn:
                conn.execute('''INSERT INTO care_chat_messages
                    (patient_id,sender_audience,sender_subject,sender_display_name,client_key,message,created_at)
                    VALUES ('A001','staff','clinician','Doctor','test-message-key','private text',?)''', (self.now,))
                push.enqueue_chat(conn, 1, 'A001', 'staff', self.now)
            self.assertEqual(self.states(), ['QUEUED'])
            sent = []
            push.dispatch_one(self.now, lambda subscription, payload: (sent.append(payload), SimpleNamespace(status_code=201))[1])
            self.assertEqual(sent[0]['url'], '/?section=chat')
            self.assertEqual(sent[0]['tag'], 'ward-chat')
            self.assertNotIn('private text', json.dumps(sent))
            self.assertEqual(unrelated.delete(f'/api/notifications/subscriptions/{device}').status_code, 404)
            with closing(push.connection()) as conn, conn:
                push.enqueue_chat(conn, 1, 'A001', 'staff', self.now + 61)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM push_outbox').fetchone()[0], 1)
                conn.execute('''INSERT INTO care_chat_messages
                    (patient_id,sender_audience,sender_subject,sender_display_name,client_key,message,created_at)
                    VALUES ('A001','staff','clinician','Doctor','second-message-key','second private text',?)''', (self.now + 61,))
                push.enqueue_chat(conn, 2, 'A001', 'staff', self.now + 61)
                conn.execute('UPDATE care_chat_messages SET read_by_patient_at=?', (self.now + 61,))
            push.dispatch_one(self.now + 61, lambda *args: self.fail('read chat must not send'))
            self.assertEqual(self.states()[-1], 'CANCELLED')
            self.assertEqual(patient.post('/api/session/logout').status_code, 200)
            with closing(push.connection()) as conn:
                self.assertEqual(conn.execute('SELECT enabled FROM push_subscriptions WHERE id=?', (device,)).fetchone()[0], 0)

    def test_staff_chat_respects_assignment_at_enqueue_and_dispatch(self):
        self.subscribe()
        with closing(push.connection()) as conn, conn:
            conn.execute('''INSERT INTO care_chat_messages
                (patient_id,sender_audience,sender_subject,sender_display_name,client_key,message,created_at)
                VALUES ('A001','patient','A001','Patient','test-message-key','hello',?)''', (self.now,))
            with patch.object(auth, 'can_access_patient', return_value=False):
                push.enqueue_chat(conn, 1, 'A001', 'patient', self.now)
            self.assertEqual(conn.execute('SELECT count(*) FROM push_outbox').fetchone()[0], 0)
            push.enqueue_chat(conn, 1, 'A001', 'patient', self.now)
        with patch.object(auth, 'can_access_patient', return_value=False):
            push.dispatch_one(self.now, lambda *args: self.fail('revoked assignment must not send'))
        self.assertEqual(self.states(), ['CANCELLED'])

    def test_alert_scope_is_checked_before_queuing(self):
        self.subscribe()
        with patch.object(auth, 'can_access_patient', return_value=False):
            self.alert()
        self.assertEqual(self.states(), [])

    def test_chat_enqueue_is_idempotent_per_device(self):
        self.subscribe()
        with closing(push.connection()) as conn, conn:
            for _ in range(3):
                push.enqueue_chat(conn, 123, 'A001', 'patient', self.now)
        self.assertEqual(self.states(), ['QUEUED'])

    def test_existing_duplicate_chat_rows_migrate_without_losing_history(self):
        device = self.subscribe()
        with closing(push.connection()) as conn, conn:
            conn.execute('DROP INDEX idx_push_dedupe')
            conn.execute('ALTER TABLE push_outbox DROP COLUMN dedupe_key')
            for _ in range(2):
                conn.execute('''INSERT INTO push_outbox
                    (subscription_id,kind,created_at,next_attempt,updated_at)
                    VALUES (?,'CHAT:42',?,?,?)''', (device, self.now, self.now, self.now))
        push.init_notifications()
        push.init_notifications()
        with closing(push.connection()) as conn, conn:
            push.enqueue_chat(conn, 42, 'A001', 'patient', self.now)
        self.assertEqual(self.states(), ['QUEUED', 'CANCELLED'])

    def test_unassigned_chat_participants_match_in_both_portals(self):
        staff_view = care_chat._participants('A001', 'clinician')
        patient_view = care_chat._participants('A001', 'A001')
        self.assertEqual(staff_view, patient_view)
        self.assertEqual(patient_view['care_team']['subject'], 'care-team')

    def test_simulation_targets_test_accounts_only(self):
        self.subscribe()
        auth.ensure_test_accounts()
        with closing(push.connection()) as conn, conn:
            push.enqueue_simulation(conn, self.now)
        self.assertEqual(self.states(), [])
        with closing(push.connection()) as conn, conn:
            conn.execute("UPDATE portal_sessions SET subject='test_d' WHERE digest=?", (self.digest,))
            with patch.dict(os.environ, {'WARD_ENABLE_TEST_ACCOUNTS': '1'}):
                push.enqueue_simulation(conn, self.now)
        payloads = []
        push.dispatch_one(self.now, lambda sub, payload: (payloads.append(payload), SimpleNamespace(status_code=201))[1])
        self.assertEqual(payloads[0]['tag'], 'ward-simulation')
        self.assertEqual(payloads[0]['url'], '/?section=triage')

    def test_simulation_deduplicates_and_rechecks_test_mode_before_send(self):
        self.subscribe()
        auth.ensure_test_accounts()
        with closing(push.connection()) as conn, conn:
            conn.execute("UPDATE portal_sessions SET subject='test_d' WHERE digest=?", (self.digest,))
            with patch.dict(os.environ, {'WARD_ENABLE_TEST_ACCOUNTS': '1'}):
                for _ in range(2):
                    push.enqueue_simulation(conn, self.now, event_key='SIMULATION:test-cycle')
        self.assertEqual(self.states(), ['QUEUED'])
        with patch.dict(os.environ, {'WARD_ENABLE_TEST_ACCOUNTS': '0'}):
            push.dispatch_one(self.now, lambda *args: self.fail('disabled test simulation must not send'))
        self.assertEqual(self.states(), ['CANCELLED'])

    def test_simulator_recovers_from_transient_failure_and_honors_shutdown(self):
        from test_simulation import TestPatientSimulator
        simulator = object.__new__(TestPatientSimulator)
        sleeps = 0

        async def stop_after_two_ticks(_delay):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise asyncio.CancelledError()

        with patch.object(simulator, 'tick', side_effect=[sqlite3.OperationalError('test-only-lock'), []]) as tick, \
                patch('test_simulation.asyncio.sleep', side_effect=stop_after_two_ticks), \
                self.assertLogs('test_simulation', level='ERROR') as logs:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(simulator.run())
        self.assertEqual(tick.call_count, 2)
        self.assertIn('OperationalError', logs.output[0])
        self.assertNotIn('test-only-lock', logs.output[0])

    def states(self):
        with closing(push.connection()) as conn:
            return [row[0] for row in conn.execute('SELECT state FROM push_outbox ORDER BY id')]

    def test_provider_allowlist_blocks_ssrf_and_confusable_urls(self):
        for endpoint in ['http://fcm.googleapis.com/x', 'https://127.0.0.1/x', 'https://fcm.googleapis.com.evil.test/x',
                         'https://user@fcm.googleapis.com/x', 'https://fcm.googleapis.com:4433/x',
                         'https://fcm.googleapis.com/x#fragment', 'https://localhost/x',
                         'https://fcm.googleapis.com\n/x']:
            with self.subTest(endpoint=endpoint), self.assertRaises(HTTPException):
                push.validate_endpoint(endpoint)
        for endpoint in ['https://fcm.googleapis.com/fcm/send/test', 'https://updates.push.services.mozilla.com/wpush/v2/test', 'https://web.push.apple.com/test']:
            push.validate_endpoint(endpoint)

    def test_auth_session_ownership_origin_and_endpoint_privacy(self):
        device = self.subscribe()
        data = self.client.get('/api/notifications/status').json()
        self.assertNotIn('endpoint', json.dumps(data))
        self.assertNotIn('keys_json', json.dumps(data))
        self.assertEqual(self.client.post('/api/notifications/subscriptions/' + str(device) + '/test', headers={'Origin': 'https://evil.test'}).status_code, 403)
        token = dict(self.client.cookies)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/notifications/status').status_code, 401)
        self.client.post('/api/session/login', json={'password': 'push-test-only'})
        self.assertEqual(self.client.delete(f'/api/notifications/subscriptions/{device}').status_code, 404)
        self.assertEqual(self.client.post(f'/api/notifications/subscriptions/{device}/test').status_code, 404)
        self.client.cookies.update(token)

    def test_zone_severity_filter_and_deduplication(self):
        self.subscribe('A')
        self.alert(patient='B001')
        self.alert(2, severity='warning')
        self.assertEqual(self.states(), [])
        self.alert(3)
        self.alert(3)
        self.assertEqual(self.states(), ['QUEUED'])

    def test_disabled_never_queues_or_sends(self):
        self.subscribe()
        with patch.dict(os.environ, {'WARD_WEB_PUSH_ENABLED': '0'}):
            self.alert()
        self.assertEqual(self.states(), [])
        self.alert(2)
        with patch.object(push, 'configuration', return_value={'ready': False}), patch.object(push, 'send_push') as sender:
            push.dispatch_one(self.now, sender)
            sender.assert_not_called()

    def test_acceptance_is_not_delivery_and_no_patient_data_in_payload(self):
        self.subscribe()
        self.alert()
        sent = []
        def sender(subscription, payload):
            sent.append(payload)
            return SimpleNamespace(status_code=201)
        self.assertEqual(push.dispatch_one(self.now, sender), 'ACCEPTED')
        self.assertEqual(self.states(), ['ACCEPTED'])
        self.assertEqual(sent[0]['url'], '/?section=alerts')
        self.assertNotIn('A001', json.dumps(sent))
        for name in ['heart_rate', 'spo2', 'patient_id', 'diagnosis']:
            self.assertNotIn(name, json.dumps(sent))

    def test_burst_grouping_and_one_minute_throttle(self):
        self.subscribe()
        self.alert()
        self.alert(2)
        sender = lambda *args: SimpleNamespace(status_code=201)
        push.dispatch_one(self.now, sender)
        self.assertEqual(self.states(), ['ACCEPTED', 'BUNDLED'])
        self.alert(3, now=self.now + 2)
        push.dispatch_one(self.now + 3, sender)
        self.assertEqual(self.states()[-1], 'QUEUED')
        push.dispatch_one(self.now + 61, sender)
        self.assertEqual(self.states()[-1], 'ACCEPTED')

    def test_resolved_items_are_not_marked_bundled(self):
        self.subscribe()
        self.alert()
        self.alert(2)
        with closing(push.connection()) as conn, conn:
            conn.execute("UPDATE agent_alerts SET status='RESOLVED' WHERE id=2")
        push.dispatch_one(self.now, lambda *args: SimpleNamespace(status_code=201))
        self.assertEqual(self.states(), ['ACCEPTED', 'QUEUED'])
        push.dispatch_one(self.now + 1, lambda *args: self.fail('resolved item must not send'))
        self.assertEqual(self.states(), ['ACCEPTED', 'CANCELLED'])

    def test_real_encryption_vapid_and_no_redirect_with_mocked_network(self):
        """Exercise the installed SDK, but replace its final HTTP boundary."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        try:
            import pywebpush  # noqa: F401
        except ImportError:
            self.skipTest('Install optional requirements-push.txt for SDK integration')
        self.subscribe()
        with closing(push.connection()) as conn:
            row = conn.execute('SELECT endpoint, keys_json FROM push_subscriptions').fetchone()
        key_path = Path(self.temp.name) / 'test-private.pem'
        key = ec.generate_private_key(ec.SECP256R1())
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with patch.dict(os.environ, {'WARD_VAPID_PRIVATE_KEY_FILE': str(key_path), 'WARD_VAPID_SUBJECT': 'mailto:test@example.org'}), \
                patch('requests.Session.request', return_value=SimpleNamespace(status_code=201, text='', reason='Created', headers={})) as request:
            response = push.send_push({'endpoint': row['endpoint'], 'keys': json.loads(row['keys_json'])}, {'body': 'test-only-payload'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(request.call_count, 1)
        kwargs = request.call_args.kwargs
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], 10)
        self.assertIn('authorization', {name.lower() for name in kwargs['headers']})
        self.assertNotIn(b'test-only-payload', kwargs['data'])

    def test_retry_backoff_and_attempt_limit(self):
        self.subscribe()
        self.alert()
        sender = lambda *args: SimpleNamespace(status_code=503)
        self.assertEqual(push.dispatch_one(self.now, sender), 'RETRY')
        self.assertIsNone(push.dispatch_one(self.now + 1, sender))
        self.assertEqual(push.dispatch_one(self.now + 31, sender), 'RETRY')
        self.assertEqual(push.dispatch_one(self.now + 92, sender), 'FAILED')

    def test_gone_subscription_is_disabled(self):
        self.subscribe()
        self.alert()
        push.dispatch_one(self.now, lambda *args: SimpleNamespace(status_code=410))
        self.assertFalse(self.client.get('/api/notifications/status').json()['devices'][0]['enabled'])

    def _assert_rebind_fences_old_send_result(self, provider_status):
        device = self.subscribe()
        self.alert()

        def rebind_during_send(_subscription, _payload):
            self.client.post('/api/session/login', json={'password': 'push-test-only'})
            self.assertEqual(self.subscribe(), device)
            self.alert(2, now=self.now + 1)
            return SimpleNamespace(status_code=provider_status)

        self.assertEqual(push.dispatch_one(self.now, rebind_during_send), 'CANCELLED')
        self.assertEqual(self.states(), ['CANCELLED', 'QUEUED'])
        with closing(push.connection()) as conn:
            row = conn.execute('SELECT enabled,last_sent FROM push_subscriptions WHERE id=?', (device,)).fetchone()
            self.assertEqual(tuple(row), (1, 0))

    def test_old_provider_gone_response_cannot_disable_rebound_device(self):
        self._assert_rebind_fences_old_send_result(410)

    def test_old_acceptance_cannot_bundle_new_sessions_alerts(self):
        self._assert_rebind_fences_old_send_result(201)

    def test_device_limit_includes_rebound_endpoints(self):
        self.subscribe(endpoint='previous-login')
        self.client.post('/api/session/login', json={'password': 'push-test-only'})
        for number in range(5):
            self.subscribe(endpoint=f'current-login-{number}')
        with closing(push.connection()) as conn:
            old = conn.execute("SELECT endpoint,keys_json FROM push_subscriptions WHERE endpoint LIKE '%previous-login'").fetchone()
        result = self.client.post('/api/notifications/subscriptions', json={'endpoint': old['endpoint'], 'keys': json.loads(old['keys_json'])})
        self.assertEqual(result.status_code, 429)

    def test_disabled_patient_account_cannot_receive_queued_or_new_pushes(self):
        auth.set_account('patient', 'A001', 'patient-test-password')
        app = FastAPI()
        auth.install_auth(app, 'patient', {'A001': {}})
        app.include_router(push.router)
        with TestClient(app) as patient:
            patient.post('/api/session/login', json={'patient_id': 'A001', 'password': 'patient-test-password'})
            self.subscribe(client=patient, endpoint='disabled-patient')
            with closing(push.connection()) as conn, conn:
                conn.execute('''INSERT INTO care_chat_messages
                    (patient_id,sender_audience,sender_subject,sender_display_name,client_key,message,created_at)
                    VALUES ('A001','staff','clinician','Doctor','revoked-patient-key','private',?)''', (self.now,))
                push.enqueue_chat(conn, 1, 'A001', 'staff', self.now)
                conn.execute("UPDATE portal_accounts SET enabled=0 WHERE audience='patient' AND subject='A001'")
            push.dispatch_one(self.now, lambda *args: self.fail('disabled patient account must not receive push'))
            with closing(push.connection()) as conn, conn:
                push.enqueue_chat(conn, 2, 'A001', 'staff', self.now)
            self.assertEqual(self.states(), ['CANCELLED'])

    def test_malformed_chat_queue_does_not_block_other_notifications(self):
        device = self.subscribe()
        with closing(push.connection()) as conn, conn:
            conn.execute('''INSERT INTO push_outbox
                (subscription_id,kind,created_at,next_attempt,updated_at)
                VALUES (?,'CHAT:broken',?,?,?)''', (device, self.now, self.now, self.now))
        self.alert()
        push.dispatch_one(self.now, lambda *args: self.fail('malformed chat must not send'))
        self.assertEqual(push.dispatch_one(self.now + 1, lambda *args: SimpleNamespace(status_code=201)), 'ACCEPTED')
        self.assertEqual(self.states(), ['CANCELLED', 'ACCEPTED'])

    def test_expired_session_and_resolved_alert_not_sent(self):
        self.subscribe()
        self.alert()
        with closing(push.connection()) as conn, conn:
            conn.execute("UPDATE agent_alerts SET status='RESOLVED'")
        push.dispatch_one(self.now, lambda *args: self.fail('must not send resolved alert'))
        self.assertEqual(self.states(), ['CANCELLED'])
        self.alert(2)
        with closing(push.connection()) as conn, conn:
            conn.execute('UPDATE portal_sessions SET expires=0')
        push.dispatch_one(self.now, lambda *args: self.fail('must not send after expiry'))
        self.assertEqual(self.states()[-1], 'CANCELLED')

    def test_logout_revokes_subscription_and_pending_queue(self):
        self.subscribe()
        self.alert()
        self.assertEqual(self.client.post('/api/session/logout').status_code, 200)
        self.assertEqual(self.states(), ['CANCELLED'])
        with closing(push.connection()) as conn:
            self.assertEqual(conn.execute('SELECT enabled FROM push_subscriptions').fetchone()[0], 0)

    def test_old_alerts_expire_and_crash_claim_recovers(self):
        self.subscribe()
        self.alert(now=self.now - 400)
        push.dispatch_one(self.now, lambda *args: self.fail('must not send old alert'))
        self.assertEqual(self.states(), ['EXPIRED'])
        self.alert(2)
        with closing(push.connection()) as conn, conn:
            conn.execute("UPDATE push_outbox SET state='SENDING', updated_at=?, attempts=1 WHERE alert_id=2", (self.now - 60,))
        push.dispatch_one(self.now, lambda *args: SimpleNamespace(status_code=201))
        self.assertEqual(self.states()[-1], 'ACCEPTED')

    def test_test_button_rate_limit_and_no_real_alert_creation(self):
        device = self.subscribe()
        self.assertEqual(self.client.post(f'/api/notifications/subscriptions/{device}/test').status_code, 200)
        self.assertEqual(self.client.post(f'/api/notifications/subscriptions/{device}/test').status_code, 429)
        with closing(push.connection()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM agent_alerts').fetchone()[0], 0)

    def test_disable_account_immediately_cancels_outbox_and_disables_subscriptions(self):
        auth.set_account('staff', 'nurse.test', 'nurse-password-1234')
        app = FastAPI()
        auth.install_auth(app, 'staff', {})
        app.include_router(push.router)
        with TestClient(app) as staff_client:
            res = staff_client.post('/api/session/login', json={'username': 'nurse.test', 'password': 'nurse-password-1234'})
            self.assertEqual(res.status_code, 200)
            device_id = self.subscribe(client=staff_client, endpoint='staff-endpoint-disable')
            with closing(push.connection()) as conn, conn:
                conn.execute('INSERT OR IGNORE INTO agent_alerts(id,patient_id,severity,status) VALUES (201,?, ?, ?)', ('A001', 'critical', 'NEW'))
                push.enqueue_alert(conn, 201, 'A001', 'critical', self.now)

            with closing(push.connection()) as conn:
                outbox = conn.execute('SELECT state FROM push_outbox WHERE subscription_id=?', (device_id,)).fetchall()
                self.assertEqual([r[0] for r in outbox], ['QUEUED'])
                sub = conn.execute('SELECT enabled FROM push_subscriptions WHERE id=?', (device_id,)).fetchone()
                self.assertEqual(sub[0], 1)

            self.assertTrue(auth.disable_account('staff', 'nurse.test'))

            with closing(push.connection()) as conn:
                sub = conn.execute('SELECT enabled FROM push_subscriptions WHERE id=?', (device_id,)).fetchone()
                self.assertEqual(sub[0], 0)
                outbox = conn.execute('SELECT state FROM push_outbox WHERE subscription_id=?', (device_id,)).fetchall()
                self.assertEqual([r[0] for r in outbox], ['CANCELLED'])
                sessions = conn.execute("SELECT COUNT(*) FROM portal_sessions WHERE audience='staff' AND subject='nurse.test'").fetchone()
                self.assertEqual(sessions[0], 0)

    def test_delete_account_immediately_cancels_outbox_and_disables_subscriptions(self):
        auth.set_account('patient', 'A001', 'patient-password-1234')
        app = FastAPI()
        auth.install_auth(app, 'patient', {'A001': {}})
        app.include_router(push.router)
        with TestClient(app) as patient_client:
            res = patient_client.post('/api/session/login', json={'patient_id': 'A001', 'password': 'patient-password-1234'})
            self.assertEqual(res.status_code, 200)
            device_id = self.subscribe(client=patient_client, endpoint='patient-endpoint-delete')
            with closing(push.connection()) as conn, conn:
                conn.execute('''INSERT INTO care_chat_messages
                    (patient_id,sender_audience,sender_subject,sender_display_name,client_key,message,created_at)
                    VALUES ('A001','staff','clinician','Doctor','chat-delete-key','hello',?)''', (self.now,))
                push.enqueue_chat(conn, 1, 'A001', 'staff', self.now)

            with closing(push.connection()) as conn:
                outbox = conn.execute('SELECT state FROM push_outbox WHERE subscription_id=?', (device_id,)).fetchall()
                self.assertEqual([r[0] for r in outbox], ['QUEUED'])
                sub = conn.execute('SELECT enabled FROM push_subscriptions WHERE id=?', (device_id,)).fetchone()
                self.assertEqual(sub[0], 1)

            self.assertTrue(auth.delete_account('patient', 'A001'))

            with closing(push.connection()) as conn:
                sub = conn.execute('SELECT enabled FROM push_subscriptions WHERE id=?', (device_id,)).fetchone()
                self.assertEqual(sub[0], 0)
                outbox = conn.execute('SELECT state FROM push_outbox WHERE subscription_id=?', (device_id,)).fetchall()
                self.assertEqual([r[0] for r in outbox], ['CANCELLED'])
                sessions = conn.execute("SELECT COUNT(*) FROM portal_sessions WHERE audience='patient' AND subject='A001'").fetchone()
                self.assertEqual(sessions[0], 0)
                accounts = conn.execute("SELECT COUNT(*) FROM portal_accounts WHERE audience='patient' AND subject='A001'").fetchone()
                self.assertEqual(accounts[0], 0)

    def test_list_accounts_returns_status_and_never_leaks_password_hash(self):
        auth.set_account('staff', 'doctor.alpha', 'secure-password-alpha')
        auth.set_account('patient', 'A002', 'secure-password-beta')
        self.assertTrue(auth.disable_account('patient', 'A002'))

        all_accounts = auth.list_accounts()
        self.assertGreaterEqual(len(all_accounts), 2)
        for acc in all_accounts:
            self.assertNotIn('password_hash', acc)
            self.assertNotIn('password', acc)
            self.assertIn('audience', acc)
            self.assertIn('subject', acc)
            self.assertIn('enabled', acc)
            self.assertIn('is_test', acc)

        doctor = next(a for a in all_accounts if a['audience'] == 'staff' and a['subject'] == 'doctor.alpha')
        self.assertEqual(doctor['enabled'], 1)
        self.assertEqual(doctor['is_test'], 0)

        patient = next(a for a in all_accounts if a['audience'] == 'patient' and a['subject'] == 'A002')
        self.assertEqual(patient['enabled'], 0)
        self.assertEqual(patient['is_test'], 0)

        staff_only = auth.list_accounts('staff')
        self.assertTrue(all(a['audience'] == 'staff' for a in staff_only))
        self.assertTrue(any(a['subject'] == 'doctor.alpha' for a in staff_only))
        self.assertFalse(any(a['subject'] == 'A002' for a in staff_only))

        patient_only = auth.list_accounts('patient')
        self.assertTrue(all(a['audience'] == 'patient' for a in patient_only))
        self.assertTrue(any(a['subject'] == 'A002' for a in patient_only))
        self.assertFalse(any(a['subject'] == 'doctor.alpha' for a in patient_only))

        with self.assertRaises(ValueError):
            auth.list_accounts('invalid_audience')


if __name__ == '__main__':
    unittest.main()
