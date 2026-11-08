#!/usr/bin/env python3
"""1 Hz × N beds telemetry soak and load test with injected artifact & deterioration scenarios.

Validates:
1. Throughput & latency under 1 Hz continuous telemetry across 60 beds: p95 latency < 500 ms.
2. 100% Clinical Abstention on injected artifacts (SpO2 > 100, HR > 240 or < 30, RR <= 0).
3. 100% Critical alert detection on deteriorating beds (Modified NEWS2 Scale 1).
4. Zero SQLite database deadlocks or unhandled exceptions under sustained load.
"""

import argparse
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["WARD_INGEST_MODE"] = "off"
os.environ["WARD_DASHBOARD_LLM"] = "0"

import main
import monitor_service
import patient_registry
from ai_models.news2 import calculate_modified_news2


def run_soak_test(beds_count: int = 60, duration_seconds: int = 60, db_path: str | None = None, verbose: bool = False):
    temp_dir = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="smart-ward-soak-")
        db_path = str(Path(temp_dir.name) / "soak_ward.db")

    os.environ["WARD_DB_PATH"] = db_path
    main.DB_NAME = db_path
    import auth
    auth.DB = Path(db_path)
    main.init_db()
    monitor_service.init_monitor_db(db_path)

    all_patient_ids = list(patient_registry.PATIENT_PROFILES.keys())
    if len(all_patient_ids) < beds_count:
        # Replicate if more than 60 requested
        all_patient_ids = [f"B{i:03d}" for i in range(1, beds_count + 1)]
    patient_ids = all_patient_ids[:beds_count]

    # Partition cohorts
    # 1. Normal beds: first N - 10 beds
    # 2. Deteriorating beds: next 5 beds
    # 3. Injected artifact beds: last 5 beds
    num_artifact = min(5, max(1, beds_count // 12))
    num_deteriorating = min(5, max(1, beds_count // 12))
    num_normal = beds_count - num_artifact - num_deteriorating

    normal_beds = patient_ids[:num_normal]
    deteriorating_beds = patient_ids[num_normal : num_normal + num_deteriorating]
    artifact_beds = patient_ids[num_normal + num_deteriorating :]

    print("=" * 70)
    print("🏥 SMART WARD 1 Hz TELEMETRY SOAK & LOAD TEST")
    print(f"Beds: {beds_count} concurrent | Duration: {duration_seconds} s | Database: {db_path}")
    print(f"Cohorts: Normal={len(normal_beds)} | Deteriorating={len(deteriorating_beds)} | Artifact={len(artifact_beds)}")
    print("=" * 70)

    worker = monitor_service.MonitorWorker(db_path, patient_registry.PATIENT_PROFILES, ingest_mode="live")

    batch_latencies_ms = []
    total_deteriorating_samples = 0
    detected_critical_samples = 0
    total_artifact_samples = 0
    abstained_artifact_samples = 0
    sqlite_errors = 0

    test_start_wall = time.time()
    sim_time = test_start_wall - duration_seconds

    for sec in range(1, duration_seconds + 1):
        tick_time = sim_time + sec
        readings = []

        # 1. Normal Cohort
        for pid in normal_beds:
            wave = math.sin((sec + hash(pid) % 30) / 10.0)
            hr = 72.0 + wave * 6.0
            spo2 = 98.0 + (wave * 0.8)
            rr = 16.0 + wave * 1.5
            readings.append({
                "patient_id": pid,
                "timestamp": tick_time,
                "heart_rate": round(hr, 1),
                "spo2": round(spo2, 1),
                "respiratory_rate": round(rr, 1),
                "source_segment": "soak_normal",
            })

        # 2. Deteriorating Cohort (Hypoxia / Tachycardia / Tachypnea -> NEWS2 High >= 7)
        for pid in deteriorating_beds:
            total_deteriorating_samples += 1
            hr = 138.0 + (sec % 5)
            spo2 = 86.0 - (sec % 3)
            rr = 28.0 + (sec % 4)
            readings.append({
                "patient_id": pid,
                "timestamp": tick_time,
                "heart_rate": round(hr, 1),
                "spo2": round(spo2, 1),
                "respiratory_rate": round(rr, 1),
                "source_segment": "soak_deteriorating",
            })

        # 3. Artifact Cohort (Out-of-physiological bounds or disconnected sensors)
        # Note: MonitorWorker filters invalid readings before DB; calculate_modified_news2 evaluates them directly.
        for idx, pid in enumerate(artifact_beds):
            total_artifact_samples += 1
            if idx == 0:
                # Extreme bradycardia / artifact
                art_reading = {"hr": 24.0, "spo2": 98.0, "rr": 16.0}
            elif idx == 1:
                # Non-physiological tachycardia artifact
                art_reading = {"hr": 255.0, "spo2": 98.0, "rr": 16.0}
            elif idx == 2:
                # Impossible SpO2 (> 100)
                art_reading = {"hr": 75.0, "spo2": 106.0, "rr": 16.0}
            elif idx == 3:
                # Apnea / sensor failure
                art_reading = {"hr": 80.0, "spo2": 98.0, "rr": 0.0}
            else:
                # Complete sensor dropout / flatline
                art_reading = {"hr": 0.0, "spo2": 0.0, "rr": 0.0}

            # Check clinical rule engine abstention
            eval_res = calculate_modified_news2(art_reading["hr"], art_reading["spo2"], art_reading["rr"])
            if eval_res.get("abstain") is True:
                abstained_artifact_samples += 1

            readings.append({
                "patient_id": pid,
                "timestamp": tick_time,
                "heart_rate": art_reading["hr"],
                "spo2": art_reading["spo2"],
                "respiratory_rate": art_reading["rr"],
                "source_segment": "soak_artifact",
            })

        # Measure batch processing time
        t0 = time.perf_counter()
        try:
            outputs = worker.process(readings, current=tick_time)
        except sqlite3.OperationalError as e:
            sqlite_errors += 1
            outputs = []
            if verbose:
                print(f"SQLite error at tick {sec}: {e}")
        t1 = time.perf_counter()

        dt_ms = (t1 - t0) * 1000.0
        batch_latencies_ms.append(dt_ms)

        # Check outputs for deteriorating beds
        output_map = {out["patient_id"]: out for out in outputs}
        for pid in deteriorating_beds:
            out = output_map.get(pid)
            if out and (out.get("status") == "CRITICAL" or out.get("analysis", {}).get("modified_news2", {}).get("level") == "HIGH"):
                detected_critical_samples += 1

        if verbose and sec % 10 == 0:
            print(f"[{sec:02d}/{duration_seconds:02d}s] Batch latency: {dt_ms:.2f} ms | Output beds: {len(outputs)}/{beds_count}")

    total_readings = beds_count * duration_seconds
    total_elapsed_wall = time.time() - test_start_wall

    batch_latencies_ms.sort()
    p50_ms = batch_latencies_ms[int(len(batch_latencies_ms) * 0.50)]
    p95_ms = batch_latencies_ms[int(len(batch_latencies_ms) * 0.95)]
    p99_ms = batch_latencies_ms[int(len(batch_latencies_ms) * 0.99)]
    max_ms = max(batch_latencies_ms)

    crit_rate = (detected_critical_samples / total_deteriorating_samples) * 100.0 if total_deteriorating_samples else 100.0
    abstain_rate = (abstained_artifact_samples / total_artifact_samples) * 100.0 if total_artifact_samples else 100.0

    print("\n" + "=" * 70)
    print("📊 SOAK TEST RESULTS & PERFORMANCE SUMMARY")
    print("=" * 70)
    print(f"Total Readings Generated:  {total_readings:,} readings ({beds_count} beds × {duration_seconds} s)")
    print(f"Wall Execution Time:       {total_elapsed_wall:.2f} s")
    print(f"Simulated Ingestion Rate:  {total_readings / total_elapsed_wall:,.1f} readings/sec")
    print("-" * 70)
    print(f"Latency p50:               {p50_ms:.2f} ms")
    print(f"Latency p95:               {p95_ms:.2f} ms  (Target: < 500 ms)")
    print(f"Latency p99:               {p99_ms:.2f} ms")
    print(f"Latency Max:               {max_ms:.2f} ms")
    print("-" * 70)
    print(f"Deteriorating Detection:   {detected_critical_samples}/{total_deteriorating_samples} ({crit_rate:.1f}%) [Requirement: 100%]")
    print(f"Artifact Abstention Rate:  {abstained_artifact_samples}/{total_artifact_samples} ({abstain_rate:.1f}%) [Requirement: 100%]")
    print(f"SQLite Lockout Errors:     {sqlite_errors} [Requirement: 0]")
    print("=" * 70)

    # Verification gates
    passed = True
    reasons = []

    if p95_ms >= 500.0:
        passed = False
        reasons.append(f"P95 latency {p95_ms:.2f} ms exceeded threshold 500 ms")
    if crit_rate < 100.0:
        passed = False
        reasons.append(f"Deteriorating bed detection was {crit_rate:.1f}% (required 100%)")
    if abstain_rate < 100.0:
        passed = False
        reasons.append(f"Artifact abstention was {abstain_rate:.1f}% (required 100%)")
    if sqlite_errors > 0:
        passed = False
        reasons.append(f"Encountered {sqlite_errors} SQLite lockup errors")

    if passed:
        print("✅ VERIFICATION STATUS: PASS — All performance and clinical guardrails met.")
    else:
        print("❌ VERIFICATION STATUS: FAIL — " + "; ".join(reasons))

    if temp_dir:
        temp_dir.cleanup()

    return 0 if passed else 1


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beds", type=int, default=60, help="Number of concurrent beds (default: 60)")
    parser.add_argument("--seconds", type=int, default=60, help="Soak test duration in seconds (default: 60)")
    parser.add_argument("--db", type=str, default=None, help="Database path (defaults to temp db)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed tick output")
    args = parser.parse_args()

    sys.exit(run_soak_test(
        beds_count=args.beds,
        duration_seconds=args.seconds,
        db_path=args.db,
        verbose=args.verbose,
    ))


if __name__ == "__main__":
    main_cli()
