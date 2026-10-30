# MASTER PLAN — Smart Ward (`ai-patient-monitor`)
**Orchestrator / Tech Lead**: Argon  
**อัปเดตล่าสุด**: 30 ตุลาคม 2569 (Sprint 4: Full Frontend Overhaul Plan)

---

## 1. สรุปสถานะปัจจุบัน (Project Status Summary)
- **Sprint 1–3 (Backend, AI Safety Gates, DevOps & Initial UI Cleanup)**: ✅ **เสร็จสมบูรณ์ 100%** (ผ่านการทดสอบอัตโนมัติ 204 tests: Backend 169 + Frontend 35)
- **เป้าหมายใหม่ใน Sprint 4 (Full Frontend Architecture & UX/UI Overhaul)**:
  - ยกระดับและปรับโฉม **Frontend ทั้งระบบ (ครบทั้ง 30+ คอมโพเนนต์)** ภายใต้แนวคิด **"Formal-Minimalist Clinical Design System"**
  - แบ่งความรับผิดชอบของไฟล์ใน `frontend/` ให้ทั้ง 4 Role (**P1, P2, P3, P4**) ช่วยกันทำแบบขนาน โดย **ห้ามแก้ไขไฟล์ทับซ้อนกันเด็ดขาด (Zero File Conflict)**

---

## 2. ตารางภาพรวมงาน Sprint 4 (Full Frontend Overhaul) และ Dependency

| รหัสงาน | Role | ชื่องาน (Task Name) | ไฟล์ที่รับผิดชอบ (ห้ามทับซ้อน) | ลำดับความสำคัญ | Dependency | สถานะ |
|---|---|---|---|---|---|---|
| **FE-P2** | **P2 (UX/UI Lead)** | **Core Design System, Login Shell, Night Shift Mode & Main Workspaces** | `frontend/app/globals.css`, `PortalShell.tsx`, `AccountProfile.tsx`, `Brand.tsx`, `StaffDashboard.tsx`, `Ward.module.css`, `PatientPortal.tsx`, `PatientPortal.module.css`, `PatientSections.tsx` | **High** | ต้นน้ำ (กำหนด Design Tokens & Shell) | ✅ **DONE** |
| **FE-P1** | **P1 (Frontend Workflow & Care)** | **Clinical Workflow, Care Plan, Daily Summary, Chat & Notification UI Overhaul** | `frontend/app/AlertWorkflow.tsx`, `OperationsPanel.tsx`, `CarePanel.tsx`, `CareProfilePanel.tsx`, `DailySummaryPanel.tsx`, `CareChat.tsx`, `CareChat.module.css`, `CareMessages.tsx`, `NotificationPanel.tsx` | **High** | ใช้ Tokens จาก `globals.css` / `Ward.module.css` | ✅ **DONE** |
| **FE-P3** | **P3 (Clinical AI & Sensor UI)** | **AI Vitals (NEWS2 + 30s Forecast), Bedside Pressure Mat, Charts & Evidence UI Overhaul** | `frontend/app/MonitorPanel.tsx`, `VitalCharts.tsx`, `StaffTrendPanel.tsx`, `BedsidePanel.tsx`, `PosturePanel.tsx`, `EvidencePanel.tsx`, `AgentPanel.tsx`, `ResearchPanel.tsx`, `ResearchPanel.module.css`, `ScenarioLab.tsx`, `AgentAssistant.tsx`, `AgentAssistant.module.css` | **High** | ใช้ Tokens จาก `globals.css` / `Ward.module.css` | ✅ **DONE** |
| **FE-P4** | **P4 (Frontend QA & Build Gate)** | **Frontend Contract Tests, CSS Purity Gate, Accessibility & Dual-Portal Build Verification** | `frontend/tests/ui-contract.test.mjs`, `frontend/tests/patient.test.mjs`, `frontend/tests/vitalView.test.mjs`, `scripts/test_all.sh`, `scripts/smoke_portals.py` | **High** | ตรวจสอบหลัง P1, P2, P3 ส่งมอบ | ✅ **DONE** |

---

## 3. กฎเหล็กการแบ่งไฟล์ (Strict Non-Overlapping File Ownership)
1. **P2** เป็นเจ้าของไฟล์ Shell หลัก, Global CSS, `Ward.module.css`, `StaffDashboard.tsx`, และ `PatientPortal.tsx`
2. **P1** เป็นเจ้าของคอมโพเนนต์ฝั่งการจัดการงานพยาบาล แผนดูแล สรุปประจำวัน แชท และแจ้งเตือนมือถือ
3. **P3** เป็นเจ้าของคอมโพเนนต์ฝั่งแสดงผลสัญญาณชีพ (`MonitorPanel`), กราฟ (`VitalCharts`, `StaffTrendPanel`), เซนเซอร์ข้างเตียง (`BedsidePanel`, `PosturePanel`), และหน้าพิสูจน์/วิจัย AI (`EvidencePanel`, `AgentPanel`, `ResearchPanel`, `ScenarioLab`, `AgentAssistant`)
4. **P4** เป็นเจ้าของไฟล์ทดสอบใน `frontend/tests/` และสคริปต์ตรวจสอบคุณภาพใน `scripts/`
5. **กฎ CSS Module**: ห้ามใช้ Selector เปลือย (`:root`, `body`, `dialog`, `button`) ในไฟล์ `*.module.css` โดยไม่มี Local Class นำหน้า เพื่อให้ `next build` ผ่าน 100%
