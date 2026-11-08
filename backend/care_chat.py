"""Session-bound two-way chat for the patient and care-team portals.

This channel is intentionally separate from AI chat and clinical alerts. Chat
text is never used for model training and never triggers emergency action.
"""
from contextlib import closing
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import auth
import notifications
from patient_registry import get_patient_profile

staff_router = APIRouter()
patient_router = APIRouter()


def connect():
    conn = sqlite3.connect(auth.DB, timeout=15)
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with closing(connect()) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS care_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            sender_audience TEXT NOT NULL CHECK(sender_audience IN ('staff','patient')),
            sender_subject TEXT NOT NULL,
            sender_display_name TEXT NOT NULL,
            client_key TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at REAL NOT NULL,
            read_by_patient_at REAL,
            read_by_staff_at REAL,
            UNIQUE(sender_audience,sender_subject,client_key)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_care_chat_patient ON care_chat_messages(patient_id,created_at,id)')


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_key: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9-]+$')
    message: str = Field(min_length=1, max_length=2000)


def _display(audience, subject):
    account = auth.account_profile(audience, subject)
    if account.get('display_name') and account['display_name'] != subject:
        return account['display_name']
    if audience == 'patient':
        profile = get_patient_profile(subject)
        if profile:
            return profile['name']
    return subject


def _serialize(row, viewer):
    return {
        'id': row['id'],
        'sender': row['sender_audience'],
        'sender_display_name': row['sender_display_name'],
        'message': row['message'],
        'created_at': row['created_at'],
        'read': bool(row['read_by_patient_at'] if viewer == 'staff' else row['read_by_staff_at']),
    }


def _require_staff_chat_allowed(request: Request) -> str:
    subject = getattr(getattr(request, 'state', None), 'subject', None)
    if not auth.is_chat_enabled_for_staff(subject):
        auth._log_security_audit(
            'CENTRAL',
            'UNAUTHORIZED_CHAT_ACCESS',
            subject or 'central',
            f'Central role ({subject}) attempted to access chat endpoint {request.url.path}',
        )
        raise HTTPException(403, 'บัญชีศูนย์กลาง (Central Console) ไม่มีระบบแชท')
    return subject


def _participants(patient_id, viewer_subject=None):
    profile = get_patient_profile(patient_id) or {}
    # Both portals describe the same room. Each patient has a single assigned
    # doctor when doctor accounts are provisioned in portal_accounts.
    doc = auth.get_patient_doctor(patient_id)
    candidate_staff_id = (doc['doctor_id'] if doc else None) or profile.get('assigned_staff_id')
    staff = auth.account_profile('staff', candidate_staff_id) if candidate_staff_id else None
    has_provisioned_staff = bool(staff and staff.get('role') != 'staff')
    effective_staff_id = candidate_staff_id if (has_provisioned_staff or patient_id == 'TEST_P') else None
    return {
        'patient': {'subject': patient_id, 'display_name': profile.get('name', patient_id), 'role': 'ผู้ป่วย'},
        'care_team': ({key: staff.get(key) for key in ('subject', 'display_name', 'role')} if has_provisioned_staff
                      else {'subject': 'care-team', 'display_name': 'ทีมดูแล Smart Ward', 'role': 'ทีมดูแล'}),
        'assignment': {'assigned_staff_id': effective_staff_id,
                       'care_setting': profile.get('care_setting', 'Smart Ward')},
    }


