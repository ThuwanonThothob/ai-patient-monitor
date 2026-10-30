# ข้อความสั่งงาน P1 — Development (Frontend Workflow, Care Plan, Chat & Notifications Overhaul)

คุณคือ P1 (Development — Frontend Workflow & Care Modules) ได้รับมอบหมายจาก Argon (Orchestrator / Tech Lead) ของโปรเจกต์ `ai-patient-monitor`

## บริบทโปรเจกต์และภารกิจ Sprint 4
ระบบ Backend และการทำงานหลักของโปรเจกต์เสร็จสมบูรณ์แล้ว ตอนนี้ทีมกำลังทำ **Sprint 4: Full Frontend Overhaul** เพื่อปรับปรุงหน้าตาและการจัดวางของคอมโพเนนต์ฝั่งการปฏิบัติงานพยาบาล แผนดูแลผู้ป่วย แชท และระบบแจ้งเตือนมือถือ ให้ดูเป็นทางการผสมมินิมอลทางการแพทย์ (Formal-Minimalist Clinical UI) ใช้งานง่าย ไม่ซับซ้อน และใช้ลิ้นชัก `Learn More` (`learnMoreDrawer`) รวบข้อมูลรองอย่างเป็นระเบียบ

## ขอบเขตไฟล์ที่คุณรับผิดชอบเท่านั้น (ห้ามแก้ไฟล์ของ Role อื่นเด็ดขาด)
- `frontend/app/AlertWorkflow.tsx`
- `frontend/app/OperationsPanel.tsx`
- `frontend/app/CarePanel.tsx`
- `frontend/app/CareProfilePanel.tsx`
- `frontend/app/DailySummaryPanel.tsx`
- `frontend/app/CareChat.tsx`
- `frontend/app/CareChat.module.css`
- `frontend/app/CareMessages.tsx`
- `frontend/app/NotificationPanel.tsx`

*(ห้ามแก้ไข `StaffDashboard.tsx`, `Ward.module.css`, `PatientPortal.tsx`, `MonitorPanel.tsx`, หรือไฟล์ใน `frontend/tests/`)*

## รายละเอียดงานที่ต้องทำ

### งานที่ 1: ปรับโฉมหน้าจัดการแจ้งเตือนและส่งต่อเวร (`AlertWorkflow.tsx` & `OperationsPanel.tsx`)
1. ใน `AlertWorkflow.tsx`:
   - จัดระเบียบการ์ดแจ้งเตือนแต่ละรายการให้แยกส่วนชัดเจน: (1) หัวการ์ดแสดงรหัสผู้ป่วย โซน ห้อง และป้ายสถานะ, (2) ค่าสัญญาณชีพและเหตุผลการเตือน, (3) แถบปุ่มบันทึกด่วน (`QUICK_CLINICAL_NOTES`) และกล่องข้อความบันทึกผล, (4) ปุ่มดำเนินการตามลำดับ (`รับผิดชอบงานนี้` → `บันทึกส่งต่อประเมิน` → `บันทึกผลและปิดงาน`)
2. ใน `OperationsPanel.tsx`:
   - จัดวางปุ่มด่วน 3 รายการแรก (`เหตุการณ์รอรับผิดชอบ`, `ข้อความแจ้งเรื่องใหม่`, `แชทแพทย์-ผู้ป่วยยังไม่อ่าน`) ให้โดดเด่นอ่านง่ายใน 3 วินาที
   - คงข้อความ `Shift Handoff Reminder` และเช็กลิสต์ส่งต่อเวร 3 ข้อพร้อมปุ่มพิมพ์ไว้ในลิ้นชัก `learnMoreDrawer` (`Learn More`)

### งานที่ 2: ปรับโฉมระบบแผนดูแล ข้อมูลการดูแล และสรุปประจำวัน (`CarePanel.tsx`, `CareProfilePanel.tsx`, `DailySummaryPanel.tsx`)
1. ใน `CarePanel.tsx`:
   - จัดระเบียบฟอร์มสร้างแผนดูแลและแถบ `แม่แบบแผนดูแลด่วน` (ต้องคงข้อความ `พลิกตัวและตรวจผิวหนังทุก 2 ชม.` ไว้ตามสัญญาเทสต์)
   - รวบคำอธิบายขั้นตอนและข้อมูลเชิงเทคนิคไว้ในลิ้นชัก `learnMoreDrawer` (`Learn More`)
2. ใน `CareProfilePanel.tsx` และ `DailySummaryPanel.tsx`:
   - จัดกลุ่มฟอร์มแก้ไขช่วงค่าอ้างอิงเฉพาะบุคคล (Personal Target Ranges) และหน้าตรวจร่างสรุปประจำวัน (Daily Summary Drafts) ให้อ่านง่าย แยกสถานะ `ฉบับร่าง (Draft)` กับ `ยืนยันแล้ว (Reviewed)` อย่างชัดเจน และซ่อนรายละเอียดประวัติเวอร์ชันเก่าไว้ใน `<details>`

### งานที่ 3: ปรับโฉมระบบแชท ข้อความผู้ป่วย และตั้งค่าแจ้งเตือนมือถือ (`CareChat.tsx`, `CareChat.module.css`, `CareMessages.tsx`, `NotificationPanel.tsx`)
1. ใน `CareChat.tsx` และ `CareChat.module.css`:
   - ปรับแต่งหน้าจอ Messenger ให้สะอาดตา ทันสมัย รองรับจอมือถือ (`@media (max-width: 768px)`, `100dvh`)
   - คงคลาส `.activeBadge` (`#31a24c`), `.bubbleMine`, `.bubbleOther`, `.composerPill`, `.quickPill` และ `aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"` รวมถึงสถานะ `อ่านแล้ว` / `ส่งแล้ว` และ**ห้ามมีคำว่า โทร / วิดีโอ / call / video เด็ดขาด**
2. ใน `CareMessages.tsx` และ `NotificationPanel.tsx`:
   - ใน `CareMessages.tsx`: จัดระเบียบรายการข้อความแจ้งเรื่องและแถบ `ข้อความด่วนสำหรับผู้ป่วย` ให้กดเลือกง่าย
   - ใน `NotificationPanel.tsx`: จัดลำดับการตั้งค่า Web Push Notification เป็น 3 ขั้นตอนที่เข้าใจง่าย พร้อมรวบตารางประวัติการส่ง (Delivery Events) ไว้ใน `<details>`

## เกณฑ์งานเสร็จ (Definition of Done)
- รัน `PATH="/opt/homebrew/bin:$PATH" npm --prefix frontend test` ผ่าน 100%
- รัน `PATH="/opt/homebrew/bin:$PATH" npm --prefix frontend run lint` และ `npx --prefix frontend tsc --noEmit` ผ่าน 0 errors

## รูปแบบรายงานผลกลับให้ Argon
- **ทำอะไรเสร็จ**: (ระบุไฟล์และสิ่งที่ปรับปรุง)
- **ติดปัญหาอะไร**: (ถ้ามี)
- **ต้องการอะไรจาก Role อื่น**: (ถ้ามี)
