"""Separate staff/patient demo sessions, enforced on the server.

ID-only admission is deliberately limited to the synthetic registry. For real
patients replace it with verified identity (password/OTP/identity provider).
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from contextlib import closing
import sqlite3
import time
from contextvars import ContextVar

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from starlette.requests import HTTPConnection

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv('WARD_DB_PATH', str(ROOT / 'vitals.db')))
ORIGINS = {'staff': {'http://localhost:3000', 'http://127.0.0.1:3000'},
           'patient': {'http://localhost:3001', 'http://127.0.0.1:3001'}}
# Explicit HTTPS origins for a reverse proxy; never trust a client-supplied Host.
from urllib.parse import urlsplit
for audience in ('staff', 'patient'):
    for origin in os.getenv(f'WARD_{audience.upper()}_ORIGIN', '').split(','):
        origin = origin.strip().rstrip('/')
        if not origin:
            continue
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('WARD portal origins must be exact HTTPS origins')
        ORIGINS[audience].add(origin)
TTL = 8 * 3600
request_patient_scope = ContextVar('ward_request_patient_scope', default=None)


def scoped_sql(column='patient_id'):
    """A trusted SQL column and request-scoped values; never interpolate user text."""
    scope = request_patient_scope.get()
    if scope is None:
        return '1=1', ()
    return column + ' IN (' + ','.join('?' for _ in scope) + ')', scope


def visible_registry(registry):
    scope = request_patient_scope.get()
    if scope is None:
        return registry
    from patient_registry import PATIENT_LOGIN_PROFILES
    return {key: PATIENT_LOGIN_PROFILES[key] for key in scope if key in PATIENT_LOGIN_PROFILES}


def require_patient_scope(patient_id):
    scope = request_patient_scope.get()
    if scope is not None and patient_id.upper() not in scope:
        raise HTTPException(403, 'บัญชีนี้ไม่ได้รับมอบหมายให้ดูแลผู้ป่วยรายนี้')


def authorize_staff_resource(request: HTTPConnection):
    """Runs after routing, before any staff endpoint reads or mutates a resource."""
    scope = request_patient_scope.get()
    if scope is None:
        return
    patient_id = request.path_params.get('patient_id') or request.query_params.get('patient_id')
    if patient_id:
        require_patient_scope(patient_id)
    lookups = {
        'alert_id': 'SELECT patient_id FROM agent_alerts WHERE id=?',
        'plan_id': 'SELECT patient_id FROM care_plans WHERE id=?',
        'task_id': 'SELECT p.patient_id FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE t.id=?',
    }
    if request.url.path.startswith('/api/care-messages/'):
        lookups['message_id'] = 'SELECT patient_id FROM care_messages WHERE id=?'
    with closing(sqlite3.connect(DB, timeout=10)) as conn:
        for key, sql in lookups.items():
            if key in request.path_params:
                row = conn.execute(sql, (request.path_params[key],)).fetchone()
                if row:
                    require_patient_scope(row[0])
    # These shared administration/research actions are not patient-scoped yet.
    if request.url.path in {'/api/bedside/dataset.jsonl', '/api/bedside/ground-truth', '/api/bedside/status'} or (
            request.url.path.startswith('/api/agent/scenarios') and request.scope.get('method') != 'GET'):
        raise HTTPException(403, 'รายการนี้ต้องใช้บัญชีผู้ดูแลภาพรวม')


def init_sessions():
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("CREATE TABLE IF NOT EXISTS portal_sessions (digest TEXT PRIMARY KEY, audience TEXT, subject TEXT, expires REAL, auth_mode TEXT NOT NULL DEFAULT 'demo')")
        session_cols = {row[1] for row in conn.execute('PRAGMA table_info(portal_sessions)')}
        if 'auth_mode' not in session_cols:
            conn.execute("ALTER TABLE portal_sessions ADD COLUMN auth_mode TEXT NOT NULL DEFAULT 'demo'")
        conn.execute('CREATE TABLE IF NOT EXISTS login_attempts (client TEXT PRIMARY KEY, started REAL, attempts INTEGER)')
        conn.execute('''CREATE TABLE IF NOT EXISTS portal_accounts (
            audience TEXT NOT NULL, subject TEXT NOT NULL, password_hash TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL,
            PRIMARY KEY(audience,subject))''')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(portal_accounts)')}
        for name, definition in (
            ('display_name', "TEXT NOT NULL DEFAULT ''"),
            ('role', "TEXT NOT NULL DEFAULT ''"),
            ('is_test', 'INTEGER NOT NULL DEFAULT 0'),
            ('profile_json', "TEXT NOT NULL DEFAULT '{}'"),
        ):
            if name not in columns:
                conn.execute(f'ALTER TABLE portal_accounts ADD COLUMN {name} {definition}')


def _encode_password(password):
    """Encode a password without changing the public 12-character policy."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()