def _history(patient_id, viewer, viewer_subject=None):
    if not get_patient_profile(patient_id):
        raise HTTPException(404, 'ไม่พบผู้ป่วย')
    if viewer == 'staff':
        if viewer_subject and not auth.is_chat_enabled_for_staff(viewer_subject):
            auth._log_security_audit(patient_id, 'UNAUTHORIZED_CHAT_ACCESS', viewer_subject, 'Central role chat read blocked')
            raise HTTPException(403, 'บัญชีศูนย์กลาง (Central Console) ไม่มีระบบแชท')
        if viewer_subject and not auth.can_access_patient(viewer_subject, patient_id):
            auth._log_security_audit(patient_id, 'UNAUTHORIZED_CHAT_ACCESS', viewer_subject, f'Doctor {viewer_subject} blocked from reading {patient_id} chat')
            raise HTTPException(403, 'บัญชีนี้ไม่ได้รับมอบหมายให้ดูแลผู้ป่วยรายนี้')
    elif viewer == 'patient' and viewer_subject and viewer_subject.upper() != patient_id.upper():
        auth._log_security_audit(patient_id, 'UNAUTHORIZED_CHAT_ACCESS', viewer_subject, f'Patient {viewer_subject} blocked from reading {patient_id} chat')
        raise HTTPException(403, 'ผู้ป่วยสามารถสนทนากับแพทย์เจ้าของไข้ของตนเองได้เท่านั้น')
    now = time.time()
    with closing(connect()) as conn, conn:
        if viewer == 'patient':
            conn.execute('''UPDATE care_chat_messages SET read_by_patient_at=COALESCE(read_by_patient_at,?)
                WHERE patient_id=? AND sender_audience='staff' ''', (now, patient_id))
        else:
            conn.execute('''UPDATE care_chat_messages SET read_by_staff_at=COALESCE(read_by_staff_at,?)
                WHERE patient_id=? AND sender_audience='patient' ''', (now, patient_id))
        rows = conn.execute('''SELECT * FROM (
            SELECT * FROM care_chat_messages WHERE patient_id=? ORDER BY id DESC LIMIT 100
        ) ORDER BY id''', (patient_id,)).fetchall()
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_audit_logs'").fetchone():
            conn.execute(
                '''INSERT INTO agent_audit_logs(patient_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)''',
                (
                    patient_id,
                    'CARE_CHAT_VIEWED' if viewer == 'staff' else 'PATIENT_CARE_CHAT_VIEWED',
                    viewer_subject or viewer,
                    f'Opened care chat history for {patient_id}',
                    now,
                ),
            )
    profile = get_patient_profile(patient_id)
    return {'patient_id': patient_id, 'patient_display_name': profile['name'],
            'participants': _participants(patient_id, viewer_subject),
            'messages': [_serialize(row, viewer) for row in rows],
            'notice': 'ช่องทางติดตามทั่วไป ไม่ใช่ช่องทางฉุกเฉิน และข้อความไม่ถูกใช้ฝึกโมเดล'}


