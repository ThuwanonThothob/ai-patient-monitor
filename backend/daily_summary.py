"""Evidence-grounded daily drafts, local Bangkok days, immutable human reviews.

No LLM/cloud calls. Narrative is a deterministic template over measured facts
and persisted trained-model results, not a new diagnostic AI. Background work
runs outside the telemetry event loop. Source types are never averaged together.
"""
import asyncio
from collections import Counter
from contextlib import closing
from datetime import date as Date, datetime, timedelta
import hashlib
import json
import logging
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from care_api import audit, validate_patient
from care_profiles import KEYS, active_profile, compare, connect, valid
from patient_registry import PATIENT_PROFILES

router = APIRouter(prefix='/api/care/patients', tags=['daily-evidence-drafts'])
TZ = ZoneInfo('Asia/Bangkok')
log = logging.getLogger(__name__)


def init_daily():
    with closing(connect()) as conn, conn:
        conn.executescript('''CREATE TABLE IF NOT EXISTS daily_summary_cache (
            patient_id TEXT NOT NULL, day TEXT NOT NULL, generated_at REAL NOT NULL,
            payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(patient_id,day));
            CREATE TABLE IF NOT EXISTS daily_summary_reviews (
            id INTEGER PRIMARY KEY, patient_id TEXT NOT NULL, day TEXT NOT NULL, digest TEXT NOT NULL,
            payload TEXT NOT NULL, reviewed_at REAL NOT NULL, reviewed_by TEXT NOT NULL, note TEXT NOT NULL,
            UNIQUE(patient_id,day,digest));''')


def period(day, now):
    today = datetime.fromtimestamp(now, TZ).date()
    if day > today or day < Date(2000, 1, 1):
        raise HTTPException(422, 'เลือกวันที่ตั้งแต่ปี 2000 ถึงวันนี้ตามเวลาไทย')
    start = datetime.combine(day, datetime.min.time(), TZ).timestamp()
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), TZ).timestamp()
    return start, min(end, now), end


def stamp(value):
    return datetime.fromtimestamp(value, TZ).isoformat()


def coverage(rows, start, end):
    times = sorted({r['timestamp'] for r in rows if all(valid(k, r[k]) for k in KEYS)})
    missing = []
    cursor = start
    covered = 0.
    # Each valid persisted snapshot represents at most five seconds, not proof
    # that every second was observed. Small overlaps and duplicate rows don't add coverage.
    for point in times:
        if point - cursor > 15:
            missing.append({'start': cursor, 'end': point, 'seconds': point - cursor})
        right = min(end, point + 5)
        covered += max(0, right - max(point, cursor))
        cursor = max(cursor, right)
    if end - cursor > 15:
        missing.append({'start': cursor, 'end': end, 'seconds': end - cursor})
    return {'valid_snapshot_count': len(times), 'estimated_seconds': round(covered, 1),
            'period_seconds': round(end - start, 1), 'estimated_percent': round(100 * covered / (end - start), 2) if end > start else 0,
            'gap_count': len(missing), 'longest_gap_seconds': round(max((g['seconds'] for g in missing), default=0), 1),
            'largest_gaps': sorted(missing, key=lambda g: -g['seconds'])[:10],
            'note': 'ประมาณจาก snapshot ทุก 5 วินาที; ช่องว่างเกิน 15 วินาทีไม่บอกสาเหตุว่าเซนเซอร์หรือเครือข่ายเสีย'}


