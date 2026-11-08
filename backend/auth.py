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


def db_connect(timeout: float = 30.0) -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=timeout)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
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
request_staff_subject = ContextVar('ward_request_staff_subject', default=None)


def _log_security_audit(patient_id: str, action: str, actor: str, detail: str):
    try:
        with closing(db_connect()) as conn, conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_audit_logs'").fetchone():
                conn.execute(
                    "INSERT INTO agent_audit_logs(patient_id, action, actor, detail, created_at) VALUES (?,?,?,?,?)",
                    (patient_id.upper(), action, actor or 'unknown', detail, time.time()),
                )
    except Exception:
        pass


def scoped_sql(column='patient_id', scope=None):
    """A trusted SQL column and request-scoped values; never interpolate user text."""
    if scope is None:
        scope = request_patient_scope.get()
    elif isinstance(scope, str):
        scope = staff_patient_scope(scope)
    elif hasattr(scope, 'subject'):
        scope = staff_patient_scope(getattr(scope, 'subject'))
    elif hasattr(scope, 'patient_scope'):
        scope = getattr(scope, 'patient_scope')
    if scope is None:
        return '1=1', ()
    if not scope:
        return '1=0', ()
    return column + ' IN (' + ','.join('?' for _ in scope) + ')', tuple(scope)


def visible_registry(registry):
    scope = request_patient_scope.get()
    if scope is None:
        return registry
    from patient_registry import PATIENT_LOGIN_PROFILES
    return {key: PATIENT_LOGIN_PROFILES[key] for key in scope if key in PATIENT_LOGIN_PROFILES}


def require_patient_scope(patient_id):
    scope = request_patient_scope.get()
    if scope is not None and patient_id.upper() not in scope:
        actor = request_staff_subject.get() or 'scoped_staff'
        _log_security_audit(
            patient_id.upper(),
            'UNAUTHORIZED_PATIENT_ACCESS',
            actor,
            f'Blocked cross-access attempt by {actor} to unassigned patient {patient_id.upper()}',
        )
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
    with closing(db_connect()) as conn:
        for key, sql in lookups.items():
            if key in request.path_params:
                row = conn.execute(sql, (request.path_params[key],)).fetchone()
                if row:
                    require_patient_scope(row[0])
    # These shared administration/research actions are not patient-scoped yet.
    if request.url.path in {'/api/bedside/dataset.jsonl', '/api/bedside/ground-truth', '/api/bedside/status'} or (
            request.url.path.startswith('/api/agent/scenarios') and request.scope.get('method') != 'GET'):
        raise HTTPException(403, 'รายการนี้ต้องใช้บัญชีผู้ดูแลภาพรวม')


def _seed_default_doctor_assignments_conn(conn: sqlite3.Connection):
    from patient_registry import PATIENT_LOGIN_PROFILES
    now = time.time()
    for pid, profile in PATIENT_LOGIN_PROFILES.items():
        doctor_id = (profile.get('assigned_staff_id') or '').strip()
        doctor_name = (profile.get('doctor') or doctor_id).strip()
        if doctor_id:
            conn.execute(
                '''INSERT OR IGNORE INTO patient_doctor_assignments(patient_id, doctor_id, doctor_display_name, assigned_at)
                   VALUES (?, ?, ?, ?)''',
                (pid.upper(), doctor_id, doctor_name, now),
            )


def init_sessions():
    with closing(db_connect()) as conn, conn:
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
        # Relational 1-doctor-per-patient constraint: patient_id is PRIMARY KEY
        conn.execute('''CREATE TABLE IF NOT EXISTS patient_doctor_assignments (
            patient_id TEXT PRIMARY KEY,
            doctor_id TEXT NOT NULL,
            doctor_display_name TEXT NOT NULL DEFAULT '',
            assigned_at REAL NOT NULL,
            CHECK(length(trim(patient_id)) > 0 AND length(trim(doctor_id)) > 0)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_patient_doctor_by_doctor ON patient_doctor_assignments(doctor_id, patient_id)')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_settings (
            audience TEXT NOT NULL,
            subject TEXT NOT NULL,
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            PRIMARY KEY(audience, subject)
        )''')
        _seed_default_doctor_assignments_conn(conn)


