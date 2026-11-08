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

try:
    from .anomaly import check_vital_quality_gate
    from .news2 import calculate_modified_news2
except ImportError:
    from ai_models.anomaly import check_vital_quality_gate
    from ai_models.news2 import calculate_modified_news2


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
        gate = check_vital_quality_gate(
            event.heart_rate,
            event.spo2,
            respiratory_rate=event.respiratory_rate,
        )
        if gate.abstain:
            return None

        news2 = calculate_modified_news2(
            event.heart_rate,
            event.spo2,
            event.respiratory_rate,
        )

        severity: str | None = None
        reason: str | None = None

        if event.spo2 < 90:
            severity = "critical"
            reason = f"SpO2 {event.spo2}% is below the configured critical threshold."
        elif event.heart_rate < 50 or event.heart_rate > 120:
            severity = "critical"
            reason = f"Heart rate {event.heart_rate} bpm is outside the configured critical range."
        elif event.respiratory_rate is not None and (event.respiratory_rate <= 8 or event.respiratory_rate >= 25):
            severity = "critical"
            reason = f"Respiratory rate {event.respiratory_rate}/min is outside the configured critical range (NEWS2 Red Score)."
        elif news2["level"] == "HIGH":
            severity = "critical"
            reason = f"Modified NEWS2 score {news2['total']} indicates high clinical risk."
        elif news2["level"] == "MEDIUM":
            severity = "warning"
            reason = f"Modified NEWS2 score {news2['total']} requests clinical review."
        elif event.model_requests_review or (event.risk_percent is not None and event.risk_percent >= 70) or event.is_anomaly:
            severity = "warning"
            if event.model_requests_review:
                reason = "The evaluated research model reached its validation-derived review threshold."
            else:
                reason = "The risk model or anomaly detector requested clinical review."

        if not severity or not reason:
            return None

        try:
            from alert_episodes import kind
            episode_key = kind(reason)
        except ImportError:
            episode_key = "model_review"
        key = (event.patient_id, episode_key)
        now = time()
        if now - self._last_sent.get(key, 0) < self.cooldown_seconds:
            return None
        self._last_sent[key] = now

        vitals: dict[str, Any] = {"heart_rate": event.heart_rate, "spo2": event.spo2}
        if event.respiratory_rate is not None:
            vitals["respiratory_rate"] = event.respiratory_rate

        return {
            "type": "agent_alert",
            "patient_id": event.patient_id,
            "severity": severity,
            "reason": reason,
            "episode_key": episode_key,
            "vitals": vitals,
            "modified_news2": news2,
            "risk_percent": event.risk_percent,
            "recommended_next_step": (
                "Verify the measurement and notify the assigned clinical team for assessment."
            ),
            "requires_human_review": True,
            "timestamp": event.timestamp,
        }

    def check_and_alert(
        self,
        patient_id: str,
        hr: float | None,
        spo2: float | None,
        rr: float | None = None,
    ) -> dict[str, Any]:
        """Evaluate vital signs with quality gate and Modified NEWS2 before generating alerts."""
        gate = check_vital_quality_gate(hr, spo2, respiratory_rate=rr)
        if gate.abstain:
            return {
                "alert": False,
                "abstain": True,
                "status": "INVALID_DATA",
                "reason": gate.reason,
                "message": gate.message,
                "modified_news2": calculate_modified_news2(hr, spo2, rr),
            }

        news2 = calculate_modified_news2(hr, spo2, rr)
        if (
            spo2 < 90
            or hr > 120
            or hr < 50
            or (rr is not None and (rr <= 8 or rr >= 25))
            or news2["level"] == "HIGH"
        ):
            status = "CRITICAL"
        elif spo2 < 94 or hr < 60 or hr > 100 or news2["level"] == "MEDIUM":
            status = "WARNING"
        else:
            status = "NORMAL"

        event = VitalEvent(
            patient_id=patient_id,
            heart_rate=int(round(float(hr))),
            spo2=int(round(float(spo2))),
            respiratory_rate=float(rr) if rr is not None else None,
            timestamp=time(),
            status=status,
            is_anomaly=False,
            risk_percent=None,
        )
        proposal = self.assess(event)
        return {
            "alert": status in ("CRITICAL", "WARNING") or proposal is not None,
            "abstain": False,
            "status": status,
            "patient_id": patient_id,
            "reason": proposal["reason"] if proposal else "NORMAL",
            "modified_news2": news2,
            "proposal": proposal,
        }
