#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentharness.stage2_analysis import synthetic_dataset, write_json  # noqa: E402


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a synthetic Stage 2 dataset with known effect.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--true-effect", type=float, default=0.18)
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--replicates", type=int, default=6)
    parser.add_argument("--without-invalids", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _cli()
    rows = synthetic_dataset(
        n_tasks=args.tasks,
        replicates=args.replicates,
        true_effect=args.true_effect,
        include_invalids=not args.without_invalids,
    )
    write_json(args.output, rows)
    print(json.dumps({"ok": True, "rows": len(rows), "true_effect": args.true_effect, "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
