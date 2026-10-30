# แผน Deploy เป็น Web และ Application

สถานะปัจจุบันเหมาะกับ **local research demo / controlled pilot** เท่านั้น ยังไม่ใช่ระบบการแพทย์ที่ผ่านการรับรอง

สำหรับรอบทดสอบส่วนตัวด้วยบัญชี TEST ให้ใช้ [PRIVATE_TEST.md](PRIVATE_TEST.md) ซึ่งคง Simulation และใช้ Tailscale Serve + HTTPS โดยไม่เปิดเว็บสาธารณะ ข้อกำหนด production ด้านล่างยังไม่ใช่ข้อบังคับของ private TEST

## รูปแบบที่แนะนำ

1. Deploy เว็บสอง hostname แยกกัน เช่น `staff.example.org` และ `patient.example.org`
2. ใช้ FastAPI หลัง reverse proxy HTTPS และให้ API อยู่ same-origin กับแต่ละ portal
3. เริ่ม Application แบบ **PWA** ก่อน หน้าเว็บมี manifest, icon และ standalone mode แล้ว ผู้ใช้เพิ่มไว้ที่หน้าจอโฮมได้
4. ทำ Native app ภายหลังเมื่อเปลี่ยน authentication เป็น OIDC/OAuth2 + short-lived token และออกแบบ secure device storage แล้ว ไม่ควรฝัง cookie หรือรหัส TEST ในแอป

## ต้องปิดก่อนเปิดอินเทอร์เน็ต

```env
WARD_DEMO_ID_LOGIN=0
WARD_ENABLE_TEST_ACCOUNTS=0
WARD_COOKIE_SECURE=1
WARD_INGEST_MODE=mqtt
WARD_STAFF_ORIGIN=https://staff.example.org
WARD_PATIENT_ORIGIN=https://patient.example.org
```

ตรวจด้วย:

```bash
.venv/bin/python scripts/deployment_preflight.py
```

คำสั่งนี้ตั้งใจให้ local demo ขึ้น `BLOCKED` เพราะ local ยังเปิดบัญชี TEST และ replay อยู่

## สิ่งที่ต้องเปลี่ยนก่อน production

- เปลี่ยน SQLite เป็น PostgreSQL พร้อม migration, backup, restore drill และ encryption at rest
- ใช้บัญชีรายบุคคลผ่าน Identity Provider, MFA, role/assignment-based authorization และ account recovery
- เก็บ secret ใน secret manager ไม่ใส่ `.env` ใน image/repository
- เปิด Web Push ด้วย VAPID key และ HTTPS แล้วทดสอบบน iOS/Android จริง
- เพิ่ม retention policy, consent, audit export, incident response, uptime/device-health monitoring
- แยกข้อมูล TEST/SIMULATION ออกจากข้อมูลอุปกรณ์จริงที่ฐานข้อมูลและ analytics
- ทดสอบโหลด WebSocket/MQTT, reconnect, duplicate event, offline device และ notification failure
- ผ่าน clinical validation และกระบวนการกำกับดูแลก่อนใช้ตัดสินใจดูแลจริง

## ขอบเขตการแจ้งเตือนปัจจุบัน

- Alert บุคลากรรองรับ Web Push เมื่อเซิร์ฟเวอร์ตั้งค่า VAPID แล้ว
- แชทมี unread count และ Web Push ทั้งบุคลากรและผู้ป่วย รวมถึงขณะปิดหน้าเว็บเมื่ออุปกรณ์รองรับและผูกอุปกรณ์แล้ว
- Simulation ส่ง Push เฉพาะสองบัญชี TEST โดยระบุว่าเป็นข้อมูลจำลอง ไม่แสดงรายละเอียดผู้ป่วยบน lock screen
- ทุกช่องทางเป็นช่องทางเสริม ไม่ใช่การรับประกันการตอบสนองฉุกเฉิน

## ลำดับ Deploy ที่ปลอดภัยกว่า

1. Staging ด้วยข้อมูลสังเคราะห์ทั้งหมด
2. ทดสอบ PWA/Push บนอุปกรณ์จริง
3. Controlled pilot แบบไม่ใช้ผล AI ตัดสินใจรักษา
4. เก็บ ground truth และประเมิน false alert/missed event
5. Security/privacy/clinical review
6. จึงพิจารณา production rollout แบบจำกัดกลุ่มและมี rollback
