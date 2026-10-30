from __future__ import annotations

from functools import lru_cache
from typing import Any
import numpy as np
from sklearn.ensemble import IsolationForest


class VitalQualityResult(dict):
    """Dictionary representing the outcome of a clinical vital signal quality check."""

    @property
    def abstain(self) -> bool:
        return bool(self.get("abstain", False))

    @property
    def is_device_fault(self) -> bool:
        return bool(self.get("is_device_fault", False))

    @property
    def reason(self) -> str:
        return str(self.get("reason", ""))

    @property
    def is_crisis(self) -> bool:
        return bool(self.get("is_crisis", False))

    @property
    def message(self) -> str:
        return str(self.get("message", ""))


def check_vital_quality_gate(
    hr: float | None,
    spo2: float | None,
    previous_hr: float | None = None,
    time_delta: float = 1.0,
    respiratory_rate: float | None = None,
) -> VitalQualityResult:
    """Evaluate whether vital readings should be processed or abstained due to sensor/artifact issues.

    Clinical Quality Gate rules:
    - Sensor disconnect / missing: hr <= 0, spo2 <= 0, or non-finite values -> abstain=True, is_device_fault=True, is_crisis=False
    - Extreme SpO2 artifact / probe off-body: spo2 < 50% or spo2 > 100% -> abstain=True, is_device_fault=True, is_crisis=False
    - Extreme sudden HR jump (artifact/lead-off spike): abs(hr - previous_hr) > 50 bpm within 1 second -> abstain=True, is_device_fault=True, is_crisis=False
    - Non-physiological limits: hr < 20 or hr > 260 -> abstain=True, is_device_fault=True, is_crisis=False

    Returns:
        VitalQualityResult with abstain=True, is_device_fault=True, and is_crisis=False on equipment issues.
    """
    if hr is None or spo2 is None or not np.isfinite(hr) or not np.isfinite(spo2):
        return VitalQualityResult({
            "abstain": True,
            "is_device_fault": True,
            "is_crisis": False,
            "reason": "SENSOR_DISCONNECTED",
            "message": "สัญญาณชีพขาดหายหรือค่าไม่สมบูรณ์ (Sensor Disconnected)",
        })

    # Sensor detached or fallen off (0 value)
    if hr <= 0 or spo2 <= 0:
        return VitalQualityResult({
            "abstain": True,
            "is_device_fault": True,
            "is_crisis": False,
            "reason": "SENSOR_DETACHED_ZERO_READING",
            "message": "ตรวจพบค่าศูนย์ เซนเซอร์อาจหลุดจากร่างกาย (Sensor Detached)",
        })

    # Extreme SpO2 artifact / probe off-body (SpO2 < 50%)
    if spo2 < 50.0:
        return VitalQualityResult({
            "abstain": True,
            "is_device_fault": True,
            "is_crisis": False,
            "reason": "SENSOR_DETACHED_LOW_SPO2",
            "message": f"SpO2 ต่ำกว่า 50% ({spo2:.1f}%) บ่งชี้ว่าหัววัดหลุดหรือสัญญาณรบกวนแสง (Sensor Off-body / Artifact)",
        })

    # Physiologically impossible SpO2 (> 100%)
    if spo2 > 100.0:
        return VitalQualityResult({
            "abstain": True,
            "is_device_fault": True,
            "is_crisis": False,
            "reason": "PHYSIOLOGICALLY_IMPOSSIBLE_SPO2",
            "message": f"SpO2 เกิน 100% ({spo2:.1f}%) เป็นค่าที่เป็นไปไม่ได้ทางสรีรวิทยา (Sensor Artifact)",
        })

    # Extreme sudden HR jump (> 50 bpm in 1 second)
    if previous_hr is not None and np.isfinite(previous_hr) and time_delta > 0:
        rate_of_change = abs(hr - previous_hr) / time_delta
        if rate_of_change > 50.0:
            return VitalQualityResult({
                "abstain": True,
                "is_device_fault": True,
                "is_crisis": False,
                "reason": "EXTREME_HR_DELTA_ARTIFACT",
                "message": f"อัตราเต้นหัวใจเปลี่ยนฉับพลัน {rate_of_change:.1f} bpm/s เกินขีดจำกัดทางสรีรวิทยา บ่งชี้สัญญาณรบกวน (Motion Artifact / Spike)",
            })

    # Non-physiological heart rate limits
    if hr < 20 or hr > 260:
        return VitalQualityResult({
            "abstain": True,
            "is_device_fault": True,
            "is_crisis": False,
            "reason": "PHYSIOLOGICALLY_IMPOSSIBLE_HR",
            "message": f"HR {hr:.0f} bpm อยู่นอกช่วงสรีรวิทยาที่เป็นไปได้ (Equipment / Lead Fault)",
        })

    # Respiratory rate check if provided
    if respiratory_rate is not None and np.isfinite(respiratory_rate):
        if respiratory_rate <= 0 or respiratory_rate > 80:
            return VitalQualityResult({
                "abstain": True,
                "is_device_fault": True,
                "is_crisis": False,
                "reason": "RESPIRATORY_SENSOR_FAULT",
                "message": f"อัตราการหายใจ {respiratory_rate:.0f} ครั้ง/นาที ผิดปกติจากอุปกรณ์",
            })

    return VitalQualityResult({
        "abstain": False,
        "is_device_fault": False,
        "is_crisis": False,
        "reason": "QUALITY_PASS",
        "message": "ผ่านการตรวจสอบคุณภาพข้อมูลสัญญาณชีพ",
    })


