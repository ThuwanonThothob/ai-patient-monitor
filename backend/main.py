import json
import sqlite3
import asyncio
import time
from matplotlib.patheffects import Stroke
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from contextlib import asynccontextmanager
#เชื่อมai
from ai_models.anomaly import detect_anomaly
from ai_models.risk_score import calculate_risk_score
from ai_models.forecasting import predict_future_vitals
from ai_models.llm_summary import chat_with_patient_data
from pydantic import  BaseModel # ใช้สำหรับรับค่า API Key จากหน้าเว็บ

DB_NAME = "vitals.db"

# 1. ฐานข้อมูลจำลองโปรไฟล์ผู้ป่วย (Patient Profiles)
PATIENT_PROFILES = {
    "A001": {"name": "นายสมชาย ใจดี", "age": 65, "gender": "ชาย", "condition": "โรคปอดอุดกั้นเรื้อรัง (COPD)", "doctor": "นพ. วิชัย รักษาดี"},
    "A002": {"name": "นางสมศรี มีสุข", "age": 72, "gender": "หญิง", "condition": "ภาวะหัวใจล้มเหลว (CHF)", "doctor": "นพ. วิชัย รักษาดี"},
    "A003": {"name": "นายอนันต์ รุ่งเรือง", "age": 58, "gender": "ชาย", "condition": "ความดันโลหิตสูง / เฝ้าระวังหลังผ่าตัด", "doctor": "พญ. นภา สดใส"},
    "A004": {"name": "นางสาวปราณี สดใส", "age": 45, "gender": "หญิง", "condition": "หอบหืดรุนแรง (Severe Asthma)", "doctor": "พญ. นภา สดใส"},
    "A005": {"name": "นายกิตติศักดิ์ มั่นคง", "age": 80, "gender": "ชาย", "condition": "ภาวะติดเชื้อในกระแสเลือด (Sepsis Risk)", "doctor": "นพ. วิชัย รักษาดี"},
    "A006": {"name": "นางสาวอรทัย แสงทอง", "age": 68, "gender": "หญิง", "condition": "โรคเบาหวาน / ความดันโลหิตสูง", "doctor": "พญ. นภา สดใส"},
    "A007": {"name": "นายปรีชา กล้าหาญ", "age": 55, "gender": "ชาย", "condition": "โรคไตเรื้อรัง (CKD)", "doctor": "นพ. วิชัย รักษาดี"},
    "A008": {"name": "นางสาวจินตนา ใจงาม", "age": 62, "gender": "หญิง", "condition": "โรคหลอดเลือดสมอง (Stroke Risk)", "doctor": "พญ. นภา สดใส"},
    "A009": {"name": "นายสมบูรณ์ แก้วใจ", "age": 70, "gender": "ชาย", "condition": "โรคหัวใจเต้นผิดจังหวะ (Arrhythmia)", "doctor": "นพ. วิชัย รักษาดี"},
    "A010": {"name": "นางสาวสุดารัตน์ แก้วใส", "age": 60, "gender": "หญิง", "condition": "โรคปอดเรื้อรัง / ภาวะหอบหืด", "doctor": "พญ. นภา สดใส"}
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

#ไว้ลบข้อมูลเก่า
def cleanup_old_logs(days_to_keep=1):
    try:
        cutoff_timestamp = time.time() - (days_to_keep * 24 * 60 * 60)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vital_logs WHERE timestamp < ?", (cutoff_timestamp,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted_count > 0:
            print(f"deleted {deleted_count} old log entries older than {days_to_keep} days.")
    except Exception as e:
        print(f"Error cleaning up old logs: {e}")


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

# อย่าลืม Import ฟังก์ชัน AI ไว้ด้านบนสุดของไฟล์ main.py
# from ai_models.anomaly import detect_anomaly 
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        p_id = payload["patient_id"]
        hr = payload["heart_rate"]
        spo2 = payload["spo2"]
        ts = payload.get("timestamp")
        
        status, alert_msg = evaluate_risk(hr, spo2)
        is_anomaly = detect_anomaly(hr, spo2)
        
        if is_anomaly and status == "Normal":
            status = "Warning"
            alert_msg = "AI ตรวจพบจังหวะการเต้นของหัวใจผิดปกติ (Anomaly)"
            
        save_to_db(p_id, hr, spo2, status, ts)
        
        profile = PATIENT_PROFILES.get(p_id, {"name": f"ผู้ป่วย {p_id}", "age": 50, "gender": "-", "condition": "-"})
        
        # ⚡ 1. เรียกใช้ AI: ประเมินความเสี่ยง 
        patient_age = profile.get("age", 50)
        risk_percent = calculate_risk_score(hr, spo2, age=patient_age if isinstance(patient_age, int) else 50)

        response_data = {
            "patient_id": p_id,
            "patient_profile": profile,
            "heart_rate": hr,
            "spo2": spo2,
            "status": status,
            "alert_message": alert_msg,
            "timestamp": ts,
            "is_anomaly": is_anomaly,
            "risk_percent": risk_percent # 👈 ส่งคะแนนความเสี่ยงไปให้หน้าเว็บ
        }

        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(response_data), main_loop)
            
    except Exception as e:
        print(f"MQTT Error: {e}")

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

    ai_assessment = generate_ai_assessment(patient_id, rows)

    history_list = [
        {"heart_rate": r[0], "spo2": r[1], "status": r[2], "timestamp": r[3]}
        for r in rows
    ]
    
    # ⚡ 2. เรียกใช้ AI: พยากรณ์ค่า HR/SpO2 ล่วงหน้า (สลับเอาข้อมูลเก่าสุดขึ้นก่อนเพื่อดูกราฟ)
    history_hr = [r[0] for r in rows][::-1]
    history_spo2 = [r[1] for r in rows][::-1]
    forecast = predict_future_vitals(history_hr, history_spo2, future_steps=3)

    return {
        "patient_id": patient_id,
        "profile": profile,
        "ai_assessment": ai_assessment,
        "history": history_list,
        "forecast": forecast # 👈 ส่งผลพยากรณ์ไปแสดงใน Modal
    }
#GEMINI API Key Model
class ChatMessage(BaseModel):
    message: str

@app.post("/api/patient/{patient_id}/chat")
def patient_chat_api(patient_id: str, request: ChatMessage):
    profile = PATIENT_PROFILES.get(patient_id, {"name": "ไม่ทราบชื่อ", "condition": "ไม่ระบุ"})
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT heart_rate, spo2 FROM vital_logs WHERE patient_id = ? ORDER BY id DESC LIMIT 30", (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    
    # ส่งข้อความและข้อมูลผู้ป่วยไปให้ Gemini คิดคำตอบ
    reply = chat_with_patient_data(
        patient_id=patient_id, 
        profile=profile, 
        history_rows=rows, 
        user_message=request.message
    )
    
    return {"reply": reply}

@app.websocket("/ws/vitals")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)