def assign_patient_doctor(patient_id: str, doctor_id: str, doctor_display_name: str = '', overwrite: bool = False) -> dict:
    """Assign a patient to a single doctor.

    Enforces the 1-doctor-per-patient invariant via PRIMARY KEY(patient_id).
    When overwrite=False (default), assigning a patient who already belongs to
    a different doctor raises sqlite3.IntegrityError.
    """
    init_sessions()
    clean_pid = (patient_id or '').strip().upper()
    clean_doc = (doctor_id or '').strip()
    if not clean_pid or not clean_doc:
        raise ValueError('patient_id and doctor_id are required')
    clean_name = (doctor_display_name or clean_doc).strip()
    now = time.time()
    with closing(db_connect()) as conn, conn:
        if overwrite:
            conn.execute(
                '''INSERT INTO patient_doctor_assignments(patient_id, doctor_id, doctor_display_name, assigned_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(patient_id) DO UPDATE SET
                   doctor_id=excluded.doctor_id,
                   doctor_display_name=excluded.doctor_display_name,
                   assigned_at=excluded.assigned_at''',
                (clean_pid, clean_doc, clean_name, now),
            )
        else:
            existing = conn.execute(
                'SELECT doctor_id FROM patient_doctor_assignments WHERE patient_id=?',
                (clean_pid,),
            ).fetchone()
            if existing and existing[0] == clean_doc:
                conn.execute(
                    'UPDATE patient_doctor_assignments SET doctor_display_name=?, assigned_at=? WHERE patient_id=?',
                    (clean_name, now, clean_pid),
                )
            else:
                # Will raise sqlite3.IntegrityError if patient_id already has a row
                conn.execute(
                    '''INSERT INTO patient_doctor_assignments(patient_id, doctor_id, doctor_display_name, assigned_at)
                       VALUES (?, ?, ?, ?)''',
                    (clean_pid, clean_doc, clean_name, now),
                )
    return {'patient_id': clean_pid, 'doctor_id': clean_doc, 'doctor_display_name': clean_name}


