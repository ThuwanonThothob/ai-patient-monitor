"""Patient-to-team messages with session-bound identity and explicit receipt."""
from contextlib import closing
import sqlite3
import time
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
import auth

staff_router = APIRouter()
patient_router = APIRouter()


def init():
    with closing(sqlite3.connect(auth.DB, timeout=10)) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS care_messages (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, request_key TEXT NOT NULL,
            topic TEXT NOT NULL, message TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'NEW',
            created_at REAL NOT NULL, updated_at REAL NOT NULL, assigned_to TEXT, reply TEXT NOT NULL DEFAULT '',
            UNIQUE(patient_id,request_key))''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_care_messages_patient ON care_messages(patient_id,created_at)')


def connect():
    conn = sqlite3.connect(auth.DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9-]+$')
    topic: Literal['symptom', 'device', 'care']
    message: str = Field(min_length=5, max_length=1000)


@patient_router.get('/api/me/messages')
def own_messages(request: Request):
    with closing(connect()) as conn:
        rows = conn.execute('SELECT * FROM care_messages WHERE patient_id=? ORDER BY id DESC LIMIT 30', (request.state.subject,)).fetchall()
    # Replies are intentionally patient-facing; staff identity remains private.
    return {'messages': [{k: r[k] for k in ('id','topic','message','state','created_at','updated_at','reply')} for r in rows]}


@patient_router.post('/api/me/messages', status_code=201)
def send(body: Message, request: Request):
    if len(body.message.strip()) < 5:
        raise HTTPException(422, 'กรุณาระบุรายละเอียดอย่างน้อย 5 ตัวอักษร')
    patient = request.state.subject
    now = time.time()
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT id,topic,message FROM care_messages WHERE patient_id=? AND request_key=?', (patient, body.request_key)).fetchone()
        if previous:
            if previous['topic'] != body.topic or previous['message'] != body.message.strip():
                raise HTTPException(409, 'รหัสรายการนี้ถูกใช้แล้ว กรุณาส่งรายการใหม่')
            return {'id': previous['id'], 'stored': True}
        count = conn.execute('SELECT COUNT(*) FROM care_messages WHERE patient_id=? AND created_at>?', (patient, now - 3600)).fetchone()[0]
        if count >= 5:
            raise HTTPException(429, 'ส่งได้ไม่เกิน 5 รายการต่อชั่วโมง หากต้องการความช่วยเหลือทันทีให้ติดต่อทีมดูแลโดยตรง')
        cur = conn.execute('INSERT INTO care_messages(patient_id,request_key,topic,message,created_at,updated_at) VALUES (?,?,?,?,?,?)', (patient, body.request_key, body.topic, body.message.strip(), now, now))
        return {'id': cur.lastrowid, 'stored': True}


@staff_router.get('/api/care-messages')
def list_messages(state: Literal['open', 'RESOLVED'] = 'open'):
    with closing(connect()) as conn:
        clause, values = auth.scoped_sql()
        rows = conn.execute("SELECT * FROM care_messages WHERE state " + ("!= 'RESOLVED'" if state == 'open' else "= 'RESOLVED'") + ' AND ' + clause + ' ORDER BY created_at LIMIT 100', values).fetchall()
    return {'messages': [dict(r) for r in rows]}


class Update(BaseModel):
    state: Literal['ACKNOWLEDGED', 'RESOLVED']
    reply: str = Field(default='', max_length=1000)


@staff_router.patch('/api/care-messages/{message_id}')
def update(message_id: int, body: Update, request: Request):
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM care_messages WHERE id=?', (message_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'ไม่พบข้อความ')
        if (row['state'], body.state) not in {('NEW','ACKNOWLEDGED'), ('ACKNOWLEDGED','RESOLVED')}:
            raise HTTPException(409, 'สถานะเปลี่ยนแล้ว กรุณาโหลดใหม่')
        if body.state == 'RESOLVED' and len(body.reply.strip()) < 5:
            raise HTTPException(422, 'กรุณาระบุคำตอบที่ผู้ป่วยจะเห็นก่อนปิดรายการ')
        now = time.time()
        conn.execute('UPDATE care_messages SET state=?,reply=?,assigned_to=?,updated_at=? WHERE id=?', (body.state, body.reply.strip(), request.state.subject, now, message_id))
        conn.execute('''INSERT INTO agent_audit_logs(patient_id,action,actor,detail,created_at)
            VALUES (?,?,?,?,?)''', (row['patient_id'], 'CARE_MESSAGE_' + body.state, request.state.subject, f'message #{message_id}: ' + body.reply.strip(), now))
    return {'state': body.state}
