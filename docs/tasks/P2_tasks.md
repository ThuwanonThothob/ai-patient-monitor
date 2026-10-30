# ข้อความสั่งงาน P2 — UX/UI Design (Core Design System, Login Shell, Night Shift Mode & Main Workspaces)

คุณคือ P2 (UX/UI — Core Design System & Main Workspaces) ได้รับมอบหมายจาก Argon (Orchestrator / Tech Lead) ของโปรเจกต์ `ai-patient-monitor`

## บริบทโปรเจกต์และภารกิจ Sprint 4
เรากำลังทำ **Sprint 4: Full Frontend Overhaul** เพื่อยกระดับหน้าจอหลักทั้งฝั่งบุคลากร (`StaffDashboard.tsx`) ฝั่งผู้ป่วย (`PatientPortal.tsx`) และหน้าเข้าสู่ระบบ (`PortalShell.tsx`) ให้เป็นระบบ **Formal-Minimalist Clinical Design System** เต็มรูปแบบ มีความนุ่มนวล (Smooth Transitions), อ่านค่าวิกฤตได้ภายใน 3 วินาที, รองรับโหมดเวรดึก (`Night Shift Mode Toggle`), มีสรุปส่งต่อแพทย์แบบ `SBAR` ในหน้าเวชระเบียนผู้ป่วย และรวบข้อมูลรองไว้ในลิ้นชัก `Learn More` (`learnMoreDrawer`)

## ขอบเขตไฟล์ที่คุณรับผิดชอบเท่านั้น (ห้ามแก้ไฟล์ของ Role อื่นเด็ดขาด)
- `frontend/app/globals.css`
- `frontend/app/PortalShell.tsx`
- `frontend/app/AccountProfile.tsx`
- `frontend/app/Brand.tsx`
- `frontend/app/StaffDashboard.tsx`
- `frontend/app/Ward.module.css`
- `frontend/app/PatientPortal.tsx`
- `frontend/app/PatientPortal.module.css`
- `frontend/app/PatientSections.tsx`

## รายละเอียดงานที่ต้องทำ

### งานที่ 1: ปรับโฉมหน้า Login Shell, แถบเซสชันด้านบน และจัดการบัญชี (`PortalShell.tsx`, `AccountProfile.tsx`, `Brand.tsx`, `globals.css`)
1. ใน `PortalShell.tsx` และ `globals.css`:
   - ปรับโฉมหน้าเข้าสู่ระบบ (`.portal-login`, `.login-story`, `.portal-card`) ให้ดูเป็นระบบการแพทย์ระดับสากล มีรายการสรุปจุดเด่น 3 ข้อด้านซ้าย และการ์ดกรอกบัญชีทดสอบ (`บัญชี TEST สำหรับสาธิต`) ที่กดปุ่ม `กรอกบัญชีทดสอบ` ได้ในคลิกเดียว
   - ปรับแถบด้านบนหลังล็อกอิน (`.portal-session`) ให้ใช้ `backdrop-filter: blur(14px)` ดูสะอาดตา แสดงสถานะบทบาท ชื่อบัญชี ปุ่มจัดการบัญชี (`AccountProfile.tsx`) และปุ่มออกจากระบบอย่างชัดเจน
   - คง `--ease-smooth: cubic-bezier(0.22, 1, 0.36, 1)` ใน `globals.css`

### งานที่ 2: เพิ่มปุ่มโหมดเวรดึก (`Night Shift Mode`) และสรุปส่งต่อ `SBAR` ใน `StaffDashboard.tsx` & `Ward.module.css`
1. **ปุ่มสลับโหมดเวรดึก (`🌙 โหมดเวรดึก` / `☀️ โหมดปกติ`)**:
   - เพิ่ม State `nightShift` ใน `StaffDashboard.tsx` (บันทึกค่าใน `localStorage`) และผูกคลาส `styles.nightShift` เข้ากับ `<div className={`${styles.app} ${nightShift ? styles.nightShift : ""}`}>`
   - เพิ่มปุ่มสลับโหมดเวรดึกบน `.headerActions` เพื่อให้พยาบาลเวรดึกกดเปลี่ยนโทนสีถนอมสายตาได้ทันที
2. **สรุปส่งต่อแพทย์ตามมาตรฐาน `SBAR` ใน `PatientModal` (`StaffDashboard.tsx`)**:
   - ในหน้าต่างเวชระเบียนผู้ป่วย (`PatientModal` แท็บ `summary`) เพิ่มกล่องสรุปย่อ **SBAR Quick Summary** (*S: สถานการณ์ปัจจุบัน, B: ประวัติ/โรคประจำตัว, A: ผลประเมินสัญญาณชีพและ AI, R: ข้อเสนอแนะการติดตาม*) พร้อมปุ่ม `📋 คัดลอก SBAR` ลง Clipboard ในคลิกเดียว
3. **กฎเหล็ก CSS Module**:
   - ใน `Ward.module.css` ห้ามใช้ Selector เปลือย (`:root`, `body`, `dialog`, `button`) โดยไม่มี Local Class นำหน้าเด็ดขาด และต้องคง `--status-critical-bg: #fff0f2` และ `--status-critical-bg: #2d0e12` ไว้ครบถ้วน

### งานที่ 3: ยกระดับหน้าผู้ป่วย (`PatientPortal.tsx`, `PatientPortal.module.css`, `PatientSections.tsx`)
1. จัดระเบียบการ์ดสัญญาณชีพ แถบทางลัดด่วน ตารางงานดูแล และลิ้นชัก `Learn More` (`คำอธิบายค่าสัญญาณชีพเบื้องต้น`) ให้สะอาดตา อ่านง่าย และสร้างความอุ่นใจให้ผู้ป่วย
2. ใน `PatientSections.tsx` คงคำแนะนำ `คำแนะนำการใช้รายงานสรุปประจำวัน`, `ต้องการแจ้งแก้ไขประวัติแพ้ยาหรือรายการยา` และคู่มือเช็กอุปกรณ์ด้วยตนเอง 4 ข้อในลิ้นชัก `learnMoreDrawer`

## เกณฑ์งานเสร็จ (Definition of Done)
- รัน `PATH="/opt/homebrew/bin:$PATH" npm --prefix frontend test` ผ่านครบทุกข้อ
- รัน `PATH="/opt/homebrew/bin:$PATH" npm --prefix frontend run build` และ `npm --prefix frontend run build:patient` ผ่าน 0 errors

## รูปแบบรายงานผลกลับให้ Argon
- **ทำอะไรเสร็จ**: (ระบุไฟล์และสิ่งที่ปรับปรุง)
- **ติดปัญหาอะไร**: (ถ้ามี)
- **ต้องการอะไรจาก Role อื่น**: (ถ้ามี)
