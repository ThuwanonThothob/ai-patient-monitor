"""Opt-in portal Web Push. Durable outbox, no clinical data in lock-screen payloads.

Provider acceptance is NOT device delivery or staff acknowledgement. Single
dispatcher (one Uvicorn worker); bounded retries may produce duplicate pushes.
Subscriptions expire with their portal session and cannot bypass portal auth.
"""
import asyncio
import base64
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import auth

router = APIRouter(prefix='/api/notifications', tags=['portal-web-push'])
MAX_ATTEMPTS = 3
MAX_AGE = 300


def connection():
    conn = sqlite3.connect(auth.DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_notifications():
    with closing(connection()) as conn, conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY, endpoint TEXT UNIQUE NOT NULL, keys_json TEXT NOT NULL,
                session_digest TEXT NOT NULL, zone TEXT NOT NULL, include_warning INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, last_sent REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS push_outbox (
                id INTEGER PRIMARY KEY, subscription_id INTEGER NOT NULL, alert_id INTEGER,
                kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'QUEUED', attempts INTEGER DEFAULT 0,
                created_at REAL NOT NULL, next_attempt REAL NOT NULL, updated_at REAL NOT NULL,
                error_code TEXT, UNIQUE(subscription_id, alert_id)
            );
            CREATE INDEX IF NOT EXISTS idx_push_pending ON push_outbox(state, next_attempt);
        ''')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(push_outbox)')}
        if 'dedupe_key' not in columns:
            conn.execute('ALTER TABLE push_outbox ADD COLUMN dedupe_key TEXT')
            # Preserve historical entries, but designate just one canonical
            # event per browser. NULL keys keep old audit rows recoverable.
            conn.execute("""UPDATE push_outbox SET dedupe_key=kind WHERE kind LIKE 'CHAT:%'
                AND id IN (SELECT MIN(id) FROM push_outbox WHERE kind LIKE 'CHAT:%'
                           GROUP BY subscription_id,kind)""")
            conn.execute("""UPDATE push_outbox SET state='CANCELLED', updated_at=?
                WHERE kind LIKE 'CHAT:%' AND dedupe_key IS NULL
                AND state IN ('QUEUED','RETRY','SENDING')""", (time.time(),))
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_push_dedupe
            ON push_outbox(subscription_id,dedupe_key) WHERE dedupe_key IS NOT NULL''')


def configuration():
    """Only public configuration is exposed. Never return a key path or secrets."""
    result = {'enabled': os.getenv('WARD_WEB_PUSH_ENABLED') == '1', 'ready': False,
              'public_key': None, 'status': 'DISABLED'}
    if not result['enabled']:
        return result
    if importlib.util.find_spec('pywebpush') is None:
        return {**result, 'status': 'MISSING_DEPENDENCY'}
    contact = os.getenv('WARD_VAPID_SUBJECT', '')
    if not (contact.startswith('mailto:') and '@' in contact and len(contact) < 250):
        return {**result, 'status': 'MISSING_CONTACT'}
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        path = Path(os.environ['WARD_VAPID_PRIVATE_KEY_FILE'])
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError('Expected P-256')
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return {**result, 'ready': True, 'status': 'READY',
                'public_key': base64.urlsafe_b64encode(public).rstrip(b'=').decode()}
    except (OSError, KeyError, ValueError, TypeError):
        return {**result, 'status': 'MISSING_OR_INVALID_KEY'}


def validate_endpoint(endpoint):
    try:
        url = urlsplit(endpoint)
        host = url.hostname or ''
        allowed = host in {'fcm.googleapis.com', 'updates.push.services.mozilla.com'} or host.endswith('.push.apple.com')
        if (url.scheme != 'https' or not allowed or url.port not in (None, 443)
                or url.username or url.password or url.fragment or not url.path
                or any(char.isspace() for char in endpoint)):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'Unsupported push provider endpoint') from None


def session_digest(request):
    return hashlib.sha256(request.cookies.get(auth.cookie_name(request.state.audience), '').encode()).hexdigest()


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=100)
    auth: str = Field(min_length=20, max_length=30)


class Subscription(BaseModel):
    endpoint: str = Field(min_length=20, max_length=2048)
    keys: PushKeys
    zone: str = Field(default='ALL', pattern='^(ALL|A|B|C)$')
    include_warning: bool = False


