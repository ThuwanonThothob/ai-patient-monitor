"""CLI that trains, calibrates, evaluates, and version-controls a research model."""

from __future__ import annotations

import argparse
from pathlib import Path

from .modeling import train_evaluated_model, write_model_card


def main() -> None:
    parser = argparse.ArgumentParser(description="Train evaluated PhysioNet 2012 research model.")
    parser.add_argument("--dataset", type=Path, required=True, help="Prepared feature CSV")
    parser.add_argument("--profile", choices=("ward_core", "full"), default="ward_core")
    parser.add_argument("--model-out", type=Path, required=True)
    parser.add_argument("--metadata-out", type=Path, required=True)
    parser.add_argument("--model-card-out", type=Path, required=True)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    metadata = train_evaluated_model(
        dataset_path=args.dataset,
        model_path=args.model_out,
        metadata_path=args.metadata_out,
        profile=args.profile,
        random_state=args.random_state,
    )
    write_model_card(metadata, args.model_card_out)
    metrics = metadata["holdout_test_metrics"]
    print(f"Selected model: {metadata['selected_estimator']}")
    print(f"Hold-out ROC-AUC={metrics['roc_auc']} PR-AUC={metrics['pr_auc']} Brier={metrics['brier_score']}")
    print(f"Model → {args.model_out}")
    print(f"Model card → {args.model_card_out}")


if __name__ == "__main__":
    main()
