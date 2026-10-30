"""Deterministic evaluation scenarios for the guarded alert workflow.

These tests validate software behaviour against synthetic cases. They are not
clinical validation and must never be presented as evidence of medical safety.
"""

from __future__ import annotations

from .agent_workflow import VitalAlertAgent, VitalEvent


SCENARIOS = (
    {
        "id": "stable_baseline",
        "label": "Stable baseline",
        "heart_rate": 78,
        "spo2": 98,
        "risk_percent": 12,
        "is_anomaly": False,
        "expected_severity": None,
    },
    {
        "id": "desaturation",
        "label": "Critical desaturation",
        "heart_rate": 108,
        "spo2": 87,
        "risk_percent": 80,
        "is_anomaly": False,
        "expected_severity": "critical",
    },
    {
        "id": "tachycardia",
        "label": "Critical tachycardia",
        "heart_rate": 132,
        "spo2": 97,
        "risk_percent": 78,
        "is_anomaly": False,
        "expected_severity": "critical",
    },
    {
        "id": "bradycardia",
        "label": "Critical bradycardia",
        "heart_rate": 45,
        "spo2": 96,
        "risk_percent": 72,
        "is_anomaly": False,
        "expected_severity": "critical",
    },
    {
        "id": "anomaly_review",
        "label": "Anomaly review",
        "heart_rate": 90,
        "spo2": 97,
        "risk_percent": 34,
        "is_anomaly": True,
        "expected_severity": "warning",
    },
    {
        "id": "high_risk_review",
        "label": "High model-risk review",
        "heart_rate": 94,
        "spo2": 96,
        "risk_percent": 75,
        "is_anomaly": False,
        "expected_severity": "warning",
    },
)


def run_alert_workflow_evaluation() -> dict:
    """Run each case with a new agent so cooldowns cannot affect results."""
    results = []
    for index, scenario in enumerate(SCENARIOS, start=1):
        agent = VitalAlertAgent(cooldown_seconds=0)
        proposal = agent.assess(VitalEvent(
            patient_id=f"TEST{index:03d}",
            heart_rate=scenario["heart_rate"],
            spo2=scenario["spo2"],
            timestamp=float(index),
            status="NORMAL",
            is_anomaly=scenario["is_anomaly"],
            risk_percent=scenario["risk_percent"],
        ))
        actual = proposal["severity"] if proposal else None
        results.append({
            "id": scenario["id"],
            "label": scenario["label"],
            "input": {
                "heart_rate": scenario["heart_rate"],
                "spo2": scenario["spo2"],
                "risk_percent": scenario["risk_percent"],
                "is_anomaly": scenario["is_anomaly"],
            },
            "expected_severity": scenario["expected_severity"],
            "actual_severity": actual,
            "passed": actual == scenario["expected_severity"],
        })
    passed = sum(result["passed"] for result in results)
    return {
        "kind": "synthetic_workflow_evaluation",
        "clinical_validation": False,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
        "note": "These synthetic cases verify alert-routing rules only; they do not measure clinical accuracy.",
    }
