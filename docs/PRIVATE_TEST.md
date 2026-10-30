# Private TEST บน Mac และ iPhone

ใช้เว็บสองฝั่งและ PWA บน iPhone โดย Mac เป็นเซิร์ฟเวอร์ ต้องเปิดเครื่องและอินเทอร์เน็ตค้างไว้ ข้อมูลและ Simulation เป็น TEST เท่านั้น ยังไม่ต้องเปลี่ยนฐานข้อมูลหรือเชื่อมเซนเซอร์จริง

## 1. เชื่อมอุปกรณ์ส่วนตัว

ติดตั้ง [Tailscale](https://tailscale.com/download) บน Mac และ iPhone เข้า tailnet เดียวกัน เปิด VPN บน iPhone หาก tailnet มีผู้อื่น ให้จำกัด access policy ให้เฉพาะผู้ทดสอบบนพอร์ต 443/8443

บน Mac เปิด CLI ได้ด้วย `tailscale` หากไม่อยู่ใน PATH ให้ใช้ `/Applications/Tailscale.app/Contents/MacOS/Tailscale` แทนทุกคำสั่ง tailscale ด้านล่าง

## 2. เตรียมและเปิดระบบ

```bash
cd /Users/thuwanon/ai-patient-monitor
source .venv/bin/activate
python scripts/prepare_private_test.py
python scripts/run_ward.py --stop
npm --prefix frontend run build
npm --prefix frontend run build:patient
python scripts/run_ward.py --production --env-file backend/runtime/private-test.env
```

สคริปต์หา DNS name จาก Tailscale และถามอีเมลผู้ดูแลเพื่อใช้กับ Web Push เก็บ config และ VAPID key ใน runtime ที่ไม่เข้า Git หากไฟล์ config มีอยู่แล้วจะเก็บเดิม ไม่เขียนทับ เปิดดู URL ได้จากข้อความผลลัพธ์ ไม่ต้องซื้อโดเมน

ใช้ฐานข้อมูลใหม่ `backend/runtime/ward-private-test.db` เพื่อแยกการทดลองมือถือจากข้อมูล local เดิม ปิด ID-only login แต่ยังมีบัญชีรหัสผ่าน `test_d / admin1234` และ `test_p / admin4321` รวมถึง Simulation เดิม ใช้ HTTPS ในโหมดนี้เพราะ cookie เป็น Secure

## 3. เปิด HTTPS ภายใน tailnet

เปิด Terminal อีกหน้าต่าง ตรวจ `tailscale serve status` ก่อน หากพอร์ตมีงานอื่นอยู่ อย่าเขียนทับ:

```bash
tailscale serve status
tailscale serve --bg --https=443 http://127.0.0.1:3000
tailscale serve --bg --https=8443 http://127.0.0.1:3001
```

หาก Tailscale แสดงลิงก์ให้เปิด HTTPS ให้เปิดและยืนยันในบัญชีของตนเอง ใช้ **Serve** เท่านั้น ไม่ใช้ Funnel ซึ่งเปิดสาธารณะ URL ของหมอเป็น `https://ชื่อ-mac.tailxxx.ts.net` ผู้ป่วยเป็น URL เดียวกันตามด้วย `:8443` ไม่ต้องเปิดพอร์ต router

## 4. ติดตั้งเป็นแอปและทดสอบ Push

1. iPhone ใช้ iOS 16.4 ขึ้นไป เปิด URL ผู้ป่วยใน Safari ผ่าน Tailscale
2. แชร์ → เพิ่มไปยังหน้าจอโฮม → เปิดจากไอคอน Smart Ward → เข้าด้วย test_p
3. แชททีมดูแล → แจ้งเตือนบนมือถือ / ขณะปิดแอป → ผูกอุปกรณ์ → อนุญาต
4. กดส่งทดสอบ ตรวจว่าโทรศัพท์แสดงแจ้งเตือนจริง ประวัติ ACCEPTED หมายถึง provider รับคำขอ ยังไม่ใช่หลักฐานว่าเครื่องแสดงแล้ว
5. กลับหน้าหลักหรือล็อกจอ จาก Mac เปิด URL บุคลากร เข้าด้วย test_d ส่งแชทถึง TEST_P ต้องเห็นข้อความแจ้งเตือนและแตะกลับเข้าห้องแชทได้
6. ทดสอบกลับทางโดยติดตั้ง URL บุคลากรเป็นไอคอนอีกอัน ผูกอุปกรณ์และส่งข้อความจากผู้ป่วย
7. รอ Simulation ถึงช่วงออกซิเจนลด (ประมาณ 145 วินาทีหลังเริ่ม backend วนทุก 4 นาที) จะมี Push ที่ระบุว่าเป็นเหตุการณ์จำลองไปยังบัญชี TEST ที่ผูกอุปกรณ์
8. ออกจากระบบ แล้วส่งอีกข้อความ: session ที่ออกจากระบบต้องไม่รับ Push เข้าระบบใหม่แล้วผูกอุปกรณ์อีกครั้ง (session 8 ชั่วโมง)

ระบบจำกัดประมาณหนึ่ง Push ต่อเครื่องต่อนาที ข้อความที่อ่านแล้วก่อนส่งจะยกเลิก คิวที่เก่าเกิน 5 นาทีจะหมดอายุ ไม่แสดงเนื้อหาแชทหรือข้อมูลผู้ป่วยบนหน้าจอล็อก

## หยุดและแก้ปัญหา

```bash
python scripts/run_ward.py --stop
tailscale serve --https=443 off
tailscale serve --https=8443 off
```

- เข้าหน้าไม่ได้: เปิด Tailscale ทั้งสองเครื่อง ตรวจ Serve และ Mac ไม่หลับ
- อนุญาต Push ไม่ได้: เปิดจากไอคอน Home Screen ใช้ HTTPS และตรวจสิทธิ์ Notification ของแอป
- ส่งไม่ถึง: ตรวจสถานะในกล่องแจ้งเตือน ต้อง READY และผูกกับ session ปัจจุบัน ตรวจ Focus/อินเทอร์เน็ต และรอ throttle 60 วินาที
- กลับทดสอบ local: หยุด private stack แล้ว `python scripts/run_ward.py` โดยไม่ใช้ `--env-file`

อ้างอิง: [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve), [Web Push บน iOS](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)
