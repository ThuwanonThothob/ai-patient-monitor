import json
import os
from pathlib import Path

from google import genai

try:
    from dotenv import load_dotenv
except ImportError:  # `export GEMINI_API_KEY=...` remains supported without dotenv.
    load_dotenv = None

# For this local application, backend/.env is the source of truth. This avoids
# an old `export GEMINI_API_KEY=...` in a terminal silently overriding a rotated key.
if load_dotenv:
    # Explicit shell/test/deployment variables take precedence over the local file.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_MODEL_PREFERENCES = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
)

print("🤖 กำลังเตรียมระบบ AI ผู้ช่วยถาม-ตอบ (Gemini Chat - อัปเดตใหม่)...")


def _is_model_not_found(error: Exception) -> bool:
    error_text = str(error).lower()
    return "not found" in error_text or "404" in error_text


def _get_available_model(client: genai.Client, requested_model: str) -> str | None:
    """Select a text-capable Flash model exposed to this API key/project."""
    available = []
    for model in client.models.list():
        name = (model.name or "").rsplit("/", maxsplit=1)[-1]
        if name:
            available.append(name)

    for candidate in (requested_model, *FALLBACK_MODEL_PREFERENCES):
        if candidate in available:
            return candidate
    return next((name for name in available if name.startswith("gemini-") and "flash" in name), None)

def chat_with_patient_data(patient_id: str, profile: dict, history_rows: list, user_message: str, monitor_context: dict | None = None) -> str:
    """
    รับคำถามจากผู้ใช้ และป้อนข้อมูลผู้ป่วยให้ AI ช่วยตอบ (อัปเดตใช้ google-genai)
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY กรุณาสร้าง backend/.env จาก .env.example แล้ว restart backend"

    try:
        # กำหนด Client ด้วยวิธีใหม่
        client = genai.Client(api_key=api_key)
        
        # คำนวณค่าเฉลี่ยล่าสุดให้ AI รู้อาการปัจจุบัน
        if history_rows:
            avg_hr = round(sum(r[0] for r in history_rows) / len(history_rows), 1)
            min_spo2 = min(r[1] for r in history_rows)
            latest_hr = history_rows[0][0]
            latest_spo2 = history_rows[0][1]
        else:
            avg_hr = min_spo2 = latest_hr = latest_spo2 = "ไม่มีข้อมูล"

        diagnoses = ", ".join(profile.get("diagnoses", [profile.get("condition", "ไม่ระบุ")]))
        # The chat is scoped to the selected synthetic record. It gives the AI
        # enough structured context for a 60-bed directory without letting it
        # invent actions such as calling a doctor or dispatching an ambulance.
        prompt = f"""
คุณคือ AI ผู้ช่วยพยาบาลสำหรับระบบสาธิต Smart Ward ทะเบียนและประวัติเป็นข้อมูลสมมติ
สัญญาณอาจมาจาก BIDMC replay หรือ MQTT ตาม source ที่แนบ ไม่ใช่เวชระเบียนของคนในทะเบียน
และเป็น decision support เท่านั้น ห้ามอนุมานโรคจากความสัมพันธ์กับทะเบียนสมมติ

ข้อมูลเตียงที่เลือก:
- Patient ID: {patient_id}
- Zone / Room: {profile.get('zone', '-')} / {profile.get('room_number', '-')}
- ชื่อในระบบสาธิต: {profile.get('name', 'ไม่ระบุ')}
- อายุ / เพศ / กรุ๊ปเลือด: {profile.get('age', '-')} / {profile.get('gender', '-')} / {profile.get('blood_group', '-')}
- โรคและแผนเฝ้าระวัง: {diagnoses}
- การเคลื่อนไหว: {profile.get('mobility', '-')}
- แพทย์ผู้ดูแลในระบบสาธิต: {profile.get('doctor', '-')}
- ค่าพื้นฐาน: RR {profile.get('respiratory_rate', '-')} ครั้ง/นาที, นอน {profile.get('sleep_hours', '-')} ชั่วโมง ({profile.get('sleep_quality', '-')}), น้ำตาล {profile.get('blood_glucose_mg_dl', '-')} mg/dL, ไขมัน {profile.get('cholesterol_mg_dl', '-')} mg/dL, ECG {profile.get('ecg_rhythm', '-')}
- สัญญาณชีพล่าสุด: Heart Rate {latest_hr} bpm, SpO2 {latest_spo2}%
- สถิติย้อนหลัง: HR เฉลี่ย {avg_hr} bpm, SpO2 ต่ำสุด {min_spo2}%
- ผลวิเคราะห์ ML ปัจจุบันของ ID นี้: {json.dumps(monitor_context or {}, ensure_ascii=False)}

เฉพาะ analysis.status=READY เท่านั้นจึงอธิบาย forecast ได้ ถ้าเก่า/ขาดช่วงต้องระบุว่ารอข้อมูล
RandomForestRegressor คาดการณ์ HR/RR ล่วงหน้า 30 วินาที; SpO2 ใช้ persistence baseline
IsolationForest ตรวจรูปแบบต่างจากชุดฝึก ไม่ใช่ความน่าจะเป็นของโรค ไม่มี accuracy ทางคลินิก
อย่าอ้างว่าโมเดลเหนือกว่า baseline ทุกตัว หรือใช้ค่า mortality จากโมเดล ICU กับข้อมูลสั้นนี้

