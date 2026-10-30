"""Deterministic TEST_P home-care telemetry, isolated from the 60-bed registry.

The values are synthetic and labelled TEST_SIMULATION at every persistence and
API boundary. They demonstrate the complete UI flow; they are not clinical
measurements and must never be used as ground truth or training data.
"""
import asyncio
from contextlib import closing
import json
import logging
import math
import sqlite3
import time

from monitor_service import MonitorWorker
from patient_registry import TEST_PATIENT_PROFILES
import notifications

log = logging.getLogger(__name__)


def seed_test_care(database):
    """Create one reviewed TEST profile and human-authored demo plans once."""
    now = time.time()
    content = {
        'conditions': 'ภาวะอ่อนแรงในผู้สูงอายุและการดูแลผู้ป่วยติดเตียง (ข้อมูลสาธิต)',
        'medications': 'ยังไม่มีรายการยาที่ผ่านการยืนยันในบัญชีทดสอบ',
        'allergies': 'ยังไม่มีประวัติแพ้ที่ผ่านการยืนยันในบัญชีทดสอบ',
        'limitations': 'ช่วยเหลือการเคลื่อนไหวและเปลี่ยนท่า ห้ามใช้ผลจำลองตัดสินใจรักษา',
        'caregiver': 'ญาติสาธิต', 'care_notes': 'โปรไฟล์ตั้งต้นสำหรับทดสอบระบบเท่านั้น',
        'ranges': {'heart_rate': {'low': 55, 'high': 105}, 'spo2': {'low': 94, 'high': 100},
                   'respiratory_rate': {'low': 12, 'high': 24}},
        'reference_minutes': 5, 'use_reference': False,
    }
    with closing(sqlite3.connect(database, timeout=10)) as conn, conn:
        if not conn.execute("SELECT 1 FROM care_profile_versions WHERE patient_id='TEST_P'").fetchone():
            conn.execute('''INSERT INTO care_profile_versions
                (patient_id,version,state,content,saved_at,saved_by,reviewed_at,reviewed_by)
                VALUES ('TEST_P',1,'ACTIVE',?,?,?,?,?)''',
                (json.dumps(content, ensure_ascii=False), now, 'test_d', now, 'test_d'))
        if not conn.execute("SELECT 1 FROM care_plans WHERE patient_id='TEST_P'").fetchone():
            plans = (
                ('เปลี่ยนท่าและตรวจผิวหนัง', 'เตือนผู้ดูแลให้เปลี่ยนท่าตามแผนที่ทีมดูแลกำหนดและบันทึกผล', 120, now + 300),
                ('ตรวจตำแหน่งเซนเซอร์', 'ตรวจว่าสายและเซนเซอร์อยู่ในตำแหน่งที่กำหนด ไม่มีการกดทับ', 480, now + 600),
            )
            for title, instructions, interval, due in plans:
                cursor = conn.execute('''INSERT INTO care_plans
                    (patient_id,title,instructions,assigned_to,interval_minutes,next_due,state,version,
                     created_at,created_by,reviewed_by,reviewed_at)
                    VALUES ('TEST_P',?,?,?,?,?,'ACTIVE',1,?,'test_d','test_d',?)''',
                    (title, instructions, 'test_d', interval, due, now, now))
                conn.execute('''INSERT INTO care_events(patient_id,plan_id,action,actor,detail,created_at)
                    VALUES ('TEST_P',?,'PLAN_ACTIVE','test_d',?,?)''',
                    (cursor.lastrowid, 'seeded TEST care plan', now))


def simulated_reading(timestamp, started_at):
    elapsed = max(0, int(timestamp - started_at))
    phase = elapsed % 240
    wave = math.sin(elapsed / 8)
    slow = math.sin(elapsed / 31)
    state = 'พักบนเตียง'
    heart_rate = 76 + 2.2 * wave + 1.1 * slow
    spo2 = 97.2 + .35 * math.sin(elapsed / 13)
    respiratory_rate = 17 + .7 * math.sin(elapsed / 10)
    if 70 <= phase < 95:
        state = 'เปลี่ยนท่าบนเตียง'
        heart_rate += 8
        respiratory_rate += 2
    elif 145 <= phase < 170:
        state = 'ช่วงออกซิเจนลดลงจำลอง'
        heart_rate += 14
        spo2 -= 4.1
        respiratory_rate += 3
    elif 170 <= phase < 190:
        state = 'ฟื้นตัวหลังเหตุการณ์จำลอง'
        heart_rate += 7
        spo2 -= 1.5
        respiratory_rate += 1.5
    return {
        'patient_id': 'TEST_P', 'timestamp': float(int(timestamp)),
        'heart_rate': round(heart_rate, 1), 'spo2': round(spo2, 1),
        'respiratory_rate': round(respiratory_rate, 1),
        'source': 'TEST_SIMULATION', 'source_record': 'home-care-demo-v1',
        'source_segment': 'home-care-demo-v1', 'simulation_state': state,
    }


class TestPatientSimulator:
    def __init__(self, database, started_at=None):
        self.started_at = time.time() if started_at is None else started_at
        self.worker = MonitorWorker(database, TEST_PATIENT_PROFILES, 'test')
        self.database = database
        self.last_push_cycle = -1

    def tick(self, now=None):
        now = time.time() if now is None else now
        reading = simulated_reading(now, self.started_at)
        result = self.worker.process([reading], now)
        cycle = int(max(0, now - self.started_at) // 240)
        if reading['simulation_state'] == 'ช่วงออกซิเจนลดลงจำลอง' and cycle != self.last_push_cycle:
            with closing(sqlite3.connect(self.database, timeout=10)) as conn, conn:
                event_key = f'SIMULATION:{self.started_at:.6f}:{cycle}'
                notifications.enqueue_simulation(conn, now, event_key=event_key)
            self.last_push_cycle = cycle
        return result

    async def run(self):
        while True:
            started = time.monotonic()
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # A transient database lock or model error must not silently
                # terminate the 24-hour TEST stream. The next real-time tick
                # resumes; missing samples stay visible as a continuity gap.
                log.error('TEST simulator tick failed (%s); retrying', type(error).__name__)
            await asyncio.sleep(max(.05, 1 - (time.monotonic() - started)))
