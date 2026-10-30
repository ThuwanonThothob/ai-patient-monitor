# AI Care Agent Team v1 — Dataset, Model และขอบเขตการทำงาน

เวอร์ชันนี้แบ่งระบบ local ที่ทำงานต่อเนื่องใน staff backend ออกเป็น Agent ตามหน้าที่
โดยไม่พึ่ง Gemini และไม่รบกวน WebSocket 1 Hz เดิม ทีม Agent ไม่วินิจฉัย ไม่เปลี่ยนยา/
การรักษา ไม่ปิด Alert และไม่ติดต่อแพทย์หรือรถพยาบาลเอง

## ทีม Agent

- **Telemetry Agent** — รับ vital event และเก็บแหล่งที่มา/เวลา
- **Data Quality Agent** — ตรวจช่วงค่า ความใหม่ และ abstain เมื่อข้อมูลไม่พร้อม
- **Monitoring AI Agent** — อ่านผลโมเดล `bidmc-monitor-v1` และ threshold ที่กำหนด
- **Device Health Agent** — เฝ้า heartbeat แบตเตอรี่ สัญญาณ เซนเซอร์และ pressure map
- **Care Coordinator Agent** — สร้างรอบงานจากแผนที่มนุษย์อนุมัติและชี้งานเกินกำหนด
- **Notification Agent** — เข้าคิว Web Push ที่ตั้งค่าไว้และบันทึกผลส่ง
- **Documentation Agent** — เขียน trace และร่างสรุปข้อมูลแบบ evidence-grounded
- **Safety Supervisor Agent** — บังคับสิทธิ์ ป้องกันงานซ้ำ และส่งงานเสี่ยงให้คนยืนยัน

รายการบทบาท สิทธิ์ และเส้นทางส่งต่องานนิยามไว้ที่
`backend/ai_models/care_team.py` และเปิดเผยใน `GET /api/agent/status`

## วงจร Agent

```text
Monitor event
  → Telemetry Agent: observe_vitals
  → Data Quality Agent: validate_data_contract
  → Monitoring AI Agent: read_trained_model
  → Care Coordinator Agent: read_reviewed_care_context
  → Safety Supervisor: apply_guarded_alert_policy
  → Alert proposal + staff notification queue (เมื่อเปิดใช้งาน)
  → Documentation Agent: document_decision
  → human acknowledgement / escalation / resolution เมื่อเป็นการตัดสินใจทางคลินิก
```

ระบบบันทึกแต่ละรอบไว้ใน `nurse_agent_runs` และแต่ละ tool step ใน
`nurse_agent_steps` พร้อม Agent owner, Patient ID, model version, source, decision, เวลา
และ Alert ID หน้า **AI และประวัติระบบ** แสดงแผนผังทีม Agent, Decision Timeline และ
Dataset/Model Registry

เพื่อจำกัดภาระ SQLite ข้อมูลยังส่ง WebSocket ทุกวินาที แต่ Agent สังเกตเมื่อสถานะเปลี่ยน
มีผลโมเดลรอบใหม่ หรือครบ heartbeat 10 วินาที ส่วน trace ปกติบันทึกไม่เกินหนึ่งครั้งต่อ
Patient ID ต่อ 10 นาที และบันทึกทุกครั้งที่เสนอ/ระงับ Alert ซ้ำ เก็บสูงสุด 5,000 runs

## เครื่องมือและสิทธิ์

Agent ทำอัตโนมัติได้:

- ตรวจอายุ/ขอบเขตข้อมูลและงดตอบเมื่อไม่ผ่าน
- อ่านผล `bidmc-monitor-v1` ที่ worker คำนวณไว้แล้ว
- อ่านเฉพาะจำนวนแผนที่คนตรวจแล้วและงานเปิด/เกินเวลา
- ใช้ Alert policy เดิมและป้องกันข้อเสนอซ้ำแบบถาวรข้าม restart
- เข้าคิว Web Push ของบุคลากรเมื่อระบบ Push เปิดและมีผู้สมัครรับ
- เขียน audit trace

ต้องให้มนุษย์ทำ:

- วินิจฉัย เปลี่ยนยา เปลี่ยนการรักษา หรือแก้ alert threshold
- ยืนยัน/แก้แผนดูแล รับงาน ปิดงาน และบันทึกผล
- ติดต่อแพทย์หรือหน่วยฉุกเฉิน
- อนุมัติการใช้ข้อมูลจริงและตัดสินใจทางคลินิก

