"""Guarded, asynchronous agent workflow for vital-sign events.

This module deliberately *proposes* an alert; it never contacts a clinician,
changes treatment, or mutates patient data.  A later Gemini tool-using agent can
enrich its explanation, but deterministic clinical guardrails remain the gate for
any workflow action.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any


@dataclass(frozen=True)
class VitalEvent:
    patient_id: str
    heart_rate: int
    spo2: int
    timestamp: float
    status: str
    is_anomaly: bool
    risk_percent: float | None
    model_requests_review: bool = False
    respiratory_rate: float | None = None
    source: str = "UNKNOWN"
    source_record: str | None = None
    analysis_status: str = "INSUFFICIENT_DATA"
    evaluated_at: float | None = None
    model_version: str = "bidmc-monitor-v1"
    forecast: dict[str, float] | None = None
    anomaly_score: float | None = None


class VitalAlertAgent:
    """Turns a high-risk vital event into a deduplicated alert proposal."""

    def __init__(self, cooldown_seconds: int = 60) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[tuple[str, str], float] = {}

    def assess(self, event: VitalEvent) -> dict[str, Any] | None:
        """Return a UI-safe alert proposal, or None when escalation is not needed."""
        severity: str | None = None
        reason: str | None = None

        if event.spo2 < 90:
            severity = "critical"
            reason = f"SpO2 {event.spo2}% is below the configured critical threshold."
        elif event.heart_rate < 50 or event.heart_rate > 120:
            severity = "critical"
            reason = f"Heart rate {event.heart_rate} bpm is outside the configured critical range."
        elif event.model_requests_review or (event.risk_percent is not None and event.risk_percent >= 70) or event.is_anomaly:
            severity = "warning"
            if event.model_requests_review:
                reason = "The evaluated research model reached its validation-derived review threshold."
            else:
                reason = "The risk model or anomaly detector requested clinical review."

        if not severity or not reason:
            return None

        from alert_episodes import kind
        key = (event.patient_id, kind(reason))
        now = time()
        if now - self._last_sent.get(key, 0) < self.cooldown_seconds:
            return None
        self._last_sent[key] = now

        return {
            "type": "agent_alert",
            "patient_id": event.patient_id,
            "severity": severity,
            "reason": reason,
            "episode_key": kind(reason),
            "vitals": {"heart_rate": event.heart_rate, "spo2": event.spo2},
            "risk_percent": event.risk_percent,
            "recommended_next_step": (
                "Verify the measurement and notify the assigned clinical team for assessment."
            ),
            "requires_human_review": True,
            "timestamp": event.timestamp,
        }