def get_patient_doctor(patient_id: str) -> dict | None:
    clean_pid = (patient_id or '').strip().upper()
    if not clean_pid:
        return None
    try:
        with closing(db_connect()) as conn:
            row = conn.execute(
                'SELECT patient_id, doctor_id, doctor_display_name, assigned_at FROM patient_doctor_assignments WHERE patient_id=?',
                (clean_pid,),
            ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row:
        return {
            'patient_id': row[0],
            'doctor_id': row[1],
            'doctor_display_name': row[2],
            'assigned_at': row[3],
        }
    from patient_registry import get_patient_profile
    profile = get_patient_profile(clean_pid)
    if profile and profile.get('assigned_staff_id'):
        return {
            'patient_id': clean_pid,
            'doctor_id': profile['assigned_staff_id'],
            'doctor_display_name': profile.get('doctor', profile['assigned_staff_id']),
            'assigned_at': 0.0,
        }
    return None


def get_doctor_patients(doctor_id: str) -> tuple[str, ...]:
    clean_doc = (doctor_id or '').strip()
    if not clean_doc:
        return ()
    try:
        with closing(db_connect()) as conn:
            rows = conn.execute(
                'SELECT patient_id FROM patient_doctor_assignments WHERE doctor_id=? ORDER BY patient_id',
                (clean_doc,),
            ).fetchall()
        return tuple(row[0] for row in rows)
    except sqlite3.OperationalError:
        return ()


DEFAULT_USER_SETTINGS = {
    'night_shift': False,
    'sound_enabled': True,
    'warning_sound_enabled': False,
    'ai_default_tab': 'ai_overview',
    'compact_cards': False,
}


def get_user_settings(audience: str, subject: str) -> dict:
    init_sessions()
    with closing(db_connect()) as conn:
        row = conn.execute(
            'SELECT settings_json, updated_at FROM user_settings WHERE audience=? AND subject=?',
            (audience, subject),
        ).fetchone()
    merged = dict(DEFAULT_USER_SETTINGS)
    updated_at = None
    if row:
        try:
            stored = json.loads(row[0] or '{}')
            if isinstance(stored, dict):
                merged.update(stored)
        except (TypeError, ValueError):
            pass
        updated_at = row[1]
    return {'audience': audience, 'subject': subject, 'settings': merged, 'updated_at': updated_at}


def save_user_settings(audience: str, subject: str, updates: dict) -> dict:
    init_sessions()
    current = get_user_settings(audience, subject)['settings']
    allowed_keys = {'night_shift', 'sound_enabled', 'warning_sound_enabled', 'ai_default_tab', 'compact_cards'}
    for k, v in (updates or {}).items():
        if k in allowed_keys:
            if k in {'night_shift', 'sound_enabled', 'warning_sound_enabled', 'compact_cards'}:
                current[k] = bool(v)
            elif k == 'ai_default_tab' and str(v) in {'ai_overview', 'evidence', 'research'}:
                current[k] = str(v)
    now = time.time()
    with closing(db_connect()) as conn, conn:
        conn.execute(
            '''INSERT INTO user_settings(audience, subject, settings_json, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(audience, subject) DO UPDATE SET
               settings_json=excluded.settings_json,
               updated_at=excluded.updated_at''',
            (audience, subject, json.dumps(current, ensure_ascii=False), now),
        )
    return {'audience': audience, 'subject': subject, 'settings': current, 'updated_at': now}


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
    with closing(db_connect()) as conn, conn:
        conn.execute('''INSERT INTO portal_accounts(audience,subject,password_hash,enabled,updated_at) VALUES (?,?,?,1,?) ON CONFLICT(audience,subject)
            DO UPDATE SET password_hash=excluded.password_hash,enabled=1,updated_at=excluded.updated_at''',
                     (audience, subject, encoded, time.time()))
        _revoke_subject_sessions(conn, audience, subject)


def disable_account(audience, subject):
    if audience not in {'staff', 'patient'} or not subject or len(subject) > 100:
        raise ValueError('Invalid audience or subject')
    subject = subject.strip() if audience == 'staff' else subject.strip().upper()
    with closing(db_connect()) as conn, conn:
        cur = conn.execute('UPDATE portal_accounts SET enabled=0, updated_at=? WHERE audience=? AND subject=?', (time.time(), audience, subject))
        _revoke_subject_sessions(conn, audience, subject)
        return bool(cur.rowcount)


def delete_account(audience, subject):
    if audience not in {'staff', 'patient'} or not subject or len(subject) > 100:
        raise ValueError('Invalid audience or subject')
    subject = subject.strip() if audience == 'staff' else subject.strip().upper()
    with closing(db_connect()) as conn, conn:
        cur = conn.execute('DELETE FROM portal_accounts WHERE audience=? AND subject=?', (audience, subject))
        _revoke_subject_sessions(conn, audience, subject)
        return bool(cur.rowcount)


def list_accounts(audience=None):
    if audience is not None and audience not in {'staff', 'patient'}:
        raise ValueError('Invalid audience')
    init_sessions()
    with closing(db_connect()) as conn:
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
        'profile': {'role_type': 'doctor', 'professional_id': 'DEMO-MD-001', 'department': 'เวชศาสตร์ผู้สูงอายุและการดูแลที่บ้าน',
                    'organization': 'Smart Ward Demo Care Team', 'assigned_patient_ids': ['TEST_P'], 'chat_enabled': True,
                    'contact_status': 'ช่องทางสาธิต · ไม่ได้ติดต่อโรงพยาบาลจริง'},
    },
    'patient': {
        'subject': 'TEST_P', 'password': 'admin4321', 'display_name': 'ธุวานนธ์ ตอบโต้', 'role': 'ผู้ป่วยทดสอบ',
        'profile': {'role_type': 'patient', 'care_setting': 'บ้านสาธิต · Remote home care', 'assigned_staff_ids': ['test_d'],
                    'assigned_doctor_id': 'test_d', 'emergency_contact': 'ญาติสาธิต · ไม่มีการโทรจริง'},
    },
}

