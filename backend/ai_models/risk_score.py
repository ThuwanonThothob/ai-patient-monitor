"""Compatibility wrappers around the offline-trained research model.

The former ten-row synthetic RandomForest has intentionally been removed.
Historical ICU mortality artifacts are offline benchmarks only; live ward
windows do not satisfy their 48-hour ICU contract and never receive a score.
"""

from __future__ import annotations

from typing import Any, Iterable

from .trained_risk import assess_patient_risk, get_model_benchmarks, get_model_status


def calculate_risk_assessment(profile: dict[str, Any], history: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return assess_patient_risk(profile, history)


def calculate_risk_score(hr: int, spo2: int, age: int = 50) -> float | None:
    """Legacy API for callers without patient history.

    It returns ``None`` because live ward readings do not meet the ICU model's
    training contract. New monitoring code uses ``monitor_model`` instead.
    """
    assessment = assess_patient_risk(
        {"age": age},
        [{"heart_rate": hr, "spo2": spo2, "timestamp": 0}],
    )
    return assessment.get("risk_percent")


__all__ = ["calculate_risk_assessment", "calculate_risk_score", "get_model_benchmarks", "get_model_status"]
