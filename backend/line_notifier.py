"""Multi-channel mobile notification service for Smart Ward alerts.

Supports:
1. LINE Messaging API (Official successor to LINE Notify, supports broadcast/push to all friends)
2. Telegram Bot API (Instant 30-second setup, 100% free with no limits)
3. Legacy LINE Notify (for backward compatibility if still active)

Features:
- Bed Isolation: Restricts alerts to designated patient bed(s) so relatives only see their patient.
- AI Family-Friendly Presentation: Re-formats clinical data into reassuring, clear, and structured Thai language.
- Non-blocking execution with alert cooldowns to prevent notification floods.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_last_sent: dict[str, float] = {}
COOLDOWN_SECONDS = 180  # 3 minutes cooldown per event key

_target_bed_override: str | None = None
_audience_override: str | None = None


POSTURE_LABELS_THAI: dict[str, str] = {
    "supine": "นอนหงาย",
    "left": "นอนตะแคงซ้าย",
    "right": "นอนตะแคงขวา",
    "other": "ท่าอื่น",
    "empty_bed": "ไม่มีผู้ป่วยบนเตียง",
    "abstain": "ไม่ระบุท่าทางแน่ชัด",
}


def translate_posture(posture: str) -> str:
    """Translate raw model posture string (e.g. 'supine', 'left') to plain Thai."""
    if not posture:
        return "นอนหงาย"
    return POSTURE_LABELS_THAI.get(posture.strip().lower(), posture)


def get_anatomical_hotspot(posture: str, fallback: str = "ก้นกบ (Sacrum) > 42 mmHg") -> tuple[str, str]:
    """Return anatomical hotspot description and EPUAP 30° lateral tilt guidance based on posture."""
    norm = (posture or "").strip().lower()
    if norm in ("left", "นอนตะแคงซ้าย"):
        return (
            "ปุ่มกระดูกสะโพกซ้าย (Greater Trochanter), หัวไหล่ซ้าย, และตาตุ่มซ้าย",
            "พยาบาลประจำเวรเตรียมเข้าช่วยเหลือจัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับด้าน หรือหนุนหมอนรองหลังเพื่อคลายแรงกดทับสะโพกซ้าย",
        )
    if norm in ("right", "นอนตะแคงขวา"):
        return (
            "ปุ่มกระดูกสะโพกขวา (Greater Trochanter), หัวไหล่ขวา, และตาตุ่มขวา",
            "พยาบาลประจำเวรเตรียมเข้าช่วยเหลือจัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับด้าน หรือหนุนหมอนรองหลังเพื่อคลายแรงกดทับสะโพกขวา",
        )
    return (
        fallback or "ก้นกบ (Sacrum Hotspot > 42 mmHg) และส้นเท้า",
        "พยาบาลประจำเวรเตรียมเข้าช่วยเหลือจัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับด้าน พร้อมหนุนหมอนรองรับหลังและหว่างขาเพื่อกระจายแรงกดทับ",
    )


def _get_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def is_configured() -> bool:
    return bool(
        (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
        or (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        or (os.getenv("LINE_NOTIFY_TOKEN") or "").strip()
    )


def get_token() -> str:
    return (
        (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
        or (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        or (os.getenv("LINE_NOTIFY_TOKEN") or "").strip()
    )


def get_target_bed() -> str:
    """Get the target bed ID for family notifications (e.g. 'A001')."""
    if _target_bed_override is not None:
        return _target_bed_override
    env_bed = os.getenv("LINE_FAMILY_TARGET_BED") or os.getenv("LINE_TARGET_BED") or "A001"
    return env_bed.strip().upper()


def set_target_bed(bed_id: str) -> None:
    """Set the target bed ID dynamically."""
    global _target_bed_override
    _target_bed_override = (bed_id or "A001").strip().upper()


def get_audience_mode() -> str:
    """Get audience mode: 'family' (default) or 'staff'."""
    if _audience_override is not None:
        return _audience_override
    env_mode = (os.getenv("LINE_AUDIENCE_MODE") or "family").strip().lower()
    return "staff" if env_mode == "staff" else "family"


def set_audience_mode(mode: str) -> None:
    """Set audience mode dynamically ('family' or 'staff')."""
    global _audience_override
    _audience_override = "staff" if (mode or "").strip().lower() == "staff" else "family"


def is_bed_allowed(patient_id: str) -> bool:
    """Check if the given bed ID is allowed under the current target bed configuration.
    
    Prevents mixing all ward patients together into a family member's LINE feed.
    """
    target = get_target_bed().upper()
    if target == "ALL":
        return True
    allowed_beds = {b.strip().upper() for b in target.split(",") if b.strip()}
    return patient_id.strip().upper() in allowed_beds


def _get_patient_details(patient_id: str) -> dict[str, Any]:
    """Look up patient room, bed, zone, and display name from patient registry if available."""
    details: dict[str, Any] = {
        "bed_label": f"เตียง {patient_id}",
        "room_label": "ห้องผู้ป่วย",
        "zone_label": "หอผู้ป่วย",
        "patient_name": f"ผู้ป่วยเตียง {patient_id}",
        "doctor_name": "ทีมแพทย์ประจำหอผู้ป่วย",
        "condition": "การดูแลผู้ป่วยใน",
        "diagnoses": ["การดูแลผู้ป่วยใน"],
        "mobility": "Assisted mobility",
        "age": 70,
        "gender": "Male",
    }
    try:
        from patient_registry import get_patient_profile
        profile = get_patient_profile(patient_id)
        if profile:
            room = profile.get("room_number") or ""
            zone = profile.get("zone") or ""
            name = profile.get("name") or ""
            doctor = profile.get("doctor") or ""
            if room:
                details["room_label"] = f"ห้อง {room}"
            if zone:
                details["zone_label"] = f"โซน {zone}"
            if room and zone:
                details["bed_label"] = f"เตียง {patient_id} ({details['room_label']} · {details['zone_label']})"
            elif room:
                details["bed_label"] = f"เตียง {patient_id} ({details['room_label']})"
            if name and not name.startswith("Synthetic Patient"):
                details["patient_name"] = name
            else:
                details["patient_name"] = f"คุณผู้ป่วยเตียง {patient_id}"
            if doctor:
                details["doctor_name"] = doctor
            if profile.get("condition"):
                details["condition"] = profile["condition"]
            if profile.get("diagnoses"):
                details["diagnoses"] = profile["diagnoses"]
            if profile.get("mobility"):
                details["mobility"] = profile["mobility"]
            if profile.get("age"):
                details["age"] = profile["age"]
            if profile.get("gender"):
                details["gender"] = profile["gender"]
    except Exception:
        pass
    return details


# ─────────────────────────────────────────────────────────────────────────────
# AI Family-Centric Message Formatters (จัดระเบียบสำหรับญาติผู้ป่วยโดยเฉพาะ)
# ─────────────────────────────────────────────────────────────────────────────

def format_family_vital_message(
    patient_id: str,
    severity: str,
    reason: str,
    recommended_next_step: str,
    vitals: dict[str, Any] | None = None,
    news2_score: int | None = None,
) -> str:
    """AI-curated vital alert formatted with empathy and clarity for patient relatives."""
    vitals = vitals or {}
    p_info = _get_patient_details(patient_id)
    
    # 1. Format human-readable vitals in Thai
    hr = vitals.get("heart_rate")
    spo2 = vitals.get("spo2")
    rr = vitals.get("respiratory_rate")
    
    vital_items: list[str] = []
    if spo2 is not None:
        if spo2 < 92:
            vital_items.append(f"• ออกซิเจนในเลือด (SpO₂): {spo2}% (ลดลงต่ำกว่าเกณฑ์ปกติชั่วคราว)")
        elif spo2 < 95:
            vital_items.append(f"• ออกซิเจนในเลือด (SpO₂): {spo2}% (อยู่ในเกณฑ์เฝ้าระวัง)")
        else:
            vital_items.append(f"• ออกซิเจนในเลือด (SpO₂): {spo2}% (อยู่ในเกณฑ์ปกติ)")
    if hr is not None:
        if hr > 100:
            vital_items.append(f"• อัตราการเต้นของหัวใจ: {hr} ครั้ง/นาที (ค่อนข้างเร็ว)")
        elif hr < 60:
            vital_items.append(f"• อัตราการเต้นของหัวใจ: {hr} ครั้ง/นาที (ค่อนข้างช้า)")
        else:
            vital_items.append(f"• อัตราการเต้นของหัวใจ: {hr} ครั้ง/นาที (สม่ำเสมอด้านปกติ)")
    if rr is not None:
        if rr > 20:
            vital_items.append(f"• จังหวะการหายใจ: {rr} ครั้ง/นาที (ค่อนข้างเร็ว)")
        elif rr < 12:
            vital_items.append(f"• จังหวะการหายใจ: {rr} ครั้ง/นาที (ค่อนข้างช้า)")
        else:
            vital_items.append(f"• จังหวะการหายใจ: {rr} ครั้ง/นาที (ปกติ)")

    # 2. AI Synthesis: Explain without alarming clinical jargon
    if spo2 is not None and spo2 < 92:
        ai_summary = (
            "ระบบ AI ตรวจพบระดับออกซิเจนในเลือดลดลงต่ำกว่าเกณฑ์ปกติเล็กน้อย "
            "ซึ่งอาจเกิดจากท่านอนกดทับ การหายใจตื้นขณะหลับ หรือสายวัดที่นิ้วมือขยับเลื่อนหลุด "
            "ระบบได้ส่งสัญญาณแจ้งเตือนทีมพยาบาลเวรเรียบร้อยแล้วโดยอัตโนมัติ"
        )
        nursing_action = (
            "พยาบาลประจำเวรได้รับทราบสัญญาณเตือนและกำลังเข้าดูแลที่เตียงทันที "
            "เพื่อจัดท่านอนให้หายใจได้สะดวก ปรับสายออกซิเจน และตรวจวัดสัญญาณชีพซ้ำ"
        )
    elif hr is not None and hr > 100:
        ai_summary = (
            "ระบบ AI ตรวจพบชีพจรเต้นเร็วกว่าปกติเล็กน้อย "
            "ซึ่งอาจสัมพันธ์กับการขยับตัว พูดคุย หรือมีไข้ต่ำๆ "
            "ระบบได้ส่งข้อมูลให้ทีมพยาบาลเข้าตรวจประเมินข้างเตียงแล้ว"
        )
        nursing_action = "พยาบาลประจำเวรกำลังเข้าตรวจวัดความดันและดูแลข้างเตียงอย่างใกล้ชิด"
    else:
        ai_summary = (
            f"ระบบ AI ตรวจพบการเปลี่ยนแปลงของสัญญาณชีพ ({reason}) "
            "และได้ประสานงานส่งข้อมูลให้พยาบาลประจำเวรเรียบร้อยแล้วเพื่อความปลอดภัยสูงสุด"
        )
        nursing_action = "พยาบาลประจำเวรได้รับทราบและกำลังเข้าดูแลตรวจเช็คอาการที่ข้างเตียง"

    status_tag = "🔴 [แจ้งเตือนด่วนสำหรับญาติ]" if severity == "critical" else "🟡 [รายงานเฝ้าระวังสำหรับญาติ]"

    lines = [
        f"{status_tag}",
        "🏥 SMART WARD · รายงานสถานะผู้ป่วยสำหรับญาติ",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🛏️ เตียงผู้ป่วย: {p_info['bed_label']}",
        f"👤 ผู้ป่วย: {p_info['patient_name']}",
        f"🩺 แพทย์เจ้าของไข้: {p_info['doctor_name']}",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 สัญญาณชีพล่าสุด:",
    ]
    if vital_items:
        lines.extend(vital_items)
    else:
        lines.append(f"• สถานะ: {reason}")

    lines.extend([
        "",
        "🤖 AI วิเคราะห์และสรุปข้อมูล:",
        ai_summary,
        "",
        "🩺 การดูแลของทีมพยาบาล:",
        nursing_action,
        "",
        "💡 คำแนะนำสำหรับญาติ:",
        "ญาติไม่ต้องตื่นตระหนก สามารถพักผ่อนหรืออยู่เป็นกำลังใจข้างเตียงได้ตามปกติ "
        "หากมีข้อสงสัยหรือต้องการสอบถาม สามารถกดปุ่มแชทติดต่อพยาบาลผ่านระบบได้ตลอด 24 ชั่วโมง",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⏰ เวลาที่บันทึก: {time.strftime('%H:%M:%S น.', time.localtime())}",
        "(ระบบ AI Smart Ward เพื่อความอุ่นใจของครอบครัวผู้ป่วย)",
    ])
    return "\n".join(lines)


def format_family_acknowledged_message(
    patient_id: str,
    actor: str,
    reason: str,
    acknowledged_at: float | None = None,
    note: str = "",
) -> str:
    """AI-curated reassurance message sent to relatives once clinician acknowledges an alert."""
    p_info = _get_patient_details(patient_id)
    time_str = time.strftime("%H:%M:%S น.", time.localtime(acknowledged_at or time.time()))

    lines = [
        "🟢 [แพทย์/พยาบาลรับทราบและเข้าดูแลแล้ว]",
        "🏥 SMART WARD · แจ้งสถานะการดูแลถึงครอบครัว",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🛏️ เตียงผู้ป่วย: {p_info['bed_label']}",
        f"👤 ผู้ป่วย: {p_info['patient_name']}",
        f"🩺 แพทย์เจ้าของไข้: {p_info['doctor_name']}",
        "━━━━━━━━━━━━━━━━━━━━",
        "👨‍⚕️ การปฏิบัติงานของทีมผู้ดูแล:",
        f"• บุคลากรผู้รับผิดชอบ: {actor or 'พยาบาลประจำเวร'}",
        f"• รับทราบข้อมูลเมื่อ: {time_str}",
        f"• อาการที่ติดตาม: {reason or 'ตรวจสอบสัญญาณชีพและการดูแลข้างเตียง'}",
    ]
    if note:
        lines.append(f"• บันทึกการดูแล: {note}")

    lines.extend([
        "",
        "🤖 AI รายงานสถานะสำหรับญาติ:",
        "ทีมแพทย์และพยาบาลเวรได้ตรวจสอบข้อมูลสัญญาณชีพและเข้าดูแลผู้ป่วยข้างเตียงเรียบร้อยแล้ว "
        "ผู้ป่วยได้รับการดูแลตามมาตรฐานความปลอดภัยทางคลินิกอย่างใกล้ชิด",
        "",
        "💙 ข้อแนะนำสำหรับครอบครัว:",
        "ท่านสบายใจได้ครับ ทีมแพทย์กำลังให้การรักษาอย่างเหมาะสม หากมีข้อกังวลหรือต้องการสอบถามเพิ่มเติม "
        "สามารถสื่อสารผ่านระบบแชทกับทีมพยาบาลได้ตลอด 24 ชั่วโมง",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⏰ อัปเดตล่าสุด: {time_str}",
        "(ระบบ AI ผู้ช่วยบริบาลผู้ป่วย Smart Ward)",
    ])
    return "\n".join(lines)


def notify_family_on_acknowledgment(
    patient_id: str,
    actor: str,
    reason: str,
    acknowledged_at: float | None = None,
    note: str = "",
) -> tuple[bool, str]:
    """Auto-trigger Family Care Agent when clinician acknowledges an alert on staff dashboard."""
    if not is_configured():
        return False, "LINE channel not configured"

    if not is_bed_allowed(patient_id):
        log.info("Bed isolation prevented family dispatch for %s (target is %s)", patient_id, get_target_bed())
        return False, f"Bed {patient_id} filtered out by bed isolation (locked to {get_target_bed()})"

    message = format_family_acknowledged_message(
        patient_id=patient_id,
        actor=actor,
        reason=reason,
        acknowledged_at=acknowledged_at,
        note=note,
    )
    return send_notification(message)


def format_family_posture_alert_message(
    patient_id: str,
    posture: str,
    dwell_minutes: int,
    hotspot: str = "ก้นกบ (Sacrum) > 42 mmHg",
    braden_score: int = 11,
) -> str:
    """AI-curated turning & pressure sore prevention alert for patient relatives."""
    p_info = _get_patient_details(patient_id)
    hours = dwell_minutes // 60
    mins = dwell_minutes % 60
    duration_str = f"{hours} ชั่วโมง {mins} นาที" if mins else f"{hours} ชั่วโมง"

    posture_map = {
        "supine": "นอนหงาย",
        "left": "นอนตะแคงซ้าย",
        "right": "นอนตะแคงขวา",
        "abstain": "ไม่ระบุท่าทางแน่ชัด",
    }
    posture_th = posture_map.get(posture.lower(), posture)
    
    # Auto-adjust anatomical hotspot based on actual posture
    norm_posture = posture.lower()
    if norm_posture == "left":
        hotspot_desc = "ปุ่มกระดูกสะโพกซ้าย (Greater Trochanter), หัวไหล่ซ้าย, และตาตุ่มซ้าย"
        tilt_action = "พยาบาลประจำเวรเตรียมเข้าช่วยเหลือจัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับด้าน หรือหนุนหมอนรองหลังเพื่อคลายแรงกดทับสะโพกซ้าย"
    elif norm_posture == "right":
        hotspot_desc = "ปุ่มกระดูกสะโพกขวา (Greater Trochanter), หัวไหล่ขวา, และตาตุ่มขวา"
        tilt_action = "พยาบาลประจำเวรเตรียมเข้าช่วยเหลือจัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับด้าน หรือหนุนหมอนรองหลังเพื่อคลายแรงกดทับสะโพกขวา"
    else:
        hotspot_desc = hotspot or "ก้นกบ (Sacrum Hotspot > 42 mmHg) และส้นเท้า"
        tilt_action = "พยาบาลประจำเวรเตรียมเข้าช่วยเหลือจัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับด้าน พร้อมหนุนหมอนรองรับหลังและหว่างขาเพื่อกระจายแรงกดทับ"

    lines = [
        "🛏️ [แจ้งเตือนรอบการดูแลสำหรับญาติ]",
        "🏥 SMART WARD · ดูแลสุขภาวะและการเปลี่ยนท่าทาง",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🛏️ เตียงผู้ป่วย: {p_info['bed_label']}",
        f"👤 ผู้ป่วย: {p_info['patient_name']}",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 สถานะการนอนปัจจุบัน:",
        f"• ท่าทาง: {posture_th} ต่อเนื่อง {duration_str} (ครบกำหนดรอบ 2 ชม.)",
        f"• จุดรับแรงกดสะสม: {hotspot_desc}",
        "",
        "🤖 AI วิเคราะห์และสรุปข้อมูล:",
        "เซนเซอร์วัดแรงกดใต้เตียงร่วมกับระบบ AI ตรวจพบการนอนในท่าเดิมต่อเนื่อง "
        "ถึงรอบเวลาที่ควรช่วยขยับเปลี่ยนท่าทาง เพื่อคลายแรงกดทับ ผ่อนคลายกล้ามเนื้อ "
        "และป้องกันการเกิดแผลกดทับตามมาตรฐานการดูแลผู้ป่วยติดเตียงสากล (EPUAP)",
        "",
        "🩺 การดูแลของทีมพยาบาล:",
        tilt_action,
        "",
        "💡 คำแนะนำสำหรับญาติ:",
        "หากญาติอยู่ข้างเตียง สามารถช่วยสังเกตความสบายตัวของผู้ป่วย และช่วยจัดผ้าห่มหรือหมอนหนุนได้ "
        "ทั้งนี้ทีมพยาบาลจะเข้ามาช่วยขยับเปลี่ยนท่าให้ถูกต้องตามหลักการแพทย์ครับ",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⏰ เวลาที่บันทึก: {time.strftime('%H:%M:%S น.', time.localtime())}",
        "(ระบบ AI Smart Ward เพื่อความอุ่นใจของครอบครัวผู้ป่วย)",
    ]
    return "\n".join(lines)


def format_family_test_message(patient_id: str) -> str:
    """AI-curated welcome test message specifically explaining bed isolation for relatives."""
    p_info = _get_patient_details(patient_id)
    lines = [
        "✅ [ทดสอบระบบแจ้งเตือนสำหรับญาติผู้ป่วย]",
        "🏥 SMART WARD · เชื่อมต่อสำเร็จเรียบร้อย",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🛏️ เตียงผู้ป่วยของคุณ: {p_info['bed_label']}",
        f"👤 สมาชิกครอบครัว: ผู้ดูแลและญาติผู้ป่วยเตียง {patient_id}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔒 การจัดระเบียบแยกเตียง (Bed Isolation):",
        f"• ระบบนี้จะส่งเฉพาะการแจ้งเตือนของ 'เตียง {patient_id}' เท่านั้น",
        "• ข้อมูลผู้ป่วยเตียงอื่นจะไม่ถูกส่งมารบกวน เพื่อความเป็นส่วนตัวและความชัดเจนสูงสุด",
        "",
        "🤖 AI จัดการข้อมูลสำหรับญาติ:",
        "• AI จะคัดกรองข้อมูลสำคัญและแปลงเป็นภาษาที่เข้าใจง่าย อบอุ่น และชัดเจน",
        "• ไม่ใช้ศัพท์เทคนิคที่น่ากลัว เพื่อให้ญาติทราบสถานะจริงโดยไม่ต้องตื่นตระหนก",
        "",
        "🩺 ความปลอดภัย:",
        "ทีมพยาบาลและแพทย์ดูแลผู้ป่วยตลอด 24 ชั่วโมง ระบบนี้ส่งข้อมูลเพื่อให้ครอบครัวอุ่นใจเสมือนอยู่ข้างเตียงตลอดเวลา",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⏰ เวลาทดสอบ: {time.strftime('%H:%M:%S น.', time.localtime())}",
        "(ระบบ AI Smart Ward เพื่อความอุ่นใจของครอบครัวผู้ป่วย)",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Clinical Staff Message Formatters (สำหรับแพทย์และพยาบาลเวร)
# ─────────────────────────────────────────────────────────────────────────────

def format_vital_alert_message(
    patient_id: str,
    severity: str,
    reason: str,
    recommended_next_step: str,
    vitals: dict[str, Any] | None = None,
    news2_score: int | None = None,
) -> str:
    vitals = vitals or {}
    p_info = _get_patient_details(patient_id)
    severity_label = "วิกฤต (CRITICAL STAT)" if severity == "critical" else "เฝ้าระวัง (WARNING)"
    status_tag = "[วิกฤต]" if severity == "critical" else "[เฝ้าระวัง]"

    lines = [
        f"[SMART WARD · การแจ้งเตือนผู้ป่วย {status_tag}]",
        f"เตียงผู้ป่วย: {patient_id} ({p_info['bed_label']})",
        f"ผู้ป่วย: {p_info['patient_name']} ({p_info.get('age', 70)} ปี, {p_info.get('gender', 'Male')})",
        f"แพทย์เจ้าของไข้: {p_info['doctor_name']}",
        f"การวินิจฉัยหลัก: {p_info.get('condition', '-')}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"ระดับความสำคัญ: {severity_label}",
        f"สาเหตุ: {reason}",
    ]
    if vitals:
        hr = vitals.get("heart_rate")
        spo2 = vitals.get("spo2")
        rr = vitals.get("respiratory_rate")
        vital_parts = []
        if hr is not None:
            hr_tag = " [Tachycardia]" if hr > 100 else " [Bradycardia]" if hr < 60 else ""
            vital_parts.append(f"HR {hr} bpm{hr_tag}")
        if spo2 is not None:
            spo2_tag = " [Hypoxemia]" if spo2 < 92 else ""
            vital_parts.append(f"SpO₂ {spo2}%{spo2_tag}")
        if rr is not None:
            rr_tag = " [Tachypnea]" if rr > 20 else ""
            vital_parts.append(f"RR {rr} ครั้ง/นาที{rr_tag}")
        if vital_parts:
            lines.append("สัญญาณชีพล่าสุด: " + " · ".join(vital_parts))

    if news2_score is not None:
        risk_tier = "High Risk" if news2_score >= 7 else "Medium Risk" if news2_score >= 5 else "Low Risk"
        lines.append(f"Modified NEWS2 Score: {news2_score} คะแนน [{risk_tier}]")

    if recommended_next_step:
        lines.append(f"คำแนะนำ: {recommended_next_step}")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"เวลา: {time.strftime('%H:%M:%S น.', time.localtime())}",
        "ระบบช่วยตัดสินใจทางการพยาบาล · ตรวจสอบผู้ป่วยจริงก่อนดำเนินการ",
    ])
    return "\n".join(lines)


def format_posture_alert_message(
    patient_id: str,
    posture: str,
    dwell_minutes: int,
    hotspot: str = "ก้นกบ (Sacrum) > 42 mmHg",
    braden_score: int = 11,
) -> str:
    p_info = _get_patient_details(patient_id)
    posture_th = translate_posture(posture)
    hotspot_desc, _ = get_anatomical_hotspot(posture, hotspot)
    lines = [
        "[SMART WARD · แจ้งเตือนรอบพลิกตัวและแผลกดทับ]",
        f"เตียงผู้ป่วย: {patient_id} ({p_info['bed_label']})",
        f"ผู้ป่วย: {p_info['patient_name']} · การเคลื่อนไหว: {p_info.get('mobility', '-')}",
        "━━━━━━━━━━━━━━━━━━━━",
        "ระดับความสำคัญ: ถึงกำหนดพลิกตัวทันที (CRITICAL DUE)",
        f"สถานะ: อยู่ท่า {posture_th} สะสม {dwell_minutes} นาที (เกินเกณฑ์ 2 ชม.)",
        f"จุดรับแรงกดวิกฤต: {hotspot_desc}",
        f"เกณฑ์ประเมิน: Braden Scale {braden_score}/23 (กลุ่มเสี่ยงสูง - High Risk)",
        "คำแนะนำทางการพยาบาล (EPUAP Standard): จัดท่านอนตะแคงกึ่งหงาย 30 องศา (30° Lateral Tilt) สลับซ้าย-ขวา หนุนหมอนรองหลังและหว่างขา หลีกเลี่ยงการนอนตะแคง 90° ตรงปุ่มกระดูกสะโพก",
        "━━━━━━━━━━━━━━━━━━━━",
        f"เวลา: {time.strftime('%H:%M:%S น.', time.localtime())}",
        "ระบบช่วยตัดสินใจทางการพยาบาล · ตรวจสอบผู้ป่วยจริงก่อนดำเนินการ",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Dispatchers & Mobile Channels (LINE Messaging API & Telegram)
# ─────────────────────────────────────────────────────────────────────────────

def send_line_messaging_api(message: str, channel_token: str | None = None) -> tuple[bool, str]:
    """Send broadcast message via official LINE Messaging API (LINE Official Account / Bot).

    Broadcast delivers the message to all users who added the bot as a friend.
    """
    token = (channel_token or os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    if not token:
        return False, "LINE_CHANNEL_ACCESS_TOKEN not configured"

    if len(token) == 32:
        return False, "รหัสที่ระบุมีความยาว 32 ตัวอักษร (Channel secret) ระบบต้องการ 'Channel access token (long-lived)' ซึ่งได้จากการกดปุ่ม Issue ในแท็บ Messaging API ของ LINE Developers ครับ"

    url = "https://api.line.me/v2/bot/message/broadcast"
    payload = json.dumps({"messages": [{"type": "text", "text": message}]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return response.status in (200, 202), "ส่งการแจ้งเตือนเข้า LINE สำเร็จเรียบร้อย (Broadcast สำเร็จ)"
    except urllib.error.HTTPError as error:
        err_msg = error.read().decode("utf-8", errors="replace")
        log.error("LINE Messaging API error: %d %s", error.code, err_msg)
        if error.code == 401:
            return False, "LINE แจ้งว่ารหัส Token ไม่ถูกต้อง (401 Unauthorized): กรุณาตรวจดูว่าเป็น 'Channel access token (long-lived)' ในแท็บ Messaging API หรือไม่"
        return False, f"LINE API HTTP {error.code}: {err_msg}"
    except Exception as error:
        log.error("Failed to send LINE Messaging API message: %s", error)
        return False, str(error)


def send_telegram(message: str, bot_token: str | None = None, chat_id: str | None = None) -> tuple[bool, str]:
    """Send message via Telegram Bot API (Instant 100% free mobile notifications)."""
    token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    cid = (chat_id or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not cid:
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": cid, "text": message}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return response.status == 200, "ส่งข้อความ Telegram สำเร็จ"
    except urllib.error.HTTPError as error:
        err_msg = error.read().decode("utf-8", errors="replace")
        log.error("Telegram error: %d %s", error.code, err_msg)
        return False, f"Telegram HTTP {error.code}: {err_msg}"
    except Exception as error:
        log.error("Failed to send Telegram message: %s", error)
        return False, str(error)


def send_line_notify(message: str, token: str | None = None) -> tuple[bool, str]:
    """Legacy LINE Notify fallback."""
    resolved_token = (token or os.getenv("LINE_NOTIFY_TOKEN") or "").strip()
    if not resolved_token:
        return False, "LINE_NOTIFY_TOKEN not configured"

    url = "https://notify-api.line.me/api/notify"
    data = urllib.parse.urlencode({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {resolved_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status == 200, body
    except urllib.error.HTTPError as error:
        err_msg = error.read().decode("utf-8", errors="replace")
        return False, f"LINE Notify HTTP {error.code}: {err_msg}"
    except Exception as error:
        return False, str(error)


def send_notification(message: str) -> tuple[bool, str]:
    """Dispatch to all configured active channels (LINE Messaging API, Telegram, LINE Notify)."""
    results: list[str] = []
    success_any = False

    # 1. Try LINE Messaging API (LINE Official Account / Bot)
    if (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip():
        ok, msg = send_line_messaging_api(message)
        results.append(f"LINE Bot: {msg}")
        if ok:
            success_any = True

    # 2. Try Telegram Bot
    if (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() and (os.getenv("TELEGRAM_CHAT_ID") or "").strip():
        ok, msg = send_telegram(message)
        results.append(f"Telegram: {msg}")
        if ok:
            success_any = True

    # 3. Try legacy LINE Notify if token present
    if (os.getenv("LINE_NOTIFY_TOKEN") or "").strip():
        ok, msg = send_line_notify(message)
        results.append(f"LINE Notify: {msg}")
        if ok:
            success_any = True

    if not results:
        return False, "ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN ใน backend/.env"
    return success_any, " | ".join(results)


def send_test_message(
    patient_id: str | None = None,
    audience: str | None = None,
    alert_type: str = "test",
) -> tuple[bool, str]:
    """Send a test message to verify active channels.
    
    Defaults to Family Audience for the configured target bed.
    """
    pid = patient_id or get_target_bed()
    aud = audience or get_audience_mode()

    if aud == "family":
        if alert_type == "posture":
            msg = format_family_posture_alert_message(
                patient_id=pid,
                posture="นอนหงาย",
                dwell_minutes=125,
                hotspot="ก้นกบ (Sacrum Hotspot > 42 mmHg)",
                braden_score=11,
            )
        elif alert_type == "vital":
            msg = format_family_vital_message(
                patient_id=pid,
                severity="critical",
                reason="ระดับออกซิเจนในเลือดลดลงชั่วคราว",
                recommended_next_step="เข้าตรวจประเมินทางเดินหายใจ ให้ออกซิเจน และวัดซ้ำ",
                vitals={"heart_rate": 110, "spo2": 88, "respiratory_rate": 22},
                news2_score=7,
            )
        else:
            msg = format_family_test_message(pid)
    else:
        if alert_type == "posture":
            msg = format_posture_alert_message(
                patient_id=pid,
                posture="นอนหงาย",
                dwell_minutes=125,
                hotspot="ก้นกบ (Sacrum Hotspot > 42 mmHg)",
                braden_score=11,
            )
        elif alert_type == "vital":
            msg = format_vital_alert_message(
                patient_id=pid,
                severity="critical",
                reason="SpO₂ ลดลงฉับพลัน (87%) ร่วมกับชีพจรเต้นเร็ว (112 bpm)",
                recommended_next_step="เข้าตรวจประเมินทางเดินหายใจ ให้ออกซิเจน และวัดซ้ำทันที",
                vitals={"heart_rate": 112, "spo2": 87, "respiratory_rate": 24},
                news2_score=7,
            )
        else:
            p_info = _get_patient_details(pid)
            msg = (
                "[SMART WARD · ทดสอบการแจ้งเตือนมือถือสำหรับเจ้าหน้าที่]\n"
                f"เตียงผู้ป่วย: {pid} ({p_info['bed_label']})\n"
                f"ผู้ป่วย: {p_info['patient_name']} · แพทย์ผู้ดูแล: {p_info['doctor_name']}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "สถานะ: ระบบ Smart Ward เชื่อมต่อกับโทรศัพท์มือถือสำเร็จเรียบร้อย\n"
                "พร้อมรับการแจ้งเตือนระดับคลินิก (SpO₂ ตก, Modified NEWS2, เซนเซอร์หลุด, รอบพลิกตัว EPUAP 2h)\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"เวลาทดสอบ: {time.strftime('%H:%M:%S น.', time.localtime())}"
            )
    return send_notification(msg)


def dispatch_alert(
    patient_id: str,
    severity: str,
    reason: str,
    recommended_next_step: str,
    vitals: dict[str, Any] | None = None,
    news2_score: int | None = None,
    alert_type: str = "vital",
    extra: dict[str, Any] | None = None,
) -> bool:
    """Non-blocking dispatch with Bed Isolation filtering and deduplication cooldown.
    
    1. Bed Isolation: If family audience is active, only sends alerts matching target bed(s).
       Alerts for other beds are ignored so relatives do not see other patients' data.
    2. AI Synthesis: Prepares reassuring, clear message for relatives.
    3. Cooldown: Prevents spamming alerts for the same condition.
    """
    if not is_configured():
        return False

    # Bed Isolation Check
    if not is_bed_allowed(patient_id):
        log.info(
            "Alert for bed %s filtered out: family channel is configured only for bed %s",
            patient_id,
            get_target_bed(),
        )
        return False

    now = time.time()
    event_key = f"{patient_id}:{reason[:30]}"
    if event_key in _last_sent and (now - _last_sent[event_key] < COOLDOWN_SECONDS):
        log.info("Mobile alert for %s throttled by cooldown", event_key)
        return False

    audience = get_audience_mode()

    if audience == "family":
        if alert_type == "posture":
            extra = extra or {}
            posture = extra.get("posture", "นอนหงาย")
            dwell_minutes = extra.get("dwell_minutes", 120)
            hotspot = extra.get("hotspot", "ก้นกบ (Sacrum) > 42 mmHg")
            braden = extra.get("braden_score", 11)
            message = format_family_posture_alert_message(patient_id, posture, dwell_minutes, hotspot, braden)
        else:
            message = format_family_vital_message(
                patient_id, severity, reason, recommended_next_step, vitals, news2_score
            )
    else:
        if alert_type == "posture":
            extra = extra or {}
            posture = extra.get("posture", "นอนหงาย")
            dwell_minutes = extra.get("dwell_minutes", 120)
            hotspot = extra.get("hotspot", "ก้นกบ (Sacrum) > 42 mmHg")
            braden = extra.get("braden_score", 11)
            message = format_posture_alert_message(patient_id, posture, dwell_minutes, hotspot, braden)
        else:
            message = format_vital_alert_message(
                patient_id, severity, reason, recommended_next_step, vitals, news2_score
            )

    success, _ = send_notification(message)
    if success:
        _last_sent[event_key] = now
    return success