Gemini ยังใช้เฉพาะการถามตอบ/อธิบายตามคำขอ ไม่อยู่ใน safety loop และไม่มีสิทธิ์เรียก
เครื่องมือเขียนข้อมูล Agent จึงยังทำงานได้เมื่อไม่มี key, quota หรืออินเทอร์เน็ต

## Dataset และ Model ที่เลือกใช้

### Active monitor

- [BIDMC PPG and Respiration Dataset v1.0.0](https://physionet.org/content/bidmc/1.0.0/)
- อินพุต HR, SpO2, RESP 1 Hz; 60 วินาทีต่อหน้าต่าง; เป้าหมาย +30 วินาที
- RandomForestRegressor สำหรับ HR/RR, persistence สำหรับ SpO2 และ IsolationForest
  สำหรับรูปแบบต่างจาก training windows
- Active เพียงชุดเดียวใน live monitor; ไม่มี disease label และยังไม่ผ่าน clinical validation

### Research-only

- [PMD pressure-map dataset](https://physionet.org/content/pmd/1.0.0/): Logistic Regression
  จำแนกสามท่ามาตรฐานจาก Experiment I; ไม่มีผู้สูงอายุติดเตียงหรือ label แผลกดทับ
- [PhysioNet Challenge 2019](https://physionet.org/content/challenge-2019/1.0.0/):
  HistGradientBoosting/Logistic Regression สำหรับ benchmark sepsis; ผล frozen protocol
  ยังพลาดเหตุการณ์จำนวนมาก จึงไม่เปิด live scoring
- [PhysioNet Challenge 2012](https://physionet.org/content/challenge-2012/1.0.0/):
  historical ICU mortality model ที่ต้องใช้ข้อมูล 48 ชั่วโมง จึง abstain กับ short live window

Registry อ่านเฉพาะ JSON metadata/report ไม่โหลดไฟล์ model pickle และไม่เลือกโมเดลใหม่เอง

## Dataset ที่สำรวจสำหรับขั้นถัดไป

- [VitalDB](https://vitaldb.net/dataset/): ข้อมูลสัญญาณหลายชนิดคุณภาพสูงจากผู้ป่วยผ่าตัด
  ภายใต้ CC BY 4.0 เหมาะกับงาน waveform/data-quality/hypotension research แต่ไม่ใช่บ้านหรือ
  ผู้สูงอายุติดเตียง จึงยังไม่ควรนำมาอ้างประสิทธิภาพเป้าหมายนี้
- [MIMIC-IV Waveform Database v0.1.0](https://physionet.org/content/mimic4wdb/0.1.0/):
  waveform ECG/PPG/BP แบบ open 200 records; การเชื่อมข้อมูลคลินิก MIMIC-IV ต้องผ่าน
  credential, training และ DUA จึงไม่ดาวน์โหลดอัตโนมัติ

การเพิ่ม public ICU dataset อีกชุดไม่แก้ช่องว่างหลักของโครงการ ข้อมูลที่ต้องการจริงคือ
prospective target-cohort data จากผู้สูงอายุ/ผู้ป่วยติดเตียงที่บ้าน ใช้เซนเซอร์รุ่นเดียวกับระบบ
มี consent และ label ที่บุคลากรตรวจ เช่น sensor หลุด เหตุการณ์ SpO2 ลด การไม่พลิกตัว
การตอบสนองต่อ Alert และผลลัพธ์หลังตรวจ

## API สำหรับบุคลากร

- `GET /api/agent/status` — runtime, policy, one-hour counts และ registry
- `GET /api/agent/runs?limit=30&patient_id=A001` — run พร้อม tool steps

ทั้งสอง route ต้องใช้ staff session และไม่มีใน patient API

## ทดสอบ

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m unittest discover -s tests -v
cd ../frontend
npm test
npm run lint
npm run build
npm run build:patient
```

Unit tests ครอบคลุม normal run, critical proposal, stale-data abstention, care-context
allowlist, persistent dedup หลัง restart, registry separation และ staff-only routes
ทั้งหมดเป็น software tests ไม่ใช่ clinical validation
