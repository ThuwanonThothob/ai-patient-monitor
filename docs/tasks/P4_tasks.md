# ข้อความสั่งงาน P4 — DevOps & QA (Frontend Contract Tests, CSS Purity Gate & Dual-Portal Build Verification)

คุณคือ P4 (DevOps & QA — Frontend Quality & Build Gate) ได้รับมอบหมายจาก Argon (Orchestrator / Tech Lead) ของโปรเจกต์ `ai-patient-monitor`

## บริบทโปรเจกต์และภารกิจ Sprint 4
ใน **Sprint 4: Full Frontend Overhaul** ทีม P1, P2 และ P3 กำลังปรับโฉมคอมโพเนนต์ Frontend ทั้งระบบ หน้าที่ของคุณคือสร้างเกราะป้องกันคุณภาพ (Automated Quality Gate) ในชุดทดสอบของ Frontend เพื่อรับประกันว่าทุกหน้าจอที่ปรับปรุงใหม่:
1. ไม่ทำลายสัญญาความถูกต้องทางคลินิกและความปลอดภัยเดิม (Contract Tests)
2. ไม่มี CSS Module Selector เปลือยที่ทำให้ Next.js Production Build พัง
3. รองรับฟีเจอร์ใหม่ใน Sprint 4 (โหมดเวรดึก `nightShift`, สรุป `SBAR`, คะแนน `NEWS2`, และลิ้นชัก `Learn More`) อย่างครบถ้วน

## ขอบเขตไฟล์ที่คุณรับผิดชอบเท่านั้น (ห้ามแก้ไฟล์ของ Role อื่นเด็ดขาด)
- `frontend/tests/ui-contract.test.mjs`
- `frontend/tests/patient.test.mjs`
- `frontend/tests/vitalView.test.mjs`
- `scripts/test_all.sh`
- `scripts/smoke_portals.py`

## รายละเอียดงานที่ต้องทำ

### งานที่ 1: เพิ่มชุดทดสอบ CSS Module Purity Gate และ Sprint 4 UI Contract ใน `frontend/tests/ui-contract.test.mjs`
1. เพิ่มเทสต์ตรวจสอบไฟล์ `.module.css` ทุกไฟล์ใน `frontend/app/` (`Ward.module.css`, `PatientPortal.module.css`, `CareChat.module.css`, `AgentAssistant.module.css`, `ResearchPanel.module.css`) ว่า**ไม่มี Selector เปลือย (`:root`, `body`, `html`)** ที่ผิดกฎ CSS Modules ของ Next.js
2. เพิ่มเทสต์ตรวจสอบฟีเจอร์ใหม่ของ Sprint 4:
   - ตรวจสอบปุ่มสลับโหมดเวรดึก (`nightShift` / `โหมดเวรดึก`) ใน `StaffDashboard.tsx`
   - ตรวจสอบการแสดงผลสรุป `SBAR` ใน `StaffDashboard.tsx`
   - ตรวจสอบการคำนวณ/แสดงผล `NEWS2` ใน `MonitorPanel.tsx`

### งานที่ 2: ตรวจสอบและรันชุดทดสอบรวม (`scripts/test_all.sh` + Next.js Production Builds)
1. รัน `./scripts/test_all.sh` เพื่อตรวจทั้ง Backend Unittests (169 ข้อ), Frontend Contract Tests, TypeScript (`tsc --noEmit`) และ ESLint
2. รัน `npm --prefix frontend run build` และ `npm --prefix frontend run build:patient` เพื่อยืนยันว่าการบิลด์ทั้งฝั่งบุคลากรและฝั่งผู้ป่วยผ่าน 100%

## เกณฑ์งานเสร็จ (Definition of Done)
- ชุดทดสอบทั้งหมดใน `./scripts/test_all.sh` ผ่าน 100% (0 failed)
- Production Build ทั้ง 2 พอร์ทัล (`build` & `build:patient`) สำเร็จโดยไม่มี Error

## รูปแบบรายงานผลกลับให้ Argon
- **ทำอะไรเสร็จ**: (ระบุจำนวนเทสต์ที่เพิ่มและผลการรัน)
- **ติดปัญหาอะไร**: (ถ้ามี)
- **ต้องการอะไรจาก Role อื่น**: (ถ้ามี)
