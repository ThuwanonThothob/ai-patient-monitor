"""CLI for building reproducible PhysioNet Challenge 2012 feature datasets."""

from __future__ import annotations

import argparse
from pathlib import Path

from .physionet2012 import CORE_PARAMETERS, FULL_PARAMETERS, prepare_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare PhysioNet Challenge 2012 ICU feature rows.")
    parser.add_argument("--records-dir", type=Path, required=True, help="Directory containing set-a/*.txt files")
    parser.add_argument("--outcomes", type=Path, required=True, help="Path to Outcomes-a.txt")
    parser.add_argument("--output", type=Path, required=True, help="Output CSV path")
    parser.add_argument("--profile", choices=("ward_core", "full"), default="ward_core")
    args = parser.parse_args()

    parameters = CORE_PARAMETERS if args.profile == "ward_core" else FULL_PARAMETERS
    result = prepare_dataset(args.records_dir, args.outcomes, args.output, parameters)
    print(
        f"Prepared {result.rows} ICU stays ({result.positives} positive outcomes), "
        f"{result.feature_count} features → {result.output_path}"
    )
    print(f"Manifest → {result.manifest_path}")


if __name__ == "__main__":
    main()
