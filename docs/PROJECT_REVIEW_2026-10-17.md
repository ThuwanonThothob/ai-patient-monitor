# รายงานตรวจ Smart Ward — 17 ตุลาคม 2569

## สรุป

โครงการมีมากกว่า dashboard: มีการรับ/เล่นซ้ำข้อมูล, inference ด้วยโมเดล,
bounded agent workflow, การติดตามงานบุคลากร, แชท, รายงาน และ Web Push infrastructure
เหมาะสำหรับสาธิตและทดสอบด้วยข้อมูล TEST ยังไม่ควรเรียกว่าพร้อมใช้ดูแลผู้ป่วยจริง

ตรวจครั้งนี้เป็นการอ่านโค้ด/เอกสาร รัน regression tests และตรวจ HTTP บน localhost
ไม่ได้แก้ logic ระบบ ไม่ได้ส่ง Push จริง ไม่ได้ Deploy หรือทำ penetration test เต็มรูปแบบ

## ผลตรวจที่รันจริงรอบนี้

| รายการ | ผล |
| --- | --- |
| Backend unittest | 145 ผ่าน |
| Frontend node tests | 24 ผ่าน |
| Launcher/backup/cloud helper tests | 19 ผ่าน |
| รวม automated tests | 188 ผ่าน |
| Frontend ESLint | ผ่าน |
| `git diff --check` | ผ่าน |
| Launcher status | RUNNING |
| API 8000/8001 `/health` | HTTP 200, audience ถูกต้อง |
| เว็บ 3000/3001 `/api/session/config` | HTTP 200, proxy ไปถูกฝั่ง |

Production build ทั้งสองฝั่งผ่านในรอบพัฒนาก่อนหน้า ไม่ได้หยุดระบบเพื่อ build ซ้ำครั้งนี้
ข้อความ `Monitor worker failed: ValueError` ระหว่างชุดทดสอบเป็นกรณีจำลองความล้มเหลว
ชุดทดสอบจบด้วย OK; พบคำเตือน deprecation ของ FastAPI/Starlette TestClient กับ httpx
ควรวางแผนอัปเดต test dependencies ภายหลัง ไม่ใช่หลักฐานว่า runtime ล่ม

## สิ่งที่มีแล้ว

- 60 เตียงสาธิตและคู่บัญชี TEST แยกสิทธิ์; staff และ patient แยกเว็บ/API
- กราฟล่าสุด/ย้อนหลังครบ HR, SpO₂, RR พร้อมตารางและระบุแหล่งข้อมูล
- ตรวจข้อมูลเก่า/ผิดรูปแบบ ไม่แสดงความมั่นใจจากข้อมูลขาด
- Random Forest forecast, persistence baseline, Isolation Forest และหลักฐานผลทดลอง
- Agent เบื้องหลังมีบทบาท/trace; ผู้ช่วยไอคอนเรียกเครื่องมืออ่านข้อมูลตามกฎ
- แผนดูแลที่ผ่านการตรวจทาน งานติดตาม ข้อความและแชท สรุป/ส่งออกเอกสาร
- Device Health, pressure-mat workflow และ Ground Truth ในขอบเขตงานวิจัย
- คิว Push พร้อม retry/deduplication และตรวจสิทธิ์ผู้รับ
- ชุด Docker/HTTPS/backup สำหรับเตรียม Cloud TEST

## ประเด็นที่ต้องทำก่อนใช้งานต่อเนื่องจริง

1. **Push ยังผูกกับเซสชัน 8 ชั่วโมง:** ตรวจจาก `auth.py` และ query session expiry
   ใน `notifications.py` ต้องออกแบบอายุการสมัครอุปกรณ์/การต่ออายุอย่างปลอดภัย
   และทดสอบ logout/revoke/offline ก่อนอ้างการรับแจ้งเตือน 24 ชั่วโมง
2. **ความแม่นยำยังไม่ใช่ clinical validation:** README ระบุ Random Forest
   ไม่ชนะ persistence บน held-out test; BIDMC และโปรไฟล์สมมติไม่พิสูจน์ผลในผู้สูงอายุ
   ติดเตียงที่บ้าน ต้องมีข้อมูลกลุ่มเป้าหมายพร้อม Ground Truth และ external validation
3. **การยกเลิกบัญชีใน demo mode:** `auth.identity()` ปฏิเสธบัญชีที่ disabled
   แต่ถ้าลบแถวบัญชีออกขณะยังเปิด demo login เซสชันเดิมอาจยังผ่าน identity check
   เป็นข้อค้นพบจากโค้ด ไม่ได้ทดลองลบบัญชีจริง; ควรผูกชนิดบัญชี/เพิกถอนเซสชันเมื่อ delete
   และปิด ID-only demo login ก่อนนำออกนอกเครื่องทดสอบ
