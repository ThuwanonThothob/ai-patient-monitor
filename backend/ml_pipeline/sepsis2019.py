"""Causal hourly feature contract and transparent research evaluation.

Labels are ALREADY shifted six hours by the dataset authors. Never shift again.
No registry diagnoses, BIDMC values, patient IDs or outcome labels are features.
"""
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/raw/sepsis2019"
SIGNALS = ("HR", "O2Sat", "Temp", "SBP", "MAP", "DBP", "Resp",
           "WBC", "Lactate", "Creatinine", "Glucose", "Platelets")
BOUNDS = ((1, 300), (1, 100), (25, 45), (1, 300), (1, 250), (1, 200), (1, 100),
          (0, 500), (0, 100), (0, 100), (1, 2000), (0, 3000))
FEATURES = [f"{name}_{suffix}" for name in SIGNALS for suffix in ("last", "age_hours", "delta_6h")]
FEATURES += ["Age", "Gender", "ICULOS"]
NOTICE = "ข้อมูลวิจัย ICU ย้อนหลัง ไม่ใช่การวินิจฉัย ไม่เชื่อมกับ 60 เตียง และไม่ใช้สั่งการรักษา"


@dataclass
class Record:
    id: str
    site: str
    values: np.ndarray
    labels: np.ndarray
    hours: np.ndarray
    age: float
    gender: float
    onset: float | None
    excluded: str | None = None


def read_record(content, record_id, site):
    header = content.splitlines()[0].decode().split("|")
    required = [*SIGNALS, "Age", "Gender", "ICULOS", "SepsisLabel"]
    if len(set(header)) != len(header) or not all(key in header for key in required):
        raise ValueError(f"Invalid schema: {record_id}")
    rows = np.loadtxt(io.BytesIO(content), delimiter="|", skiprows=1, ndmin=2)
    if rows.shape[1] != len(header) or not len(rows):
        raise ValueError(f"Invalid rows: {record_id}")
    labels = rows[:, header.index("SepsisLabel")]
    hours = rows[:, header.index("ICULOS")]
    if not np.isin(labels, [0, 1]).all() or np.any(np.diff(labels) < 0):
        raise ValueError(f"Invalid outcome labels: {record_id}")
    if not np.isfinite(hours).all() or np.any(np.diff(hours) != 1):
        raise ValueError(f"Non-hourly data: {record_id}")
    onset, excluded = None, None
    positive = np.flatnonzero(labels)
    if len(positive):
        onset = float(hours[positive[0]] + 6)
        if positive[0] == 0:
            excluded = "left_censored_onset"
        elif onset > hours[-1]:
            excluded = "onset_outside_observation"
    values = rows[:, [header.index(key) for key in SIGNALS]].copy()
    for j, (low, high) in enumerate(BOUNDS):
        values[~np.isfinite(values[:, j]) | (values[:, j] < low) | (values[:, j] > high), j] = np.nan
    age = rows[0, header.index("Age")]
    gender = rows[0, header.index("Gender")]
    if not 0 <= age <= 100:
        age = np.nan
    if gender not in (0, 1):
        gender = np.nan
    return Record(record_id, site, values, labels.astype(int), hours, age, gender, onset, excluded)