check_abstention = check_vital_quality_gate
validate_vital_signal = check_vital_quality_gate


def evaluate_forecast_error_bounds(
    actuals: Any,
    predictions: Any,
    clinical_tolerance: float = 5.0,
) -> dict[str, Any]:
    """Calculate stratified forecast error bounds and clinical tolerance exceedance.

    Metrics:
    - mae: Mean Absolute Error
    - rmse: Root Mean Squared Error
    - p95_abs_error: 95th percentile of absolute error (|actual - pred|)
    - exceed_tolerance_rate: Proportion of points where |actual - pred| > clinical_tolerance

    If inputs are empty, have mismatched lengths, or contain NaN/Inf:
    returns {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}
    """
    if actuals is None or predictions is None:
        return {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}

    try:
        y_true = np.asarray(actuals, dtype=float)
        y_pred = np.asarray(predictions, dtype=float)
    except (ValueError, TypeError):
        return {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}

    if y_true.size == 0 or y_pred.size == 0:
        return {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}

    if y_true.size != y_pred.size or y_true.shape != y_pred.shape:
        return {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}

    y_true = y_true.ravel()
    y_pred = y_pred.ravel()

    if not np.all(np.isfinite(y_true)) or not np.all(np.isfinite(y_pred)):
        return {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}

    if clinical_tolerance is None or not np.isfinite(clinical_tolerance) or clinical_tolerance < 0:
        return {"abstain": True, "reason": "INVALID_EVALUATION_INPUT"}

    abs_errors = np.abs(y_true - y_pred)
    mae = float(np.mean(abs_errors))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    p95_abs_error = float(np.percentile(abs_errors, 95))
    exceed_tolerance_rate = float(np.mean(abs_errors > float(clinical_tolerance)))

    return {
        "abstain": False,
        "mae": mae,
        "rmse": rmse,
        "p95_abs_error": p95_abs_error,
        "exceed_tolerance_rate": exceed_tolerance_rate,
        "clinical_tolerance": float(clinical_tolerance),
        "sample_count": int(len(abs_errors)),
    }


