#!/usr/bin/env python3
"""Idempotent seed script for Smart Ward demo accounts, 1-doctor-per-patient assignments,
and initial demonstration Care Plans, Care Tasks, and Care Profiles.

Safe to re-run at any time:
    python3 scripts/seed_demo_accounts.py
    python3 scripts/seed_demo_accounts.py --db backend/runtime/ward-demo.db
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


DEMO_CARE_PLANS = {
    "A001": (
        ("พลิกตัวและตรวจผิวหนังทุก 2 ชม.", "จัดท่าตะแคงสลับซ้าย-ขวา ตรวจจุดกดทับบริเวณก้นกบและส้นเท้า พร้อมบันทึกสภาพผิวหนัง", "ทีมพยาบาลเวร", 120),
        ("ตรวจตำแหน่งเซนเซอร์และค่าสัญญาณชีพ", "ตรวจสอบความกระชับของเซนเซอร์วัด SpO2 และแผ่นวัดแรงกดข้างเตียง พร้อมเทียบค่าสัญญาณชีพ", "นพ. วิชัย / ทีมพยาบาล", 60),
    ),
    "A002": (
        ("จัดท่านอนศีรษะสูงและสังเกตการหายใจ", "จัดท่าศีรษะสูง 30-45 องศา สังเกตจังหวะการหายใจ อาการเหนื่อยหอบ และค่าออกซิเจน", "ทีมพยาบาลเวร", 180),
    ),
    "A003": (
        ("ตรวจตำแหน่งเซนเซอร์และค่าสัญญาณชีพ", "ตรวจสอบความกระชับของเซนเซอร์วัด SpO2 และบันทึกการหายใจ", "ทีมพยาบาลเวร", 120),
    ),
    "A004": (
        ("พลิกตัวและตรวจผิวหนังทุก 2 ชม.", "จัดท่าตะแคงสลับซ้าย-ขวาและประเมินแผลกดทับตามแผนดูแล", "ทีมพยาบาลเวร", 120),
    ),
    "B001": (
        ("ตรวจตำแหน่งเซนเซอร์และค่าสัญญาณชีพ", "ติดตามอัตราการเต้นหัวใจและค่า SpO2 ตามรอบการดูแลผู้ป่วยโรคหัวใจ", "ทีมพยาบาลเวร", 60),
    ),
    "TEST_P": (
        ("พลิกตัวและตรวจผิวหนังทุก 2 ชม.", "จัดท่าผู้ป่วยติดเตียงที่บ้านและตรวจความกระชับของเซนเซอร์", "ธุวานนธ์ โต้ตอบ", 120),
    ),
}


def _seed_care_plans_and_profiles(db_file: Path) -> dict:
    now = time.time()
    seeded_plans = 0
    seeded_profiles = 0
    from patient_registry import PATIENT_LOGIN_PROFILES

    with closing(sqlite3.connect(db_file, timeout=15)) as conn, conn:
        for pid, plans in DEMO_CARE_PLANS.items():
            actor = "test_d" if pid == "TEST_P" else "doctor5"
            existing_plans = conn.execute(
                "SELECT COUNT(*) FROM care_plans WHERE patient_id=?",
                (pid,),
            ).fetchone()[0]
            if existing_plans == 0:
                for idx, (title, instructions, assigned_to, interval_min) in enumerate(plans):
                    due_time = now - 60 if idx == 0 else now + 1800
                    cur = conn.execute(
                        """INSERT INTO care_plans(
                               patient_id, title, instructions, assigned_to, interval_minutes,
                               next_due, state, version, created_at, created_by, reviewed_by, reviewed_at
                           ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', 2, ?, ?, ?, ?)""",
                        (pid, title, instructions, assigned_to, interval_min, due_time, now - 300, actor, actor, now - 240),
                    )
                    plan_id = cur.lastrowid
                    seeded_plans += 1
                    if due_time <= now:
                        conn.execute(
                            "INSERT OR IGNORE INTO care_tasks(plan_id, scheduled_at, state, version) VALUES (?, ?, 'PENDING', 1)",
                            (plan_id, due_time),
                        )
                    conn.execute(
                        "INSERT INTO care_events(patient_id, plan_id, action, actor, detail, created_at) VALUES (?, ?, 'PLAN_ACTIVE', ?, ?, ?)",
                        (pid, plan_id, actor, title, now - 240),
                    )

            existing_profile = conn.execute(
                "SELECT COUNT(*) FROM care_profile_versions WHERE patient_id=?",
                (pid,),
            ).fetchone()[0]
            if existing_profile == 0:
                reg = PATIENT_LOGIN_PROFILES.get(pid, {})
                content = {
                    "conditions": f"{reg.get('condition', 'เฝ้าระวังอาการทั่วไป')} (ข้อมูลสาธิตที่ยืนยันแล้ว)",
                    "medications": "รายการยาตามเวชระเบียนสาธิต (ใช้ทบทวนเท่านั้น ไม่ใช่ใบสั่งยา)",
                    "allergies": "ไม่มีประวัติแพ้ยาที่บันทึกไว้ในทะเบียนสาธิต",
                    "limitations": f"การเคลื่อนไหว: {reg.get('mobility', 'Assisted mobility')} · ระวังสายเซนเซอร์หลุดขณะพลิกตัว",
                    "caregiver": reg.get("doctor", "ทีมดูแล Smart Ward"),
                    "care_notes": "ติดตามค่า SpO2, HR และ RR คู่กับแผนการพลิกตัวตามรอบเวร",
                    "ranges": {
                        "heart_rate": {"low": 60.0, "high": 100.0},
                        "spo2": {"low": 94.0, "high": 100.0},
                        "respiratory_rate": {"low": 12.0, "high": 20.0},
                    },
                    "reference_minutes": 5,
                    "use_reference": False,
                }
                conn.execute(
                    """INSERT INTO care_profile_versions(
                           patient_id, version, state, content, reference, saved_at, saved_by, reviewed_at, reviewed_by
                       ) VALUES (?, 1, 'ACTIVE', ?, NULL, ?, ?, ?, ?)""",
                    (pid, json.dumps(content, ensure_ascii=False), now - 600, actor, now - 540, actor),
                )
                seeded_profiles += 1

    return {"seeded_plans": seeded_plans, "seeded_profiles": seeded_profiles}


