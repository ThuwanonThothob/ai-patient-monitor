"""Care plan helpers, audit trail and overdue/upcoming open task summary."""
from contextlib import closing
import time
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import care_api
from care_api import (
    Plan,
    Review,
    TaskUpdate,
    audit,
    care_report,
    connect,
    create_plan,
    init_care,
    materialize,
    patient_care,
    review_plan,
    router,
    run_scheduler,
    update_task,
    validate_patient,
)


def init_task_history():
    """Ensure care_task_history table exists for audit trail."""
    with closing(connect()) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS care_task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            plan_id INTEGER,
            patient_id TEXT,
            previous_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            skip_reason TEXT,
            timestamp REAL NOT NULL,
            created_at REAL NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_care_task_history_task ON care_task_history(task_id, timestamp)')


def record_task_transition(conn, task_id: int, previous_state: str, new_state: str, actor: str,
                           skip_reason: str | None = None, plan_id: int | None = None,
                           patient_id: str | None = None, timestamp: float | None = None):
    """Insert a care task status transition into the audit trail."""
    now = time.time() if timestamp is None else float(timestamp)
    conn.execute('''INSERT INTO care_task_history
        (task_id, plan_id, patient_id, previous_state, new_state, actor, skip_reason, timestamp, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (task_id, plan_id, patient_id, previous_state, new_state, actor, skip_reason, now, now))


def get_task_history(task_id: int) -> list[dict]:
    """Retrieve status transition audit trail for a task."""
    init_task_history()
    with closing(connect()) as conn:
        task = conn.execute(
            'SELECT t.*, p.patient_id FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE t.id=?',
            (task_id,)
        ).fetchone()
        if not task:
            raise HTTPException(404, 'Task not found')
        rows = conn.execute(
            'SELECT * FROM care_task_history WHERE task_id=? ORDER BY timestamp ASC, id ASC',
            (task_id,)
        ).fetchall()
        history = [dict(row) for row in rows]
        if not history:
            events = conn.execute(
                "SELECT * FROM care_events WHERE task_id=? AND action LIKE 'TASK_%' ORDER BY id ASC",
                (task_id,)
            ).fetchall()
            prev = 'PENDING'
            for ev in events:
                action = ev['action']
                new_st = action.replace('TASK_', '')
                skip_r = ev['detail'] if new_st == 'SKIPPED' else None
                history.append({
                    'id': ev['id'],
                    'task_id': task_id,
                    'plan_id': ev['plan_id'],
                    'patient_id': ev['patient_id'],
                    'previous_state': prev,
                    'new_state': new_st,
                    'actor': ev['actor'],
                    'skip_reason': skip_r,
                    'timestamp': ev['created_at'],
                    'created_at': ev['created_at'],
                })
                prev = new_st
        return history


class ExtendedTaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int = Field(ge=1)
    state: Literal['ACKNOWLEDGED', 'DONE', 'SKIPPED', 'COMPLETED']
    note: str = Field('', max_length=1000)


_original_update_task = care_api.update_task

def recorded_update_task(task_id: int, body: ExtendedTaskUpdate, request: Request):
    init_task_history()
    with closing(connect()) as conn:
        task = conn.execute(
            'SELECT t.*, p.patient_id FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE t.id=?',
            (task_id,)
        ).fetchone()
    if not task:
        raise HTTPException(404, 'Task not found')

    previous_state = task['state']
    plan_id = task['plan_id']
    patient_id = task['patient_id']
    requested_state = body.state

    delegate_body = body
    if requested_state == 'COMPLETED':
        delegate_body = TaskUpdate(version=body.version, state='DONE', note=body.note)
    elif isinstance(body, ExtendedTaskUpdate):
        delegate_body = TaskUpdate(version=body.version, state=body.state, note=body.note)

    result = _original_update_task(task_id, delegate_body, request)

    actor = getattr(getattr(request, 'state', None), 'subject', 'clinician')
    skip_reason = body.note if requested_state == 'SKIPPED' else None

    with closing(connect()) as conn, conn:
        record_task_transition(
            conn,
            task_id=task_id,
            previous_state=previous_state,
            new_state=requested_state,
            actor=actor,
            skip_reason=skip_reason,
            plan_id=plan_id,
            patient_id=patient_id,
        )
    return result


_original_review_plan = care_api.review_plan

def recorded_review_plan(plan_id: int, body: Review, request: Request):
    init_task_history()
    with closing(connect()) as conn:
        cancelled_tasks = []
        if body.state == 'PAUSED':
            cancelled_tasks = conn.execute(
                "SELECT t.*, p.patient_id FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id WHERE t.plan_id=? AND t.state IN ('PENDING','ACKNOWLEDGED')",
                (plan_id,)
            ).fetchall()

    result = _original_review_plan(plan_id, body, request)

    if cancelled_tasks:
        actor = getattr(getattr(request, 'state', None), 'subject', 'clinician')
        with closing(connect()) as conn, conn:
            for t in cancelled_tasks:
                record_task_transition(
                    conn,
                    task_id=t['id'],
                    previous_state=t['state'],
                    new_state='CANCELLED',
                    actor=actor,
                    skip_reason='Plan paused',
                    plan_id=plan_id,
                    patient_id=t['patient_id'],
                )
    return result


# Patch router route endpoints so PATCH /api/care/tasks/{task_id} and PATCH /api/care/plans/{plan_id}
# use the recorded versions
for route in router.routes:
    path = getattr(route, 'path', '')
    methods = getattr(route, 'methods', set())
    if path in ('/api/care/tasks/{task_id}', '/tasks/{task_id}') and 'PATCH' in methods:
        route.endpoint = recorded_update_task
    elif path in ('/api/care/plans/{plan_id}', '/plans/{plan_id}') and 'PATCH' in methods:
        route.endpoint = recorded_review_plan

care_api.update_task = recorded_update_task
care_api.review_plan = recorded_review_plan


def overdue_care_summary(patient_id: str | None = None, now: float | None = None) -> dict:
    """Count open care tasks (PENDING, ACKNOWLEDGED) split into overdue and upcoming."""
    current = time.time() if now is None else float(now)
    query = """
        SELECT t.scheduled_at
        FROM care_tasks t
        LEFT JOIN care_plans p ON p.id = t.plan_id
        WHERE t.state IN ('PENDING', 'ACKNOWLEDGED')
    """
    params: list[object] = []
    if patient_id is not None:
        query += " AND p.patient_id = ?"
        params.append(patient_id)

    overdue_count = 0
    upcoming_count = 0
    with closing(connect()) as conn:
        for row in conn.execute(query, params):
            if float(row["scheduled_at"]) <= current:
                overdue_count += 1
            else:
                upcoming_count += 1

    return {
        "overdue_count": overdue_count,
        "upcoming_count": upcoming_count,
        "total_open": overdue_count + upcoming_count,
    }


care_api.overdue_care_summary = overdue_care_summary
init_task_history()
