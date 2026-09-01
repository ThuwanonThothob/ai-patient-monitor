import os
import google.generativeai as genai

API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCFn-ZubmqWpvVkK-Lr5PR9HETP1G-a69c")

print("🤖 กำลังเตรียมระบบ AI สรุปรายงานการแพทย์ (LLM Gemini)...")

def chat_with_patient_data(patient_id: str, profile: dict, history_rows: list, user_message: str) -> str:
    """
    รับคำถามจากผู้ใช้ และป้อนข้อมูลผู้ป่วยให้ AI ช่วยตอบ
    """
    if not API_KEY or API_KEY.startswith("ใส่_API"):
        return "⚠️ กรุณาใส่ API Key ในไฟล์ llm_summary.py ก่อนใช้งาน"

    try:
        genai.configure(api_key=API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # คำนวณค่าเฉลี่ยล่าสุดให้ AI รู้อาการปัจจุบัน
        if history_rows:
            avg_hr = round(sum(r[0] for r in history_rows) / len(history_rows), 1)
            min_spo2 = min(r[1] for r in history_rows)
            latest_hr = history_rows[0][0]
            latest_spo2 = history_rows[0][1]
        else:
            avg_hr = min_spo2 = latest_hr = latest_spo2 = "ไม่มีข้อมูล"

        # 🧠 สร้างบริบท (Prompt) สั่งให้ AI สวมบทบาทเป็นผู้ช่วยแพทย์
        prompt = f"""
        คุณคือ AI ผู้ช่วยแพทย์และพยาบาล ข้อมูลผู้ป่วยที่คุณกำลังดูแลมีดังนี้:
        - รหัสผู้ป่วย: เตียง {patient_id}
        - ชื่อ: {profile.get('name', 'ไม่ระบุ')}
        - โรคประจำตัว: {profile.get('condition', 'ไม่ระบุ')}
        - สัญญาณชีพล่าสุด: Heart Rate {latest_hr} bpm, SpO2 {latest_spo2}%
        - สถิติย้อนหลัง: HR เฉลี่ย {avg_hr} bpm, SpO2 ต่ำสุด {min_spo2}%
        
        คำสั่ง: จงตอบคำถามของผู้ใช้งานโดยอ้างอิงจากข้อมูลผู้ป่วยด้านบน ตอบเป็นภาษาไทยด้วยภาษาที่สุภาพและกระชับ
        
        คำถามจากผู้ใช้งาน: "{user_message}"
        """
        
        response = model.generate_content(prompt)
        return response.text.strip()
        
    except Exception as e:
        print(f"❌ LLM Chat Error: {e}")
        return "ขออภัย ไม่สามารถเชื่อมต่อกับ AI ได้ในขณะนี้"