def seed_demo_accounts(db_path: Path | None = None) -> dict:
    if db_path is not None:
        os.environ["WARD_DB_PATH"] = str(db_path.resolve())
    import auth
    import main
    from patient_registry import PATIENT_LOGIN_PROFILES

    if db_path is not None:
        auth.DB = db_path.resolve()
        main.DB_NAME = str(db_path.resolve())

    main.init_db()
    auth.ensure_test_accounts()

    # Explicitly verify and upsert every patient's single doctor assignment
    for pid, profile in sorted(PATIENT_LOGIN_PROFILES.items()):
        doctor_id = profile.get("assigned_staff_id")
        doctor_name = profile.get("doctor", doctor_id)
        if doctor_id:
            auth.assign_patient_doctor(pid, doctor_id, doctor_name, overwrite=True)

    care_counts = _seed_care_plans_and_profiles(Path(auth.DB))
    doctor5_patients = auth.get_doctor_patients("doctor5")
    test_d_patients = auth.get_doctor_patients("test_d")
    accounts = auth.list_accounts()

    return {
        "database": str(Path(auth.DB).resolve()),
        "accounts_count": len(accounts),
        "doctor5_patients": list(doctor5_patients),
        "test_d_patients": list(test_d_patients),
        "total_patient_assignments": len(PATIENT_LOGIN_PROFILES),
        **care_counts,
    }


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Smart Ward three-role demo accounts (Doctor, Patient, Central).")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "backend" / "runtime" / "ward-demo.db",
        help="Target SQLite database path (default: backend/runtime/ward-demo.db)",
    )
    args = parser.parse_args(argv)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    summary = seed_demo_accounts(args.db)

    print("=== Smart Ward Demo Accounts & Care Data Seeded (Idempotent) ===")
    print(f"Database: {summary['database']}")
    print(f"1-Doctor-Per-Patient Assignments: {summary['total_patient_assignments']} patients")
    print(f"Care Plans Seeded: {summary['seeded_plans']} | Care Profiles Seeded: {summary['seeded_profiles']}")
    print()
    print("| Role    | Portal                 | Username / ID | Password    | Scope / Chat                                       |")
    print("|---------|------------------------|---------------|-------------|----------------------------------------------------|")
    print(f"| Doctor  | Staff (:3000/:8000)    | doctor5       | doctor1234  | 5 patients ({', '.join(summary['doctor5_patients'])}) · 2-way chat |")
    print("| Central | Staff (:3000/:8000)    | central       | central1234 | All 60 ward beds + doctor names · NO chat system   |")
    print(f"| Doctor  | Staff (:3000/:8000)    | test_d        | admin1234   | 1 home-care patient ({', '.join(summary['test_d_patients'])}) · 2-way chat |")
    print("| Patient | Patient (:3001/:8001)  | A001          | (ID-only)   | Own data only · chats with doctor5 (Dr. Wichai)    |")
    print("| Patient | Patient (:3001/:8001)  | TEST_P        | admin4321   | Own data only · chats with test_d                  |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
