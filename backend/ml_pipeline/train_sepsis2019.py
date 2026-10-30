"""Offline research training. Never called from an HTTP request or live worker."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
import warnings

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .sepsis2019 import (FEATURES, NOTICE, ROOT, SIGNALS, choose_threshold, evaluate,
                         features, load_records, prepare, split_records)

OUTPUT = ROOT / "models/sepsis2019"


def write_json(path, value):
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def finite(value):
    return round(float(value), 5) if np.isfinite(value) else None


def confidence_intervals(entries, outcomes, repetitions=400):
    """Patient-level bootstrap, not treating overlapping hourly rows as independent."""
    a = np.array([[int(o["outcome"] == "timely_alert"), int(e["onset"] is not None),
                   int(o["first_alert_hour"] is not None and o["outcome"] != "timely_alert"), e["total"]]
                  for e, o in zip(entries, outcomes)], dtype=float)
    rng = np.random.default_rng(2020)
    values = []
    for _ in range(repetitions):
        sums = a[rng.integers(0, len(a), len(a))].sum(axis=0)
        if sums[1] and sums[3]:
            values.append([sums[0] / sums[1], 100 * sums[2] / sums[3]])
    if not values:
        return {"event_sensitivity_ci95": None, "false_alert_rate_ci95": None}
    intervals = np.quantile(values, [.025, .975], axis=0).T.tolist()
    return {"event_sensitivity_ci95": intervals[0], "false_alert_rate_ci95": intervals[1]}


def train(output=OUTPUT, budget=1.0):
    records, manifest, data_hash = load_records()
    splits = split_records(records)
    print("Records:", {key: len(value) for key, value in splits.items()}, flush=True)
    prepared = {key: prepare(value) for key, value in splits.items()}
    models = {
        "logistic": make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                                   StandardScaler(), LogisticRegression(max_iter=1000, C=1.0, random_state=2019)),
        # No automatic row-level early-stopping split (would leak the same patient's rows).
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
                                                                 min_samples_leaf=30, learning_rate=.05,
                                                                 l2_regularization=1.0, early_stopping=False,
                                                                 random_state=2019),
    }
    predictions, thresholds = {}, {"threshold_rule": .5}
    with threadpool_limits(limits=2), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        for name, model in models.items():
            print("Fitting", name, "on", len(prepared["train"][1]), "eligible pre-onset hours", flush=True)
            model.fit(prepared["train"][0], prepared["train"][1])
            predictions[name] = {key: model.predict_proba(value[0])[:, 1] for key, value in prepared.items() if key != "train"}
            thresholds[name] = choose_threshold(prepared["validation"][2], predictions[name]["validation"], budget)
    predictions["threshold_rule"] = {key: np.concatenate([entry["rule"] for entry in value[2]])
                                      for key, value in prepared.items() if key != "train"}
    metrics, outcomes = {}, {}
    for name, subsets in predictions.items():
        metrics[name], outcomes[name] = {}, {}
        for split, scores in subsets.items():
            metric, cases = evaluate(prepared[split][1], scores, prepared[split][2], thresholds[name])
            metric.update(confidence_intervals(prepared[split][2], cases))
            metrics[name][split], outcomes[name][split] = metric, cases
    # Select using validation only. Report all test results even if the chosen model loses.
    selected = max(models, key=lambda name: (metrics[name]["validation"]["event_sensitivity"] or 0,
                                             metrics[name]["validation"]["hourly_average_precision"] or 0))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run = output / run_id
    (run / "cases").mkdir(parents=True)
    report = {
        "schema_version": 1, "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY", "research_only": True, "live_enabled": False, "notice": NOTICE,
        "dataset": "PhysioNet Challenge 2019 v1.0.0", "source": manifest["source"],
        "downloaded_records": len(records), "publisher_records": sum(manifest["publisher_counts"].values()),
        "sampling": manifest["sampling"], "data_manifest_sha256": data_hash,
        "license_note": "Source page says CC BY 4.0; bundled LICENSE.txt says ODbL. Both retained; clarify before redistribution.",
        "excluded_records": dict(Counter(r.excluded for r in records if r.excluded)),
        "split_ids": {key: [r.id for r in value] for key, value in splits.items()},
        "splits": {key: {"patients": len(value), "events": sum(r.onset is not None for r in value),
                          "eligible_hours": len(prepared[key][1])} for key, value in splits.items()},
        "features": FEATURES, "selected_model": selected, "thresholds": thresholds, "metrics": metrics,
        "versions": {"sklearn": sklearn.__version__, "numpy": np.__version__},
        "training_parameters": {"seed": 2019, "logistic": {"max_iter": 1000, "C": 1.0},
                                "hist_gradient_boosting": models["hist_gradient_boosting"].get_params()},
        "protocol": {
            "split": "Site A patient-file-disjoint 70/15/15 stratified split; all sampled site B held out. No calendar-time validation.",
            "endpoint": "Hourly provided SepsisLabel, already shifted 6h; only pre-onset rows. Not a calibrated clinical probability.",
            "exclusions": "Exclude label-positive-at-first-row (unknown onset) and inferred onset beyond observation; no outcome filtering otherwise.",
            "features": "12 measured signals: bounded past-only carry (vitals 6h/labs 24h), age since measurement, 6h change; age/sex/hour. No future fill.",
            "coverage": "Abstain unless >=3 of 7 vital signs available within 6h. Event metrics include stays with zero eligible rows.",
            "threshold": f"Validation only: maximize timely event recall, then PPV, with <= {budget} false first alerts / 100 pre-onset patient-hours.",
            "alarm": "One first crossing per stay. Correct only in [onset-6h, onset); earlier crossing is false and the event remains missed. No repeats.",
            "baseline": "Unvalidated demo rule: at least 2 of HR>100, RR>22, SBP<100; fixed threshold. Not NEWS2 or a sepsis diagnosis.",
            "selection": "Validation event recall then hourly average precision; never choose using test or external_B.",
            "uncertainty": "400 patient-bootstrap replicates for event recall and false-alarm rate; pointwise 95% percentile intervals.",
            "calibration": "No post-hoc calibration. Brier and reliability bins reported, not proof of calibrated risk.",
        },
        "limitations": ["Retrospective ICU research, not validated for Thai wards or bedridden patients.",
                        "Subset of public training data, not the hidden official Challenge test set or official utility score.",
                        "Labels are algorithmically derived clinical definitions, not perfect clinician adjudication.",
                        "No prospective evaluation, no measured staff time saving, no treatment automation.",
                        "Demographic subgroup validation and calendar-time validation remain future work."],
    }
    case_index = []
    with threadpool_limits(limits=2):
        for split in ("test", "external_B"):
            for index, record in enumerate(splits[split]):
                x, eligible, carried = features(record)
                before = np.ones(len(x), dtype=bool) if record.onset is None else record.hours < record.onset
                visible = np.flatnonzero(before)
                mask = eligible & before
                scores = {name: np.full(len(x), np.nan) for name in models}
                if mask.any():
                    for name, model in models.items():
                        scores[name][mask] = model.predict_proba(x[mask])[:, 1]
                rule = np.full(len(x), np.nan)
                rule[mask] = prepared[split][2][index]["rule"]
                scores["threshold_rule"] = rule
                timeline = [{"hour": float(record.hours[i]), "eligible": bool(eligible[i]),
                             "observed": dict(zip(SIGNALS, map(finite, record.values[i]))),
                             "input_values": dict(zip(SIGNALS, map(finite, carried[i]))),
                             "input_age_hours": dict(zip(SIGNALS, map(finite, x[i, 1:36:3]))),
                             # Do not round a score across the alert threshold in replay/export.
                             "scores": {name: float(score[i]) if np.isfinite(score[i]) else None for name, score in scores.items()},
                             "label": int(record.labels[i])} for i in visible]
                case_outcomes = {name: outcomes[name][split][index] for name in predictions}
                payload = {"id": record.id, "split": split, "site": record.site, "onset_hour": record.onset,
                           "research_only": True, "timeline": timeline, "outcomes": case_outcomes}
                digest = write_json(run / "cases" / f"{record.id}.json", payload)
                case_index.append({"id": record.id, "split": split, "site": record.site, "hours": len(timeline),
                                   "event": record.onset is not None, "outcome": case_outcomes[selected]["outcome"],
                                   "sha256": digest})
    report["cases"] = case_index
    report_hash = write_json(run / "report.json", report)
    joblib.dump({"models": models, "features": FEATURES, "thresholds": thresholds,
                 "run_id": run_id, "research_only": True}, run / "models.joblib")
    # Publish one pointer only after every artifact is complete; previous runs survive.
    temporary = output / f"current-{run_id}.tmp"
    write_json(temporary, {"run_id": run_id, "report_sha256": report_hash})
    os.replace(temporary, output / "current.json")
    print(json.dumps({"run_id": run_id, "selected_on_validation": selected,
                      "test": metrics[selected]["test"], "external_B": metrics[selected]["external_B"]}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--false-alert-budget", type=float, default=1.0)
    args = parser.parse_args()
    if not 0 < args.false_alert_budget <= 10:
        parser.error("false-alert-budget must be >0 and <=10")
    train(budget=args.false_alert_budget)
