import json
import sqlite3
import asyncio
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from contextlib import asynccontextmanager

DB_NAME = "vitals.db"

# 1. ฐานข้อมูลจำลองโปรไฟล์ผู้ป่วย (Patient Profiles)
PATIENT_PROFILES = {
    "A001": {"name": "นายสมชาย ใจดี", "age": 65, "gender": "ชาย", "condition": "โรคปอดอุดกั้นเรื้อรัง (COPD)", "doctor": "นพ. วิชัย รักษาดี"},
    "A002": {"name": "นางสมศรี มีสุข", "age": 72, "gender": "หญิง", "condition": "ภาวะหัวใจล้มเหลว (CHF)", "doctor": "นพ. วิชัย รักษาดี"},
    "A003": {"name": "นายอนันต์ รุ่งเรือง", "age": 58, "gender": "ชาย", "condition": "ความดันโลหิตสูง / เฝ้าระวังหลังผ่าตัด", "doctor": "พญ. นภา สดใส"},
    "A004": {"name": "นางสาวปราณี สดใส", "age": 45, "gender": "หญิง", "condition": "หอบหืดรุนแรง (Severe Asthma)", "doctor": "พญ. นภา สดใส"},
    "A005": {"name": "นายกิตติศักดิ์ มั่นคง", "age": 80, "gender": "ชาย", "condition": "ภาวะติดเชื้อในกระแสเลือด (Sepsis Risk)", "doctor": "นพ. วิชัย รักษาดี"},
}

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

#  2. สมอง AI วิเคราะห์และประเมินอาการเชิงลึก (AI Clinical Intelligence)
def generate_ai_assessment(patient_id: str, history_rows: list):
    profile = PATIENT_PROFILES.get(patient_id, {"name": "ไม่ทราบ", "age": 0, "condition": "ไม่ระบุ"})
    
    if not history_rows:
        return {"risk_score": 0, "summary": "ยังไม่มีข้อมูลเพียงพอในการวิเคราะห์", "recommendation": "รอการรวบรวมข้อมูลสัญญาณชีพ"}

    hrs = [r[0] for r in history_rows]
    spo2s = [r[1] for r in history_rows]

    avg_hr = round(sum(hrs) / len(hrs), 1)
    min_spo2 = min(spo2s)
    max_hr = max(hrs)
    
    # ลอจิก AI ประเมินความเสี่ยงตามประวัติโรคและค่าสัญญาณชีพ
    risk_score = 10
    findings = []
    recommendations = []

    if min_spo2 < 90:
        risk_score += 50
        findings.append(f"พบภาวะออกซิเจนในเลือดต่ำวิกฤต (SpO2 ต่ำสุด {min_spo2}%)")
        recommendations.append("ให้ออกซิเจนเสริมทันที และเตรียมเครื่องช่วยหายใจ")
    elif min_spo2 < 95:
        risk_score += 25
        findings.append(f"ออกซิเจนลดต่ำกว่ามาตรฐาน (SpO2 ต่ำสุด {min_spo2}%)")
        recommendations.append("ตรวจสอบการหลุดของสาย O2 Cannula และจัดท่านอนหัวสูง")

    if max_hr > 120:
        risk_score += 35
        findings.append(f"หัวใจเต้นเร็วผิดปกติ (Tachycardia Peak {max_hr} bpm)")
        recommendations.append("ตรวจคลื่นไฟฟ้าหัวใจ (EKG 12-lead) และประเมินความเจ็บปวด")
    elif avg_hr > 100:
        risk_score += 15
        findings.append(f"ชีพจรเฉลี่ยค่อนข้างสูง ({avg_hr} bpm)")

    # ปรับตามปัจจัยอายุและโรคประจำตัว
    if profile["age"] >= 70:
        risk_score += 10
        findings.append("ผู้ป่วยสูงอายุ มีความเสี่ยงต่อการทรุดตัวรวดเร็ว")

    risk_score = min(risk_score, 100)

    if risk_score >= 70:
        risk_level = "HIGH RISK (วิกฤต)"
        ai_summary = f" AI เตือนภัยระดับสูง: ผู้ป่วยมีแนวโน้มภาวะแทรกซ้อนจาก {profile['condition']} ({' / '.join(findings)})"
    elif risk_score >= 40:
        risk_level = "MEDIUM RISK (เฝ้าระวัง)"
        ai_summary = f" AI แนะนำเฝ้าระวัง: พบความผิดปกติเบื้องต้น ({' / '.join(findings)})"
    else:
        risk_level = "LOW RISK (ปกติ)"
        ai_summary = f" AI ประเมิน: สัญญาณชีพอยู่ในเกณฑ์ปลอดภัย สอดคล้องกับแผนการรักษา"
        recommendations.append("บันทึกสัญญาณชีพตามรอบปกติ")

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "summary": ai_summary,
        "recommendations": recommendations,
        "stats": {
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "min_hr": min(hrs),
            "avg_spo2": round(sum(spo2s) / len(spo2s), 1),
            "min_spo2": min_spo2,
            "total_samples": len(history_rows)
        }
    }

