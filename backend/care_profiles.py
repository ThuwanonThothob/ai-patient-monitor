"""Versioned human-authored demo profiles and frozen statistical references.

Personal ranges never replace global alerts. No prescriptions, online learning,
cloud calls, clinical normality claims, or patient-facing writes.
"""
from contextlib import closing
import json
import math
import sqlite3
import time
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
import auth
from care_api import audit, validate_patient
from patient_registry import get_patient_profile

router = APIRouter(prefix='/api/care/patients', tags=['demo-personal-care'])
KEYS = ('heart_rate', 'spo2', 'respiratory_rate')
MAXIMUM = {'heart_rate': 250, 'spo2': 100, 'respiratory_rate': 80}


def connect():
    conn = sqlite3.connect(auth.DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_profiles():
    with closing(connect()) as conn, conn:
        conn.executescript('''CREATE TABLE IF NOT EXISTS care_profile_versions (
            patient_id TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL,
            content TEXT NOT NULL, reference TEXT, saved_at REAL NOT NULL, saved_by TEXT NOT NULL,
            reviewed_at REAL, reviewed_by TEXT, retired_at REAL, PRIMARY KEY(patient_id,version));
            CREATE INDEX IF NOT EXISTS idx_vital_logs_patient_ts ON vital_logs(patient_id,timestamp);
            CREATE INDEX IF NOT EXISTS idx_vital_logs_ts ON vital_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_care_profiles_state ON care_profile_versions(patient_id,state);''')


def valid(key, value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value <= MAXIMUM[key]


class Range(BaseModel):
    model_config = ConfigDict(extra='forbid')
    low: float = Field(gt=0, le=250, allow_inf_nan=False)
    high: float = Field(gt=0, le=250, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered(self):
        if self.low >= self.high:
            raise ValueError('Lower boundary must be less than upper boundary')
        return self


class ProfileContent(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    conditions: str = Field('', max_length=1500)
    medications: str = Field('', max_length=1500)
    allergies: str = Field('', max_length=1000)
    limitations: str = Field('', max_length=1500)
    caregiver: str = Field('', max_length=150)
    care_notes: str = Field('', max_length=2000)
    ranges: dict[Literal['heart_rate', 'spo2', 'respiratory_rate'], Range] = Field(default_factory=dict)
    reference_minutes: int = Field(5, ge=5, le=1440, strict=True)
    use_reference: bool = False

    @model_validator(mode='after')
    def bounds(self):
        if any(value.high > MAXIMUM[key] for key, value in self.ranges.items()):
            raise ValueError('Boundary outside the supported measurement domain')
        return self


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=0, strict=True)
    content: ProfileContent


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1, strict=True)
    action: Literal['APPROVE', 'PAUSE']
    confirmed: bool = False


def unpack(row):
    if not row:
        return None
    value = dict(row)
    value['content'] = json.loads(value['content'])
    value['reference'] = json.loads(value['reference']) if value['reference'] else None
    return value


def active_profile(conn, patient_id, at=None):
    if at is None:
        return unpack(conn.execute("SELECT * FROM care_profile_versions WHERE patient_id=? AND state='ACTIVE'", (patient_id,)).fetchone())
    value = unpack(conn.execute('''SELECT * FROM care_profile_versions WHERE patient_id=? AND reviewed_at<=?
        AND (retired_at IS NULL OR retired_at>?) ORDER BY reviewed_at DESC LIMIT 1''', (patient_id, at, at)).fetchone())
    if value:
        value.update(state='ACTIVE', retired_at=None)  # don't leak a later pause/replacement into a past report
    return value


def make_reference(conn, patient_id, minutes, now):
    start = now - minutes * 60
    rows = [dict(r) for r in conn.execute('''SELECT id,timestamp,heart_rate,spo2,respiratory_rate,
        simulation_state,source_record,source_segment FROM vital_logs
        WHERE patient_id=? AND timestamp>=? AND timestamp<? ORDER BY timestamp,id''', (patient_id, start, now))]
    # Duplicate timestamps are not independent measurements.
    eligible = [r for r in rows if all(valid(k, r[k]) for k in KEYS)]
    sources = {r['simulation_state'] for r in eligible}
    segments = {r['source_segment'] for r in eligible}
    unique = {r['timestamp']: r for r in rows}
    rows = [r for r in unique.values() if all(valid(k, r[k]) for k in KEYS)]
    base = {'status': 'INSUFFICIENT_DATA', 'start': start, 'end': now, 'sample_count': len(rows),
            'expires_at': now + 86400, 'notice': 'ช่วงอ้างอิงเชิงสถิติ ไม่ใช่การยืนยันภาวะปกติ; ใช้เปรียบเทียบ 24 ชั่วโมงแล้วต้องทบทวนใหม่'}
    if len(rows) < 60 or rows[-1]['timestamp'] - rows[0]['timestamp'] < 295:
        return base
    if len(sources) != 1 or not sources <= {'BIDMC_REPLAY', 'MQTT', 'TEST_SIMULATION'}:
        return {**base, 'status': 'SOURCE_MIXED_OR_UNKNOWN'}
    source = next(iter(sources))
    if source == 'BIDMC_REPLAY' and (None in segments or len(segments) != 1):
        return {**base, 'status': 'REPLAY_SEGMENT_CHANGED'}
    times = [start, *[r['timestamp'] for r in rows], now]
    cursor, covered = start, 0.
    for row in rows:
        point = row['timestamp']
        right = min(now, point + 5)
        covered += max(0, right - max(point, cursor))
        cursor = max(cursor, right)
    if max(np.diff(times)) > 15 or covered / (minutes * 60) < .8:
        return {**base, 'status': 'DATA_GAPS'}
    return {**base, 'status': 'READY', 'source': source, 'source_record': rows[-1]['source_record'],
            'source_segment': rows[-1]['source_segment'], 'first_row_id': rows[0]['id'], 'last_row_id': rows[-1]['id'],
            'statistics': {k: {'median': float(np.median([r[k] for r in rows])),
                               'p05': float(np.percentile([r[k] for r in rows], 5)),
                               'p95': float(np.percentile([r[k] for r in rows], 95))} for k in KEYS}}


def compare(profile, reading, now):
    result = {'status': 'NO_REVIEWED_PROFILE', 'ranges': {}, 'reference_status': 'NOT_CONFIGURED', 'reference': {},
              'changes_live_alerts': False, 'method': 'human ranges + descriptive statistics, not a new trained ML model'}
    if not profile:
        return result
    result['profile_version'] = profile['version']
    result['reference_status'] = (profile.get('reference') or {}).get('status', 'NOT_CONFIGURED')
    if not reading or not isinstance(reading.get('timestamp'), (int, float)):
        return {**result, 'status': 'NO_READING'}
    measured = reading['timestamp']
    result['reading_at'] = measured
    if measured > now or now - measured > 15:
        return {**result, 'status': 'STALE_READING'}
    if measured < profile['reviewed_at']:
        return {**result, 'status': 'READING_BEFORE_REVIEW'}
    source = reading.get('simulation_state', reading.get('source'))
    if source not in {'BIDMC_REPLAY', 'MQTT', 'TEST_SIMULATION'}:
        return {**result, 'status': 'UNKNOWN_SOURCE'}
    if not all(valid(k, reading.get(k)) for k in KEYS):
        return {**result, 'status': 'INVALID_READING'}
    result['status'] = 'READY'
    result['source'] = source
    result['ranges'] = {k: {'value': reading[k], **bounds,
                            'outside': reading[k] < bounds['low'] or reading[k] > bounds['high']}
                        for k, bounds in profile['content']['ranges'].items()}
    reference = profile.get('reference')
    if not reference:
        return result
    result['reference_status'] = reference['status']
    if reference['status'] != 'READY':
        return result
    if now >= reference['expires_at']:
        return {**result, 'reference_status': 'EXPIRED'}
    if measured < reference['end']:
        return {**result, 'reference_status': 'READING_OVERLAPS_REFERENCE'}
    if source != reference['source'] or (source == 'BIDMC_REPLAY' and reading.get('source_segment') != reference['source_segment']):
        return {**result, 'reference_status': 'SOURCE_CHANGED'}
    result['reference'] = {k: {**stats, 'value': reading[k], 'difference': reading[k] - stats['median'],
                              'outside_sample_band': not stats['p05'] <= reading[k] <= stats['p95']}
                           for k, stats in reference['statistics'].items()}
    return result


@router.get('/{patient_id}/profile')
def get_profile(patient_id: str):
    validate_patient(patient_id)
    with closing(connect()) as conn:
        versions = [unpack(r) for r in conn.execute('SELECT * FROM care_profile_versions WHERE patient_id=? ORDER BY version DESC LIMIT 20', (patient_id,))]
        active = active_profile(conn, patient_id)
        row = conn.execute('SELECT payload FROM monitor_results WHERE patient_id=?', (patient_id,)).fetchone()
        reading = json.loads(row[0]) if row else None
    now = time.time()
    comparison = compare(active, reading, now)
    recent = [r for r in (reading or {}).get('history', []) if isinstance(r.get('timestamp'), (int, float))
              and now - 60 <= r['timestamp'] <= now and all(valid(k, r.get(k)) for k in KEYS)] if comparison['status'] == 'READY' else []
    return {'patient_id': patient_id, 'version': versions[0]['version'] if versions else 0,
            'latest': versions[0] if versions else None, 'active': active, 'history': versions,
            'registry_condition': get_patient_profile(patient_id)['condition'],
            'comparison': comparison, 'recent_readings': recent, 'demo_only': True,
            'notice': 'ข้อมูลที่คนกรอกแยกจากทะเบียนสมมติ ไม่ส่งยา ไม่เปลี่ยนกฎ alert และไม่ส่งข้อมูลนี้เข้า Gemini'}


@router.post('/{patient_id}/profile', status_code=201)
def save_draft(patient_id: str, body: Draft, request: Request):
    validate_patient(patient_id)
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        version = conn.execute('SELECT COALESCE(MAX(version),0) FROM care_profile_versions WHERE patient_id=?', (patient_id,)).fetchone()[0]
        if version != body.expected_version:
            raise HTTPException(409, 'โปรไฟล์เปลี่ยนแล้ว กรุณาโหลดใหม่ก่อนบันทึก')
        conn.execute("UPDATE care_profile_versions SET state='SUPERSEDED' WHERE patient_id=? AND state='DRAFT'", (patient_id,))
        conn.execute('INSERT INTO care_profile_versions(patient_id,version,state,content,saved_at,saved_by) VALUES (?,?,?,?,?,?)',
                     (patient_id, version + 1, 'DRAFT', body.content.model_dump_json(), time.time(), request.state.subject))
        audit(conn, patient_id, 'PROFILE_DRAFTED', request.state.subject, f'version={version + 1}')
    return {'version': version + 1, 'state': 'DRAFT'}


@router.patch('/{patient_id}/profile/review')
def review(patient_id: str, body: Review, request: Request):
    validate_patient(patient_id)
    if not body.confirmed:
        raise HTTPException(422, 'ต้องยืนยันการตรวจโปรไฟล์สาธิตก่อน')
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        latest = unpack(conn.execute('SELECT * FROM care_profile_versions WHERE patient_id=? ORDER BY version DESC LIMIT 1', (patient_id,)).fetchone())
        if not latest or latest['version'] != body.expected_version:
            raise HTTPException(409, 'โปรไฟล์เปลี่ยนแล้ว กรุณาโหลดใหม่')
        now = time.time()
        if body.action == 'APPROVE':
            if latest['state'] != 'DRAFT':
                raise HTTPException(409, 'ยืนยันได้เฉพาะฉบับร่าง')
            content = latest['content']
            reference = make_reference(conn, patient_id, content['reference_minutes'], now) if content['use_reference'] else None
            conn.execute("UPDATE care_profile_versions SET state='SUPERSEDED',retired_at=? WHERE patient_id=? AND state='ACTIVE'", (now, patient_id))
            conn.execute("UPDATE care_profile_versions SET state='ACTIVE',reviewed_at=?,reviewed_by=?,reference=? WHERE patient_id=? AND version=?",
                         (now, request.state.subject, json.dumps(reference, allow_nan=False) if reference else None, patient_id, latest['version']))
        else:
            active = active_profile(conn, patient_id)
            if not active:
                raise HTTPException(409, 'ไม่มีโปรไฟล์ที่กำลังใช้')
            conn.execute("UPDATE care_profile_versions SET state='PAUSED',retired_at=? WHERE patient_id=? AND state='ACTIVE'", (now, patient_id))
        audit(conn, patient_id, 'PROFILE_' + body.action, request.state.subject, f'head_version={latest["version"]}')
    return get_profile(patient_id)