STAFF_DEMO_ACCOUNTS = [
    {
        'subject': 'doctor5',
        'password': 'doctor1234',
        'display_name': 'นพ. วิชัย ใจดี',
        'role': 'แพทย์เจ้าของไข้ (ดูแล 5 เตียง)',
        'profile': {
            'role_type': 'doctor',
            'professional_id': 'DEMO-MD-005',
            'department': 'อายุรกรรมระบบทางเดินหายใจและหัวใจ',
            'organization': 'Smart Ward Demo Care Team',
            'assigned_patient_ids': ['A001', 'A002', 'A003', 'A004', 'B001'],
            'chat_enabled': True,
            'contact_status': 'แชทสองทางกับผู้ป่วยในความดูแล 5 ราย (A001–A004, B001)',
        },
    },
    {
        'subject': 'central',
        'password': 'central1234',
        'display_name': 'ศูนย์กลางหอผู้ป่วย (Central Console)',
        'role': 'ศูนย์กลางติดตามภาพรวม (Central)',
        'profile': {
            'role_type': 'central',
            'professional_id': 'DEMO-CENTRAL-001',
            'department': 'ศูนย์กลางเฝ้าระวังหอผู้ป่วยใน (Central Monitoring)',
            'organization': 'Smart Ward Central Station',
            'assigned_patient_ids': None,
            'chat_enabled': False,
            'contact_status': 'โหมดศูนย์กลาง (Central) · ดูทุกเตียงและแพทย์ผู้รับผิดชอบ (ไม่มีระบบแชท)',
        },
    },
    TEST_ACCOUNTS['staff'],
    {
        'subject': 'dr_napat',
        'password': 'doctor1234',
        'display_name': 'พญ. ณภัทร สุขใจ',
        'role': 'แพทย์เจ้าของไข้ (โซน A)',
        'profile': {
            'role_type': 'doctor',
            'professional_id': 'DEMO-MD-002',
            'department': 'อายุรกรรมระบบทางเดินหายใจ',
            'organization': 'Smart Ward Demo Care Team',
            'assigned_patient_ids': [f'A{i:03d}' for i in range(5, 21)],
            'chat_enabled': True,
            'contact_status': 'ช่องทางสาธิต · แชทได้เฉพาะผู้ป่วยโซน A ในความดูแล',
        },
    },
    {
        'subject': 'dr_anong',
        'password': 'doctor1234',
        'display_name': 'พญ. อนงค์ รักษ์ดี',
        'role': 'แพทย์เจ้าของไข้ (โซน B)',
        'profile': {
            'role_type': 'doctor',
            'professional_id': 'DEMO-MD-003',
            'department': 'อายุรกรรมโรคหัวใจและเมตาบอลิซึม',
            'organization': 'Smart Ward Demo Care Team',
            'assigned_patient_ids': [f'B{i:03d}' for i in range(2, 21)],
            'chat_enabled': True,
            'contact_status': 'ช่องทางสาธิต · แชทได้เฉพาะผู้ป่วยโซน B ในความดูแล',
        },
    },
    {
        'subject': 'dr_kittisak',
        'password': 'doctor1234',
        'display_name': 'นพ. กิตติศักดิ์ มั่นคง',
        'role': 'แพทย์เจ้าของไข้ (โซน C)',
        'profile': {
            'role_type': 'doctor',
            'professional_id': 'DEMO-MD-004',
            'department': 'อายุรกรรมระบบประสาทและการดูแลระยะยาว',
            'organization': 'Smart Ward Demo Care Team',
            'assigned_patient_ids': [f'C{i:03d}' for i in range(1, 21)],
            'chat_enabled': True,
            'contact_status': 'ช่องทางสาธิต · แชทได้เฉพาะผู้ป่วยโซน C ในความดูแล',
        },
    },
]


def test_accounts_enabled():
    # Test identities are demo-only unless an operator explicitly opts in.
    default = '1' if demo_login_enabled() else '0'
    return os.getenv('WARD_ENABLE_TEST_ACCOUNTS', default) == '1'


