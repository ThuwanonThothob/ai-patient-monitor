"""Read-only, allowlisted projections for the session-bound demo patient portal.

Never expose staff audit, draft profiles/plans, internal notes, identities or
raw report payloads. No cloud calls, new inference or clinical actions.
"""
from contextlib import closing
from datetime import datetime
import time

from care_profiles import KEYS, active_profile, connect, valid
from daily_summary import TZ, coverage, get_daily, stamp
from patient_registry import get_patient_profile

SOURCES = {'BIDMC_REPLAY', 'MQTT', 'TEST_SIMULATION'}
UNITS = {'heart_rate': 'bpm', 'spo2': '%', 'respiratory_rate': 'ครั้ง/นาที'}


def public_registry(patient_id):
    profile = get_patient_profile(patient_id)
    if not profile:
        raise KeyError(patient_id)
    return {key: profile.get(key) for key in (
        'name', 'zone', 'room_number', 'bed_number', 'age', 'gender', 'blood_group', 'condition', 'mobility',
        'care_setting', 'care_goal', 'emergency_contact', 'doctor', 'assigned_staff_id')}


def measurements(rows):
    result = {}
    for key in KEYS:
        values = [r[key] for r in rows if valid(key, r[key])]
        result[key] = {'count': len(values), 'mean': round(sum(values) / len(values), 2),
                       'min': min(values), 'max': max(values), 'first': values[0], 'last': values[-1]} if values else None
    return result


