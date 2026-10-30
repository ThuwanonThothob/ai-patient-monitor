"""Auditable role registry for the bounded AI care team.

The project calls these components agents because each one owns a small goal,
input contract and tool boundary.  They are deliberately not free-form LLM
personas.  The safety-critical path stays local and deterministic; Gemini may
explain evidence on demand but cannot approve clinical actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AgentRole:
    id: str
    name: str
    responsibility: str
    implementation: str
    automatic_actions: tuple[str, ...]
    human_gate: tuple[str, ...]
    event_sources: tuple[str, ...]


ROLES = (
    AgentRole(
        "telemetry_agent",
        "Telemetry Agent",
        "รับค่าสัญญาณชีพและจัดข้อมูลให้เป็นสัญญาเดียวกัน",
        "main.publish_monitor + NurseAgent trace",
        ("read_validated_vitals", "attach_source_and_timestamp"),
        (),
        ("vital_event",),
    ),
    AgentRole(
        "data_quality_agent",
        "Data Quality Agent",
        "ตรวจช่วงค่า ความใหม่ และหยุดการประเมินเมื่อข้อมูลไม่น่าเชื่อถือ",
        "NurseAgent local guard",
        ("validate_range", "validate_freshness", "abstain"),
        (),
        ("vital_event", "device_event"),
    ),
    AgentRole(
        "monitoring_agent",
        "Monitoring AI Agent",
        "อ่านผลโมเดลที่อนุมัติไว้และตรวจรูปแบบผิดปกติจากข้อมูลต่อเนื่อง",
        "MonitorWorker + bidmc-monitor-v1",
        ("read_model_result", "compare_thresholds", "propose_review"),
        ("diagnosis", "treatment_change"),
        ("vital_event",),
    ),
    AgentRole(
        "device_health_agent",
        "Device Health Agent",
        "ติดตาม heartbeat แบตเตอรี่ สัญญาณ เซนเซอร์หลุด และแผ่นแรงกด",
        "BedsideService + watchdog",
        ("detect_device_fault", "detect_stale_device", "propose_review"),
        ("repair_device", "declare_patient_emergency"),
        ("device_event", "pressure_map"),
    ),
    AgentRole(
        "care_coordinator_agent",
        "Care Coordinator Agent",
        "ติดตามเฉพาะแผนที่บุคลากรอนุมัติ สร้างรอบงาน และชี้งานเกินกำหนด",
        "care_api scheduler",
        ("materialize_approved_task", "count_overdue_tasks", "prioritize_open_work"),
        ("activate_care_plan", "complete_or_skip_task", "change_medication"),
        ("care_schedule", "vital_event"),
    ),
    AgentRole(
        "notification_agent",
        "Notification Agent",
        "ส่ง Web Push ที่ตั้งค่าไว้และบันทึกผลการส่งโดยไม่ส่งซ้ำ",
        "notifications dispatcher",
        ("enqueue_configured_push", "retry_delivery", "write_delivery_audit"),
        ("contact_doctor", "contact_emergency_service"),
        ("approved_alert",),
    ),
    AgentRole(
        "documentation_agent",
        "Documentation Agent",
        "สร้างหลักฐานการทำงานและร่างสรุปรายวันจากข้อมูลที่บันทึกไว้",
        "nurse_agent trace + daily_summary",
        ("write_agent_trace", "draft_evidence_summary"),
        ("sign_clinical_document", "edit_historical_measurement"),
        ("agent_decision", "daily_schedule"),
    ),
    AgentRole(
        "safety_supervisor",
        "Safety Supervisor Agent",
        "บังคับสิทธิ์ ตรวจข้อเสนอซ้ำ และส่งต่อการตัดสินใจเสี่ยงให้มนุษย์",
        "NurseAgent guarded policy + persistent episode dedupe",
        ("enforce_policy", "suppress_duplicate", "route_for_human_review"),
        ("diagnosis", "treatment_or_dose_change", "close_alert", "external_dispatch"),
        ("agent_decision",),
    ),
)

ROLE_BY_ID = {role.id: role for role in ROLES}

STEP_OWNER = {
    "observe_vitals": "telemetry_agent",
    "validate_data_contract": "data_quality_agent",
    "read_trained_model": "monitoring_agent",
    "read_reviewed_care_context": "care_coordinator_agent",
    "apply_guarded_alert_policy": "safety_supervisor",
    "document_decision": "documentation_agent",
}


def owner_for_step(tool_name: str) -> str:
    """Return a stable owner for an auditable workflow step."""
    return STEP_OWNER.get(tool_name, "safety_supervisor")


def team_manifest() -> dict[str, Any]:
    """JSON-only description used by the staff UI and project evidence."""
    return {
        "version": "care-agent-team-v1",
        "orchestrator": {
            "id": "care_team_orchestrator",
            "name": "Care Team Orchestrator",
            "strategy": "event-driven guarded routing",
            "cloud_llm_required": False,
        },
        "roles": [
            {
                **asdict(role),
                "automatic_actions": list(role.automatic_actions),
                "human_gate": list(role.human_gate),
                "event_sources": list(role.event_sources),
            }
            for role in ROLES
        ],
        "handoff": [
            "telemetry_agent",
            "data_quality_agent",
            "monitoring_agent",
            "care_coordinator_agent",
            "safety_supervisor",
            "notification_agent",
            "documentation_agent",
        ],
        "safety_contract": {
            "automatic_low_risk_work": True,
            "human_approval_for_clinical_action": True,
            "model_may_abstain": True,
            "all_actions_audited": True,
        },
    }