def ensure_test_accounts():
    """Create the clearly labelled demo identities (Doctor, Central, Patient) without weakening set_account."""
    init_sessions()
    enabled = test_accounts_enabled()
    with closing(db_connect()) as conn, conn:
        if not enabled:
            conn.execute('UPDATE portal_accounts SET enabled=0,updated_at=? WHERE is_test=1', (time.time(),))
            conn.execute('''DELETE FROM portal_sessions WHERE EXISTS (
                SELECT 1 FROM portal_accounts a WHERE a.audience=portal_sessions.audience
                AND a.subject=portal_sessions.subject AND a.is_test=1)''')
            return
        now = time.time()
        all_records = [('staff', rec) for rec in STAFF_DEMO_ACCOUNTS] + [('patient', TEST_ACCOUNTS['patient'])]
        for audience, record in all_records:
            variable = 'WARD_TEST_DOCTOR_PASSWORD' if (audience == 'staff' and record['subject'] == 'test_d') else (
                'WARD_TEST_PATIENT_PASSWORD' if audience == 'patient' else None
            )
            override = os.getenv(variable) if variable else None
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
        _seed_default_doctor_assignments_conn(conn)


def account_profile(audience, subject):
    with closing(db_connect()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('''SELECT subject,display_name,role,is_test,profile_json FROM portal_accounts
            WHERE audience=? AND subject=? AND enabled=1''', (audience, subject)).fetchone()
    if not row:
        if audience == 'patient':
            from patient_registry import get_patient_profile
            patient = get_patient_profile(subject)
            if patient:
                doc = get_patient_doctor(subject)
                doc_id = (doc['doctor_id'] if doc else None) or patient.get('assigned_staff_id')
                doc_name = (doc['doctor_display_name'] if doc else None) or patient.get('doctor', '')
                return {
                    'subject': subject,
                    'display_name': patient.get('name', subject),
                    'role': 'ผู้ป่วยในหอผู้ป่วย' if patient.get('zone') != 'HOME' else 'ผู้ป่วยทดสอบ',
                    'is_test': 0,
                    'profile': {
                        'role_type': 'patient',
                        'care_setting': patient.get('care_setting') or f"โซน {patient.get('zone')} · ห้อง {patient.get('room_number')}",
                        'assigned_staff_ids': [doc_id] if doc_id else [],
                        'assigned_doctor_id': doc_id,
                        'doctor': doc_name,
                    },
                }
        if audience == 'staff' and subject == 'clinician':
            return {
                'subject': 'clinician',
                'display_name': 'ผู้ดูแลระบบหอผู้ป่วย (Clinician)',
                'role': 'เจ้าหน้าที่หอผู้ป่วย',
                'is_test': 0,
                'profile': {'role_type': 'operator', 'chat_enabled': True},
            }
        return {'subject': subject, 'display_name': subject, 'role': audience, 'is_test': 0, 'profile': {}}
    result = dict(row)
    try:
        result['profile'] = json.loads(result.pop('profile_json') or '{}')
    except (TypeError, ValueError):
        result['profile'] = {}
    return result


def staff_role_type(subject: str | None) -> str:
    """Return 'central', 'doctor', or 'operator' for a staff subject."""
    if not subject:
        return 'central'
    if subject == 'central':
        return 'central'
    profile = account_profile('staff', subject)
    explicit = profile.get('profile', {}).get('role_type')
    if explicit in {'central', 'doctor', 'operator'}:
        return explicit
    assigned = profile.get('profile', {}).get('assigned_patient_ids')
    if isinstance(assigned, list):
        return 'doctor'
    return 'central'


def is_chat_enabled_for_staff(subject: str | None) -> bool:
    """Central Console role ('central') has NO chat system at all."""
    if not subject:
        return False
    if subject == 'central':
        return False
    profile = account_profile('staff', subject).get('profile', {})
    if profile.get('chat_enabled') is False or profile.get('role_type') == 'central':
        return False
    return True


def staff_patient_scope(subject):
    """Return assigned IDs for scoped accounts; None means ward-wide access (Central / clinician)."""
    profile = account_profile('staff', subject)
    with closing(db_connect()) as conn:
        exists = conn.execute("SELECT enabled FROM portal_accounts WHERE audience='staff' AND subject=?", (subject,)).fetchone()
    if not exists:
        return None if subject == 'clinician' and demo_login_enabled() else ()
    if not exists[0]:
        return ()
    prof_data = profile.get('profile', {})
    if prof_data.get('role_type') == 'central' or subject == 'central':
        return None
    assigned = prof_data.get('assigned_patient_ids')
    if isinstance(assigned, list):
        db_patients = get_doctor_patients(subject)
        if db_patients:
            return db_patients
        return tuple(str(item).upper() for item in assigned)
    return None


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
    with closing(db_connect()) as conn, conn:
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
    with closing(db_connect()) as conn, conn:
        conn.execute('DELETE FROM portal_sessions WHERE expires<?', (time.time(),))
        conn.execute('INSERT INTO portal_sessions(digest, audience, subject, expires, auth_mode) VALUES (?,?,?,?,?)',
                     (hashlib.sha256(token.encode()).hexdigest(), audience, subject, time.time() + TTL, auth_mode))
    response.set_cookie(cookie_name(audience), token, httponly=True, samesite='strict',
                        secure=os.getenv('WARD_COOKIE_SECURE') == '1', max_age=TTL, path='/')


class Login(BaseModel):
    patient_id: str = Field(default='', max_length=20)
    username: str = Field(default='clinician', max_length=100)
    password: str = Field(default='', max_length=256)


class SettingsPayload(BaseModel):
    night_shift: bool | None = None
    sound_enabled: bool | None = None
    warning_sound_enabled: bool | None = None
    ai_default_tab: str | None = None
    compact_cards: bool | None = None


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
        subj_val = request.state.subject if audience == 'staff' and hasattr(request.state, 'subject') else None
        token = request_patient_scope.set(scope)
        subj_token = request_staff_subject.set(subj_val)
        try:
            response = await call_next(request)
        finally:
            request_patient_scope.reset(token)
            request_staff_subject.reset(subj_token)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.get('/api/session/config')
    def session_config():
        if test_accounts_enabled():
            try:
                ensure_test_accounts()
            except Exception:
                pass
        allow_prefill = test_accounts_enabled() and demo_login_enabled() and not (
            os.getenv('WARD_TEST_DOCTOR_PASSWORD') or os.getenv('WARD_TEST_PATIENT_PASSWORD'))
        test = TEST_ACCOUNTS[audience] if allow_prefill else None
        demo_accounts = []
        if allow_prefill:
            if audience == 'staff':
                demo_accounts = [
                    {
                        'subject': 'doctor5',
                        'display_name': 'นพ. วิชัย ใจดี',
                        'role': 'Doctor (ดูแล 5 เตียง: A001–A004, B001)',
                        'role_type': 'doctor',
                        'chat_enabled': True,
                        'hint_password': 'doctor1234',
                    },
                    {
                        'subject': 'central',
                        'display_name': 'ศูนย์กลางหอผู้ป่วย (Central Console)',
                        'role': 'Central (ดูทุกเตียง · ไม่มีระบบแชท)',
                        'role_type': 'central',
                        'chat_enabled': False,
                        'hint_password': 'central1234',
                    },
                    {
                        'subject': 'test_d',
                        'display_name': 'ธุวานนธ์ โต้ตอบ',
                        'role': 'Doctor ทดสอบ Home-Care (ดูแล TEST_P)',
                        'role_type': 'doctor',
                        'chat_enabled': True,
                        'hint_password': 'admin1234',
                    },
                ]
            else:
                demo_accounts = [
                    {
                        'subject': 'A001',
                        'display_name': 'Synthetic Patient A001',
                        'role': 'ผู้ป่วยหอผู้ป่วยใน (คู่กับ นพ. วิชัย / doctor5)',
                        'role_type': 'patient',
                        'chat_enabled': True,
                        'hint_password': '',
                    },
                    {
                        'subject': 'TEST_P',
                        'display_name': 'ธุวานนธ์ ตอบโต้',
                        'role': 'ผู้ป่วยทดสอบ Home-Care (คู่กับ test_d)',
                        'role_type': 'patient',
                        'chat_enabled': True,
                        'hint_password': 'admin4321',
                    },
                ]
        return {
            'demo_login': demo_login_enabled(),
            'audience': audience,
            'test_account': {k: test[k] for k in ('subject', 'display_name', 'role')} if test else None,
            'demo_accounts': demo_accounts,
        }

    @app.get('/health')
    def health():
        return {'status': 'ok', 'portal': audience}

    @app.post('/api/session/login')
    def login(body: Login, request: Request, response: Response):
        # Persistent, bounded brute-force control. No credential is logged.
        trust_proxy = os.getenv("WARD_TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes")
        forwarded = request.headers.get('x-forwarded-for') if trust_proxy else None
        host = forwarded.split(',')[0].strip() if forwarded else (request.client.host if request.client else 'local')
        client = audience + ':' + host
        with closing(db_connect()) as conn, conn:
            conn.execute('DELETE FROM login_attempts WHERE started<?', (time.time() - 60,))
            conn.execute('INSERT INTO login_attempts VALUES (?,?,1) ON CONFLICT(client) DO UPDATE SET attempts=attempts+1', (client, time.time()))
            attempts = conn.execute('SELECT attempts FROM login_attempts WHERE client=?', (client,)).fetchone()[0]
        if attempts > 20:
            raise HTTPException(429, 'Please wait a minute before retrying')
        subject = body.username.strip() if audience == 'staff' else body.patient_id.strip().upper()
        with closing(db_connect()) as conn:
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
        prof = account_profile(audience, subject)
        role_type = staff_role_type(subject) if audience == 'staff' else 'patient'
        chat_enabled = is_chat_enabled_for_staff(subject) if audience == 'staff' else True
        return {'subject': subject, 'audience': audience, 'demo': True, 'role_type': role_type, 'chat_enabled': chat_enabled, **prof}

    @app.get('/api/session')
    def session(request: Request):
        subject = request.state.subject
        prof = account_profile(audience, subject)
        role_type = staff_role_type(subject) if audience == 'staff' else 'patient'
        chat_enabled = is_chat_enabled_for_staff(subject) if audience == 'staff' else True
        return {'subject': subject, 'audience': audience, 'demo': True, 'role_type': role_type, 'chat_enabled': chat_enabled, **prof}

    @app.get('/api/session/profile')
    def session_profile(request: Request):
        subject = request.state.subject
        account = account_profile(audience, subject)
        result = {key: account[key] for key in ('subject', 'display_name', 'role', 'is_test')}
        result['role_type'] = staff_role_type(subject) if audience == 'staff' else 'patient'
        result['chat_enabled'] = is_chat_enabled_for_staff(subject) if audience == 'staff' else True
        result['details'] = account.get('profile', {})
        if audience == 'patient':
            patient = registry.get(subject, {})
            doc = get_patient_doctor(subject)
            staff_id = (doc['doctor_id'] if doc else None) or patient.get('assigned_staff_id')
            doctor_label = (doc['doctor_display_name'] if doc else None) or patient.get('doctor')
            result['patient'] = {
                **{key: patient.get(key) for key in (
                    'patient_id', 'name', 'age', 'gender', 'blood_group', 'condition', 'mobility',
                    'care_setting', 'care_goal', 'emergency_contact', 'doctor', 'assigned_staff_id')},
                'doctor': doctor_label,
                'assigned_staff_id': staff_id,
            }
            if staff_id:
                staff = account_profile('staff', staff_id)
                result['care_team'] = {key: staff.get(key) for key in ('subject', 'display_name', 'role')}
        else:
            assigned = staff_patient_scope(subject)
            result['assigned_patients'] = [
                {key: registry[patient_id].get(key) for key in ('patient_id', 'name', 'condition', 'care_setting', 'room_number', 'zone', 'doctor')}
                for patient_id in (assigned or ()) if patient_id in registry
            ]
        return result

    @app.get('/api/session/settings')
    def read_session_settings(request: Request):
        return get_user_settings(audience, request.state.subject)

    @app.put('/api/session/settings')
    def update_session_settings(body: SettingsPayload, request: Request):
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        return save_user_settings(audience, request.state.subject, updates)

    @app.post('/api/session/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get(cookie_name(audience), '')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with closing(db_connect()) as conn, conn:
            conn.execute('DELETE FROM portal_sessions WHERE digest=?', (digest,))
            if audience in {'staff', 'patient'}:
                conn.execute('UPDATE push_subscriptions SET enabled=0 WHERE session_digest=?', (digest,))
                conn.execute("UPDATE push_outbox SET state='CANCELLED', updated_at=? WHERE subscription_id IN (SELECT id FROM push_subscriptions WHERE session_digest=?) AND state IN ('QUEUED','RETRY','SENDING')", (time.time(), digest))
        response.delete_cookie(cookie_name(audience), path='/')
        return {'status': 'signed_out'}