ตอบภาษาไทย สุภาพ กระชับ และอ้างอิงเฉพาะข้อมูลที่มีจริงในบริบทนี้
คุณช่วยสรุปรายละเอียดผู้ป่วย อาการ/แนวโน้ม และสิ่งที่ควรให้บุคลากรตรวจสอบได้
ห้ามวินิจฉัย สั่งยา หรืออ้างว่าได้ติดต่อแพทย์หรือสั่งรถพยาบาลแล้ว
หากมีสัญญาณผิดปกติ ให้แนะนำให้เจ้าหน้าที่ประเมินทันที และย้ำว่าต้องมีมนุษย์ตรวจสอบก่อนดำเนินการ

คำถามจากผู้ใช้งาน: "{user_message}"
        """
        
        # Try the configured model first. Some keys/projects expose a smaller
        # model catalogue; on a 404, discover and retry one available Flash model.
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        except Exception as model_error:
            if not _is_model_not_found(model_error):
                raise
            fallback_model = _get_available_model(client, MODEL_NAME)
            if not fallback_model:
                return "⚠️ API key นี้ไม่พบ Gemini Flash model ที่ใช้งานได้ กรุณาตรวจสอบสิทธิ์ใน Google AI Studio"
            print(f"ℹ️ Gemini model fallback: {MODEL_NAME} -> {fallback_model}")
            response = client.models.generate_content(model=fallback_model, contents=prompt)
        text = (response.text or "").strip()
        return text or "ขออภัย Gemini ไม่ได้ส่งข้อความตอบกลับ กรุณาลองใหม่อีกครั้ง"
        
    except Exception as e:
        # Do not log request data or the API key. Return a useful, safe diagnosis.
        error_text = str(e).lower()
        print(f"❌ LLM Chat Error ({type(e).__name__})")
        if "api key" in error_text or "api_key" in error_text or "unauthenticated" in error_text:
            return "⚠️ Gemini ปฏิเสธ API key กรุณาตรวจสอบ GEMINI_API_KEY และ restart backend"
        if "permission" in error_text or "forbidden" in error_text:
            return "⚠️ API key นี้ไม่มีสิทธิ์ใช้ Gemini API หรือโปรเจกต์ยังไม่ได้เปิดใช้งานบริการ"
        if "not found" in error_text or "404" in error_text:
            return "⚠️ API key นี้เข้าถึง Gemini model ไม่ได้ กรุณาตรวจสอบสิทธิ์ของ key ใน Google AI Studio"
        if "quota" in error_text or "resource_exhausted" in error_text or "429" in error_text:
            return "⚠️ Gemini quota เต็มหรือถูกจำกัดอัตราการเรียกใช้ กรุณาตรวจสอบ Billing/Quota"
        return "⚠️ ไม่สามารถเรียก Gemini ได้ กรุณาดูข้อความ `LLM Chat Error` ใน Terminal ของ backend"


def summarize_dashboard_section(section: str, snapshot: dict) -> str:
    """Create a concise Thai decision-support summary for a dashboard section."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "ยังไม่ได้ตั้งค่า Gemini จึงแสดงเฉพาะข้อมูลจากระบบติดตามสัญญาณชีพ"

    prompt = f"""
คุณคือผู้ช่วยวิเคราะห์ข้อมูลสำหรับหอผู้ป่วย ข้อมูลนี้เป็น decision support เท่านั้น
ห้ามวินิจฉัยโรค สั่งยา หรือแทนการประเมินโดยบุคลากรทางการแพทย์

หมวดที่ผู้ใช้กำลังดู: {section}
ข้อมูลสรุปจากระบบ: {json.dumps(snapshot, ensure_ascii=False)}

สรุปเป็นภาษาไทย 3 ถึง 5 ประโยค โดยระบุสิ่งที่ควรตรวจสอบก่อน
ให้พูดถึงข้อมูลที่มีจริงเท่านั้น และลงท้ายว่าต้องให้บุคลากรตรวจสอบก่อนดำเนินการ
"""
    try:
        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        except Exception as model_error:
            if not _is_model_not_found(model_error):
                raise
            fallback_model = _get_available_model(client, MODEL_NAME)
            if not fallback_model:
                return "ไม่พบ Gemini model ที่ใช้งานได้สำหรับสรุปข้อมูล"
            response = client.models.generate_content(model=fallback_model, contents=prompt)
        return (response.text or "").strip() or "Gemini ไม่ได้ส่งข้อความสรุปกลับมา"
    except Exception as error:
        print(f"❌ Dashboard AI Summary Error ({type(error).__name__})")
        return "ไม่สามารถสร้าง AI summary ได้ในขณะนี้ แต่ข้อมูลตัวเลขยังอัปเดตตามปกติ"