# --- WebSocket & Connection Manager ---
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
        return "CRITICAL", " วิกฤต: ค่าสัญญาณชีพผิดปกติรุนแรง!"
    elif spo2 < 95 or hr > 100:
        return "WARNING", " เตือน: ค่า SpO2 ต่ำหรือหัวใจเต้นเร็ว"
    return "NORMAL", " สัญญาณชีพปกติ"

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        p_id = payload["patient_id"]
        hr = payload["heart_rate"]
        spo2 = payload["spo2"]
        ts = payload.get("timestamp")
        
        status, alert_msg = evaluate_risk(hr, spo2)
        save_to_db(p_id, hr, spo2, status, ts)
        
        profile = PATIENT_PROFILES.get(p_id, {"name": f"ผู้ป่วย {p_id}", "age": "-", "gender": "-", "condition": "-"})

        response_data = {
            "patient_id": p_id,
            "patient_profile": profile,
            "heart_rate": hr,
            "spo2": spo2,
            "status": status,
            "alert_message": alert_msg,
            "timestamp": ts
        }

        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(response_data), main_loop)
            
    except Exception as e:
        print(f" Error: {e}")

BROKER = "broker.emqx.io"
PORT = 8083
TOPIC = "my_ai_hospital/vitals"

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
mqtt_client.on_message = on_message

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    init_db()
    main_loop = asyncio.get_running_loop()
    mqtt_client.connect(BROKER, PORT, 60)
    mqtt_client.subscribe(TOPIC)
    mqtt_client.loop_start()
    print(" Backend + AI Clinical Assessment Engine พร้อมทำงาน")
    yield
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 📌 3. API สำหรับดึงข้อมูลรายละเอียดฉบับเต็ม + ผลวิเคราะห์ AI
@app.get("/api/patient/{patient_id}/details")
def get_patient_details(patient_id: str):
    profile = PATIENT_PROFILES.get(patient_id, {
        "name": f"ผู้ป่วย {patient_id}", "age": "-", "gender": "-", "condition": "ทั่วไป", "doctor": "-"
    })
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT heart_rate, spo2, status, timestamp FROM vital_logs WHERE patient_id = ? ORDER BY id DESC LIMIT 50",
        (patient_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    # สรุปผลด้วย AI
    ai_assessment = generate_ai_assessment(patient_id, rows)

    history_list = [
        {"heart_rate": r[0], "spo2": r[1], "status": r[2], "timestamp": r[3]}
        for r in rows
    ]

    return {
        "patient_id": patient_id,
        "profile": profile,
        "ai_assessment": ai_assessment,
        "history": history_list
    }

@app.websocket("/ws/vitals")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)