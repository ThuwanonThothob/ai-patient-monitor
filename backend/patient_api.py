"""Port 8001: patient-only API. It cannot list or mutate other patients.

Reads results computed by the staff backend; never starts another ML worker.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
import sqlite3
import time
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from starlette.responses import JSONResponse
from main import init_db, DB_NAME
import auth
import patient_views
import care_messages
import care_chat
import assistant_api
import notifications
from monitor_service import patient_state
from patient_registry import PATIENT_LOGIN_PROFILES


import os

# In-memory sliding window rate limits: { key: [timestamp, ...] }
_rate_limits: dict[str, list[float]] = defaultdict(list)


def reset_rate_limits():
    """Reset all in-memory rate limit counters."""
    _rate_limits.clear()


def check_rate_limit(key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - window
    if len(_rate_limits) > 500:
        stale_keys = [k for k, ts in _rate_limits.items() if not ts or ts[-1] <= cutoff]
        for k in stale_keys:
            _rate_limits.pop(k, None)
    timestamps = [ts for ts in _rate_limits[key] if ts > cutoff]
    _rate_limits[key] = timestamps
    if len(timestamps) >= limit:
        oldest = timestamps[0]
        retry_after = max(1, int(window - (now - oldest)))
        return False, retry_after
    _rate_limits[key].append(now)
    return True, 0


@asynccontextmanager
async def lifespan(app):
    try:
        init_db()
    except sqlite3.OperationalError as e:
        if 'locked' in str(e).lower() or 'busy' in str(e).lower():
            pass
        else:
            raise
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def rate_limit_middleware(request: Request, call_next):
    if request.method == 'OPTIONS':
        return await call_next(request)

    trust_proxy = os.getenv("WARD_TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes")
    forwarded = request.headers.get('x-forwarded-for') if trust_proxy else None
    client_ip = forwarded.split(',')[0].strip() if forwarded else (request.client.host if request.client else 'local')

    is_login = request.url.path == '/api/session/login' and request.method == 'POST'
    key = f'login:{client_ip}' if is_login else f'general:{client_ip}'
    limit = 5 if is_login else 60

    allowed, retry_after = check_rate_limit(key, limit, window=60.0)
    if not allowed:
        return JSONResponse(
            {'detail': 'Too Many Requests'},
            status_code=429,
            headers={'Retry-After': str(retry_after)}
        )

    return await call_next(request)


auth.install_auth(app, 'patient', PATIENT_LOGIN_PROFILES)
app.include_router(care_messages.patient_router)
app.include_router(care_chat.patient_router)
app.include_router(assistant_api.router)
app.include_router(notifications.router)


def own_monitor(patient_id):
    state = patient_state(DB_NAME, patient_id)
    result = {key: state[key] for key in ('patient_id', 'status', 'timestamp', 'source', 'source_record',
        'heart_rate', 'spo2', 'respiratory_rate', 'simulation_state') if key in state}
    result['history'] = [{key: sample[key] for key in ('timestamp', 'heart_rate', 'spo2', 'respiratory_rate') if key in sample}
                         for sample in state.get('history', [])[-20:]]
    result['analysis'] = {key: value for key, value in state.get('analysis', {}).items() if key in (
        'status', 'history_points', 'summary', 'evaluated_at', 'prediction_at', 'forecast', 'forecast_methods', 'is_anomaly')}
    evaluated = result['analysis'].get('evaluated_at')
    if result['analysis'].get('status') == 'READY' and (not isinstance(evaluated, (int, float)) or not 0 <= time.time() - evaluated <= 30):
        result['analysis'].update(status='STALE_ANALYSIS', forecast=None, is_anomaly=False, summary='ผลวิเคราะห์ไม่ใหม่พอ จึงงดแสดงค่าคาดการณ์')
    return result


@app.get('/api/me')
def me(request: Request):
    patient_id = request.state.subject
    auth._log_security_audit(patient_id, 'PATIENT_SELF_DATA_VIEWED', patient_id, f'Patient {patient_id} viewed own portal data')
    monitor = own_monitor(patient_id)
    # Explicit patient view: no cross-patient query and no staff audit/actions.
    return {'patient_id': patient_id, 'profile': patient_views.public_registry(patient_id),
            'monitor': monitor, 'history': monitor.get('history', []),
            'demo': True}


@app.get('/api/me/trends')
def trends(request: Request, hours: Literal['1', '6', '24', '168'] = '24'):
    return patient_views.trends(request.state.subject, int(hours))


@app.get('/api/me/care')
def care(request: Request):
    return patient_views.care(request.state.subject)


@app.get('/api/me/daily')
def daily(request: Request, day: date | None = None):
    return patient_views.daily(request.state.subject, day)


@app.get('/api/me/daily/report', response_class=PlainTextResponse)
def daily_report(request: Request, day: date | None = None, digest: str | None = None):
    data = daily(request, day)
    if digest and digest != data['digest']:
        raise HTTPException(409, 'ร่างเปลี่ยนแล้ว กรุณาโหลดสรุปล่าสุดก่อนดาวน์โหลด')
    return PlainTextResponse(data['text'], headers={'Content-Disposition': f'attachment; filename="my-daily-{data["patient_id"]}-{data["day"]}.txt"'})


@app.get('/api/me/report', response_class=PlainTextResponse)
def report(request: Request):
    content = me(request)
    state = content['monitor']
    analysis = state.get('analysis', {})
    measured = state.get('timestamp', 0)
    fresh = isinstance(measured, (int, float)) and 0 <= time.time() - measured <= 15 and state.get('status') not in ('STALE_DATA', 'WAITING', 'INVALID_DATA')
    return PlainTextResponse('\n'.join(['Smart Ward — ข้อมูลสาธิต', 'Patient ID: ' + content['patient_id'],
                      'สถานะ: ' + state.get('status', 'WAITING'),
                      'HR: ' + str(state.get('heart_rate', '—') if fresh else 'ไม่มีข้อมูลใหม่'),
                      'SpO2: ' + str(state.get('spo2', '—') if fresh else 'ไม่มีข้อมูลใหม่'),
                      'RR: ' + str(state.get('respiratory_rate', '—') if fresh else 'ไม่มีข้อมูลใหม่'),
                      'AI: ' + (analysis.get('summary', analysis.get('status', 'WAITING')) if fresh else 'งดแสดงผลวิเคราะห์จากข้อมูลเก่า'),
                      'ไม่ใช่คำวินิจฉัยหรือการยืนยันว่าปลอดภัย']),
        headers={'Content-Disposition': f'attachment; filename="my-monitor-{content["patient_id"]}.txt"'})


@app.websocket('/ws/me')
async def stream(websocket: WebSocket):
    subject = auth.identity(websocket.cookies, 'patient')
    if not subject or websocket.headers.get('origin') not in auth.ORIGINS['patient']:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while auth.identity(websocket.cookies, 'patient') == subject:
            # The client cannot supply/change an ID after login.
            state = await asyncio.to_thread(own_monitor, subject)
            await asyncio.wait_for(websocket.send_json(state), timeout=2)
            await asyncio.sleep(2)
        await websocket.close(code=4401)
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass
