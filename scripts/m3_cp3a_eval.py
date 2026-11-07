"""Read-only CP3-A evaluation of the frozen DEP detection labels.

Extraction uses a temporary directory. The script does not execute fixture
commands, inspect evidence, or alter benchmark files.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "m3_dep"
EXPECTED = {"S": "risk", "N": "no_change", "A": "abstain"}
sys.path.insert(0, str(ROOT / "src" / "agentharness"))
from risk_dep import detect_dependency_change  # noqa: E402 - pure module, no package runtime needed


def evaluate() -> dict:
    ledger = json.loads((DATASET / "ledger.json").read_text(encoding="utf-8"))
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    rows = []
    for scenario in ledger["scenarios"]:
        with tempfile.TemporaryDirectory(prefix="m3-cp3a-") as temporary:
            with zipfile.ZipFile(DATASET / "fixtures" / f"{scenario['id']}.zip") as archive:
                if any(not name.startswith("repo/") or ".." in Path(name).parts for name in archive.namelist()):
                    raise ValueError("unsafe fixture path")
                archive.extractall(temporary)
            repo = Path(temporary) / "repo"
            kwargs = {}
            if scenario["state_kind"] == "committed":
                kwargs = {"base_commit": scenario["base_commit"], "target_commit": scenario["target_commit"]}
            started = time.perf_counter_ns()
            detected = detect_dependency_change(repo, **kwargs)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            expected = EXPECTED[scenario["risk_label"]]
            matrix[expected][detected.status] += 1
            rows.append({"id": scenario["id"], "expected": expected, "observed": detected.status,
                         "reason": detected.reason, "elapsed_ms": round(elapsed_ms, 3)})
    durations = sorted(row["elapsed_ms"] for row in rows)
    result = {
        "schema_version": "m3.cp3a-eval.v0",
        "scope": "detection only; evidence matching NOT RUN",
        "fixture_count": len(rows),
        "matrix": {label: dict(counts) for label, counts in sorted(matrix.items())},
        "correct": sum(row["expected"] == row["observed"] for row in rows),
        "p50_ms": durations[len(durations) // 2],
        "p95_ms": durations[max(0, (95 * len(durations) + 99) // 100 - 1)],
        "rows": rows,
    }
    return result


if __name__ == "__main__":
    result = evaluate()
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if result["correct"] == result["fixture_count"] else 1)