@router.get('/status')
def status(request: Request):
    digest = session_digest(request)
    with closing(connection()) as conn:
        devices = [dict(row) for row in conn.execute('''SELECT id, endpoint, zone, include_warning, enabled, created_at
            FROM push_subscriptions WHERE session_digest=?''', (digest,))]
        for device in devices:
            device['fingerprint'] = hashlib.sha256(device.pop('endpoint').encode()).hexdigest()
        events = [dict(row) for row in conn.execute('''SELECT o.id, o.alert_id, o.kind, o.state,
            o.attempts, o.updated_at, o.error_code FROM push_outbox o
            JOIN push_subscriptions s ON s.id=o.subscription_id
            WHERE s.session_digest=? ORDER BY o.id DESC LIMIT 30''', (digest,))]
        expires = conn.execute('SELECT expires FROM portal_sessions WHERE digest=?', (digest,)).fetchone()
    return {**configuration(), 'devices': devices, 'events': events,
            'session_expires_at': expires[0] if expires else None,
            'delivery_guaranteed': False, 'lock_screen_contains_patient_data': False}


@router.post('/subscriptions')
def subscribe(body: Subscription, request: Request):
    if not configuration()['ready']:
        raise HTTPException(503, 'Web Push is not configured')
    validate_endpoint(body.endpoint)
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        raw_key = base64.b64decode(body.keys.p256dh + '=' * (-len(body.keys.p256dh) % 4), altchars=b'-_', validate=True)
        raw_auth = base64.b64decode(body.keys.auth + '=' * (-len(body.keys.auth) % 4), altchars=b'-_', validate=True)
        if len(raw_key) != 65 or raw_key[0] != 4 or len(raw_auth) != 16:
            raise ValueError()
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw_key)
    except ValueError:
        raise HTTPException(422, 'Invalid subscription encryption keys') from None
    digest, now = session_digest(request), time.time()
    with closing(connection()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT id, session_digest, enabled FROM push_subscriptions WHERE endpoint=?', (body.endpoint,)).fetchone()
        if (not existing or existing['session_digest'] != digest or not existing['enabled']) and conn.execute(
                'SELECT count(*) FROM push_subscriptions WHERE session_digest=? AND enabled=1', (digest,)).fetchone()[0] >= 5:
            raise HTTPException(429, 'Maximum 5 devices per session')
        # A new login rebinds this browser, but never replays the previous session's backlog.
        if existing and existing['session_digest'] != digest:
            conn.execute("UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE subscription_id=? AND state IN ('QUEUED','RETRY','SENDING')", (now, existing['id']))
        conn.execute('''INSERT INTO push_subscriptions(endpoint, keys_json, session_digest, zone, include_warning, created_at)
            VALUES (?,?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET keys_json=excluded.keys_json,
            session_digest=excluded.session_digest, zone=excluded.zone, include_warning=excluded.include_warning, enabled=1''',
            (body.endpoint, body.keys.model_dump_json(), digest, body.zone, int(body.include_warning), now))
        row = conn.execute('SELECT id FROM push_subscriptions WHERE endpoint=?', (body.endpoint,)).fetchone()
    return {'id': row[0], 'status': 'SUBSCRIBED'}


@router.delete('/subscriptions/{device_id}')
def unsubscribe(device_id: int, request: Request):
    with closing(connection()) as conn, conn:
        result = conn.execute('UPDATE push_subscriptions SET enabled=0 WHERE id=? AND session_digest=?', (device_id, session_digest(request)))
        if not result.rowcount:
            raise HTTPException(404, 'Device not found in this session')
        conn.execute("UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE subscription_id=? AND state IN ('QUEUED','RETRY','SENDING')", (time.time(), device_id))
    return {'status': 'DISABLED'}


@router.post('/subscriptions/{device_id}/test')
def test_notification(device_id: int, request: Request):
    if not configuration()['ready']:
        raise HTTPException(503, 'Web Push is not configured')
    now = time.time()
    with closing(connection()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id FROM push_subscriptions WHERE id=? AND session_digest=? AND enabled=1', (device_id, session_digest(request))).fetchone()
        if not row:
            raise HTTPException(404, 'Active device not found in this session')
        if conn.execute("SELECT 1 FROM push_outbox WHERE subscription_id=? AND kind='TEST' AND created_at>?", (device_id, now - 60)).fetchone():
            raise HTTPException(429, 'Wait 60 seconds before another test')
        cursor = conn.execute("INSERT INTO push_outbox(subscription_id,kind,created_at,next_attempt,updated_at) VALUES (?,'TEST',?,?,?)", (device_id, now, now, now))
    return {'id': cursor.lastrowid, 'state': 'QUEUED'}


def enqueue_alert(conn, alert_id, patient_id, severity, now):
    """Use the alert's transaction: no network and no replay of historical alerts."""
    if os.getenv('WARD_WEB_PUSH_ENABLED') != '1':
        return
    recipients = conn.execute('''SELECT s.id,p.subject,p.auth_mode FROM push_subscriptions s
        JOIN portal_sessions p ON p.digest=s.session_digest
        WHERE s.enabled=1 AND p.audience='staff' AND p.expires>?
          AND (s.zone='ALL' OR s.zone=?) AND (?='critical' OR s.include_warning=1)''',
        (now, patient_id[:1], severity)).fetchall()
    for subscription_id, subject, auth_mode in recipients:
        if _active_recipient(conn, 'staff', subject, auth_mode) and auth.can_access_patient(subject, patient_id):
            conn.execute('''INSERT OR IGNORE INTO push_outbox
                (subscription_id,alert_id,kind,created_at,next_attempt,updated_at)
                VALUES (?,?,'ALERT',?,?,?)''', (subscription_id, alert_id, now, now, now))


def enqueue_chat(conn, message_id, patient_id, sender_audience, now):
    """Queue within the message transaction, only for authorized recipients."""
    if os.getenv('WARD_WEB_PUSH_ENABLED') != '1':
        return
    audience = 'patient' if sender_audience == 'staff' else 'staff'
    rows = conn.execute('''SELECT s.id,p.subject,p.auth_mode FROM push_subscriptions s
        JOIN portal_sessions p ON p.digest=s.session_digest
        WHERE s.enabled=1 AND p.audience=? AND p.expires>?''', (audience, now)).fetchall()
    for row in rows:
        if (not _active_recipient(conn, audience, row['subject'], row['auth_mode'])
                or (audience == 'patient' and row['subject'] != patient_id)
                or (audience == 'staff' and not auth.can_access_patient(row['subject'], patient_id))):
            continue
        event_key = f'CHAT:{message_id}'
        conn.execute('''INSERT OR IGNORE INTO push_outbox
            (subscription_id,kind,dedupe_key,created_at,next_attempt,updated_at)
            VALUES (?,?,?,?,?,?)''', (row['id'], event_key, event_key, now, now, now))


def send_push(subscription, payload):
    from pywebpush import webpush
    import requests

    class NoRedirectSession(requests.Session):
        def request(self, method, url, **kwargs):
            validate_endpoint(url)
            kwargs['allow_redirects'] = False
            return super().request(method, url, **kwargs)

    with NoRedirectSession() as session:
        return webpush(subscription_info=subscription, data=json.dumps(payload, ensure_ascii=False),
                       vapid_private_key=os.environ['WARD_VAPID_PRIVATE_KEY_FILE'],
                       vapid_claims={'sub': os.environ['WARD_VAPID_SUBJECT']},
                       ttl=60, timeout=10, headers={'Urgency': 'high'}, requests_session=session)


def enqueue_simulation(conn, now, event_key=None):
    """Only the two explicit TEST identities receive simulated event pushes."""
    if os.getenv('WARD_WEB_PUSH_ENABLED') != '1' or not auth.test_accounts_enabled():
        return
    conn.execute('''INSERT OR IGNORE INTO push_outbox
        (subscription_id,kind,dedupe_key,created_at,next_attempt,updated_at)
        SELECT s.id,'SIMULATION',?,?,?,? FROM push_subscriptions s
        JOIN portal_sessions p ON p.digest=s.session_digest
        JOIN portal_accounts a ON a.audience=p.audience AND a.subject=p.subject AND a.enabled=1
        WHERE s.enabled=1 AND p.expires>? AND
        ((p.audience='staff' AND p.subject='test_d') OR (p.audience='patient' AND p.subject='TEST_P'))''',
        (event_key, now, now, now, now))


def _active_recipient(conn, audience, subject, auth_mode='demo'):
    """Account revocation also applies to background delivery, without a request."""
    if not audience or not subject:
        return False
    auth_mode = auth_mode or 'demo'
    account = conn.execute('SELECT enabled,is_test FROM portal_accounts WHERE audience=? AND subject=?',
                           (audience, subject)).fetchone()
    if account:
        return bool(account[0]) and (not account[1] or auth.test_accounts_enabled())
    if auth_mode == 'account' or not auth.demo_login_enabled():
        return False
    if audience == 'staff':
        return subject == 'clinician'
    if audience == 'patient':
        from patient_registry import get_patient_profile
        return get_patient_profile(subject) is not None
    return False


def _chat_authorized(conn, row):
    """Malformed or obsolete queue entries cannot stall delivery to other users."""
    try:
        message_id = int(row['kind'].split(':', 1)[1])
    except (IndexError, ValueError):
        return False
    message = conn.execute('SELECT * FROM care_chat_messages WHERE id=?', (message_id,)).fetchone()
    return bool(message and (
        (row['audience'] == 'patient' and row['subject'] == message['patient_id']
         and message['sender_audience'] == 'staff' and message['read_by_patient_at'] is None)
        or (row['audience'] == 'staff' and message['sender_audience'] == 'patient'
            and auth.can_access_patient(row['subject'], message['patient_id'])
            and message['read_by_staff_at'] is None)))


def dispatch_one(now=None, sender=send_push):
    """Called in a thread, never on the telemetry event loop. No secret error logs."""
    now = time.time() if now is None else now
    if not configuration()['ready']:
        return
    with closing(connection()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        # Recover abandoned leases. Retry is at-least-once, never exactly-once.
        conn.execute("UPDATE push_outbox SET state='RETRY', next_attempt=? WHERE state='SENDING' AND updated_at<?", (now, now - 45))
        conn.execute("UPDATE push_outbox SET state='EXPIRED', updated_at=? WHERE state IN ('QUEUED','RETRY') AND created_at<?", (now, now - MAX_AGE))
        conn.execute("UPDATE push_outbox SET state='FAILED', updated_at=? WHERE state='RETRY' AND attempts>=?", (now, MAX_ATTEMPTS))
        row = conn.execute('''SELECT o.*, s.endpoint, s.keys_json, s.session_digest, s.zone, s.include_warning, s.last_sent,
            s.enabled, p.expires, p.audience, p.subject, p.auth_mode, a.status AS alert_status, a.patient_id, a.severity, a.merged_into
            FROM push_outbox o JOIN push_subscriptions s ON s.id=o.subscription_id
            LEFT JOIN portal_sessions p ON p.digest=s.session_digest
            LEFT JOIN agent_alerts a ON a.id=o.alert_id
            WHERE o.state IN ('QUEUED','RETRY') AND o.next_attempt<=? ORDER BY o.id LIMIT 1''', (now,)).fetchone()
        if not row:
            return
        chat_allowed = not row['kind'].startswith('CHAT:') or _chat_authorized(conn, row)
        known_kind = row['kind'] in {'TEST', 'ALERT', 'SIMULATION'} or row['kind'].startswith('CHAT:')
        simulation_allowed = row['kind'] != 'SIMULATION' or (auth.test_accounts_enabled() and (
            (row['audience'] == 'staff' and row['subject'] == 'test_d')
            or (row['audience'] == 'patient' and row['subject'] == 'TEST_P')))
        if not known_kind or not simulation_allowed or not chat_allowed or (row['kind'] == 'ALERT' and (
                row['audience'] != 'staff' or not auth.can_access_patient(row['subject'], row['patient_id'] or ''))):
            conn.execute("UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE id=?", (now, row['id']))
            return
        if (not row['enabled'] or (row['expires'] or 0) <= now
                or not _active_recipient(conn, row['audience'], row['subject'], row['auth_mode'] or 'demo') or (row['kind'] == 'ALERT' and (
            row['merged_into'] is not None or row['alert_status'] not in ('NEW', 'ESCALATED') or (row['zone'] != 'ALL' and row['zone'] != (row['patient_id'] or '')[:1])
            or (row['severity'] != 'critical' and not row['include_warning'])))):
            conn.execute("UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE id=?", (now, row['id']))
            return

        # One provider request per device per minute; consolidate pending alerts.
        if row['last_sent'] > now - 60:
            conn.execute('UPDATE push_outbox SET next_attempt=? WHERE id=?', (row['last_sent'] + 60, row['id']))
            return
        conn.execute("UPDATE push_outbox SET state='SENDING', attempts=attempts+1, updated_at=? WHERE id=?", (now, row['id']))
    payload = {'title': 'Smart Ward · ทดสอบ' if row['kind'] == 'TEST' else 'Smart Ward · มีรายการให้ตรวจสอบ',
               'body': 'เปิดศูนย์ดูแลและเข้าสู่ระบบเพื่อตรวจสอบรายละเอียด ไม่ใช่ระบบฉุกเฉิน',
               'url': '/?section=notifications' if row['kind'] == 'TEST' else '/?section=alerts',
               'tag': 'ward-test' if row['kind'] == 'TEST' else 'ward-review'}
    if row['kind'].startswith('CHAT:'):
        payload = {'title': 'Smart Ward · มีข้อความใหม่',
                   'body': 'เปิดแอปเพื่ออ่านข้อความ', 'tag': 'ward-chat',
                   'url': '/?section=triage' if row['audience'] == 'staff' else '/?section=chat'}
    elif row['kind'] == 'TEST' and row['audience'] == 'patient':
        payload['url'] = '/?section=chat'
    elif row['kind'] == 'SIMULATION':
        payload = {'title': 'Smart Ward · เหตุการณ์จำลอง TEST', 'body': 'เปิดแอปดูเหตุการณ์จำลอง',
                   'tag': 'ward-simulation', 'url': '/?section=triage' if row['audience'] == 'staff' else '/'}
    code, state, error = None, 'ACCEPTED', None
    try:
        response = sender({'endpoint': row['endpoint'], 'keys': json.loads(row['keys_json'])}, payload)
        code = response.status_code
    except Exception as exc:
        response = getattr(exc, 'response', None)
        code = getattr(response, 'status_code', None)
    if code not in (200, 201, 202):
        error = 'NETWORK_OR_SEND_ERROR' if code is None else f'HTTP_{code}'
        retry = code is None or code == 429 or code >= 500
        state = 'RETRY' if retry and row['attempts'] + 1 < MAX_ATTEMPTS else 'FAILED'
    with closing(connection()) as conn, conn:
        result = conn.execute('''UPDATE push_outbox SET state=?, updated_at=?, next_attempt=?, error_code=?
            WHERE id=? AND state='SENDING' AND attempts=? AND EXISTS (
                SELECT 1 FROM push_subscriptions s WHERE s.id=subscription_id
                AND s.session_digest=? AND s.keys_json=?)''',
            (state, now, now + 30 * 2 ** row['attempts'], error, row['id'], row['attempts'] + 1,
             row['session_digest'], row['keys_json']))
        if not result.rowcount:
            # Logout/unsubscribe/rebind may happen while the network request
            # is in flight. Its result must not mutate the new subscription
            # or bundle messages queued for a different authenticated session.
            return 'CANCELLED'
        if code in (404, 410):
            conn.execute('UPDATE push_subscriptions SET enabled=0 WHERE id=?', (row['subscription_id'],))
        if state == 'ACCEPTED':
            conn.execute('UPDATE push_subscriptions SET last_sent=? WHERE id=?', (now, row['subscription_id']))
            if row['kind'] == 'ALERT':
                conn.execute('''UPDATE push_outbox SET state='BUNDLED', updated_at=?
                    WHERE subscription_id=? AND kind='ALERT' AND state IN ('QUEUED','RETRY') AND created_at<=?
                    AND alert_id IN (SELECT id FROM agent_alerts WHERE merged_into IS NULL AND status IN ('NEW','ESCALATED')
                        AND (?='ALL' OR substr(patient_id,1,1)=?) AND (severity='critical' OR ?=1))''',
                    (now, row['subscription_id'], now, row['zone'], row['zone'], row['include_warning']))
    return state


async def run_dispatcher():
    while True:
        try:
            await asyncio.to_thread(dispatch_one)
        except Exception:
            # Deliberately no exception repr: provider errors may contain keys/endpoints.
            print('Web Push dispatcher failed; pending entries remain in SQLite')
        await asyncio.sleep(1)
