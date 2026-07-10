#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentharness.stage2_analysis import build_dataset_from_progress, write_json  # noqa: E402


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the frozen Stage 2 analysis dataset from a run progress.json file.")
    parser.add_argument("progress", type=Path, help="Path to the Stage 2 progress.json file")
    parser.add_argument("--output", type=Path, required=True, help="Output dataset JSON path")
    return parser.parse_args()


def main() -> int:
    args = _cli()
    rows = build_dataset_from_progress(args.progress)
    write_json(args.output, rows)
    print(json.dumps({"ok": True, "rows": len(rows), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