def _send(patient_id, body, audience, subject):
    profile = get_patient_profile(patient_id)
    if not profile:
        raise HTTPException(404, 'ไม่พบผู้ป่วย')
    if audience == 'staff':
        if not auth.is_chat_enabled_for_staff(subject):
            auth._log_security_audit(patient_id, 'UNAUTHORIZED_CHAT_ACCESS', subject, 'Central role chat send blocked')
            raise HTTPException(403, 'บัญชีศูนย์กลาง (Central Console) ไม่มีระบบแชท')
        if not auth.can_access_patient(subject, patient_id):
            auth._log_security_audit(patient_id, 'UNAUTHORIZED_CHAT_ACCESS', subject, f'Doctor {subject} blocked from sending chat to {patient_id}')
            raise HTTPException(403, 'บัญชีนี้ไม่ได้รับมอบหมายให้ดูแลผู้ป่วยรายนี้')
    elif audience == 'patient' and subject.upper() != patient_id.upper():
        auth._log_security_audit(patient_id, 'UNAUTHORIZED_CHAT_ACCESS', subject, f'Patient {subject} blocked from sending chat to {patient_id}')
        raise HTTPException(403, 'ผู้ป่วยสามารถสนทนากับแพทย์เจ้าของไข้ของตนเองได้เท่านั้น')
    message = body.message.strip()
    if not message:
        raise HTTPException(422, 'กรุณาพิมพ์ข้อความ')
    now = time.time()
    sender_display = _display(audience, subject)
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('''SELECT * FROM care_chat_messages
            WHERE sender_audience=? AND sender_subject=? AND client_key=?''',
            (audience, subject, body.client_key)).fetchone()
        if existing:
            if existing['patient_id'] != patient_id or existing['message'] != message:
                raise HTTPException(409, 'รหัสข้อความนี้ถูกใช้แล้ว กรุณาส่งข้อความใหม่')
            return {'id': existing['id'], 'stored': True}
        count = conn.execute('''SELECT COUNT(*) FROM care_chat_messages
            WHERE sender_audience=? AND sender_subject=? AND created_at>?''',
            (audience, subject, now - 3600)).fetchone()[0]
        if count >= 30:
            raise HTTPException(429, 'ส่งข้อความได้ไม่เกิน 30 ข้อความต่อชั่วโมง')
        read_patient = now if audience == 'patient' else None
        read_staff = now if audience == 'staff' else None
        cursor = conn.execute('''INSERT INTO care_chat_messages
            (patient_id,sender_audience,sender_subject,sender_display_name,client_key,message,
             created_at,read_by_patient_at,read_by_staff_at) VALUES (?,?,?,?,?,?,?,?,?)''',
            (patient_id, audience, subject, sender_display, body.client_key,
             message, now, read_patient, read_staff))
        message_id = cursor.lastrowid
        notifications.enqueue_chat(conn, message_id, patient_id, audience, now)
        conn.execute('''INSERT INTO agent_audit_logs(patient_id,action,actor,detail,created_at)
            VALUES (?,?,?,?,?)''',
            (patient_id, 'CARE_CHAT_SENT' if audience == 'staff' else 'PATIENT_CARE_CHAT_SENT', subject, f'care chat message #{message_id}', now))
    return {'id': message_id, 'stored': True}


@patient_router.get('/api/me/chat')
def own_chat(request: Request):
    return _history(request.state.subject, 'patient', request.state.subject)


@patient_router.get('/api/me/chat/status')
def own_chat_status(request: Request):
    patient_id = request.state.subject
    with closing(connect()) as conn:
        unread = conn.execute('''SELECT COUNT(*) FROM care_chat_messages WHERE patient_id=?
            AND sender_audience='staff' AND read_by_patient_at IS NULL''', (patient_id,)).fetchone()[0]
        latest = conn.execute('''SELECT id,sender_display_name,created_at FROM care_chat_messages
            WHERE patient_id=? ORDER BY id DESC LIMIT 1''', (patient_id,)).fetchone()
    return {'unread': unread, 'latest': dict(latest) if latest else None,
            'care_team': _participants(patient_id)['care_team']}


@patient_router.post('/api/me/chat', status_code=201)
def send_own_chat(body: ChatMessage, request: Request):
    return _send(request.state.subject, body, 'patient', request.state.subject)