def check_temporal_and_flatline_gate(
    window: Any,
    timestamps: Any = None,
    required_length: int = 60,
    check_flatline: bool = False,
) -> VitalQualityResult:
    """Evaluate window completeness and temporal continuity before model inference.

    Clinical Quality Gate rules:
    - Incomplete window: len(window) < required_length -> abstain=True, reason="INSUFFICIENT_WINDOW_LENGTH"
    - Non-monotonic timestamps: t[i] <= t[i-1] -> abstain=True, reason="TEMPORAL_DISCONTINUITY"
    - Discontinuous gap: t[i] - t[i-1] > 5 seconds -> abstain=True, reason="TEMPORAL_DISCONTINUITY"
    - Flatline (optional): if check_flatline is True and all values in window are identical -> abstain=True, reason="FLATLINE_DETECTED"

    Returns:
        VitalQualityResult with abstain=False if valid, or abstain=True with appropriate reason.
    """
    if window is None:
        return VitalQualityResult({
            "abstain": True,
            "reason": "INSUFFICIENT_WINDOW_LENGTH",
            "is_device_fault": True,
            "is_crisis": False,
            "message": "หน้าต่างข้อมูลขาดหาย (None window)",
        })

    try:
        w_len = len(window)
    except TypeError:
        return VitalQualityResult({
            "abstain": True,
            "reason": "INSUFFICIENT_WINDOW_LENGTH",
            "is_device_fault": True,
            "is_crisis": False,
            "message": "หน้าต่างข้อมูลไม่สามารถวัดความยาวได้",
        })

    if w_len < required_length:
        return VitalQualityResult({
            "abstain": True,
            "reason": "INSUFFICIENT_WINDOW_LENGTH",
            "is_device_fault": True,
            "is_crisis": False,
            "message": f"จำนวนจุดข้อมูล ({w_len}) น้อยกว่าเกณฑ์ขั้นต่ำ ({required_length})",
            "length": w_len,
            "required_length": required_length,
        })

    if timestamps is not None:
        try:
            t = np.asarray(timestamps, dtype=float)
        except (ValueError, TypeError):
            return VitalQualityResult({
                "abstain": True,
                "reason": "TEMPORAL_DISCONTINUITY",
                "is_device_fault": True,
                "is_crisis": False,
                "message": "รูปแบบ timestamps ไม่ถูกต้อง",
            })

        if t.size != w_len:
            return VitalQualityResult({
                "abstain": True,
                "reason": "TEMPORAL_DISCONTINUITY",
                "is_device_fault": True,
                "is_crisis": False,
                "message": f"ความยาว timestamps ({t.size}) ไม่ตรงกับความยาวหน้าต่าง ({w_len})",
            })

        if not np.all(np.isfinite(t)):
            return VitalQualityResult({
                "abstain": True,
                "reason": "TEMPORAL_DISCONTINUITY",
                "is_device_fault": True,
                "is_crisis": False,
                "message": "พบค่า timestamp ที่ไม่เป็นตัวเลขที่ถูกต้อง (NaN/Inf)",
            })

        if len(t) > 1:
            diffs = np.diff(t)
            # Non-monotonic or reversed/duplicate timestamps (t[i] <= t[i-1])
            if np.any(diffs <= 0):
                return VitalQualityResult({
                    "abstain": True,
                    "reason": "TEMPORAL_DISCONTINUITY",
                    "is_device_fault": True,
                    "is_crisis": False,
                    "message": "เวลาไม่เรียงลำดับเพิ่มขึ้นอย่างต่อเนื่อง (t[i] <= t[i-1])",
                })

            # Time gap > 5 seconds
            if np.any(diffs > 5.0):
                max_gap = float(np.max(diffs))
                return VitalQualityResult({
                    "abstain": True,
                    "reason": "TEMPORAL_DISCONTINUITY",
                    "is_device_fault": True,
                    "is_crisis": False,
                    "message": f"ตรวจพบช่องว่างเวลาขาดหาย {max_gap:.2f} วินาที (เกินเกณฑ์ 5 วินาที)",
                })

    if check_flatline:
        w_arr = np.asarray(window, dtype=float)
        if np.all(np.isfinite(w_arr)) and np.ptp(w_arr) == 0:
            return VitalQualityResult({
                "abstain": True,
                "reason": "FLATLINE_DETECTED",
                "is_device_fault": True,
                "is_crisis": False,
                "message": "ตรวจพบสัญญาณนิ่งสนิทไร้การเปลี่ยนแปลง (Flatline Detected)",
            })

    return VitalQualityResult({
        "abstain": False,
        "reason": "QUALITY_PASS",
        "is_device_fault": False,
        "is_crisis": False,
        "message": "ผ่านการตรวจสอบความต่อเนื่องของเวลาและความยาวหน้าต่างข้อมูล",
        "sample_count": w_len,
    })


@lru_cache(maxsize=1)
def _get_model() -> IsolationForest:
    # Prototype model for standalone tests; production ward monitoring uses monitor_model.py
    model = IsolationForest(contamination=0.05, random_state=42)
    normal_data = [
        [70, 98], [75, 99], [80, 97], [85, 98], [65, 96],
        [72, 98], [78, 99], [82, 97], [68, 98], [74, 99]
    ]
    X_train = np.array(normal_data * 10)
    model.fit(X_train)
    return model


def detect_anomaly(hr: int, spo2: int) -> bool:
    """
    รับค่าปัจจุบันมาตรวจสอบว่า "แปลก" ไปจากปกติหรือไม่
    Return True ถ้าผิดปกติ, False ถ้าปกติ
    """
    try:
        model = _get_model()
        prediction = model.predict([[hr, spo2]])
        return bool(prediction[0] == -1)
    except Exception:
        return False