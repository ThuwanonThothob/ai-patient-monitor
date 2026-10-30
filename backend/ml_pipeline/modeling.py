"""Training, calibration, evaluation, and serialisation for the research model.

The code separates a hold-out test set before any model selection.  The test
set is never used to select features, tune a threshold, or calibrate scores.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


MODEL_ENDPOINT = "In-hospital mortality from the first 48 hours of an ICU stay"
RESEARCH_ONLY_NOTICE = (
    "Research/education prototype only. This model is not clinically validated, "
    "is not a medical device, and must not be used for diagnosis, treatment, "
    "or autonomous escalation."
)


@dataclass
class CalibratedRiskBundle:
    """A serialisable estimator plus a calibration map learned on validation data."""

    estimator: Any
    calibrator: IsotonicRegression
    feature_names: list[str]
    metadata: dict[str, Any]

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        raw_probability = self.estimator.predict_proba(matrix)[:, 1]
        calibrated = self.calibrator.predict(raw_probability)
        # Avoid presenting absolute certainty to users of a research model.
        return np.clip(np.asarray(calibrated, dtype=float), 0.001, 0.999)


def read_feature_dataset(path: Path) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Load a prepared CSV without treating a record ID as a feature."""
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "record_id" not in reader.fieldnames or "target" not in reader.fieldnames:
            raise ValueError("Prepared dataset must contain record_id and target columns")
        columns = [name for name in reader.fieldnames if name not in {"record_id", "target"}]
        ids: list[str] = []
        labels: list[int] = []
        rows: list[list[float]] = []
        for row in reader:
            try:
                target = int(row["target"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid target in {path}") from error
            if target not in {0, 1}:
                raise ValueError(f"Target must be 0 or 1 in {path}")
            values = []
            for column in columns:
                raw = (row.get(column) or "").strip()
                try:
                    value = float(raw) if raw else math.nan
                except ValueError:
                    value = math.nan
                values.append(value if math.isfinite(value) else math.nan)
            ids.append(str(row["record_id"]))
            labels.append(target)
            rows.append(values)
    if len(set(labels)) != 2:
        raise ValueError("Training data must contain both outcome classes")
    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=int), columns, ids


def _candidate_models(random_state: int) -> dict[str, Pipeline]:
    """Keep a transparent baseline beside the non-linear candidate."""
    return {
        "logistic_regression": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(
                max_iter=3000,
                class_weight="balanced",
                random_state=random_state,
            )),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("classifier", HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=250,
                max_leaf_nodes=15,
                l2_regularization=1.0,
                random_state=random_state,
            )),
        ]),
    }


def _safe_auc(y_true: np.ndarray, probabilities: np.ndarray, scorer) -> float | None:
    try:
        return round(float(scorer(y_true, probabilities)), 6)
    except ValueError:
        return None


def choose_threshold(y_true: np.ndarray, probabilities: np.ndarray, target_sensitivity: float = 0.80) -> float:
    """Choose on validation data only: highest specificity at required sensitivity."""
    best: tuple[float, float] | None = None  # (specificity, threshold)
    for threshold in np.unique(np.concatenate(([0.001], probabilities, [0.999]))):
        prediction = probabilities >= threshold
        tn, fp, fn, tp = confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()
        sensitivity = tp / (tp + fn) if tp + fn else 0.0
        specificity = tn / (tn + fp) if tn + fp else 0.0
        if sensitivity >= target_sensitivity and (best is None or specificity > best[0]):
            best = (specificity, float(threshold))
    return round(best[1] if best else 0.5, 6)


def calculate_metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, float | int | None]:
    prediction = probabilities >= threshold
    tn, fp, fn, tp = confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()
    sensitivity = recall_score(y_true, prediction, zero_division=0)
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "rows": int(len(y_true)),
        "positive_cases": int(y_true.sum()),
        "positive_rate": round(float(y_true.mean()), 6),
        "roc_auc": _safe_auc(y_true, probabilities, roc_auc_score),
        "pr_auc": _safe_auc(y_true, probabilities, average_precision_score),
        "brier_score": round(float(brier_score_loss(y_true, probabilities)), 6),
        "threshold": float(threshold),
        "sensitivity": round(float(sensitivity), 6),
        "specificity": round(float(specificity), 6),
        "ppv": round(float(precision_score(y_true, prediction, zero_division=0)), 6),
        "npv": round(float(tn / (tn + fn) if tn + fn else 0.0), 6),
        "true_positive": int(tp),
        "false_positive": int(fp),
        "true_negative": int(tn),
        "false_negative": int(fn),
    }


