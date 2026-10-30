"""Bounded, read-only agent: authorize -> select tools -> retrieve -> explain.

Deterministic tool routing, not an autonomous LLM or a treatment decision maker.
Both portals use patient-safe projections; no provider receives patient data.
"""
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import auth
import patient_views
from monitor_service import patient_state
from patient_registry import PATIENT_LOGIN_PROFILES

router = APIRouter()


class Question(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    patient_id: str | None = Field(default=None, max_length=20)
    section: str = Field(default='overview', max_length=40)


@router.post('/api/assistant/ask')
def ask(body: Question, request: Request):
    audience, subject = request.state.audience, request.state.subject
    patient_id = subject if audience == 'patient' else (body.patient_id or '').strip().upper()
    if audience == 'patient' and body.patient_id and body.patient_id.upper() != subject:
        raise HTTPException(403, 'เรียกดูได้เฉพาะข้อมูลของคุณ')
    if not patient_id:
        return {'answer': 'เลือกผู้ป่วยหรือใส่ ID ก่อน เพื่อให้ผู้ช่วยใช้ข้อมูลถูกคน', 'steps': [], 'patient_id': None, 'mode': 'READ_ONLY_AGENT', 'as_of': time.time()}
    if audience == 'staff' and not auth.can_access_patient(subject, patient_id):
        raise HTTPException(403, 'บัญชีนี้ไม่ได้รับมอบหมายให้ดูแลผู้ป่วยรายนี้')
    if patient_id not in PATIENT_LOGIN_PROFILES:
        raise HTTPException(404, 'ไม่พบผู้ป่วย')
    question = body.message.strip().lower()
    if not question:
        raise HTTPException(422, 'กรุณาระบุคำถาม')
    steps = ['ตรวจสอบสิทธิ์และยืนยันผู้ป่วย']
    parts = [f'ข้อมูลผู้ป่วย {patient_id}']
    state = patient_state(auth.DB, patient_id)
    steps.append('อ่านค่าล่าสุดและตรวจความใหม่ของข้อมูล')
    fresh = state.get('status') not in {'WAITING', 'STALE_DATA', 'INVALID_DATA'}
    if fresh:
        parts.append('ค่าที่บันทึกล่าสุด: ' + ' · '.join(f'{label} {state.get(key, "—")} {unit}' for key, label, unit in (
            ('heart_rate', 'HR', 'bpm'), ('spo2', 'SpO₂', '%'), ('respiratory_rate', 'RR', 'ครั้ง/นาที'))))
        analysis = state.get('analysis', {})
        steps.append('ตรวจผลโมเดลที่ประเมินไว้แล้ว (ไม่รันการฝึกใหม่)')
        if analysis.get('status') == 'READY':
            parts.append('โมเดลพบรูปแบบต่างจากชุดฝึก ควรให้ทีมดูแลตรวจสอบ' if analysis.get('is_anomaly')
                         else 'โมเดลไม่พบรูปแบบต่างจากชุดฝึกในรอบนี้ ไม่ได้ยืนยันว่าปลอดภัย')
        else:
            parts.append('ยังไม่มีผลโมเดลที่ใหม่และพร้อมใช้ จึงงดสรุปผล AI')
    else:
        parts.append('ข้อมูลการวัดยังไม่พร้อมหรือเก่าแล้ว งดใช้ค่านี้ประเมินสถานะปัจจุบัน')
    if body.section in {'trends', 'evidence', 'reports'} or any(word in question for word in ('กราฟ', 'แนวโน้ม', 'ย้อนหลัง', 'trend', 'สรุป')):
        trend = patient_views.trends(patient_id, 24)
        steps.append('อ่านสถิติย้อนหลัง 24 ชั่วโมง แยกตามแหล่งข้อมูล')
        for source, group in trend['sources'].items():
            stats = group['statistics']
            parts.append(f'{source} · {group["snapshot_count"]} การบันทึก: ' + ' · '.join(
                f'{label} เฉลี่ย {stats[key]["mean"]} {unit}' for key, label, unit in (
                    ('heart_rate', 'HR', 'bpm'), ('spo2', 'SpO₂', '%'), ('respiratory_rate', 'RR', 'ครั้ง/นาที')) if stats.get(key)))
        if not trend['sources']:
            parts.append('ยังไม่มีข้อมูลย้อนหลัง 24 ชั่วโมง ไม่เติมค่าที่หายไป')
    if body.section == 'care' or any(word in question for word in ('ดูแล', 'งาน', 'แผน', 'care', 'สรุป')):
        care = patient_views.care(patient_id)
        steps.append('อ่านเฉพาะงานดูแลที่บุคลากรตรวจทานแล้ว')
        parts.append(f'งานดูแลที่เปิดอยู่ {care["open_count"]} งาน · บันทึกเสร็จวันนี้ {care["done_today"]} งาน')
    parts.append('ที่มา: ' + str(state.get('source', 'ยังไม่มีแหล่งข้อมูล')))
    parts.append('ผู้ช่วยนี้เลือกเครื่องมือด้วยกฎและอ่านหลักฐาน ไม่ใช่ LLM อิสระ รองรับค่าล่าสุด แนวโน้ม และงานดูแล; ไม่วินิจฉัย สั่งยา ส่งข้อความ หรือเปลี่ยนแผนรักษา')
    return {'answer': '\n\n'.join(parts), 'steps': steps, 'patient_id': patient_id,
            'mode': 'READ_ONLY_AGENT', 'as_of': time.time()}
