# หลักฐาน Dataset และโมเดลที่ใช้งาน

## โมดูลวิจัยใหม่ (2026-09-29)

เพิ่ม **AI Research Lab** จาก PhysioNet Challenge 2019 ชุดย่อยจริง 4,000 ราย
เทรน Logistic Regression เทียบ HistGradientBoosting พร้อมกราฟย้อนหลังและผลทดสอบข้ามโรงพยาบาล
แยกจาก BIDMC live worker และทะเบียน 60 เตียงทั้งหมด ไม่เปิด sepsis scoring สำหรับผู้ป่วยจริง
ผลยังตรวจพบเหตุการณ์ได้ต่ำ จึงไม่อ้างความพร้อมใช้ทางคลินิก
ดูวิธีรัน ผลจริง และข้อจำกัดใน [SEPSIS_RESEARCH_LAB.md](SEPSIS_RESEARCH_LAB.md)

## Dataset ที่ใช้งานจริงในเวอร์ชันนี้

[BIDMC PPG and Respiration Dataset v1.0.0](https://physionet.org/content/bidmc/1.0.0/)
จาก PhysioNet เปิดให้ดาวน์โหลดฟรีภายใต้ Open Data Commons Attribution License v1.0
ต้องคงการอ้างอิงที่มาและเงื่อนไข attribution เมื่อใช้งาน/แจกจ่ายต่อ

- ดาวน์โหลดเฉพาะ Numerics 53 recordings ประมาณ 8 นาทีต่อ recording
- ใช้ HR, SpO2, RESP ที่ความถี่ 1 Hz ไม่ได้ใช้ waveform ECG/PPG
- ตรวจ SHA256 ทุกไฟล์กับ manifest ของผู้เผยแพร่ และเก็บ LICENSE ไว้กับข้อมูล
- ไม่สร้าง label โรคขึ้นเอง ไม่ได้นำโรค/น้ำตาล/ไขมัน/การนอนจากทะเบียนสมมติมาเทรน
- ไม่สามารถอ้างว่าโมเดลวินิจฉัยโรคหรือครอบคลุมผู้ป่วยติดเตียงจากข้อมูลนี้เพียงชุดเดียว

## ขั้นตอนการเทรน

1. อ่าน numeric files และตรวจ checksum
2. คัดหน้าต่างข้อมูลที่ไม่มีค่าขาดหาย/ศูนย์/ไม่ finite หรือเกินขอบเขตตรวจคุณภาพ
3. รับ 60 จุดที่ห่างกัน 1 วินาที สร้าง 21 features: last, mean, std, min, max, delta, slope ของทั้ง 3 ตัวแปร
4. เป้าหมายคือค่าที่วัดจริงอีก 30 วินาทีข้างหน้า เลื่อนหน้าต่างทุก 5 วินาที
5. แบ่ง recording ไม่ซ้ำกัน: train 30, validation 11, test 11 โดยใช้ seeds 42/43
6. เทรน RandomForestRegressor 160 trees, max_depth=10, min_samples_leaf=15, seed=42 เพื่อทำนาย delta จากค่าล่าสุด
7. เปรียบเทียบ MAE กับ persistence และเลือกวิธีรายตัวแปรด้วย validation เท่านั้น
8. เทรน IsolationForest 160 trees, contamination=0.05, seed=42 บน training windows เท่านั้น
9. ประเมิน hold-out test และบันทึก model, metadata, split IDs, hash ของ data manifest

ได้ 3,939 valid windows จาก 52 recordings ที่มีหน้าต่างครบเงื่อนไข (หนึ่ง recording ใช้ไม่ได้)
มี test windows 778 หน้าต่างซึ่งอาจซ้อนทับกัน ไม่ใช่ผู้ป่วยอิสระ 778 คน
แยกแบบ recording-disjoint เท่านั้น ไม่ยืนยัน subject-disjoint เพราะไม่มี subject identity ใน numeric files

## ผลที่วัดได้ (ห้ามเรียกเป็นเปอร์เซ็นต์ accuracy)

| ตัวแปร | Validation RF MAE | Validation persistence MAE | วิธีที่เลือก | Test MAE ที่เลือก | Test persistence MAE |
| --- | ---: | ---: | --- | ---: | ---: |
| HR (bpm) | 1.6861 | 1.7503 | Random Forest | 1.9770 | 1.9704 |
| SpO2 (จุดเปอร์เซ็นต์) | 0.4537 | 0.4281 | Persistence | 0.2918 | 0.2918 |
| RR (ครั้ง/นาที) | 0.9262 | 0.9574 | Random Forest | 1.2717 | 1.2584 |

MAE คือขนาดความคลาดเคลื่อนเฉลี่ย ยิ่งต่ำยิ่งดี ไม่ใช่ความแม่นยำวินิจฉัยโรค
Random Forest ที่เลือกจาก validation ยังไม่ชนะ baseline ใน test set จึงยังอ้างความเหนือกว่าไม่ได้
ไม่ปรับโมเดลหรือเลือกวิธีใหม่จาก test set นี้เพื่อให้ตัวเลขดูดี
ผลนี้ยังไม่มี confidence interval, external validation หรือ prospective clinical evaluation

Isolation Forest ไม่มี ground-truth anomaly labels จึงไม่รายงาน sensitivity/specificity หรือ accuracy
ค่า contamination 0.05 เป็นพารามิเตอร์ฝึก ไม่ใช่อัตราโรคหรือความแม่นยำ 95%

## การทำงานอัตโนมัติในระบบ

backend worker → ข้อมูลรายวินาที → ตรวจคุณภาพ → features → โมเดลทุก 10 วินาที → SQLite → แจ้งเตือน/หน้าจอ

- ไม่เริ่ม worker ใหม่ตอน login และไม่เทรนใหม่ใน request ของผู้ใช้
- กระบวนการ inference แบบ batch รันใน worker thread ไม่บล็อก FastAPI event loop
- พอร์ตบุคลากร 3000 ดู 60 เตียง; พอร์ตผู้ป่วย 3001 ดูตาม ID ที่ผูกกับ session
- ข้อมูลเก่าหรือช่วงเวลาผิดเงื่อนไขจะไม่แสดง forecast ที่อ้างว่าเป็นปัจจุบัน
- Replay ใช้ 11 held-out recordings ซ้ำบน 60 เตียงสมมติ พร้อมแสดง source_record
- เมื่อวนจบ recording จะรอหน้าต่างใหม่ ไม่เชื่อมปลายไฟล์กับต้นไฟล์เป็นเหตุการณ์เดียว
- Agent สร้าง alert proposal/audit เท่านั้น การรักษาและการติดต่อภายนอกยังให้มนุษย์อนุมัติ
- Gemini ทำหน้าที่สรุป/อธิบายเมื่อผู้ใช้ขอ ไม่ได้เทรน Gemini ด้วย BIDMC และไม่จำเป็นต่อ worker

## คำอธิบายให้อาจารย์

“ระบบนี้แยก AI เป็นสองส่วน: ML ที่เราเทรนจริงจาก BIDMC สำหรับ forecast และตรวจรูปแบบผิดไปจากชุดฝึก
กับ Gemini ที่ช่วยสรุปข้อมูล ภายในมี worker ประมวลผลต่อเนื่องและ rule-based alert agent จัดงานให้เจ้าหน้าที่
เราแบ่งชุดข้อมูลตาม recording ป้องกันหน้าต่างจาก recording เดียวกันปะปนระหว่าง train และ test
พร้อมรายงาน baseline และข้อจำกัดอย่างตรงไปตรงมา ผลยังเป็นงานวิจัย ไม่ใช่เครื่องมือวินิจฉัยที่ผ่านการรับรอง”

## งานก่อนใช้จริง

ต้องกำหนด endpoint ทางคลินิกกับผู้เชี่ยวชาญ รวบรวม labels ที่ตรวจสอบได้ แยก subject/site/time
และมี external test ชุดใหม่ก่อนอ้างผลทั่วไป ตรวจ subgroup, missingness, drift, calibration,
false alarms per patient-hour และทดสอบ prospective แบบ silent mode
ต้องเพิ่ม verified login/OTP, บัญชีบุคลากรรายคน, สิทธิ์แพทย์/พยาบาล/ญาติ, HTTPS และระบบกำกับข้อมูล
ไม่ใช้ ID-only กับเวชระเบียนจริง และไม่ส่งข้อมูลจริงไป cloud โดยไม่มีการอนุญาตที่เหมาะสม

โค้ดหลัก: backend/ml_pipeline/{download_bidmc,bidmc,train_bidmc}.py,
backend/ai_models/monitor_model.py, backend/monitor_service.py, backend/auth.py และ backend/patient_api.py
