# Device Health, pressure mat และ Ground Truth

ส่วนนี้เป็นระบบ **research/shadow mode** สำหรับตรวจคุณภาพอุปกรณ์และประเมินท่ามาตรฐาน
บนเตียง ยังไม่ใช่อุปกรณ์การแพทย์ และไม่ทำนายแผลกดทับ

## สิ่งที่ทำงานแล้ว

- รับ heartbeat ของอุปกรณ์สัญญาณชีพและ pressure mat ทาง MQTT topic แยก
- ตรวจ device ID, Patient ID, timestamp, battery, signal, sensor attached และ calibration due
- แจ้งเตือนแบตต่ำ สัญญาณอ่อน เซนเซอร์หลุด และ heartbeat หาย
- รับ pressure map ขนาด 32×64 แล้วใช้โมเดล PMD ที่ตรวจ checksum ก่อนโหลด
- โมเดลเลือก `left`, `right`, `supine` หรือ `ABSTAIN` เมื่อไม่มั่นใจ
- ติดตามระยะเวลาท่าเดิมและสร้างงานให้บุคลากรตรวจเมื่อถึงเวลาที่ตั้งไว้
- บุคลากรเปิดผู้ป่วยแล้วบันทึก Ground Truth แบบ blinded; prediction/confidence จะเปิดหลังยืนยันเฉลย
- ส่งออก feature/label แบบ JSONL โดยใช้ pseudonymous subject key และไม่ใส่ชื่อผู้บันทึก

## MQTT contract

Backend ใช้ `WARD_INGEST_MODE=mqtt` เมื่อรับทั้ง vital และ bedside จาก MQTT หรือใช้
`WARD_INGEST_MODE=replay` ร่วมกับ `WARD_BEDSIDE_MQTT_ENABLED=1` เพื่อคง vital demo แล้วรับ
เฉพาะอุปกรณ์ข้างเตียง ระบบ subscribe `WARD_BEDSIDE_TOPIC` (ค่าเริ่มต้น
`my_ai_hospital/bedside`) อุปกรณ์ต้องส่งเวลา Unix วินาทีที่คลาดจาก backend ไม่เกิน 60 วินาที

Device heartbeat:

```json
{
  "message_type": "device_health",
  "patient_id": "A001",
  "device_id": "A001-vital-01",
  "kind": "vital",
  "timestamp": 1791820800,
  "battery_percent": 82,
  "signal_quality": 0.92,
  "sensor_attached": true,
  "calibration_due_at": 1794412800,
  "source": "MQTT"
}
```

Pressure mat ใช้ schema เดียวกัน เปลี่ยน `kind` เป็น `pressure_mat`, `message_type`
เป็น `pressure_map` และเพิ่ม `pressure_map` เป็น array 32 แถว × 64 ค่า ค่าต้องเป็นตัวเลข finite,
ไม่ติดลบ และผลรวมมากกว่า 0 ฮาร์ดแวร์ที่มี resolution อื่นต้องมี adapter ที่ผ่านการทดสอบก่อนส่ง
ห้าม resize แบบเดาใน backend เพราะจะทำให้ input distribution ต่างจากชุดฝึก

สำหรับ broker ที่จำกัด packet สามารถส่งแบบบีบอัดที่ simulator ใช้: `pressure_encoding` เป็น
`zlib+base64+json`, `pressure_shape` เป็น `[32,64]` และ `pressure_data` เป็น zlib-compressed
JSON ที่เข้ารหัส Base64 ตัว backend จำกัดขนาดทั้งก่อนและหลังคลายข้อมูลเพื่อป้องกัน payload ผิดปกติ

## ทดสอบอัตโนมัติโดยไม่ใช้ broker

จาก root ของโครงการ:

```bash
source .venv/bin/activate
python -m unittest backend/tests/test_bedside_monitor.py -v
```

ต้องผ่านกรณี healthy/fault, heartbeat timeout, dwell alert, Ground Truth/export, invalid payload
และ model artifact verification

## ทดสอบครบเส้นทางผ่าน MQTT

1. เปิด MQTT broker ที่รองรับ WebSocket พอร์ต 8083 หรือกำหนด `MQTT_BROKER`/`MQTT_PORT`
2. ใน `backend/.env` ตั้ง:

```dotenv
WARD_INGEST_MODE=replay
WARD_BEDSIDE_MQTT_ENABLED=1
WARD_BEDSIDE_TOPIC=my_ai_hospital/bedside
WARD_DEVICE_STALE_SECONDS=30
WARD_TURN_REMINDER_SECONDS=7200
WARD_DATASET_EXPORT_KEY=ค่าลับสุ่มอย่างน้อย16ตัวอักษร
```

3. เปิดระบบตามปกติ แล้วเปิด terminal อีกหน้าหนึ่ง:

```bash
source .venv/bin/activate
python iot-simulator/bedside_simulator.py --scenario demo
```

4. ตรวจหน้าเจ้าหน้าที่:
   - A001: vital + pressure mat ปกติ และมีผลท่า
   - A002: alert แบตใกล้หมด
   - A003: alert sensor หลุด
   - A004: หลังเกิน 30 วินาทีต้องเป็น STALE และสร้าง alert heartbeat หาย
5. เปิด A001 → “อุปกรณ์และท่าบนเตียง” → ตรวจท่าจริง → บันทึก Ground Truth
6. ตรวจ `GET /api/bedside/dataset.jsonl` หลังล็อกอินบุคลากร ควรไม่มี Patient ID และชื่อผู้บันทึก

ทดสอบ fault เดี่ยวได้ เช่น:

```bash
python iot-simulator/bedside_simulator.py --scenario single --patient B003 --kind vital --battery 5
python iot-simulator/bedside_simulator.py --scenario single --patient B004 --kind pressure_mat --posture left
```

## แผนเก็บ Dataset กลุ่มเป้าหมาย

1. กำหนด protocol, consent, retention และผู้มีสิทธิ์ก่อนเก็บข้อมูลจริง
2. เก็บ pressure feature + ผลทำนาย แล้วให้บุคลากรตรวจท่าจริงโดยไม่เห็นคำตอบ AI ก่อน
3. เพิ่ม label เหตุการณ์ที่ต้องการอย่างมีนิยามเดียวกัน และตรวจ inter-rater agreement
4. แบ่ง train/validation/test **ตามบุคคล** ไม่แบ่ง frame สุ่ม เพื่อป้องกันข้อมูลคนเดียวกันรั่วข้ามชุด
5. รายงาน coverage/ABSTAIN, macro-F1 ต่อท่า, confusion matrix, false alert ต่อ patient-day,
   missed-event review และผลแยก subgroup
6. ทดลอง shadow mode ก่อน ห้ามให้ alert เปลี่ยนการรักษาโดยอัตโนมัติ

PMD ที่ใช้เริ่มต้นมีผู้เข้าร่วม 13 คนใน Experiment I และไม่ใช่ cohort ผู้สูงอายุ/ผู้ป่วยติดเตียง
จึงใช้พิสูจน์ pipeline ได้ แต่ใช้ยืนยันความแม่นยำทางคลินิกของกลุ่มเป้าหมายไม่ได้