def train_evaluated_model(
    dataset_path: Path,
    model_path: Path,
    metadata_path: Path,
    profile: str,
    random_state: int = 42,
) -> dict[str, Any]:
    """Train candidate models, select/calibrate on validation, evaluate once on test."""
    matrix, labels, names, _ = read_feature_dataset(dataset_path)
    x_development, x_test, y_development, y_test = train_test_split(
        matrix, labels, test_size=0.20, stratify=labels, random_state=random_state,
    )
    x_train, x_validation, y_train, y_validation = train_test_split(
        x_development, y_development, test_size=0.25, stratify=y_development,
        random_state=random_state,
    )

    candidates = _candidate_models(random_state)
    validation_scores: dict[str, dict[str, float | None]] = {}
    fitted_candidates: dict[str, Pipeline] = {}
    for name, candidate in candidates.items():
        fitted = candidate.fit(x_train, y_train)
        probabilities = fitted.predict_proba(x_validation)[:, 1]
        validation_scores[name] = {
            "roc_auc": _safe_auc(y_validation, probabilities, roc_auc_score),
            "pr_auc": _safe_auc(y_validation, probabilities, average_precision_score),
        }
        fitted_candidates[name] = fitted

    # PR-AUC is selected because mortality is imbalanced.  A transparent
    # Logistic Regression remains in the metadata as a baseline comparison.
    selected_name = max(
        validation_scores,
        key=lambda name: validation_scores[name]["pr_auc"] if validation_scores[name]["pr_auc"] is not None else -1.0,
    )
    estimator = fitted_candidates[selected_name]
    validation_raw = estimator.predict_proba(x_validation)[:, 1]
    calibrator = IsotonicRegression(y_min=0.001, y_max=0.999, out_of_bounds="clip")
    calibrator.fit(validation_raw, y_validation)
    validation_probability = np.clip(calibrator.predict(validation_raw), 0.001, 0.999)
    threshold = choose_threshold(y_validation, validation_probability)
    test_probability = np.clip(calibrator.predict(estimator.predict_proba(x_test)[:, 1]), 0.001, 0.999)

    metadata: dict[str, Any] = {
        "model_version": f"physionet2012-{profile}-v1",
        "profile": profile,
        "endpoint": MODEL_ENDPOINT,
        "training_completed_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "PhysioNet/CinC Challenge 2012 v1.0.0",
        "dataset_path": str(dataset_path),
        "feature_count": len(names),
        "feature_names": names,
        "split": {
            "strategy": "stratified patient-record split (60% train / 20% validation / 20% hold-out test)",
            "random_state": random_state,
            "test_set_used_for_model_selection": False,
        },
        "candidate_validation_metrics": validation_scores,
        "selected_estimator": selected_name,
        "threshold_selection": "validation set: highest specificity with sensitivity >= 0.80",
        "validation_metrics": calculate_metrics(y_validation, validation_probability, threshold),
        "holdout_test_metrics": calculate_metrics(y_test, test_probability, threshold),
        "research_only_notice": RESEARCH_ONLY_NOTICE,
        "runtime_requirements": {
            "minimum_history_points": 5,
            "minimum_feature_coverage": 0.80,
            "when_unavailable": "Return INSUFFICIENT_DATA; do not calculate a risk score.",
        },
    }
    bundle = CalibratedRiskBundle(estimator=estimator, calibrator=calibrator, feature_names=names, metadata=metadata)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def write_model_card(metadata: dict[str, Any], output_path: Path) -> None:
    """Write a compact, presentation-ready model card from the saved metadata."""
    test = metadata["holdout_test_metrics"]
    lines = [
        f"# {metadata['model_version']} model card",
        "",
        "## Intended use",
        "",
        f"- Endpoint: {metadata['endpoint']}",
        f"- Dataset: {metadata['dataset']}",
        "- Intended use: research/education demonstration only.",
        "",
        "## Hold-out test metrics",
        "",
        f"- ROC-AUC: {test['roc_auc']}",
        f"- PR-AUC: {test['pr_auc']}",
        f"- Brier score: {test['brier_score']}",
        f"- Sensitivity / specificity: {test['sensitivity']} / {test['specificity']}",
        f"- PPV / NPV: {test['ppv']} / {test['npv']}",
        f"- Threshold: {test['threshold']}",
        "",
        "## Limits",
        "",
        f"{metadata['research_only_notice']}",
        "",
        "This is an ICU mortality endpoint, not a diagnosis or ward-deterioration prediction. "
        "It requires external validation and clinician governance before any real-world use.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
