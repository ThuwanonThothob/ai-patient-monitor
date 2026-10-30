"""Deterministic synthetic registry for the 60-bed Smart Ward demonstration.

No record in this module represents a real person or a real clinical record.
"""

from __future__ import annotations

import random


ZONE_LABELS = {
    "A": "Respiratory and high dependency",
    "B": "Cardiac and metabolic care",
    "C": "Neurological and long term care",
}

_TEMPLATES = {
    "A": (
        {"condition": "Chronic obstructive pulmonary disease", "hr": 84, "spo2": 94, "rr": 21, "episodes": ("desaturation", "tachycardia"), "risk": 0.012},
        {"condition": "Severe asthma", "hr": 82, "spo2": 96, "rr": 20, "episodes": ("desaturation", "tachycardia"), "risk": 0.011},
        {"condition": "Pneumonia recovery", "hr": 88, "spo2": 95, "rr": 22, "episodes": ("desaturation", "infection_stress"), "risk": 0.010},
        {"condition": "Post operative respiratory monitoring", "hr": 78, "spo2": 97, "rr": 17, "episodes": ("tachycardia",), "risk": 0.006},
    ),
    "B": (
        {"condition": "Congestive heart failure", "hr": 88, "spo2": 95, "rr": 19, "episodes": ("tachycardia", "desaturation"), "risk": 0.010},
        {"condition": "Cardiac arrhythmia", "hr": 86, "spo2": 96, "rr": 17, "episodes": ("tachycardia", "bradycardia"), "risk": 0.018},
        {"condition": "Diabetes and hypertension", "hr": 76, "spo2": 97, "rr": 16, "episodes": ("tachycardia",), "risk": 0.004},
        {"condition": "Acute coronary observation", "hr": 82, "spo2": 97, "rr": 18, "episodes": ("tachycardia",), "risk": 0.008},
    ),
    "C": (
        {"condition": "Stroke recovery", "hr": 74, "spo2": 97, "rr": 16, "episodes": ("tachycardia",), "risk": 0.005},
        {"condition": "Chronic kidney disease", "hr": 80, "spo2": 96, "rr": 17, "episodes": ("bradycardia", "tachycardia"), "risk": 0.007},
        {"condition": "Bedbound frailty care", "hr": 78, "spo2": 96, "rr": 17, "episodes": ("infection_stress", "desaturation"), "risk": 0.010},
        {"condition": "Dementia with aspiration risk", "hr": 76, "spo2": 95, "rr": 18, "episodes": ("desaturation", "infection_stress"), "risk": 0.009},
    ),
}

_BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
_DOCTORS = ("Dr. Wichai", "Dr. Napat", "Dr. Anong", "Dr. Kittisak")


def build_patient_registry() -> dict[str, dict]:
    registry: dict[str, dict] = {}
    for zone_index, zone in enumerate(("A", "B", "C")):
        rng = random.Random(20260922 + zone_index)
        templates = _TEMPLATES[zone]
        for bed_index in range(1, 21):
            template = templates[(bed_index - 1) % len(templates)]
            patient_id = f"{zone}{bed_index:03d}"
            age = rng.randint(48, 91)
            bedbound = zone == "C" or (zone == "A" and bed_index % 5 == 0)
            glucose = round(rng.uniform(92, 142) + (18 if "Diabetes" in template["condition"] else 0), 1)
            registry[patient_id] = {
                "patient_id": patient_id,
                "name": f"Synthetic Patient {patient_id}",
                "zone": zone,
                "zone_name": ZONE_LABELS[zone],
                "room_number": f"{zone}{100 + bed_index}",
                "bed_number": bed_index,
                "age": age,
                "gender": "Female" if bed_index % 2 == 0 else "Male",
                "blood_group": _BLOOD_GROUPS[(bed_index + zone_index) % len(_BLOOD_GROUPS)],
                "condition": template["condition"],
                "diagnoses": [template["condition"], "Bedbound care" if bedbound else "Mobility monitoring"],
                "mobility": "Bedbound" if bedbound else "Assisted mobility",
                "doctor": _DOCTORS[(bed_index + zone_index) % len(_DOCTORS)],
                "respiratory_rate": template["rr"],
                "sleep_hours": round(rng.uniform(4.5, 7.5), 1),
                "sleep_quality": ("Poor" if bedbound and bed_index % 3 == 0 else "Fair" if bed_index % 3 else "Good"),
                "blood_glucose_mg_dl": glucose,
                "cholesterol_mg_dl": rng.randint(145, 255),
                "ecg_rhythm": "Irregular rhythm" if "arrhythmia" in template["condition"].lower() else "Sinus rhythm",
                "simulation": {
                    "base_hr": template["hr"] + rng.uniform(-3, 3),
                    "base_spo2": template["spo2"] + rng.uniform(-0.7, 0.7),
                    "base_rr": template["rr"] + rng.uniform(-1, 1),
                    "episode_probability": template["risk"],
                    "episode_types": template["episodes"],
                },
            }
    return registry


PATIENT_PROFILES = build_patient_registry()

# Login-only demonstration identity. It is intentionally not part of
# PATIENT_PROFILES so ward capacity, triage and the 60-bed model input stay
# unchanged. This record has no fabricated live measurements.
TEST_PATIENT_PROFILES = {
    "TEST_P": {
        "patient_id": "TEST_P",
        "name": "ธุวานนธ์ ตอบโต้",
        "zone": "HOME",
        "zone_name": "Home care demonstration",
        "room_number": "DEMO-01",
        "bed_number": 1,
        "age": 70,
        "gender": "ไม่ระบุ",
        "blood_group": "ไม่ระบุ",
        "condition": "บัญชีสาธิตผู้ป่วยติดเตียง",
        "diagnoses": ["ภาวะอ่อนแรงในผู้สูงอายุ (ข้อมูลสาธิต)", "การดูแลผู้ป่วยติดเตียงที่บ้าน (ข้อมูลสาธิต)"],
        "mobility": "Bedbound demo",
        "doctor": "ธุวานนธ์ โต้ตอบ",
        "assigned_staff_id": "test_d",
        "care_setting": "บ้านสาธิต · Remote home care",
        "care_goal": "ติดตามสัญญาณชีพ การเปลี่ยนท่า และการสื่อสารกับทีมดูแล",
        "emergency_contact": "ญาติสาธิต · ไม่มีการโทรจริง",
        "respiratory_rate": 17,
        "sleep_hours": 6.5,
        "sleep_quality": "Fair (simulation)",
        "blood_glucose_mg_dl": 112,
        "cholesterol_mg_dl": 188,
        "ecg_rhythm": "Sinus rhythm (simulation)",
        "simulation": {
            "base_hr": 76,
            "base_spo2": 97,
            "base_rr": 17,
            "scenario": "home-care-demo-v1",
        },
    }
}

# Only the patient portal uses this registry for admission/profile display.
PATIENT_LOGIN_PROFILES = {**PATIENT_PROFILES, **TEST_PATIENT_PROFILES}


def get_patient_profile(patient_id: str) -> dict | None:
    return PATIENT_LOGIN_PROFILES.get(patient_id.upper())
