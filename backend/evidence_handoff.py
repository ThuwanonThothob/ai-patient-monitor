"""Grounded text draft for the existing ward: no LLM, no inferred diagnoses."""
from datetime import datetime, timezone
import math


def clock(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "ไม่มีเวลาอ้างอิง"
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def format_evidence_handoff(patient_id, profile, monitor):
    analysis = monitor.get("analysis", {})
    measured_at = monitor.get("timestamp")
    lines = ["Smart Ward — Evidence-grounded handoff / ร่างสรุปส่งเวร",
             "ต้องให้บุคลากรตรวจสอบก่อนใช้ ไม่ใช่คำสั่งรักษา", "",
             f"Patient ID: {patient_id}",
             f"Zone / Room: {profile.get('zone', '—')} / {profile.get('room_number', '—')}",
             "ทะเบียนและโรคใน profile เป็นข้อมูลสมมติ ไม่ใช่ label ของสัญญาณ BIDMC", "",
             "S — สถานการณ์", f"Monitor status: {monitor.get('status', 'WAITING')}",
             f"Source: {monitor.get('source', 'WAITING')} / record {monitor.get('source_record', '—')}",
             f"Measured at (UTC): {clock(measured_at)}", "",
             "B — ค่าที่มีหลักฐานล่าสุด"]
    for key, label, unit in (("heart_rate", "HR", "bpm"), ("spo2", "SpO2", "%"), ("respiratory_rate", "RR", "breaths/min")):
        value = monitor.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            lines.append(f"{label}: {value:g} {unit} [source: {clock(measured_at)}]")
        else:
            lines.append(f"{label}: ไม่มีข้อมูล ไม่แทนด้วยค่าจากทะเบียน")
    lines += ["น้ำตาล ไขมัน ECG และการนอน: ไม่สรุปจากค่าทะเบียนสมมติว่าเป็นผลตรวจจริง", "",
              "A — ผลโมเดล", f"Analysis status: {analysis.get('status', 'INSUFFICIENT_DATA')}"]
    if analysis.get("status") == "READY" and monitor.get("status") != "STALE_DATA":
        lines.append(f"Evaluated at (UTC): {clock(analysis.get('evaluated_at'))}")
        if analysis.get("forecast"):
            lines.append(f"Forecast for (UTC): {clock(analysis.get('prediction_at'))}")
            for key, value in analysis["forecast"].items():
                if isinstance(value, (int, float)) and math.isfinite(value):
                    method = analysis.get("forecast_methods", {}).get(key, "see model metadata")
                    lines.append(f"{key}: {value:g} [{method}; forecast ไม่ใช่ค่าที่วัดแล้ว]")
        lines.append(f"Unusual pattern: {bool(analysis.get('is_anomaly'))} — ไม่ใช่การวินิจฉัยโรค")
    else:
        lines.append("งดแสดง forecast: ข้อมูลหรือผลวิเคราะห์ยังไม่พร้อม / เก่า / ขาดช่วง")
    lines += ["", "R — สิ่งที่ต้องทบทวน", "ตรวจเวลา แหล่งสัญญาณ และค่าที่ผิดปกติกับผู้ป่วย/อุปกรณ์ก่อนดำเนินการ",
              "ไม่มีการสรุปว่าเป็น sepsis และไม่มีการนำผล Research Lab มาใช้กับเตียงนี้",
              "ร่างนี้สร้างจากข้อมูลในระบบโดยตรง ไม่เรียก Gemini และไม่สร้างข้อเท็จจริงเพิ่มเติม"]
    return "\n".join(lines)