@staff_router.get('/api/care-chat/conversations')
def conversations(request: Request, unread_only: bool = False, q: str | None = None):
    subject = _require_staff_chat_allowed(request)
    scope = auth.staff_patient_scope(subject)
    with closing(connect()) as conn:
        rows = conn.execute('''SELECT m.patient_id,m.message,m.created_at,m.sender_audience,
            (SELECT COUNT(*) FROM care_chat_messages unread
             WHERE unread.patient_id=m.patient_id AND unread.sender_audience='patient'
             AND unread.read_by_staff_at IS NULL) AS unread
            FROM care_chat_messages m
            JOIN (SELECT patient_id,MAX(id) AS max_id FROM care_chat_messages GROUP BY patient_id) latest
              ON latest.max_id=m.id
            ORDER BY m.id DESC''').fetchall()
        latest = {row['patient_id']: dict(row) for row in rows}
        # Ensure all assigned patients for a doctor (and TEST_P when test accounts enabled) are listed
        if scope is not None:
            for pid in scope:
                if pid not in latest:
                    latest[pid] = {'patient_id': pid, 'message': '', 'created_at': None,
                                   'sender_audience': None, 'unread': 0}
        elif auth.test_accounts_enabled() and 'TEST_P' not in latest:
            latest['TEST_P'] = {'patient_id': 'TEST_P', 'message': '', 'created_at': None,
                                'sender_audience': None, 'unread': 0}
    result = []
    clean_q = q.strip().lower() if q and q.strip() else None
    for patient_id, row in latest.items():
        if scope is not None and patient_id not in scope:
            continue
        if unread_only and (row.get('unread') or 0) <= 0:
            continue
        profile = get_patient_profile(patient_id)
        if not profile:
            continue
        display_name = profile.get('name', '')
        if clean_q:
            if clean_q not in patient_id.lower() and clean_q not in display_name.lower():
                continue
        doc = auth.get_patient_doctor(patient_id)
        result.append({
            **row,
            'patient_display_name': display_name,
            'doctor': (doc['doctor_display_name'] if doc else None) or profile.get('doctor', ''),
            'assigned_staff_id': (doc['doctor_id'] if doc else None) or profile.get('assigned_staff_id', ''),
        })
    result.sort(key=lambda row: (row['created_at'] is not None, row['created_at'] or 0), reverse=True)
    return {'conversations': result}


@staff_router.get('/api/care-chat/status')
def staff_chat_status(request: Request):
    subject = _require_staff_chat_allowed(request)
    scope = auth.staff_patient_scope(subject)
    with closing(connect()) as conn:
        if scope is None:
            unread = conn.execute("SELECT COUNT(*) FROM care_chat_messages WHERE sender_audience='patient' AND read_by_staff_at IS NULL").fetchone()[0]
        elif not scope:
            unread = 0
        else:
            placeholders = ','.join('?' for _ in scope)
            unread = conn.execute(f'''SELECT COUNT(*) FROM care_chat_messages WHERE sender_audience='patient'
                AND read_by_staff_at IS NULL AND patient_id IN ({placeholders})''', scope).fetchone()[0]
    return {'unread': unread}


def count_unread_by_patient(staff_subject=None):
    """Count unread messages (read_by_staff_at IS NULL) grouped by patient_id."""
    if staff_subject and not auth.is_chat_enabled_for_staff(staff_subject):
        return {}
    scope = auth.staff_patient_scope(staff_subject) if staff_subject else None
    with closing(connect()) as conn:
        if scope is not None and not scope:
            return {}
        if scope is not None:
            placeholders = ','.join('?' for _ in scope)
            rows = conn.execute(f'''SELECT patient_id, COUNT(*) AS count
                FROM care_chat_messages
                WHERE sender_audience='patient' AND read_by_staff_at IS NULL
                  AND patient_id IN ({placeholders})
                GROUP BY patient_id''', scope).fetchall()
        else:
            rows = conn.execute('''SELECT patient_id, COUNT(*) AS count
                FROM care_chat_messages
                WHERE sender_audience='patient' AND read_by_staff_at IS NULL
                GROUP BY patient_id''').fetchall()
        return {row['patient_id']: row['count'] for row in rows}


unread_summary = count_unread_by_patient
get_unread_summary = count_unread_by_patient


@staff_router.get('/api/care-chat/unread-summary')
def staff_chat_unread_summary(request: Request):
    subject = _require_staff_chat_allowed(request)
    summary = count_unread_by_patient(subject)
    total = sum(summary.values())
    return {'summary': summary, 'total_unread': total, 'unread_by_patient': summary}


@staff_router.get('/api/care-chat/{patient_id}')
def staff_chat(patient_id: str, request: Request):
    subject = _require_staff_chat_allowed(request)
    return _history(patient_id.strip().upper(), 'staff', subject)


@staff_router.post('/api/care-chat/{patient_id}', status_code=201)
def send_staff_chat(patient_id: str, body: ChatMessage, request: Request):
    subject = _require_staff_chat_allowed(request)
    return _send(patient_id.strip().upper(), body, 'staff', subject)
