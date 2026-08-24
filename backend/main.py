import json
import sqlite3
import asyncio
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from contextlib import asynccontextmanager

# --- 1. ตั้งค่าฐานข้อมูล SQLite ---
DB_NAME = "vitals.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vital_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            heart_rate INTEGER,
            spo2 INTEGER,
            status TEXT,
            timestamp REAL
        )
    """)
    conn.commit()
    conn.close()

def save_to_db(patient_id: str, hr: int, spo2: int, status: str, ts: float):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO vital_logs (patient_id, heart_rate, spo2, status, timestamp) VALUES (?, ?, ?, ?, ?)",
        (patient_id, hr, spo2, status, ts)
    )
    conn.commit()
    conn.close()

# --- 2. WebSocket Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()
main_loop = None

def evaluate_risk(hr: int, spo2: int):
    if spo2 < 90 or hr > 120 or hr < 50:
        return "CRITICAL", "🚨 วิกฤต: ค่าสัญญาณชีพผิดปกติรุนแรง!"
    elif spo2 < 95 or hr > 100:
        return "WARNING", "⚠️ เตือน: ค่า SpO2 ต่ำหรือหัวใจเต้นเร็ว"
    return "NORMAL", "✅ สัญญาณชีพปกติ"

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        p_id = payload["patient_id"]
        hr = payload["heart_rate"]
        spo2 = payload["spo2"]
        ts = payload.get("timestamp")
        
        status, alert_msg = evaluate_risk(hr, spo2)
        
        # บันทึกลง SQLite
        save_to_db(p_id, hr, spo2, status, ts)
        
        response_data = {
            "patient_id": p_id,
            "heart_rate": hr,
            "spo2": spo2,
            "status": status,
            "alert_message": alert_msg,
            "timestamp": ts
        }

        print(f"💾 [DB SAVED] เตียง {p_id} | HR={hr}, SpO2={spo2}% | Status={status}")

        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(response_data), main_loop)
            
    except Exception as e:
        print(f"❌ Error: {e}")

BROKER = "broker.emqx.io"
PORT = 8083
TOPIC = "my_ai_hospital/vitals"

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
mqtt_client.on_message = on_message

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    init_db() # สร้าง ตารางใน DB บน startup
    main_loop = asyncio.get_running_loop()
    mqtt_client.connect(BROKER, PORT, 60)
    mqtt_client.subscribe(TOPIC)
    mqtt_client.loop_start()
    print("✅ Backend + SQLite Database พร้อมทำงาน")
    yield
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

app = FastAPI(lifespan=lifespan)

# อนุญาตให้ React ดึง API ได้
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/history/{patient_id}")
def get_patient_history(patient_id: str, limit: int = 15):
    """API สำหรับดึงประวัติย้อนหลัง N จุดไปวาดกราฟเริ่มต้น"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT heart_rate, spo2, status, timestamp FROM vital_logs WHERE patient_id = ? ORDER BY id DESC LIMIT ?",
        (patient_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # เรียงลำดับจากเก่าไปใหม่เพื่อให้เส้นกราฟวิ่งจากซ้ายไปขวา
    history = [
        {"heart_rate": r[0], "spo2": r[1], "status": r[2], "timestamp": r[3]}
        for r in reversed(rows)
    ]
    return history

@app.websocket("/ws/vitals")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)