def hash_password(password):
    if len(password) < 12:
        raise ValueError('Password must contain at least 12 characters')
    return _encode_password(password)


def verify_password(password, encoded):
    try:
        salt, expected = encoded.split(':')
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _revoke_subject_sessions(conn, audience, subject):
    digests = [row[0] for row in conn.execute('SELECT digest FROM portal_sessions WHERE audience=? AND subject=?', (audience, subject)).fetchall()]
    conn.execute('DELETE FROM portal_sessions WHERE audience=? AND subject=?', (audience, subject))
    if digests:
        placeholders = ','.join('?' for _ in digests)
        try:
            conn.execute(f'UPDATE push_subscriptions SET enabled=0 WHERE session_digest IN ({placeholders})', digests)
            conn.execute(
                f"UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE subscription_id IN (SELECT id FROM push_subscriptions WHERE session_digest IN ({placeholders})) AND state IN ('QUEUED','RETRY','SENDING')",
                (time.time(), *digests),
            )
        except sqlite3.OperationalError:
            pass


def set_account(audience, subject, password):
    if audience not in {'staff', 'patient'} or not subject or len(subject) > 100:
        raise ValueError('Invalid audience or subject')
    subject = subject.strip() if audience == 'staff' else subject.strip().upper()
    encoded = hash_password(password)
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        conn.execute('''INSERT INTO portal_accounts(audience,subject,password_hash,enabled,updated_at) VALUES (?,?,?,1,?) ON CONFLICT(audience,subject)
            DO UPDATE SET password_hash=excluded.password_hash,enabled=1,updated_at=excluded.updated_at''',
                     (audience, subject, encoded, time.time()))
        _revoke_subject_sessions(conn, audience, subject)


def disable_account(audience, subject):
    if audience not in {'staff', 'patient'} or not subject or len(subject) > 100:
        raise ValueError('Invalid audience or subject')
    subject = subject.strip() if audience == 'staff' else subject.strip().upper()
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        cur = conn.execute('UPDATE portal_accounts SET enabled=0, updated_at=? WHERE audience=? AND subject=?', (time.time(), audience, subject))
        _revoke_subject_sessions(conn, audience, subject)
        return bool(cur.rowcount)


def delete_account(audience, subject):
    if audience not in {'staff', 'patient'} or not subject or len(subject) > 100:
        raise ValueError('Invalid audience or subject')
    subject = subject.strip() if audience == 'staff' else subject.strip().upper()
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        cur = conn.execute('DELETE FROM portal_accounts WHERE audience=? AND subject=?', (audience, subject))
        _revoke_subject_sessions(conn, audience, subject)
        return bool(cur.rowcount)


