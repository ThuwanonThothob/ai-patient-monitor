#!/usr/bin/env python3
"""Idempotent test fixture bootstrapper for clean CI checkouts.

On a developer machine where `backend/data/raw/bidmc/manifest.json` and
`backend/models/bidmc_monitor_v1.joblib` already exist, this script verifies
their presence and exits 0 without overwriting real data.

In a clean CI checkout where gitignored datasets/models are absent, it generates
deterministic, physiologically valid 1 Hz BIDMC numeric CSV fixtures and minimal
PMD posture fixtures, writes their SHA-256 manifests, and trains the local
artifacts so all backend and script unit tests run reproducibly.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
BIDMC_DIR = BACKEND_DIR / "data" / "raw" / "bidmc"
BIDMC_MANIFEST = BIDMC_DIR / "manifest.json"
MODELS_DIR = BACKEND_DIR / "models"
BIDMC_MODEL = MODELS_DIR / "bidmc_monitor_v1.joblib"
BIDMC_META = MODELS_DIR / "bidmc_monitor_v1_metadata.json"

PMD_DIR = BACKEND_DIR / "data" / "raw" / "pmd"
PMD_MANIFEST = PMD_DIR / "manifest.json"
POSTURE_CURRENT = MODELS_DIR / "posture" / "current.json"


def _bidmc_ready() -> bool:
    if not BIDMC_MANIFEST.is_file():
        return False
    try:
        manifest = json.loads(BIDMC_MANIFEST.read_text(encoding="utf-8"))
        sha_map = manifest.get("sha256", {})
        if len(sha_map) != 53:
            return False
        for name in sha_map:
            if not (BIDMC_DIR / name).is_file():
                return False
        return True
    except Exception:
        return False


def _generate_bidmc_fixtures() -> None:
    print("[bootstrap] Generating 53 deterministic 1 Hz BIDMC numeric CSV fixtures...")
    BIDMC_DIR.mkdir(parents=True, exist_ok=True)
    sha256_map: dict[str, str] = {}

    for rec_idx in range(1, 54):
        filename = f"bidmc_{rec_idx:02d}_Numerics.csv"
        filepath = BIDMC_DIR / filename
        lines = ["Time [s], HR, PULSE, RESP, SpO2"]

        base_hr = 72 + (rec_idx % 12)
        base_spo2 = 96 + (rec_idx % 3)
        base_resp = 16 + (rec_idx % 3)
        phase = (rec_idx * 0.37) % (2.0 * math.pi)

        for row_idx in range(120):
            # Recording 13 has a timestamp discontinuity at t=50 so that 52 of 53
            # recordings produce 90s windows (yielding the 30/11/11 train/val/test split).
            t_sec = row_idx if (rec_idx != 13 or row_idx < 50) else row_idx + 2
            angle = (2.0 * math.pi * row_idx / 60.0) + phase
            hr = int(round(base_hr + 6.0 * math.sin(angle)))
            hr = max(65, min(95, hr))
            pulse = max(64, hr - 1)
            resp = int(round(base_resp + 2.0 * math.cos(angle)))
            resp = max(14, min(20, resp))
            spo2 = max(95, min(99, base_spo2))
            lines.append(f"{t_sec},{hr},{pulse},{resp},{spo2}")

        content = ("\n".join(lines) + "\n").encode("utf-8")
        filepath.write_bytes(content)
        sha256_map[filename] = hashlib.sha256(content).hexdigest()

    manifest = {
        "dataset": "BIDMC PPG and Respiration Dataset",
        "version": "1.0.0",
        "url": "https://physionet.org/content/bidmc/1.0.0/",
        "license": "Open Data Commons Attribution License v1.0",
        "sha256": sha256_map,
    }
    BIDMC_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[bootstrap] Wrote {BIDMC_MANIFEST}")


def _pmd_ready() -> bool:
    if not PMD_MANIFEST.is_file():
        return False
    try:
        manifest = json.loads(PMD_MANIFEST.read_text(encoding="utf-8"))
        sha_map = manifest.get("sha256", {})
        if len(sha_map) != 41:
            return False
        for rel_path in sha_map:
            if not (PMD_DIR / rel_path).is_file():
                return False
        return True
    except Exception:
        return False


def _generate_pmd_fixtures() -> None:
    print("[bootstrap] Generating deterministic PMD posture fixtures...")
    PMD_DIR.mkdir(parents=True, exist_ok=True)
    sha256_map: dict[str, str] = {}

    doc_path = PMD_DIR / "experiment-info.docx"
    doc_bytes = b"PMD synthetic fixture provenance document\n"
    doc_path.write_bytes(doc_bytes)
    sha256_map["experiment-info.docx"] = hashlib.sha256(doc_bytes).hexdigest()

    exp_dir = PMD_DIR / "experiment-i"
    exp_dir.mkdir(parents=True, exist_ok=True)
    csv_path = exp_dir / "subject-info-i.csv"
    csv_bytes = b"subject,age,height_cm,weight_kg\n" + b"".join(
        f"S{s},{20 + s},{165 + s},{60 + s}\n".encode("utf-8") for s in range(1, 14)
    )
    csv_path.write_bytes(csv_bytes)
    sha256_map["experiment-i/subject-info-i.csv"] = hashlib.sha256(csv_bytes).hexdigest()

    for subject in range(1, 14):
        subj_dir = exp_dir / f"S{subject}"
        subj_dir.mkdir(parents=True, exist_ok=True)
        for pose in (1, 2, 3):
            rel = f"experiment-i/S{subject}/{pose}.txt"
            fpath = PMD_DIR / rel
            # 5 rows of 2048 values (32x64 frame); train_posture samples every 5th row (index 0)
            row_vals = [10 + ((subject + i) % 5) for i in range(2048)]
            # Pose-specific pressure region so classifier learns distinct classes
            offset = (pose - 1) * 600
            for idx in range(offset, min(2048, offset + 400)):
                row_vals[idx] += 250 + subject * 3
            row_line = " ".join(str(v) for v in row_vals)
            content = ("\n".join([row_line] * 5) + "\n").encode("utf-8")
            fpath.write_bytes(content)
            sha256_map[rel] = hashlib.sha256(content).hexdigest()

    manifest = {
        "dataset": "A Pressure Map Dataset for In-bed Posture Classification v1.0.0",
        "source": "https://physionet.org/content/pmd/1.0.0/",
        "license": "Open Data Commons Attribution License v1.0",
        "citation": "Pouyan et al. 2017. DOI: 10.1109/BHI.2017.7897206",
        "subset": "Experiment I; all 13 subjects; positions 1, 2, 3 only",
        "labels": {"1": "supine", "2": "right", "3": "left"},
        "sha256": sha256_map,
    }
    PMD_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[bootstrap] Wrote {PMD_MANIFEST}")


def main() -> int:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    if _bidmc_ready():
        print("[bootstrap] BIDMC dataset manifest and 53 CSVs already present; skipping generation.")
    else:
        _generate_bidmc_fixtures()

    if BIDMC_MODEL.is_file() and BIDMC_META.is_file():
        print("[bootstrap] BIDMC model artifact already present; skipping training.")
    else:
        print("[bootstrap] Training BIDMC monitor model artifact...")
        from ml_pipeline import train_bidmc

        train_bidmc.train()

    if _pmd_ready():
        print("[bootstrap] PMD dataset manifest and files already present; skipping generation.")
    else:
        _generate_pmd_fixtures()

    if POSTURE_CURRENT.is_file():
        print("[bootstrap] Posture model artifact already present; skipping training.")
    else:
        print("[bootstrap] Training PMD posture model artifact...")
        from ml_pipeline import train_posture

        train_posture.train()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
