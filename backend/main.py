import json
import asyncio
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List
from contextlib import asynccontextmanager

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

# ฟังก์ชันประเมินความเสี่ยงแบบ Real-time รายบุคคล
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
        
        status, alert_msg = evaluate_risk(hr, spo2)
        
        response_data = {
            "patient_id": p_id,
            "heart_rate": hr,
            "spo2": spo2,
            "status": status,
            "alert_message": alert_msg,
            "timestamp": payload.get("timestamp")
        }

        print(f" [{status}] เตียง {p_id} | HR={hr}, SpO2={spo2}% | {alert_msg}")

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
    main_loop = asyncio.get_running_loop()
    mqtt_client.connect(BROKER, PORT, 60)
    mqtt_client.subscribe(TOPIC)
    mqtt_client.loop_start()
    print("Backend พร้อมทำงานแบบ Multi-Patient (Real-time)")
    yield
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws/vitals")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)