4. **Agentic ใหม่มีขอบเขตจำกัด:** เป็น deterministic read-only tool routing
   ไม่ใช่ LLM วางแผนอิสระ; ไม่มีการทำงานแทนมนุษย์ทุกชนิดและไม่เรียนรู้เองจากแชท
5. **ยังไม่ตรวจการติดตั้งปลายทาง:** Docker image/host, HTTPS, notification บนมือถือจริง,
   เซนเซอร์จริง และการ restore หลัง host ล้มเหลว ต้องมี acceptance test แยก
6. **เอกสารเก่าบางส่วนไม่ตรงรุ่นล่าสุด:** WEB_PUSH.md ยังเรียกช่องทางนี้ว่าเฉพาะบุคลากร
   แต่โค้ดปัจจุบันรองรับ patient chat/TEST notifications ด้วย; ใช้คู่มือรวมใหม่ประกอบ

## ลำดับแนะนำ

1. ตรวจรับ flow TEST สองฝั่งตามคู่มือ รวมเน็ตขาด/เซสชันหมดอายุ/สิทธิ์ข้ามคน
2. แก้ session lifecycle และจัดการบัญชีให้ครบก่อนออกอินเทอร์เน็ต
3. ทดสอบ Cloud ด้วยข้อมูลจำลอง: HTTPS, restart, backup/restore, Push บนอุปกรณ์จริง
4. เก็บผลการทดสอบระยะยาว เช่น latency, data gaps, ส่งซ้ำ, ส่งไม่ถึง และเวลาที่คนรับงาน
5. ก่อน pilot คนไข้จริง จัดระบบความยินยอม สิทธิ์ผู้ใช้ การตรวจสอบทางคลินิก
   ความปลอดภัย/ความเป็นส่วนตัว และช่องทางสำรองเมื่อระบบใช้งานไม่ได้

จำนวน tests ผ่านเป็นหลักฐาน regression ของซอฟต์แวร์ ไม่ใช่คะแนนความปลอดภัยทางการแพทย์

## อัปเดตการพัฒนาเพิ่มเติม (19 ตุลาคม 2569 — แผน P1–P4)

- **P1 (Security & Session Lifecycle):**
  - เพิ่มคอลัมน์ `auth_mode` (`'account'` / `'demo'`) ใน `portal_sessions` เพื่อให้เซสชันที่ล็อกอินด้วยบัญชีจริงถูกเพิกถอนทันทีเมื่อบัญชีถูกลบหรือปิดใช้งาน แม้จะยังเปิด `WARD_DEMO_ID_LOGIN=1` อยู่
  - เพิ่ม **Sliding Session Renewal** ใน `auth.identity()` ต่ออายุเซสชันอัตโนมัติเมื่อมีการใช้งานและเหลือเวลาน้อยกว่า `TTL / 2` ช่วยให้เวรเฝ้าระวังต่อเนื่องไม่หลุดกลางคัน
  - เพิ่มฟังก์ชัน `auth.disable_account()` และ `auth.delete_account()` พร้อม CLI `scripts/manage_account.py --disable / --delete` ที่เพิกถอนเซสชัน ปิด `push_subscriptions` และยกเลิก `push_outbox` ใน transaction เดียว
- **P2 (Clinician-Grade Staff UX):**
  - เพิ่มเสียงเตือนสัญญาณชีพวิกฤต (`🔊 เสียงเตือนวิกฤต`, Web Audio API) พร้อมปุ่มเปิด/ปิดและระบบป้องกันเสียงรบกวนซ้ำถี่เกินไป
  - เพิ่มตัวกรองด่วนในหน้าภาพรวม (`ทั้งหมด`, `เร่งด่วน`, `เฝ้าระวัง`) และปุ่มลัดคีย์บอร์ด `/` เพื่อกระโดดไปค้นหาผู้ป่วยทันที
- **P3 (Patient-Friendly & Accessible UX):**
  - เพิ่มปุ่มสลับขนาดตัวอักษรใหญ่ (`ก+ ตัวอักษรใหญ่`) สำหรับผู้ป่วยและผู้สูงอายุ
  - เพิ่มการ์ดคำอธิบายค่าสัญญาณชีพเบื้องต้น (HR, SpO₂, RR) ด้วยภาษาที่เข้าใจง่ายและลดความกังวล
  - เพิ่มปุ่มข้อความด่วน (1-Tap Quick Care Chips) ในหน้าแจ้งเรื่องและหน้าแชทของฝั่งผู้ป่วย
- **P4 (Documentation & Regression Tests):**
  - ปรับปรุงเอกสาร `docs/WEB_PUSH.md` และเพิ่มชุดทดสอบอัตโนมัติสำหรับตรวจสอบการเพิกถอนเซสชันเมื่อลบ/ปิดบัญชี และการต่ออายุเซสชันอัตโนมัติ
