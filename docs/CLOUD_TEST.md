# Private Cloud TEST — ยังไม่ใช่ระบบรักษาพยาบาลจริง

ชุดนี้เตรียมไว้สำหรับเซิร์ฟเวอร์หนึ่งเครื่อง มีเว็บบุคลากรและคนไข้คนละ hostname,
HTTPS ผ่าน Caddy, API แยกสิทธิ์, SQLite แบบ persistent, TEST simulation,
Web Push และสำรองข้อมูลรายวัน ไม่ต้องเปิด Mac ค้างเมื่อย้ายขึ้นเซิร์ฟเวอร์สำเร็จ

**สถานะ:** ยังไม่ได้ provision เซิร์ฟเวอร์หรือทดสอบ Docker image/HTTPS/Push
บนมือถือจริง เครื่องพัฒนานี้ไม่มี Docker จึงยังรับรองการ Deploy สำเร็จไม่ได้
ไม่มีการสมัครบริการ เปิด billing หรือส่งข้อความจริงจากการเตรียมชุดนี้
ราคา/โควตาของ host และ domain ต้องตรวจสอบก่อนเลือกใช้ ไม่มีการรับประกันฟรี 24/7

## เตรียมก่อน Deploy

ต้องมี Linux host พร้อม Docker Compose, สอง DNS hostnames ชี้ IP เครื่องเดียวกัน,
พอร์ต 80/443 ที่เข้าถึงได้ และอีเมลติดต่อจริง ใช้เฉพาะข้อมูลจำลอง

จาก project root บนเครื่องพัฒนา (แทน hostname/email ด้วยค่าของคุณ):

```bash
source .venv/bin/activate
python scripts/prepare_cloud_test.py --staff-host staff.example.org --patient-host patient.example.org --email you@example.org
python scripts/deployment_preflight.py --profile private-test --cloud-dir deploy
```

สคริปต์คัดลอกเฉพาะ dataset/model ที่เตรียมไว้แล้ว สร้าง `deploy/.env`,
VAPID private key และรหัสผ่านสุ่ม ไม่อ่าน/อัปโหลดฐานข้อมูลผู้ป่วย
ถ้าไฟล์เดิมมีอยู่จะไม่ทับ ตรวจ preflight ให้ผ่านก่อนดำเนินต่อ
เก็บไฟล์ลับเป็นความลับ ไม่ส่งใน Git/ภาพหน้าจอ

คัดลอก source พร้อม `deploy/artifacts`, `.env` และ `secrets` ไป host ด้วยช่องทางปลอดภัย
ไม่คัดลอกฐานข้อมูลเดิมหรือ `backend/.env` ที่มี Gemini key
ตรวจว่าบน host ผู้ใช้ container UID 10001 อ่าน private key ได้
ตัวอย่างตั้งเจ้าของเฉพาะไฟล์บน host:

```bash
sudo chown 10001:10001 deploy/secrets/webpush-private.pem
sudo chmod 600 deploy/secrets/webpush-private.pem
docker compose --env-file deploy/.env -f deploy/compose.yml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yml ps
```

`config --quiet` ป้องกันการพิมพ์ค่าลับออก terminal หาก build/readiness ไม่ผ่าน
ตรวจ log โดยไม่เผยแพร่รหัสผ่าน ชุดนี้ใช้ API worker เดียวต่อฝั่ง ห้ามเพิ่ม replicas
SQLite volume ต้องไม่ถูกลบ และห้ามใช้ `down -v` ถ้ายังต้องเก็บข้อมูล

## ตรวจรับก่อนทดลองใช้

1. เปิด HTTPS ทั้งสอง hostname แล้ว login `test_d` / `test_p` ด้วยรหัสสุ่มจาก `.env`
   รหัส `admin1234` / `admin4321` ต้องใช้ไม่ได้ และต้องไม่มีปุ่มเติมรหัส demo อัตโนมัติ
2. หมอเห็นเฉพาะ TEST_P; patient API ต้องไม่อ่านข้อมูลคนอื่นได้
3. ตรวจค่า TEST_SIMULATION เดินต่อเนื่องและเวลาอัปเดตสด รอข้อมูลต่อเนื่องประมาณ
   60–70 วินาทีจึงตรวจผล ML; ค่าจำลองไม่ใช่หลักฐานความแม่นยำทางคลินิก
4. ส่งแชทไปกลับ ทดสอบเน็ตขาด/เชื่อมใหม่และกด retry ต้องไม่เกิดข้อความซ้ำ
5. บน iPhone เปิดด้วย Safari → เพิ่มไปยังหน้าจอโฮม → เปิดจากไอคอน → login →
   อนุญาตแจ้งเตือน → กดทดสอบ ตรวจว่ามือถือได้รับจริงทั้งขณะเปิดและปิดหน้าจอ
6. Logout/ปิดบัญชีแล้วตรวจว่าการแจ้งเตือนใหม่หยุดส่ง Provider accepted
   ไม่เท่ากับมือถือได้รับหรือบุคลากรรับทราบ การแจ้งเตือนไม่ทดแทนระบบฉุกเฉิน
7. Restart host แล้วตรวจบริการ/แชท/ข้อมูลยังอยู่ รวมถึงตรวจ backup และลอง restore
   ลงฐานข้อมูลใหม่ก่อนถือว่าผ่าน ระบบไม่ได้รับประกัน uptime 24/7

## สำรองและกู้คืน

บริการ `backup` ใช้ SQLite backup API รวมข้อมูล WAL ที่ commit แล้ว ตรวจ checksum
และ integrity เก็บสำเนาที่สร้างโดยบริการนี้ล่าสุด 7 ชุดใน volume `ward-backups`
ไม่ลบไฟล์อื่น และไม่ทับฐานข้อมูลขณะ restore สำเนาบน host เดียวไม่ป้องกัน host สูญหาย
ควรคัดลอกสำเนาออกไปพื้นที่ปลอดภัยอีกแห่งก่อน pilot

ตัวอย่างกู้คืนหลังคัดลอกไฟล์ `.sqlite3` และ `.json` คู่กันออกจาก backup volume:

```bash
python deploy/backup.py restore /safe/backups/ward-YYYYMMDDTHHMMSSZ-xxxxxxxx.sqlite3 --destination /safe/ward-restored.db
```

ตรวจข้อมูลในไฟล์ใหม่ก่อนสลับฐานข้อมูล และหยุด API ทั้งสองฝั่งก่อนเปลี่ยน DB path
การสำรอง/restore ไม่ใช่การอนุญาตให้นำข้อมูลคนไข้จริงขึ้นคลาวด์