def list_accounts(audience=None):
    if audience is not None and audience not in {'staff', 'patient'}:
        raise ValueError('Invalid audience')
    init_sessions()
    with closing(sqlite3.connect(DB, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        if audience is not None:
            rows = conn.execute(
                '''SELECT audience, subject, enabled, updated_at, display_name, role, is_test, profile_json
                   FROM portal_accounts WHERE audience=? ORDER BY audience, subject''',
                (audience,)
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT audience, subject, enabled, updated_at, display_name, role, is_test, profile_json
                   FROM portal_accounts ORDER BY audience, subject'''
            ).fetchall()
        result = []
        for row in rows:
            record = dict(row)
            try:
                record['profile'] = json.loads(record.pop('profile_json') or '{}')
            except (TypeError, ValueError):
                record['profile'] = {}
            record['enabled'] = int(record['enabled'])
            record['is_test'] = int(record['is_test'])
            record.pop('password_hash', None)
            result.append(record)
        return result



TEST_ACCOUNTS = {
    'staff': {
        'subject': 'test_d', 'password': 'admin1234', 'display_name': 'ธุวานนธ์ โต้ตอบ', 'role': 'แพทย์ทดสอบ',
        'profile': {'professional_id': 'DEMO-MD-001', 'department': 'เวชศาสตร์ผู้สูงอายุและการดูแลที่บ้าน',
                    'organization': 'Smart Ward Demo Care Team', 'assigned_patient_ids': ['TEST_P'],
                    'contact_status': 'ช่องทางสาธิต · ไม่ได้ติดต่อโรงพยาบาลจริง'},
    },
    'patient': {
        'subject': 'TEST_P', 'password': 'admin4321', 'display_name': 'ธุวานนธ์ ตอบโต้', 'role': 'ผู้ป่วยทดสอบ',
        'profile': {'care_setting': 'บ้านสาธิต · Remote home care', 'assigned_staff_ids': ['test_d'],
                    'emergency_contact': 'ญาติสาธิต · ไม่มีการโทรจริง'},
    },
}


def test_accounts_enabled():
    # Test identities are demo-only unless an operator explicitly opts in.
    default = '1' if demo_login_enabled() else '0'
    return os.getenv('WARD_ENABLE_TEST_ACCOUNTS', default) == '1'


def ensure_test_accounts():
    """Create the two clearly labelled demo identities without weakening set_account."""
    init_sessions()
    enabled = test_accounts_enabled()
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        if not enabled:
            conn.execute('UPDATE portal_accounts SET enabled=0,updated_at=? WHERE is_test=1', (time.time(),))
            conn.execute('''DELETE FROM portal_sessions WHERE EXISTS (
                SELECT 1 FROM portal_accounts a WHERE a.audience=portal_sessions.audience
                AND a.subject=portal_sessions.subject AND a.is_test=1)''')
            return
        now = time.time()
        for audience, record in TEST_ACCOUNTS.items():
            # The requested demo passwords are shorter than production policy,
            # so they are accepted only through this fixed, gated bootstrap.
            variable = 'WARD_TEST_DOCTOR_PASSWORD' if audience == 'staff' else 'WARD_TEST_PATIENT_PASSWORD'
            override = os.getenv(variable)
            if override is not None and len(override) < 12:
                raise ValueError(variable + ' must contain at least 12 characters')
            existing = conn.execute('SELECT password_hash FROM portal_accounts WHERE audience=? AND subject=?',
                                    (audience, record['subject'])).fetchone()
            password = override if override is not None else record['password']
            # Preserve an operator-changed password; restart is not a password reset.
            encoded = existing[0] if existing else _encode_password(password)
            if override is not None and existing and not verify_password(override, existing[0]):
                encoded = _encode_password(override)
                conn.execute('DELETE FROM portal_sessions WHERE audience=? AND subject=?', (audience, record['subject']))
            conn.execute('''INSERT INTO portal_accounts
                (audience,subject,password_hash,enabled,updated_at,display_name,role,is_test,profile_json)
                VALUES (?,?,?,?,?,?,?,1,?)
                ON CONFLICT(audience,subject) DO UPDATE SET
                password_hash=excluded.password_hash,enabled=1,updated_at=excluded.updated_at,
                display_name=excluded.display_name,role=excluded.role,is_test=1,profile_json=excluded.profile_json''',
                (audience, record['subject'], encoded, 1, now, record['display_name'], record['role'],
                 json.dumps(record['profile'], ensure_ascii=False)))


def account_profile(audience, subject):
    with closing(sqlite3.connect(DB, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('''SELECT subject,display_name,role,is_test,profile_json FROM portal_accounts
            WHERE audience=? AND subject=? AND enabled=1''', (audience, subject)).fetchone()
    if not row:
        return {'subject': subject, 'display_name': subject, 'role': audience, 'is_test': 0, 'profile': {}}
    result = dict(row)
    try:
        result['profile'] = json.loads(result.pop('profile_json') or '{}')
    except (TypeError, ValueError):
        result['profile'] = {}
    return result


def staff_patient_scope(subject):
    """Return assigned IDs for scoped accounts; None means ward-wide demo access."""
    profile = account_profile('staff', subject)
    with closing(sqlite3.connect(DB, timeout=10)) as conn:
        exists = conn.execute("SELECT enabled FROM portal_accounts WHERE audience='staff' AND subject=?", (subject,)).fetchone()
    if not exists:
        return None if subject == 'clinician' and demo_login_enabled() else ()
    if not exists[0]:
        return ()
    assigned = profile.get('profile', {}).get('assigned_patient_ids')
    return tuple(str(item).upper() for item in assigned) if isinstance(assigned, list) else None


def can_access_patient(staff_subject, patient_id):
    scope = staff_patient_scope(staff_subject)
    return scope is None or patient_id.upper() in scope


def demo_login_enabled():
    return os.getenv('WARD_DEMO_ID_LOGIN', '1') == '1'


def credential_path():
    return ROOT / '.staff-password'


def staff_password():
    value = os.getenv('WARD_STAFF_PASSWORD')
    if value:
        return value
    path = credential_path()
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(secrets.token_urlsafe(18) + '\n')
        except FileExistsError:
            pass
    return path.read_text().strip()


def cookie_name(audience):
    return 'ward_' + audience + '_session'


def identity(cookies, audience):
    token = cookies.get(cookie_name(audience), '')
    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        row = conn.execute('SELECT subject, expires, auth_mode FROM portal_sessions WHERE digest=? AND audience=? AND expires>?',
                           (digest, audience, now)).fetchone()
        if row:
            subject, expires, auth_mode = row[0], row[1], row[2] if len(row) > 2 else 'demo'
            account = conn.execute('SELECT enabled, is_test FROM portal_accounts WHERE audience=? AND subject=?', (audience, subject)).fetchone()
            if account:
                if not account[0] or (account[1] and not test_accounts_enabled()):
                    return None
            elif auth_mode == 'account' or not demo_login_enabled():
                return None
            if expires - now < TTL / 2:
                conn.execute('UPDATE portal_sessions SET expires=? WHERE digest=?', (now + TTL, digest))
            return subject
    return None


def issue(response, audience, subject, auth_mode='demo'):
    token = secrets.token_urlsafe(32)
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        conn.execute('DELETE FROM portal_sessions WHERE expires<?', (time.time(),))
        conn.execute('INSERT INTO portal_sessions(digest, audience, subject, expires, auth_mode) VALUES (?,?,?,?,?)',
                     (hashlib.sha256(token.encode()).hexdigest(), audience, subject, time.time() + TTL, auth_mode))
    response.set_cookie(cookie_name(audience), token, httponly=True, samesite='strict',
                        secure=os.getenv('WARD_COOKIE_SECURE') == '1', max_age=TTL, path='/')


class Login(BaseModel):
    patient_id: str = Field(default='', max_length=20)
    username: str = Field(default='clinician', max_length=100)
    password: str = Field(default='', max_length=256)


def install_auth(app, audience, registry):
    @app.middleware('http')
    async def authorize(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in ORIGINS[audience]:
            return JSONResponse({'detail': 'Portal origin not allowed'}, status_code=403)
        if request.url.path not in {'/health', '/api/session/login', '/api/session/config'}:
            subject = identity(request.cookies, audience)
            if not subject:
                return JSONResponse({'detail': 'Login required'}, status_code=401)
            request.state.subject = subject
            request.state.audience = audience
        scope = staff_patient_scope(request.state.subject) if audience == 'staff' and hasattr(request.state, 'subject') else None
        token = request_patient_scope.set(scope)
        try:
            response = await call_next(request)
        finally:
            request_patient_scope.reset(token)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.get('/api/session/config')
    def session_config():
        test = TEST_ACCOUNTS[audience] if test_accounts_enabled() and demo_login_enabled() and not (
            os.getenv('WARD_TEST_DOCTOR_PASSWORD') or os.getenv('WARD_TEST_PATIENT_PASSWORD')) else None
        return {'demo_login': demo_login_enabled(), 'audience': audience,
                'test_account': {k: test[k] for k in ('subject', 'display_name', 'role')} if test else None}

    @app.get('/health')
    def health():
        return {'status': 'ok', 'portal': audience}

    @app.post('/api/session/login')
    def login(body: Login, request: Request, response: Response):
        # Persistent, bounded brute-force control. No credential is logged.
        client = audience + ':' + (request.client.host if request.client else 'local')
        with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
            conn.execute('DELETE FROM login_attempts WHERE started<?', (time.time() - 60,))
            conn.execute('INSERT INTO login_attempts VALUES (?,?,1) ON CONFLICT(client) DO UPDATE SET attempts=attempts+1', (client, time.time()))
            attempts = conn.execute('SELECT attempts FROM login_attempts WHERE client=?', (client,)).fetchone()[0]
        if attempts > 20:
            raise HTTPException(429, 'Please wait a minute before retrying')
        subject = body.username.strip() if audience == 'staff' else body.patient_id.strip().upper()
        with closing(sqlite3.connect(DB, timeout=10)) as conn:
            account = conn.execute('SELECT password_hash,enabled FROM portal_accounts WHERE audience=? AND subject=?', (audience, subject)).fetchone()
        if account:
            valid = bool(account[1]) and verify_password(body.password, account[0])
            auth_mode = 'account'
        elif demo_login_enabled():
            valid = (subject == 'clinician' and hmac.compare_digest(body.password, staff_password())) if audience == 'staff' else subject in registry
            auth_mode = 'demo'
        else:
            valid = False
            auth_mode = 'demo'
        if not valid or (audience == 'patient' and subject not in registry):
            raise HTTPException(401, 'ข้อมูลเข้าสู่ระบบไม่ถูกต้อง')
        issue(response, audience, subject, auth_mode=auth_mode)
        return {'subject': subject, 'audience': audience, 'demo': True, **account_profile(audience, subject)}


    @app.get('/api/session')
    def session(request: Request):
        return {'subject': request.state.subject, 'audience': audience, 'demo': True,
                **account_profile(audience, request.state.subject)}

    @app.get('/api/session/profile')
    def session_profile(request: Request):
        subject = request.state.subject
        account = account_profile(audience, subject)
        result = {key: account[key] for key in ('subject', 'display_name', 'role', 'is_test')}
        result['details'] = account.get('profile', {})
        if audience == 'patient':
            patient = registry.get(subject, {})
            result['patient'] = {key: patient.get(key) for key in (
                'patient_id', 'name', 'age', 'gender', 'blood_group', 'condition', 'mobility',
                'care_setting', 'care_goal', 'emergency_contact', 'doctor', 'assigned_staff_id')}
            staff_id = patient.get('assigned_staff_id')
            if staff_id:
                staff = account_profile('staff', staff_id)
                result['care_team'] = {key: staff.get(key) for key in ('subject', 'display_name', 'role')}
        else:
            assigned = staff_patient_scope(subject)
            result['assigned_patients'] = [
                {key: registry[patient_id].get(key) for key in ('patient_id', 'name', 'condition', 'care_setting')}
                for patient_id in (assigned or ()) if patient_id in registry
            ]
        return result

    @app.post('/api/session/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get(cookie_name(audience), '')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
            conn.execute('DELETE FROM portal_sessions WHERE digest=?', (digest,))
            if audience in {'staff', 'patient'}:
                conn.execute('UPDATE push_subscriptions SET enabled=0 WHERE session_digest=?', (digest,))
                conn.execute("UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE subscription_id IN (SELECT id FROM push_subscriptions WHERE session_digest=?) AND state IN ('QUEUED','RETRY','SENDING')", (time.time(), digest))
        response.delete_cookie(cookie_name(audience), path='/')
        return {'status': 'signed_out'}
