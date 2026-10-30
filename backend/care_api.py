"""Human-reviewed demonstration care tasks. No treatment advice or push dispatch.

Scheduling is a rule, never claimed as ML. Plans are immutable after creation;
staff activate/pause them. Recurrence starts from human completion, no backlog
is silently marked done. All actors come from the authenticated session.
"""
import asyncio
from contextlib import closing
import json
import sqlite3
import time
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
import auth
from patient_registry import get_patient_profile

router = APIRouter(prefix='/api/care', tags=['demo-care-plans'])


def connect():
    conn = sqlite3.connect(auth.DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_care():
    with closing(connect()) as conn, conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS care_plans (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, title TEXT NOT NULL,
            instructions TEXT NOT NULL, assigned_to TEXT NOT NULL, interval_minutes INTEGER NOT NULL,
            next_due REAL NOT NULL, state TEXT NOT NULL DEFAULT 'DRAFT', version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL, created_by TEXT NOT NULL, reviewed_by TEXT, reviewed_at REAL);
        CREATE TABLE IF NOT EXISTS care_tasks (
            id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, scheduled_at REAL NOT NULL,
            state TEXT NOT NULL DEFAULT 'PENDING', version INTEGER NOT NULL DEFAULT 1,
            acknowledged_at REAL, completed_at REAL, note TEXT NOT NULL DEFAULT '',
            UNIQUE(plan_id, scheduled_at));
        CREATE TABLE IF NOT EXISTS care_events (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, plan_id INTEGER, task_id INTEGER,
            action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);
        ''')


def audit(conn, patient_id, action, actor, detail='', plan_id=None, task_id=None):
    conn.execute('INSERT INTO care_events(patient_id,plan_id,task_id,action,actor,detail,created_at) VALUES (?,?,?,?,?,?,?)',
                 (patient_id, plan_id, task_id, action, actor, detail, time.time()))


def validate_patient(patient_id):
    if get_patient_profile(patient_id) is None:
        raise HTTPException(404, 'Unknown demonstration patient')


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=120)
    instructions: str = Field(min_length=3, max_length=1000)
    assigned_to: str = Field(min_length=2, max_length=100)
    interval_minutes: int = Field(0, ge=0, le=10080, strict=True)
    first_due: float = Field(allow_inf_nan=False)


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)
    state: Literal['ACTIVE', 'PAUSED']
    demo_review_confirmed: bool = False


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int = Field(ge=1)
    state: Literal['ACKNOWLEDGED', 'DONE', 'SKIPPED']
    note: str = Field('', max_length=1000)


@router.post('/patients/{patient_id}/plans', status_code=201)
def create_plan(patient_id: str, body: Plan, request: Request):
    validate_patient(patient_id)
    now = time.time()
    if not now - 60 <= body.first_due <= now + 365 * 86400:
        raise HTTPException(422, 'Due time must be now or within the next year')
    with closing(connect()) as conn, conn:
        cursor = conn.execute('''INSERT INTO care_plans(patient_id,title,instructions,assigned_to,interval_minutes,
            next_due,created_at,created_by) VALUES (?,?,?,?,?,?,?,?)''',
            (patient_id, body.title, body.instructions, body.assigned_to, body.interval_minutes,
             body.first_due, now, request.state.subject))
        audit(conn, patient_id, 'PLAN_DRAFTED', request.state.subject, body.title, cursor.lastrowid)
        return {'id': cursor.lastrowid, 'state': 'DRAFT'}


@router.patch('/plans/{plan_id}')
def review_plan(plan_id: int, body: Review, request: Request):
    if body.state == 'ACTIVE' and not body.demo_review_confirmed:
        raise HTTPException(422, 'Human review confirmation required')
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        plan = conn.execute('SELECT * FROM care_plans WHERE id=?', (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(404, 'Plan not found')
        if plan['version'] != body.version or plan['state'] == body.state or plan['state'] == 'COMPLETED':
            raise HTTPException(409, 'Plan changed; reload before updating')
        now = time.time()
        conn.execute('UPDATE care_plans SET state=?,version=version+1,reviewed_by=?,reviewed_at=? WHERE id=?',
                     (body.state, request.state.subject, now, plan_id))
        if body.state == 'PAUSED':
            conn.execute("UPDATE care_tasks SET state='CANCELLED',version=version+1,completed_at=? WHERE plan_id=? AND state IN ('PENDING','ACKNOWLEDGED')", (now, plan_id))
        else:
            # Resume starts a new due time, so UNIQUE doesn't strand a cancelled occurrence.
            if plan['state'] == 'PAUSED':
                conn.execute('UPDATE care_plans SET next_due=? WHERE id=?', (now, plan_id))
        audit(conn, plan['patient_id'], 'PLAN_' + body.state, request.state.subject, plan_id=plan_id)
    materialize()
    return {'state': body.state}


def materialize(now=None):
    now = time.time() if now is None else now
    with closing(connect()) as conn, conn:
        conn.execute('''INSERT OR IGNORE INTO care_tasks(plan_id,scheduled_at)
            SELECT p.id,p.next_due FROM care_plans p WHERE p.state='ACTIVE' AND p.next_due<=?
            AND NOT EXISTS (SELECT 1 FROM care_tasks t WHERE t.plan_id=p.id AND t.state IN ('PENDING','ACKNOWLEDGED'))''', (now,))


@router.patch('/tasks/{task_id}')
def update_task(task_id: int, body: TaskUpdate, request: Request):
    if body.state in ('DONE', 'SKIPPED') and not body.note:
        raise HTTPException(422, 'Completion or skip note required')
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        task = conn.execute('''SELECT t.*,p.patient_id,p.interval_minutes,p.state AS plan_state
            FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE t.id=?''', (task_id,)).fetchone()
        if not task:
            raise HTTPException(404, 'Task not found')
        transitions = {'PENDING': {'ACKNOWLEDGED', 'SKIPPED'}, 'ACKNOWLEDGED': {'DONE', 'SKIPPED'}}
        if task['plan_state'] != 'ACTIVE' or task['version'] != body.version or body.state not in transitions.get(task['state'], set()):
            raise HTTPException(409, 'Task changed or transition invalid; reload')
        now = time.time()
        done = body.state in ('DONE', 'SKIPPED')
        conn.execute('UPDATE care_tasks SET state=?,version=version+1,note=?,acknowledged_at=?,completed_at=? WHERE id=?',
                     (body.state, body.note, now if not done else task['acknowledged_at'], now if done else None, task_id))
        if done:
            if task['interval_minutes']:
                conn.execute('UPDATE care_plans SET next_due=?,version=version+1 WHERE id=?', (now + task['interval_minutes'] * 60, task['plan_id']))
            else:
                conn.execute("UPDATE care_plans SET state='COMPLETED',version=version+1 WHERE id=?", (task['plan_id'],))
        audit(conn, task['patient_id'], 'TASK_' + body.state, request.state.subject, body.note, task['plan_id'], task_id)
    return {'state': body.state}


@router.get('/patients/{patient_id}')
def patient_care(patient_id: str):
    validate_patient(patient_id)
    with closing(connect()) as conn:
        plans = [dict(row) for row in conn.execute('SELECT * FROM care_plans WHERE patient_id=? ORDER BY id DESC', (patient_id,))]
        counts = conn.execute('''SELECT COUNT(*) AS total,
            COALESCE(SUM(t.state IN ('PENDING','ACKNOWLEDGED')),0) AS open
            FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE p.patient_id=?''', (patient_id,)).fetchone()
        tasks = [dict(row) for row in conn.execute('''SELECT t.*,p.title,p.instructions,p.assigned_to FROM care_tasks t
            JOIN care_plans p ON p.id=t.plan_id WHERE p.patient_id=?
            ORDER BY CASE WHEN t.state IN ('PENDING','ACKNOWLEDGED') THEN 0 ELSE 1 END,
            CASE WHEN t.state IN ('PENDING','ACKNOWLEDGED') THEN t.scheduled_at END, t.id DESC LIMIT 100''', (patient_id,))]
        events = [dict(row) for row in conn.execute('SELECT * FROM care_events WHERE patient_id=? ORDER BY id DESC LIMIT 100', (patient_id,))]
    now = time.time()
    for task in tasks:
        task['overdue_seconds'] = max(0, now - task['scheduled_at']) if task['state'] in ('PENDING', 'ACKNOWLEDGED') else 0
    return {'patient_id': patient_id, 'plans': plans, 'tasks': tasks, 'events': events, 'generated_at': now,
            'task_count': counts['total'], 'open_task_count': counts['open'], 'task_list_truncated': counts['total'] > len(tasks),
            'notice': 'แผนสาธิตที่คนกำหนด ไม่ใช่ AI สั่งการรักษา; ชื่อผู้รับผิดชอบเป็นข้อความ ไม่ได้ส่งถึงบุคคลจริง',
            'automatic_external_contact': False}


@router.get('/patients/{patient_id}/report', response_class=PlainTextResponse)
def care_report(patient_id: str):
    data = patient_care(patient_id)
    return PlainTextResponse('Smart Ward — Demonstration care handoff (human-entered, not AI-generated)\n'
        + json.dumps(data, ensure_ascii=False, indent=2),
        headers={'Content-Disposition': f'attachment; filename="care-{patient_id}.txt"'})


async def run_scheduler():
    while True:
        try:
            await asyncio.to_thread(materialize)
        except Exception:
            print('Care scheduler failed; existing tasks preserved')
        await asyncio.sleep(5)
