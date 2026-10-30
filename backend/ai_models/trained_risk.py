"""Runtime loader for the evaluated, versioned research model.

No training occurs here. This module accepts a selected patient record and
returns an explicit ``INSUFFICIENT_DATA`` state when the history does not meet
the feature contract instead of inventing a score.
"""

from __future__ import annotations

import math
import os
import json
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np

from ml_pipeline.physionet2012 import CORE_PARAMETERS, feature_names, summarize_measurements


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = BACKEND_DIR / "models" / "physionet2012_ward_core_v1.joblib"
MODEL_PATH = Path(os.getenv("RISK_MODEL_PATH", str(DEFAULT_MODEL_PATH))).expanduser()
MINIMUM_HISTORY_POINTS = 5
MINIMUM_FEATURE_COVERAGE = 0.80
_bundle_cache: tuple[int, Any] | None = None


def _as_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) and number >= 0 else math.nan


def _gender_code(value: Any) -> float:
    normalized = str(value or "").strip().lower()
    if normalized in {"male", "m", "1"}:
        return 1.0
    if normalized in {"female", "f", "0"}:
        return 0.0
    return math.nan


def _load_bundle() -> tuple[Any | None, str | None]:
    global _bundle_cache
    if not MODEL_PATH.is_file():
        return None, "MODEL_NOT_TRAINED"
    try:
        modified_at = MODEL_PATH.stat().st_mtime_ns
        if _bundle_cache and _bundle_cache[0] == modified_at:
            return _bundle_cache[1], None
        bundle = joblib.load(MODEL_PATH)
        if not hasattr(bundle, "predict_proba") or not hasattr(bundle, "feature_names"):
            return None, "INVALID_MODEL_ARTIFACT"
        _bundle_cache = (modified_at, bundle)
        return bundle, None
    except Exception:
        # Do not expose a path/exception which may reveal local details to the UI.
        return None, "MODEL_LOAD_FAILED"


def get_model_status() -> dict[str, Any]:
    bundle, error = _load_bundle()
    if error:
        return {
            "available": False,
            "status": error,
            "model_path": str(MODEL_PATH),
            "message": "No evaluated model artifact is loaded. Run the offline training pipeline first.",
        }
    metadata = dict(getattr(bundle, "metadata", {}))
    return {
        "available": True,
        "status": "READY",
        "model_path": str(MODEL_PATH),
        "model_version": metadata.get("model_version"),
        "endpoint": metadata.get("endpoint"),
        "profile": metadata.get("profile"),
        "holdout_test_metrics": metadata.get("holdout_test_metrics"),
        "research_only_notice": metadata.get("research_only_notice"),
        "runtime_requirements": metadata.get("runtime_requirements"),
    }


def get_model_benchmarks() -> dict[str, Any]:
    """List local, evaluated model cards without loading raw patient records."""
    benchmarks: list[dict[str, Any]] = []
    for metadata_path in sorted(MODEL_PATH.parent.glob("physionet2012_*_metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            benchmarks.append({
                "model_version": metadata.get("model_version"),
                "profile": metadata.get("profile"),
                "feature_count": metadata.get("feature_count"),
                "endpoint": metadata.get("endpoint"),
                "holdout_test_metrics": metadata.get("holdout_test_metrics"),
                "runtime_compatible": False,
                "research_only_notice": metadata.get("research_only_notice"),
            })
        except (OSError, ValueError, TypeError):
            continue
    return {"models": benchmarks, "research_only": True}


def _measurement_series(profile: dict[str, Any], history: Iterable[dict[str, Any]]) -> tuple[dict[str, list[tuple[float, float]]], int]:
    rows = list(history)
    timestamps = [_as_number(row.get("timestamp")) for row in rows]
    known_timestamps = [value for value in timestamps if math.isfinite(value)]
    first_timestamp = min(known_timestamps) if known_timestamps else 0.0
    series: dict[str, list[tuple[float, float]]] = {parameter: [] for parameter in CORE_PARAMETERS}

    age = _as_number(profile.get("age"))
    gender = _gender_code(profile.get("gender"))
    if math.isfinite(age):
        series["Age"].append((0.0, age))
    if math.isfinite(gender):
        series["Gender"].append((0.0, gender))

    mapping = {"HR": "heart_rate", "SaO2": "spo2", "RespRate": "respiratory_rate", "Glucose": "blood_glucose"}
    for index, row in enumerate(rows):
        raw_time = _as_number(row.get("timestamp"))
        time_hours = (raw_time - first_timestamp) / 3600.0 if math.isfinite(raw_time) else float(index)
        for parameter, key in mapping.items():
            value = _as_number(row.get(key))
            if math.isfinite(value):
                series[parameter].append((time_hours, value))

    # A declared simulation baseline is usable as a single value only. It never
    # replaces a missing current vital sign, which the coverage gate will catch.
    if not series["Glucose"]:
        baseline_glucose = _as_number(profile.get("blood_glucose_mg_dl"))
        if math.isfinite(baseline_glucose):
            series["Glucose"].append((0.0, baseline_glucose))
    return series, len(series["HR"])


def build_runtime_matrix(profile: dict[str, Any], history: Iterable[dict[str, Any]], expected_feature_names: list[str]) -> tuple[np.ndarray, float, int, list[str]]:
    """Build the exact feature contract used by the ward-core training profile."""
    series, vital_points = _measurement_series(profile, history)
    values: dict[str, float] = {}
    available_parameters: list[str] = []
    for parameter in CORE_PARAMETERS:
        summary = summarize_measurements(series[parameter])
        if any(math.isfinite(value) for value in summary.values()):
            available_parameters.append(parameter)
        for stat, value in summary.items():
            values[f"{parameter}__{stat}"] = value

    expected = feature_names(CORE_PARAMETERS)
    if expected_feature_names != expected:
        raise ValueError("The loaded artifact does not use the supported ward-core feature contract")
    matrix = np.asarray([[values[name] for name in expected_feature_names]], dtype=float)
    coverage = len(available_parameters) / len(CORE_PARAMETERS)
    missing = [parameter for parameter in CORE_PARAMETERS if parameter not in available_parameters]
    return matrix, coverage, vital_points, missing


def assess_patient_risk(profile: dict[str, Any], history: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a guarded research-model assessment for one selected patient ID."""
    # Five short samples cannot satisfy a first-48-hour ICU training contract.
    # SaO2 and pulse-oximeter SpO2 also cannot be silently interchanged.
    return {
        "status": "UNSUPPORTED_CONTEXT", "risk_percent": None, "research_only": True,
        "message": "โมเดล mortality ต้องใช้ข้อมูล ICU 48 ชั่วโมงตามเงื่อนไขชุดฝึก จึงไม่ใช้คำนวณกับข้อมูล monitor ระยะสั้น",
        "endpoint": "Historical ICU mortality benchmark only",
    }