def load_records(data=DATA):
    manifest_bytes = (data / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    records = []
    for key, info in sorted(manifest["files"].items()):
        path = data / key
        if path.resolve().parent not in [(data / "A").resolve(), (data / "B").resolve()]:
            raise ValueError("Invalid manifest path")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != info["sha256"]:
            raise ValueError(f"Dataset integrity failure: {key}")
        site = key.split("/")[0]
        records.append(read_record(content, site + "-" + path.stem, site))
    return records, manifest, hashlib.sha256(manifest_bytes).hexdigest()


def features(record):
    """Only past/current values; expire vitals after 6h, labs after 24h."""
    n, width = record.values.shape
    carried = np.full((n, width), np.nan)
    ages = np.full((n, width), 168.0)
    last = np.full(width, np.nan)
    last_hour = np.full(width, -np.inf)
    for i, row in enumerate(record.values):
        observed = np.isfinite(row)
        last[observed] = row[observed]
        last_hour[observed] = record.hours[i]
        age = record.hours[i] - last_hour
        fresh = age <= np.array([6] * 7 + [24] * 5)
        carried[i] = np.where(fresh, last, np.nan)
        ages[i] = np.minimum(age, 168)
    delta = np.full_like(carried, np.nan)
    delta[6:] = carried[6:] - carried[:-6]
    x = np.stack((carried, ages, delta), axis=2).reshape(n, -1)
    x = np.column_stack((x, np.full(n, record.age), np.full(n, record.gender), record.hours))
    eligible = np.isfinite(carried[:, :7]).sum(axis=1) >= 3
    return x.astype(np.float32), eligible, carried


def split_records(records, seed=2019):
    usable = [r for r in records if r.excluded is None]
    a = [r for r in usable if r.site == "A"]
    b = [r for r in usable if r.site == "B"]
    train, hold = train_test_split(a, test_size=.30, random_state=seed, stratify=[r.onset is not None for r in a])
    validation, test = train_test_split(hold, test_size=.50, random_state=seed + 1, stratify=[r.onset is not None for r in hold])
    return {"train": train, "validation": validation, "test": test, "external_B": b}


def prepare(records):
    xs, ys, entries = [], [], []
    for record in records:
        x, eligible, carried = features(record)
        # Stop at onset: evaluating post-onset recognition as prediction inflates results.
        before = np.ones(len(x), dtype=bool) if record.onset is None else record.hours < record.onset
        mask = eligible & before
        xs.append(x[mask])
        ys.append(record.labels[mask])
        entries.append({"id": record.id, "hours": record.hours[mask], "onset": record.onset,
                        "eligible": int(mask.sum()), "total": int(before.sum()),
                        "rule": ((carried[:, 0] > 100).astype(int) + (carried[:, 6] > 22).astype(int)
                                 + (carried[:, 3] < 100).astype(int) >= 2)[mask].astype(float)})
    if not xs or sum(len(x) for x in xs) == 0:
        raise ValueError("No eligible hourly observations")
    return np.concatenate(xs), np.concatenate(ys), entries


def alarm_stats(entries, scores, threshold):
    """One first-crossing proposal per stay, no repeat alerts. Early >6h counts false."""
    offset = 0
    tp = fp = positive = total_hours = eligible_hours = 0
    leads = []
    outcomes = []
    for item in entries:
        size = item["eligible"]
        p = scores[offset:offset + size]
        offset += size
        crossings = np.flatnonzero(p >= threshold)
        first = float(item["hours"][crossings[0]]) if len(crossings) else None
        onset = item["onset"]
        lead = None if first is None or onset is None else onset - first
        correct = lead is not None and 0 < lead <= 6
        tp += int(correct)
        fp += int(first is not None and not correct)
        positive += int(onset is not None)
        total_hours += item["total"]
        eligible_hours += size
        if correct:
            leads.append(lead)
        outcome = "timely_alert" if correct else "early_false_alert" if first is not None and onset is not None else "false_alert" if first is not None else "missed_event" if onset is not None else "no_alert_no_event"
        outcomes.append({"id": item["id"], "first_alert_hour": first, "lead_hours": lead, "outcome": outcome})
    if offset != len(scores):
        raise ValueError("Prediction alignment error")
    return {"event_sensitivity": tp / positive if positive else None,
            "alert_ppv": tp / (tp + fp) if tp + fp else None,
            "false_alerts_per_100_patient_hours": 100 * fp / total_hours if total_hours else None,
            "timely_alerts": tp, "false_alerts": fp, "missed_events": positive - tp,
            "event_patients": positive, "patient_hours": total_hours,
            "coverage": eligible_hours / total_hours if total_hours else 0,
            "median_timely_lead_hours": float(np.median(leads)) if leads else None}, outcomes


def choose_threshold(entries, scores, budget=1.0):
    candidates = np.r_[np.arange(.005, .101, .005), np.arange(.125, 1.001, .025), 1.01]
    choices = []
    for threshold in candidates:
        stats, _ = alarm_stats(entries, scores, float(threshold))
        if stats["false_alerts_per_100_patient_hours"] <= budget:
            key = (stats["event_sensitivity"] or 0, stats["alert_ppv"] or 0,
                   -stats["false_alerts_per_100_patient_hours"], threshold)
            choices.append((key, float(threshold)))
    return max(choices)[1]


def evaluate(y, scores, entries, threshold):
    alerts, outcomes = alarm_stats(entries, scores, threshold)
    predicted = scores >= threshold
    tp = int(((y == 1) & predicted).sum())
    fp = int(((y == 0) & predicted).sum())
    bins = []
    for lower in np.arange(0, 1, .1):
        mask = (scores >= lower) & (scores < lower + .1 if lower < .9 else scores <= 1)
        bins.append({"lower": round(float(lower), 1), "count": int(mask.sum()),
                     "mean_score": float(scores[mask].mean()) if mask.any() else None,
                     "observed_rate": float(y[mask].mean()) if mask.any() else None})
    return {**alerts, "threshold": threshold, "hourly_auroc": float(roc_auc_score(y, scores)) if len(np.unique(y)) == 2 else None,
            "hourly_average_precision": float(average_precision_score(y, scores)) if y.sum() else None,
            "hourly_brier": float(brier_score_loss(y, scores)), "hourly_positive_rate": float(y.mean()),
            "hourly_recall": tp / int(y.sum()) if y.sum() else None,
            "hourly_ppv": tp / (tp + fp) if tp + fp else None, "eligible_hours": len(y),
            "patients": len(entries), "reliability_bins": bins}, outcomes
