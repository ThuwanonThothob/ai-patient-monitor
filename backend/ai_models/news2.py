"""Deterministic Modified NEWS2 (3-parameter) rule engine.

Implements Royal College of Physicians (RCP) NEWS2 Scale 1 scoring tables
strictly for the three continuously monitored parameters available in this
system:
- Respiratory Rate (breaths/min)
- SpO2 (%) — Scale 1 (room air / no hypercapnic respiratory failure)
- Heart Rate / Pulse (bpm)

No machine learning or unmeasured parameters (BP, temperature, consciousness,
supplemental O2) are fabricated. Any reading that fails the physiological/sensor
quality gate abstains immediately.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from .anomaly import check_vital_quality_gate
except ImportError:
    from ai_models.anomaly import check_vital_quality_gate

NEWS2_DISCLAIMER = (
    "Modified NEWS2 (3-variable sub-score: HR, SpO2, RR) "
    "สำหรับช่วยคัดกรองเบื้องต้น ไม่ใช่การวินิจฉัยทางการแพทย์"
)


def _is_valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def score_news2_rr(rr: float | None) -> int | None:
    """Score respiratory rate (breaths/min) per RCP NEWS2 table."""
    if not _is_valid_number(rr):
        return None
    val = float(rr)
    if val <= 0 or val > 60:
        return None
    if val <= 8:
        return 3
    if val <= 11:
        return 1
    if val <= 20:
        return 0
    if val <= 24:
        return 2
    return 3


def score_news2_spo2(spo2: float | None) -> int | None:
    """Score SpO2 (%) per RCP NEWS2 Scale 1 table."""
    if not _is_valid_number(spo2):
        return None
    val = float(spo2)
    if val < 50 or val > 100:
        return None
    if val <= 91:
        return 3
    if val <= 93:
        return 2
    if val <= 95:
        return 1
    return 0


def score_news2_hr(hr: float | None) -> int | None:
    """Score heart rate / pulse (bpm) per RCP NEWS2 table."""
    if not _is_valid_number(hr):
        return None
    val = float(hr)
    if val < 30 or val > 240:
        return None
    if val <= 40:
        return 3
    if val <= 50:
        return 1
    if val <= 90:
        return 0
    if val <= 110:
        return 1
    if val <= 130:
        return 2
    return 3


def calculate_modified_news2(
    hr: float | None,
    spo2: float | None,
    rr: float | None = None,
) -> dict[str, Any]:
    """Compute the deterministic 3-parameter Modified NEWS2 sub-score with quality gating."""
    gate = check_vital_quality_gate(hr, spo2, respiratory_rate=rr)
    if gate.abstain:
        return {
            "abstain": True,
            "reason": gate.reason,
            "total": None,
            "level": "ABSTAIN",
            "label_th": "งดประเมินคะแนน (ข้อมูลไม่ผ่านเกณฑ์คุณภาพ)",
            "hr_score": None,
            "spo2_score": None,
            "rr_score": None,
            "has_single_red": False,
            "parameters_used": 0,
            "disclaimer": NEWS2_DISCLAIMER,
        }

    hr_score = score_news2_hr(hr)
    spo2_score = score_news2_spo2(spo2)
    rr_score = score_news2_rr(rr) if rr is not None else None

    if hr_score is None or spo2_score is None or (rr is not None and rr_score is None):
        return {
            "abstain": True,
            "reason": "OUT_OF_BOUNDS_VITAL_SIGN",
            "total": None,
            "level": "ABSTAIN",
            "label_th": "งดประเมินคะแนน (ข้อมูลไม่ผ่านเกณฑ์คุณภาพ)",
            "hr_score": None,
            "spo2_score": None,
            "rr_score": None,
            "has_single_red": False,
            "parameters_used": 0,
            "disclaimer": NEWS2_DISCLAIMER,
        }

    scores = [s for s in (hr_score, spo2_score, rr_score) if s is not None]
    total = int(sum(scores))
    has_single_red = any(s == 3 for s in scores)
    parameters_used = 2 if rr is None else 3

    if total >= 7 or (total >= 5 and has_single_red):
        level = "HIGH"
        label_th = "ความเสี่ยงสูง (ควรแจ้งทีมพยาบาล/แพทย์ประเมินทันที)"
    elif total >= 5 or has_single_red:
        level = "MEDIUM"
        label_th = "ความเสี่ยงปานกลาง / พบค่าวิกฤตรายตัว (ควรเพิ่มความถี่ในการเฝ้าระวัง)"
    else:
        level = "LOW"
        label_th = "ความเสี่ยงต่ำ (เฝ้าระวังตามมาตรฐาน)"

    return {
        "abstain": False,
        "reason": "QUALITY_PASS",
        "total": total,
        "level": level,
        "label_th": label_th,
        "hr_score": hr_score,
        "spo2_score": spo2_score,
        "rr_score": rr_score,
        "has_single_red": has_single_red,
        "parameters_used": parameters_used,
        "disclaimer": NEWS2_DISCLAIMER,
    }
