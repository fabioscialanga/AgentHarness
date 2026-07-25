#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentharness.stage2_recovery import RecoveryError, finalize_recovery  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize an explicitly authorized exploratory Stage 2 recovery")
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = finalize_recovery(
            recovery_root=args.recovery_root,
            output_root=args.output_root,
            manifest_path=args.manifest,
            authorization_path=args.authorization,
        )
    except (RecoveryError, OSError, ValueError):
        print(json.dumps({"status": "FAIL"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
