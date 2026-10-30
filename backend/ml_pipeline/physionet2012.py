"""Feature extraction for PhysioNet/CinC Challenge 2012 records.

The source challenge predicts *in-hospital mortality from the first 48 hours
of an ICU stay*.  It is not a ward-deterioration dataset and must not be used
as a clinical decision system.  This module intentionally excludes outcome
columns such as SAPS-I and SOFA from model features to prevent leakage.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


DATASET_NAME = "PhysioNet/CinC Challenge 2012"
DATASET_VERSION = "1.0.0"
DATASET_URL = "https://physionet.org/content/challenge-2012/1.0.0/"
TARGET_COLUMN = "In-hospital_death"

# These parameters are available in the raw first-48-hour files.  The core
# profile is deliberately limited to fields the Smart Ward can collect today;
# the full profile exists for an offline benchmark, not to fabricate missing
# information at runtime.
CORE_PARAMETERS = ("Age", "Gender", "HR", "SaO2", "RespRate", "Glucose")
FULL_PARAMETERS = (
    "Age", "Gender", "Height", "ICUType", "Weight", "HR", "SaO2",
    "RespRate", "Glucose", "Temp", "MAP", "SysABP", "DiasABP",
    "NISysABP", "NIDiasABP", "NIMAP", "GCS", "Creatinine", "BUN",
    "WBC", "Platelets", "pH", "PaO2", "PaCO2", "FiO2", "Lactate",
)
SUMMARY_STATS = ("last", "min", "max", "mean", "std", "slope", "count")
STATIC_PARAMETERS = {"Age", "Gender", "Height", "ICUType", "Weight"}


def feature_names(parameters: Iterable[str]) -> list[str]:
    return [
        f"{parameter}__{stat}"
        for parameter in parameters
        for stat in (("last",) if parameter in STATIC_PARAMETERS else SUMMARY_STATS)
    ]


def parse_time_hours(value: str) -> float:
    """Convert Challenge time values such as ``35:19`` into elapsed hours."""
    hours, minutes = value.strip().split(":", maxsplit=1)
    return int(hours) + int(minutes) / 60.0


def _finite_number(value: str | float | int | None) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan
    # The Challenge represents unknown values as -1. They must remain missing,
    # not be interpreted as a real physiologic measurement.
    return number if math.isfinite(number) and number >= 0 else math.nan


def summarize_measurements(measurements: Iterable[tuple[float, float]]) -> dict[str, float]:
    """Summarize one variable without looking beyond the supplied time window."""
    usable = [(time, value) for time, value in measurements if math.isfinite(value)]
    if not usable:
        return {stat: math.nan for stat in SUMMARY_STATS}
    usable.sort(key=lambda item: item[0])
    times = np.asarray([item[0] for item in usable], dtype=float)
    values = np.asarray([item[1] for item in usable], dtype=float)
    slope = math.nan
    if len(values) >= 2 and np.ptp(times) > 0:
        slope = float(np.polyfit(times, values, 1)[0])
    return {
        "last": float(values[-1]),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)) if len(values) > 1 else 0.0,
        "slope": slope,
        "count": float(len(values)),
    }


def read_challenge_record(path: Path) -> dict[str, list[tuple[float, float]]]:
    """Read a single ``set-a/<record_id>.txt`` file into parameter series."""
    series: dict[str, list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"Time", "Parameter", "Value"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Unexpected Challenge record format: {path}")
        for row in reader:
            parameter = (row.get("Parameter") or "").strip()
            if not parameter:
                continue
            series.setdefault(parameter, []).append((
                parse_time_hours(row.get("Time") or "0:00"),
                _finite_number(row.get("Value")),
            ))
    return series


def build_feature_row(record_path: Path, parameters: Iterable[str]) -> dict[str, float | str]:
    series = read_challenge_record(record_path)
    row: dict[str, float | str] = {"record_id": record_path.stem}
    for parameter in parameters:
        summary = summarize_measurements(series.get(parameter, ()))
        for name in feature_names((parameter,)):
            stat = name.rsplit("__", maxsplit=1)[1]
            row[name] = summary[stat]
    return row


def read_outcomes(path: Path) -> dict[str, int]:
    """Return only the supervised target; never add outcome columns as features."""
    outcomes: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"RecordID", TARGET_COLUMN}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Unexpected outcomes format: {path}")
        for row in reader:
            record_id = (row.get("RecordID") or "").strip()
            target = (row.get(TARGET_COLUMN) or "").strip()
            if record_id and target in {"0", "1"}:
                outcomes[record_id] = int(target)
    return outcomes


@dataclass(frozen=True)
class PreparedDataset:
    rows: int
    positives: int
    feature_count: int
    output_path: Path
    manifest_path: Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_dataset(records_dir: Path, outcomes_path: Path, output_path: Path, parameters: Iterable[str]) -> PreparedDataset:
    """Create one feature row per ICU stay and an auditable manifest."""
    parameters = tuple(parameters)
    outcomes = read_outcomes(outcomes_path)
    record_paths = sorted(records_dir.glob("*.txt"))
    if not record_paths:
        raise FileNotFoundError(f"No .txt record files found in {records_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    names = ["record_id", "target", *feature_names(parameters)]
    rows_written = 0
    positives = 0
    with output_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=names)
        writer.writeheader()
        for record_path in record_paths:
            row = build_feature_row(record_path, parameters)
            record_id = str(row["record_id"])
            if record_id not in outcomes:
                continue
            target = outcomes[record_id]
            writer.writerow({
                **row,
                "target": target,
            })
            rows_written += 1
            positives += target

    if rows_written == 0:
        raise ValueError("No records matched the outcome labels")
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest = {
        "dataset": DATASET_NAME,
        "dataset_version": DATASET_VERSION,
        "dataset_url": DATASET_URL,
        "task": "Predict in-hospital mortality from the first 48 hours of an ICU stay.",
        "target": TARGET_COLUMN,
        "parameters": list(parameters),
        "features": feature_names(parameters),
        "rows": rows_written,
        "positive_cases": positives,
        "positive_rate": round(positives / rows_written, 6),
        "raw_records_sha256": sha256(Path(records_dir).parent / "set-a.tar.gz") if (Path(records_dir).parent / "set-a.tar.gz").exists() else None,
        "outcomes_sha256": sha256(outcomes_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return PreparedDataset(rows_written, positives, len(feature_names(parameters)), output_path, manifest_path)