def source_stats(rows, start, end):
    unique = list({r['timestamp']: r for r in rows}.values())
    measurements = {}
    hourly = {}
    for key in KEYS:
        eligible = [r for r in unique if valid(key, r[key])]
        if not eligible:
            measurements[key] = None
            continue
        low, high = min(eligible, key=lambda r: r[key]), max(eligible, key=lambda r: r[key])
        first, last = eligible[0], eligible[-1]
        measurements[key] = {'count': len(eligible), 'mean': round(sum(r[key] for r in eligible) / len(eligible), 2),
            'min': low[key], 'max': high[key], 'first': first[key], 'last': last[key], 'change': round(last[key] - first[key], 2),
            'first_at': first['timestamp'], 'last_at': last['timestamp'],
            'evidence_ids': {'first': first['id'], 'last': last['id'], 'min': low['id'], 'max': high['id']}}
    for row in unique:
        hour = int((row['timestamp'] - start) // 3600)
        hourly.setdefault(hour, []).append(row)
    chart = []
    for hour in range(min(24, int((end - start) // 3600) + 1)):
        bucket = hourly.get(hour, [])
        point = {'hour': hour, 'timestamp': start + hour * 3600}
        for key in KEYS:
            values = [r[key] for r in bucket if valid(key, r[key])]
            point[key] = round(sum(values) / len(values), 2) if values else None
        chart.append(point)
    return {'row_count': len(rows), 'unique_timestamps': len(unique),
            'invalid_snapshot_count': sum(not all(valid(k, r[k]) for k in KEYS) for r in unique),
            'measurements': measurements, 'coverage': coverage(unique, start, end), 'hourly': chart}


def assemble(patient_id, day, now=None):
    now = time.time() if now is None else now
    start, cutoff, day_end = period(day, now)
    with closing(connect()) as conn:
        conn.execute('BEGIN')  # consistent read snapshot while monitor keeps writing in WAL mode
        rows = [dict(r) for r in conn.execute('''SELECT id,timestamp,heart_rate,spo2,respiratory_rate,simulation_state,
            source_record,source_segment FROM vital_logs WHERE patient_id=? AND timestamp>=? AND timestamp<? ORDER BY timestamp,id''', (patient_id, start, cutoff))]
        analyses = [(r['evaluated_at'], r['source'], json.loads(r['payload'])) for r in conn.execute('''SELECT * FROM monitor_analysis_logs
            WHERE patient_id=? AND evaluated_at>=? AND evaluated_at<? ORDER BY evaluated_at''', (patient_id, start, cutoff))]
        new_alerts = [dict(r) for r in conn.execute('''SELECT id,severity,reason,created_at FROM agent_alerts
            WHERE patient_id=? AND merged_into IS NULL AND created_at>=? AND created_at<? ORDER BY created_at''', (patient_id, start, cutoff))]
        open_alerts = [dict(r) for r in conn.execute('''SELECT id,severity,reason,created_at FROM agent_alerts
            WHERE patient_id=? AND merged_into IS NULL AND created_at<? AND (resolved_at IS NULL OR resolved_at>=?) ORDER BY created_at''', (patient_id, cutoff, cutoff))]
        resolved = conn.execute('SELECT COUNT(*) FROM agent_alerts WHERE patient_id=? AND resolved_at>=? AND resolved_at<?', (patient_id, start, cutoff)).fetchone()[0]
        tasks = [dict(r) for r in conn.execute('''SELECT t.*,p.title,p.assigned_to FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id
            WHERE p.patient_id=? AND p.created_at<? AND t.scheduled_at<? ORDER BY t.scheduled_at,t.id''', (patient_id, cutoff, cutoff))]
        events = [dict(r) for r in conn.execute('''SELECT id,action,actor,detail,created_at FROM care_events
            WHERE patient_id=? AND created_at>=? AND created_at<? ORDER BY created_at DESC LIMIT 100''', (patient_id, start, cutoff))]
        profile = active_profile(conn, patient_id, cutoff)
    groups = {}
    for row in rows:
        source = row['simulation_state'] if row['simulation_state'] in {'BIDMC_REPLAY', 'MQTT', 'TEST_SIMULATION'} else 'UNKNOWN'
        groups.setdefault(source, []).append(row)
    # Historical report never exposes notes written after its cutoff.
    open_tasks = [{'id': t['id'], 'title': t['title'], 'assigned_to': t['assigned_to'], 'scheduled_at': t['scheduled_at'],
                   'state': 'ACKNOWLEDGED' if t['acknowledged_at'] is not None and t['acknowledged_at'] < cutoff else 'PENDING'}
                  for t in tasks if t['completed_at'] is None or t['completed_at'] >= cutoff]
    finished = [t for t in tasks if t['completed_at'] is not None and start <= t['completed_at'] < cutoff]
    ml = {}
    for evaluated_at, source, analysis in analyses:
        item = ml.setdefault(source, {'evaluations': 0, 'ready': 0, 'unusual_pattern_evaluations': 0, 'abstention_statuses': {}, 'latest': None})
        item['evaluations'] += 1
        if analysis.get('status') == 'READY':
            item['ready'] += 1
            item['unusual_pattern_evaluations'] += int(bool(analysis.get('is_anomaly')))
        else:
            state = analysis.get('status', 'UNKNOWN')
            item['abstention_statuses'][state] = item['abstention_statuses'].get(state, 0) + 1
        item['latest'] = {'evaluated_at': evaluated_at, 'analysis': analysis}
    result = {'patient_id': patient_id, 'day': day.isoformat(), 'timezone': 'Asia/Bangkok', 'generated_at': now,
              'start': start, 'as_of': cutoff, 'day_end': day_end, 'partial_day': cutoff < day_end,
              'method': 'local-evidence-template-v1', 'is_llm_generated': False, 'requires_human_review': True,
              'sources': {name: source_stats(values, start, cutoff) for name, values in groups.items()},
              'overall_recording': coverage(rows, start, cutoff), 'ml': ml,
              'alerts': {'new_count': len(new_alerts), 'new_by_severity': dict(Counter(a['severity'] for a in new_alerts)),
                         'resolved_count': resolved, 'open_as_of_count': len(open_alerts),
                         'new_items': new_alerts[:100], 'open_items': open_alerts[:100]},
              'care': {'due_in_period': sum(t['scheduled_at'] >= start for t in tasks),
                       'done_in_period': sum(t['state'] == 'DONE' for t in finished),
                       'skipped_in_period': sum(t['state'] == 'SKIPPED' for t in finished),
                       'cancelled_in_period': sum(t['state'] == 'CANCELLED' for t in finished),
                       'open_due_as_of_count': len(open_tasks), 'open_items': open_tasks[:100],
                       'finished_items': [{'id': t['id'], 'title': t['title'], 'state': t['state'], 'note': t['note'], 'completed_at': t['completed_at']} for t in finished[-100:]],
                       'events': events},
              'profile': profile, 'personal_comparison': compare(profile, rows[-1] if rows else None, cutoff),
              'notice': 'ร่างสาธิตจากหลักฐาน ไม่วินิจฉัย ไม่สั่งยา และไม่สร้าง alert; ค่า registry ไม่ใช่ผลตรวจจริง',
              'limitations': ['Snapshot ทุก 5 วินาที ไม่ใช่ raw sensor stream ทั้งหมด',
                              'จำนวน alert ไม่ใช่จำนวนเหตุการณ์โรค; จำนวน anomaly คือรอบประเมิน ไม่ใช่จำนวนผู้ป่วย',
                              'ไม่พบข้อมูลไม่เท่ากับปลอดภัย; ช่องว่างอาจมาจากช่วงที่ยังไม่ได้เปิดระบบ',
                              'ML history มีเฉพาะผลที่บันทึกหลังเพิ่มฟีเจอร์นี้ ไม่คำนวณย้อนหลังแล้วอ้างว่าเคยแจ้งเตือน',
                              'รายการหลักฐานแต่ละกลุ่มแสดงสูงสุด 100 รายการ แต่จำนวนรวมคำนวณครบ',
                              'สถานะค้างอิงเวลาที่บันทึก completion/resolution; งานที่ถูกสร้างย้อนหลังอาจทำให้รายงานที่สร้างใหม่ต่างจากเดิม']}
    result['text'] = narrative(result)
    return result


def narrative(data):
    lines = ['Smart Ward — ร่างสรุปการดูแลประจำวัน', data['notice'],
             f"Patient ID: {data['patient_id']} | วันที่ {data['day']} (Asia/Bangkok)",
             f"ข้อมูลตั้งแต่ {stamp(data['start'])} ถึงก่อน {stamp(data['as_of'])}",
             f"สร้างร่างเมื่อ {stamp(data['generated_at'])}; {'ยังไม่ครบวัน' if data['partial_day'] else 'สิ้นสุดวันแล้ว'}",
             'วิธีสรุป: template จากหลักฐานและผล ML ที่บันทึกไว้ ไม่ได้เรียก Gemini', '', '1. ค่าที่บันทึกและแนวโน้ม']
    if not data['sources']:
        lines.append('ไม่มีข้อมูลการวัดในช่วงนี้ ไม่สรุปว่าผู้ป่วยปกติหรือปลอดภัย')
    for source, info in data['sources'].items():
        lines.append(f"แหล่งข้อมูล {source}: {info['row_count']} แถว / {info['unique_timestamps']} เวลาที่ไม่ซ้ำ")
        for key, m in info['measurements'].items():
            if m:
                unit = {'heart_rate': 'bpm', 'spo2': '%', 'respiratory_rate': 'ครั้ง/นาที'}[key]
                lines.append(f"{key} ({unit}): เฉลี่ย {m['mean']:g}, ต่ำสุด {m['min']:g}, สูงสุด {m['max']:g}, แรก→ท้าย {m['first']:g}→{m['last']:g}; หลักฐาน vital_logs IDs {m['evidence_ids']}")
            else:
                lines.append(f'{key}: ไม่มีค่าที่ผ่านการตรวจคุณภาพ')
    coverage_data = data['overall_recording']
    lines += ['', '2. ความครอบคลุมข้อมูล', f"ความครอบคลุมประมาณ {coverage_data['estimated_percent']:g}% ของช่วงรายงาน",
              f"ช่องว่างเกิน 15 วินาที {coverage_data['gap_count']} ช่วง; นานสุด {coverage_data['longest_gap_seconds']:g} วินาที", coverage_data['note'],
              '', '3. ผลโมเดลที่บันทึกจริง']
    if not data['ml']:
        lines.append('ไม่มีประวัติผล ML ในช่วงนี้ ไม่ตีความว่าโมเดลประเมินแล้วไม่พบความผิดปกติ')
    for source, model in data['ml'].items():
        lines.append(f"{source}: ประเมิน {model['evaluations']} รอบ, พร้อม {model['ready']} รอบ, รูปแบบต่างจากชุดฝึก {model['unusual_pattern_evaluations']} รอบ; งดประเมิน {model['abstention_statuses']}")
    alerts, care = data['alerts'], data['care']
    lines += ['', '4. แจ้งเตือนและงานดูแล',
              f"Alert ใหม่ {alerts['new_count']}; ปิดในช่วงนี้ {alerts['resolved_count']}; ยังไม่ปิด ณ เวลาตัดข้อมูล {alerts['open_as_of_count']}",
              f"งานกำหนดในช่วงนี้ {care['due_in_period']}; เสร็จ {care['done_in_period']}; ข้าม {care['skipped_in_period']}; ยกเลิก {care['cancelled_in_period']}; ค้างถึงกำหนดรวม {care['open_due_as_of_count']}"]
    lines += [f"งานค้าง #{t['id']}: {t['title']} / {t['assigned_to']} / {stamp(t['scheduled_at'])}" for t in care['open_items']]
    lines += ['', '5. โปรไฟล์การดูแล',
              f"ฉบับยืนยัน v{data['profile']['version']} โดย {data['profile']['reviewed_by']}" if data['profile'] else 'ยังไม่มีโปรไฟล์ยืนยัน ณ เวลารายงาน',
              f"เปรียบเทียบรายคน: {data['personal_comparison']['status']} / ช่วงอ้างอิง: {data['personal_comparison']['reference_status']}"]
    if data['profile']:
        content = data['profile']['content']
        for key, label in (('conditions', 'โรค/ภาวะที่คนบันทึก'), ('medications', 'รายการยาที่บันทึก ไม่ใช่ใบสั่งยา'),
                           ('allergies', 'ประวัติแพ้ที่บันทึก'), ('limitations', 'ข้อจำกัด'), ('caregiver', 'ป้ายชื่อผู้ดูแล'), ('care_notes', 'หมายเหตุ')):
            lines.append(f"{label}: {content[key] or 'ยังไม่ได้บันทึก'}")
    for key, item in data['personal_comparison']['ranges'].items():
        lines.append(f"{key}: ล่าสุด {item['value']:g}, ขอบเขตที่คนกำหนด {item['low']:g}–{item['high']:g}; {'นอกขอบเขต ให้ทบทวน' if item['outside'] else 'อยู่ในขอบเขต ไม่ใช่การยืนยันว่าปลอดภัย'}")
    for key, item in data['personal_comparison']['reference'].items():
        lines.append(f"{key}: ต่างจากมัธยฐานอ้างอิง {item['difference']:g}; ไม่ใช่คะแนนความเสี่ยงโรค")
    lines += ['', '6. สิ่งที่ต้องให้บุคลากรทบทวน', 'ตรวจงานค้าง ข้อมูลขาดช่วง และการวัดก่อนตัดสินใจ ไม่ปรับการรักษาจากรายงานนี้', *data['limitations']]
    return '\n'.join(lines)


def refresh(patient_id, day, now=None):
    validate_patient(patient_id)
    data = assemble(patient_id, day, now)
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with closing(connect()) as conn, conn:
        conn.execute('''INSERT INTO daily_summary_cache VALUES (?,?,?,?,?) ON CONFLICT(patient_id,day)
            DO UPDATE SET generated_at=excluded.generated_at,payload=excluded.payload,digest=excluded.digest
            WHERE excluded.generated_at>=daily_summary_cache.generated_at''', (patient_id, day.isoformat(), data['generated_at'], payload, digest))
    return data


@router.get('/{patient_id}/daily')
def get_daily(patient_id: str, day: Date | None = None):
    validate_patient(patient_id)
    day = day or datetime.now(TZ).date()
    period(day, time.time())
    with closing(connect()) as conn:
        cached = conn.execute('SELECT payload,digest FROM daily_summary_cache WHERE patient_id=? AND day=?', (patient_id, day.isoformat())).fetchone()
    if not cached:
        refresh(patient_id, day)
        return get_daily(patient_id, day)
    with closing(connect()) as conn:
        reviews = [dict(r) for r in conn.execute('''SELECT id,day,digest,reviewed_at,reviewed_by,note FROM daily_summary_reviews
            WHERE patient_id=? AND day=? ORDER BY id DESC LIMIT 20''', (patient_id, day.isoformat()))]
    return {**json.loads(cached['payload']), 'digest': cached['digest'], 'reviews': reviews}


@router.post('/{patient_id}/daily/refresh')
def refresh_daily(patient_id: str, day: Date | None = None):
    refresh(patient_id, day or datetime.now(TZ).date())
    return get_daily(patient_id, day)


class ReviewDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    day: Date
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: bool = False
    note: str = Field(min_length=3, max_length=1000)


@router.post('/{patient_id}/daily/review', status_code=201)
def review_daily(patient_id: str, body: ReviewDraft, request: Request):
    validate_patient(patient_id)
    if not body.confirmed:
        raise HTTPException(422, 'ต้องยืนยันการตรวจร่างก่อนบันทึก')
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM daily_summary_cache WHERE patient_id=? AND day=?', (patient_id, body.day.isoformat())).fetchone()
        if not row or row['digest'] != body.digest:
            raise HTTPException(409, 'ร่างเปลี่ยนแล้ว กรุณาโหลดและตรวจฉบับใหม่')
        existing = conn.execute('SELECT id FROM daily_summary_reviews WHERE patient_id=? AND day=? AND digest=?', (patient_id, body.day.isoformat(), body.digest)).fetchone()
        if existing:
            return {'id': existing['id'], 'already_reviewed': True}
        cursor = conn.execute('INSERT INTO daily_summary_reviews(patient_id,day,digest,payload,reviewed_at,reviewed_by,note) VALUES (?,?,?,?,?,?,?)',
                             (patient_id, body.day.isoformat(), body.digest, row['payload'], time.time(), request.state.subject, body.note))
        audit(conn, patient_id, 'DAILY_REVIEWED', request.state.subject, f"review_id={cursor.lastrowid}; sha256={body.digest}")
        return {'id': cursor.lastrowid, 'already_reviewed': False}


def exported(data, extra=''):
    return PlainTextResponse(data['text'] + '\n\n' + extra + '\n\nStructured evidence:\n' + json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
                             headers={'Content-Disposition': f'attachment; filename="daily-{data["patient_id"]}-{data["day"]}.txt"'})


@router.get('/{patient_id}/daily/report', response_class=PlainTextResponse)
def report(patient_id: str, day: Date | None = None, digest: str | None = None):
    data = get_daily(patient_id, day)
    if digest and digest != data['digest']:
        raise HTTPException(409, 'ร่างเปลี่ยนแล้ว กรุณาโหลดใหม่ก่อนดาวน์โหลด')
    return exported(data, 'UNREVIEWED DRAFT — ตรวจเวลาและหลักฐานก่อนใช้งาน')


@router.get('/{patient_id}/daily/reviews/{review_id}/report', response_class=PlainTextResponse)
def reviewed_report(patient_id: str, review_id: int):
    validate_patient(patient_id)
    with closing(connect()) as conn:
        row = conn.execute('SELECT * FROM daily_summary_reviews WHERE id=? AND patient_id=?', (review_id, patient_id)).fetchone()
    if not row:
        raise HTTPException(404, 'ไม่พบฉบับที่ตรวจแล้วของผู้ป่วยนี้')
    return exported(json.loads(row['payload']), f"Reviewed by {row['reviewed_by']} at {stamp(row['reviewed_at'])}; SHA256 {row['digest']}\n{row['note']}")


def refresh_all():
    now = time.time()
    today = datetime.fromtimestamp(now, TZ).date()
    yesterday = today - timedelta(days=1)
    with closing(connect()) as conn:
        ids = {r[0] for r in conn.execute('''SELECT DISTINCT patient_id FROM vital_logs WHERE timestamp>=?
            UNION SELECT patient_id FROM care_plans UNION SELECT patient_id FROM care_profile_versions
            UNION SELECT patient_id FROM agent_alerts WHERE resolved_at IS NULL OR resolved_at>=?''',
            (period(yesterday, now)[0], period(yesterday, now)[0]))}
    for patient_id in sorted(ids & PATIENT_PROFILES.keys()):
        try:
            refresh(patient_id, today)
            with closing(connect()) as conn:
                prior = conn.execute('SELECT payload FROM daily_summary_cache WHERE patient_id=? AND day=?', (patient_id, yesterday.isoformat())).fetchone()
            if not prior or json.loads(prior[0])['partial_day']:
                refresh(patient_id, yesterday)
        except Exception:
            log.exception('Daily summary generation failed for a demonstration record')


async def run_daily():
    while True:
        try:
            await asyncio.to_thread(refresh_all)
        except Exception:
            log.exception('Daily summary worker failed; previous drafts retained')
        await asyncio.sleep(300)
