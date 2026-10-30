# ข้อความสั่งงาน P3 — Clinical AI & Sensor UI (AI Vitals, NEWS2 Score, Charts, Bedside Sensors & Evidence/Research UI)

คุณคือ P3 (Clinical AI Model Validation & Clinical Visualization UI) ได้รับมอบหมายจาก Argon (Orchestrator / Tech Lead) ของโปรเจกต์ `ai-patient-monitor`

## บริบทโปรเจกต์และภารกิจ Sprint 4
ใน **Sprint 4: Full Frontend Overhaul** หน้าที่ของคุณคือปรับโฉมคอมโพเนนต์ฝั่งแสดงผลสัญญาณชีพ กราฟแนวโน้ม เซนเซอร์แผ่นวัดแรงกดข้างเตียง และหน้าพิสูจน์/วิจัย AI ทั้งหมดให้มีความแม่นยำทางการแพทย์ อ่านง่ายใน 3 วินาที แสดงคะแนนเตือนภัยมาตรฐานการแพทย์ **Modified NEWS2 Score** ควบคู่กับผลพยากรณ์ 30 วินาทีของ AI และจัดเก็บตารางข้อมูลเชิงลึกไว้ในลิ้นชัก `Learn More` (`learnMoreDrawer`)

## ขอบเขตไฟล์ที่คุณรับผิดชอบเท่านั้น (ห้ามแก้ไฟล์ของ Role อื่นเด็ดขาด)
- `frontend/app/MonitorPanel.tsx`
- `frontend/app/VitalCharts.tsx`
- `frontend/app/StaffTrendPanel.tsx`
- `frontend/app/BedsidePanel.tsx`
- `frontend/app/PosturePanel.tsx`
- `frontend/app/EvidencePanel.tsx`
- `frontend/app/AgentPanel.tsx`
- `frontend/app/ResearchPanel.tsx`
- `frontend/app/ResearchPanel.module.css`
- `frontend/app/ScenarioLab.tsx`
- `frontend/app/AgentAssistant.tsx`
- `frontend/app/AgentAssistant.module.css`

## รายละเอียดงานที่ต้องทำ

### งานที่ 1: เพิ่มการแสดงผลคะแนนมาตรฐานการแพทย์ `Modified NEWS2` คู่กับผล AI ใน `MonitorPanel.tsx`
1. ใน `LatestVitals` (`frontend/app/MonitorPanel.tsx`):
   - เมื่อข้อมูลสดใหม่ (`fresh === true`) ให้คำนวณคะแนนย่อยตามเกณฑ์มาตรฐาน **NEWS2 (Sub-score จาก HR, SpO₂, RR)**:
     - **RR (ครั้ง/นาที)**: `<=8` (3 คะแนน), `9–11` (1 คะแนน), `12–20` (0 คะแนน), `21–24` (2 คะแนน), `>=25` (3 คะแนน)
     - **SpO₂ (%)**: `<=91` (3 คะแนน), `92–93` (2 คะแนน), `94–95` (1 คะแนน), `>=96` (0 คะแนน)
     - **HR (bpm)**: `<=40` (3 คะแนน), `41–50` (1 คะแนน), `51–90` (0 คะแนน), `91–110` (1 คะแนน), `111–130` (2 คะแนน), `>=131` (3 คะแนน)
   - แสดงป้ายกำกับสรุปคะแนน **Modified NEWS2 (3 ตัวแปร)** พร้อมระบุชัดเจนว่าเป็นคะแนนประกอบการเฝ้าระวังเบื้องต้นจาก 3 สัญญาณชีพ (ยังไม่รวมความดัน อุณหภูมิ และระดับความรู้สึกตัว)
2. ใน `PatientAnalysis` และ `MonitorPanel`:
   - จัดระเบียบการแสดงผลค่าคาดการณ์ 30 วินาทีข้างหน้า (`HR`, `SpO2`, `RR`) และแสดงป้ายสถานะ **Abstention (ระงับผลคาดการณ์)** อย่างชัดเจนเมื่อข้อมูลขาดช่วงหรือมีสัญญาณรบกวน

### งานที่ 2: ปรับโฉมกราฟแนวโน้มและเซนเซอร์ข้างเตียง (`VitalCharts.tsx`, `StaffTrendPanel.tsx`, `BedsidePanel.tsx`, `PosturePanel.tsx`)
1. ใน `VitalCharts.tsx` และ `StaffTrendPanel.tsx`:
   - ปรับแต่งการ์ดกราฟแนวโน้มและแถบสรุปค่าเฉลี่ย/ต่ำสุด/สูงสุด (`historyStats`) ให้อ่านง่าย คมชัด และไม่แปลงค่าว่างเป็นศูนย์
2. ใน `BedsidePanel.tsx` และ `PosturePanel.tsx`:
   - จัดระเบียบการ์ดสุขภาพอุปกรณ์ (`deviceCard`), แถบเตือนการพลิกตัวผู้ป่วยติดเตียง (`turnReminderBox`), และแผนภาพแผ่นวัดแรงกด (Pressure Mat Heatmap) ให้อ่านง่ายสำหรับพยาบาลเวร

### งานที่ 3: จัดระเบียบหน้าพิสูจน์ AI, ทีม Agent และห้องแล็บวิจัย (`EvidencePanel.tsx`, `AgentPanel.tsx`, `ResearchPanel.tsx`, `ScenarioLab.tsx`, `AgentAssistant.tsx`)
1. คงข้อความสำคัญตามสัญญาเทสต์ครบถ้วน (`PhysioNet BIDMC`, `1 Hz`, `Train / Validation / Test`, `Zero Data Leakage`, `Random Forest`, `Persistence Baseline`, `30 วินาที`, `งดพยากรณ์` / `Abstain`, `โมเดลเฝ้าระวังสัญญาณชีพสด 1 Hz`, `โมเดลวิจัยย้อนหลัง ICU Sepsis Benchmark`)
2. รวบตารางเมทริกซ์เชิงลึกและข้อมูลสำหรับนักวิจัยไว้ในลิ้นชัก `learnMoreDrawer` (`Learn More`) เพื่อให้ส่วนบนของหน้าจออ่านเข้าใจได้ภายใน 3 วินาที
3. ใน `AgentAssistant.module.css` คง `.launcher { position: fixed; right: 24px; ... }` และ `.dialog { margin: auto; text-align: center; ... }` ตามสัญญาเทสต์ R2

## เกณฑ์งานเสร็จ (Definition of Done)
- รัน `PATH="/opt/homebrew/bin:$PATH" npm --prefix frontend test` ผ่าน 100%
- รัน `PATH="/opt/homebrew/bin:$PATH" npm --prefix frontend run lint` และ `npx --prefix frontend tsc --noEmit` ผ่าน 0 errors

## รูปแบบรายงานผลกลับให้ Argon
- **ทำอะไรเสร็จ**: (ระบุไฟล์และสิ่งที่ปรับปรุง)
- **ติดปัญหาอะไร**: (ถ้ามี)
- **ต้องการอะไรจาก Role อื่น**: (ถ้ามี)
