#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from agentharness.level2_reliability import compute_level2_gate, load_results


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: level2_gate_report.py <stage-b-diagnostics-results.json>")
    results_path = Path(args[0]).resolve()
    summary = compute_level2_gate(load_results(results_path))
    summary["results_path"] = str(results_path)
    summary_path = results_path.with_name("stage-b-diagnostics-summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
