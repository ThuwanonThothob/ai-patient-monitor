import time 
import json
import random
import paho.mqtt.client as mqtt

BROKER = "broker.emqx.io"
PORT = 8083
TOPIC = "my_ai_hospital/vitals"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")

print("⏳ กำลังเชื่อมต่อ MQTT...")
client.connect(BROKER, PORT, 60)
print("เชื่อมต่อสำเร็จ! เริ่มส่งข้อมูลผู้ป่วยหลายคน...")

# 🔴 กำหนดรายชื่อผู้ป่วยทั้งหมดที่ต้องการจำลอง
patients = ["A001", "A002", "A003", "A004", "A005"]

try:
    while True:
        # 🔴 วนลูปส่งข้อมูลให้ผู้ป่วยทุกคนในรายการ
        for pt_id in patients:
            hr = random.randint(60, 120)
            spo2 = random.randint(90, 100)

            payload = {
                "patient_id": pt_id,
                "heart_rate": hr,
                "spo2": spo2,
                "timestamp": time.time()
            }

            client.publish(TOPIC, json.dumps(payload))
            print(f"Send Data: {pt_id} | HR={hr}, SpO2={spo2}")
        
        # ส่งครบทุกคนแล้ว รอก่อนส่งรอบถัดไป 2 วินาที
        time.sleep(5)

except KeyboardInterrupt:
    print("\n Simulation stopped.")
finally:
    client.disconnect()
    print("Disconnected from Broker.")