def trends(patient_id, hours, now=None):
    now = time.time() if now is None else now
    seconds = {1: 60, 6: 300, 24: 900, 168: 3600}[hours]
    start = now - hours * 3600
    with closing(connect()) as conn:
        rows = [dict(r) for r in conn.execute('''SELECT timestamp,heart_rate,spo2,respiratory_rate,simulation_state
            FROM vital_logs WHERE patient_id=? AND timestamp>=? AND timestamp<? ORDER BY timestamp,id''', (patient_id, start, now))]
    groups = {}
    for row in rows:
        source = row['simulation_state'] if row['simulation_state'] in SOURCES else 'UNKNOWN'
        groups.setdefault(source, {})[row['timestamp']] = row
    sources = {}
    for source, unique in groups.items():
        items = list(unique.values())
        buckets = {}
        for row in items:
            index = int((row['timestamp'] - start) // seconds)
            buckets.setdefault(index, []).append(row)
        points = []
        for index in range(hours * 3600 // seconds):
            stats = measurements(buckets.get(index, []))
            points.append({'timestamp': start + index * seconds,
                           **{key: stats[key]['mean'] if stats[key] else None for key in KEYS},
                           'count': len(buckets.get(index, []))})
        sources[source] = {'snapshot_count': len(items), 'statistics': measurements(items), 'points': points,
                           'coverage': coverage(items, start, now)}
    return {'patient_id': patient_id, 'hours': hours, 'start': start, 'as_of': now, 'bucket_seconds': seconds,
            'sources': sources, 'demo': True,
            'notice': 'กราฟค่าเฉลี่ยตามช่วง ไม่ใช่ค่าทุกวินาที; ชั่วโมงที่ไม่มีข้อมูลไม่ถูกเติมค่า และไม่เฉลี่ยข้ามแหล่งข้อมูล'}


def care(patient_id, now=None):
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with closing(connect()) as conn:
        conn.execute('BEGIN')
        profile = active_profile(conn, patient_id)
        plans = [dict(r) for r in conn.execute('''SELECT id,title,instructions,interval_minutes,next_due,state,reviewed_at
            FROM care_plans WHERE patient_id=? AND reviewed_at IS NOT NULL AND reviewed_at<=? AND state!='DRAFT'
            ORDER BY CASE WHEN state='ACTIVE' THEN 0 ELSE 1 END,next_due,id LIMIT 50''', (patient_id, now))]
        plan_count = conn.execute("SELECT COUNT(*) FROM care_plans WHERE patient_id=? AND reviewed_at IS NOT NULL AND reviewed_at<=? AND state!='DRAFT'", (patient_id, now)).fetchone()[0]
        tasks = [dict(r) for r in conn.execute('''SELECT t.id,t.scheduled_at,t.state,t.acknowledged_at,t.completed_at,p.title,p.instructions
            FROM care_tasks t JOIN care_plans p ON p.id=t.plan_id
            WHERE p.patient_id=? AND p.reviewed_at IS NOT NULL AND p.reviewed_at<=? AND p.state!='DRAFT'
            AND (t.state IN ('PENDING','ACKNOWLEDGED') OR (t.completed_at>=? AND t.completed_at<?))
            ORDER BY CASE WHEN t.state IN ('PENDING','ACKNOWLEDGED') THEN 0 ELSE 1 END,
                CASE WHEN t.state IN ('PENDING','ACKNOWLEDGED') THEN t.scheduled_at END,t.completed_at DESC,t.id DESC''',
            (patient_id, now, today, now))]
    for task in tasks:
        task['overdue'] = task['state'] in ('PENDING', 'ACKNOWLEDGED') and task['scheduled_at'] < now
    safe_profile = None
    if profile and profile['reviewed_at'] <= now:
        safe_profile = {'version': profile['version'], 'reviewed_at': profile['reviewed_at'],
                        **{key: profile['content'][key] for key in ('conditions', 'medications', 'allergies', 'limitations')}}
    return {'patient_id': patient_id, 'as_of': now, 'profile': safe_profile, 'plans': plans,
            'plan_count': plan_count, 'plans_truncated': plan_count > len(plans), 'tasks': tasks[:50],
            'task_count': len(tasks), 'tasks_truncated': len(tasks) > 50,
            'open_count': sum(t['state'] in ('PENDING', 'ACKNOWLEDGED') for t in tasks),
            'done_today': sum(t['state'] == 'DONE' and t['completed_at'] < now for t in tasks),
            'read_only': True, 'notice': 'แสดงแผนที่ทีมดูแลยืนยันแล้วและสถานะที่บันทึก ไม่ใช่การสั่งรักษาใหม่; บันทึกภายในไม่แสดงในหน้านี้'}


def daily(patient_id, day=None):
    raw = get_daily(patient_id, day)
    # Explicit projection: never serialize raw, care events/notes, staff actors,
    # draft profile contents, alert reasons, or immutable staff review payloads.
    result = {key: raw[key] for key in ('patient_id', 'day', 'timezone', 'start', 'as_of', 'generated_at', 'partial_day', 'digest')}
    result['sources'] = {source: {'row_count': group['row_count'],
        'measurements': {key: {field: value[field] for field in ('count', 'mean', 'min', 'max', 'first', 'last')} if value else None
                         for key, value in group['measurements'].items()}}
                         for source, group in raw['sources'].items()}
    result['recording'] = {key: raw['overall_recording'][key] for key in ('estimated_percent', 'gap_count', 'longest_gap_seconds')}
    result['ml'] = {source: {key: model[key] for key in ('evaluations', 'ready', 'unusual_pattern_evaluations', 'abstention_statuses')}
                    for source, model in raw['ml'].items()}
    result['care'] = {key: raw['care'][key] for key in ('due_in_period', 'done_in_period', 'skipped_in_period', 'cancelled_in_period', 'open_due_as_of_count')}
    result['alerts'] = {key: raw['alerts'][key] for key in ('new_count', 'resolved_count', 'open_as_of_count')}
    result['notice'] = 'สรุปอัตโนมัติจากหลักฐานสาธิต ไม่ใช่คำวินิจฉัยหรือการรับรองว่าปลอดภัย; ไม่พบข้อมูลไม่เท่ากับไม่มีความผิดปกติ'
    lines = ['Smart Ward — สรุปประจำวันสำหรับผู้ป่วย (ข้อมูลสาธิต)', result['notice'],
             f"Patient ID: {patient_id} | วันที่ {raw['day']} (Asia/Bangkok)",
             f"ข้อมูลตั้งแต่ {stamp(raw['start'])} ถึงก่อน {stamp(raw['as_of'])}",
             f"สร้างเมื่อ {stamp(raw['generated_at'])}; {'ยังไม่ครบวัน' if raw['partial_day'] else 'สิ้นสุดวันแล้ว'}",
             'วิธีสรุป: สถิติและผล ML ที่บันทึกจริง ไม่เรียก Gemini', '']
    if not result['sources']:
        lines.append('ไม่มีข้อมูลการวัดในช่วงนี้ ไม่สรุปว่าผู้ป่วยปลอดภัย')
    for source, group in result['sources'].items():
        lines.append(f"แหล่งข้อมูล {source}: {group['row_count']} แถว")
        for key, m in group['measurements'].items():
            lines.append(f"{key} ({UNITS[key]}): เฉลี่ย {m['mean']:g}, ต่ำสุด {m['min']:g}, สูงสุด {m['max']:g}" if m else f'{key}: ไม่มีค่าที่ผ่านคุณภาพ')
    lines += ['', f"ความครอบคลุม snapshot โดยประมาณ {result['recording']['estimated_percent']:g}% ไม่ใช่เวลาที่อุปกรณ์ออนไลน์จริง",
              f"ข้อมูลขาดช่วงเกิน 15 วินาที {result['recording']['gap_count']} ช่วง",
              f"งานเสร็จในวัน {result['care']['done_in_period']} / ยังค้างถึงกำหนด ณ เวลาตัดข้อมูล {result['care']['open_due_as_of_count']}",
              f"รายการให้ทีมตรวจสอบใหม่ {result['alerts']['new_count']} / ยังไม่ปิด ณ เวลาตัดข้อมูล {result['alerts']['open_as_of_count']}"]
    if not result['ml']:
        lines.append('ไม่มีประวัติผล ML ที่บันทึกในช่วงนี้ ไม่ได้แปลว่าโมเดลตรวจแล้วไม่พบความผิดปกติ')
    for source, model in result['ml'].items():
        lines.append(f"{source}: ML พร้อมประเมิน {model['ready']}/{model['evaluations']} รอบ; รูปแบบต่างจากชุดฝึก {model['unusual_pattern_evaluations']} รอบ ไม่ใช่จำนวนเหตุการณ์โรค")
    result['text'] = '\n'.join(lines)
    return result
