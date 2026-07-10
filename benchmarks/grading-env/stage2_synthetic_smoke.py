#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthetic smoke for frozen Stage 2 analysis.")
    parser.add_argument("--true-effect", type=float, default=0.18)
    parser.add_argument("--tolerance", type=float, default=0.03)
    return parser.parse_args()


def main() -> int:
    args = _cli()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        dataset = tmp / "synthetic-dataset.json"
        output_dir = tmp / "synthetic-analysis"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "benchmarks" / "grading-env" / "stage2_generate_synthetic_dataset.py"),
                "--output",
                str(dataset),
                "--true-effect",
                str(args.true_effect),
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "benchmarks" / "grading-env" / "stage2_run_analysis.py"),
                str(dataset),
                "--output-dir",
                str(output_dir),
                "--cluster-resamples",
                "2000",
                "--wild-resamples",
                "2000",
            ],
            check=True,
        )
        final_report = json.loads((output_dir / "final-report.json").read_text(encoding="utf-8"))
        observed = float(final_report["primary_analysis"]["effect_b_minus_a"])
        if abs(observed - args.true_effect) > args.tolerance:
            raise SystemExit(
                f"Synthetic effect check failed: observed {observed:.6f} vs true {args.true_effect:.6f} > tolerance {args.tolerance:.6f}"
            )
        print(json.dumps({"ok": True, "observed_effect": observed, "true_effect": args.true_effect, "output_dir": str(output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
