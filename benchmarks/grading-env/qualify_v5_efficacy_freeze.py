from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentharness.benchmark_heldout_evaluator_v5 import evaluate_heldout
from agentharness.efficacy_v5 import (
    EVALUATION_TASKS,
    OPAQUE_FINDING_IDS,
    TASK_DEFECTS,
    clone_pair,
    leakage_scan,
    materialize_clean_reference,
    materialize_controlled_start,
    opaque_review_feedback,
    tree_fingerprint,
    validate_opaque_feedback,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="v5-efficacy-freeze-") as raw:
        temporary = Path(raw)
        for index, task_id in enumerate(EVALUATION_TASKS, 1):
            clean = temporary / f"{index:02d}-clean"
            controlled = temporary / f"{index:02d}-controlled"
            clone_a = temporary / f"{index:02d}-A"
            clone_b = temporary / f"{index:02d}-B"
            clean_materialization = materialize_clean_reference(task_id=task_id, repo_root=ROOT, destination=clean)
            controlled_materialization = materialize_controlled_start(task_id=task_id, repo_root=ROOT, destination=controlled)
            clone_fingerprint = clone_pair(controlled, clone_a, clone_b)
            clone_identity = clone_fingerprint == tree_fingerprint(controlled) == tree_fingerprint(clone_a) == tree_fingerprint(clone_b)
            clean_result = evaluate_heldout(clean, task_id, repo_root=ROOT)
            controlled_result = evaluate_heldout(controlled, task_id, repo_root=ROOT)
            feedback = opaque_review_feedback(task_id)
            finding_id = validate_opaque_feedback(feedback, task_id=task_id)
            checks = {
                "clean_target_green": clean_result["target_passed"] is True,
                "clean_guards_green": clean_result["guards_passed"] is True,
                "controlled_target_red": controlled_result["target_passed"] is False,
                "controlled_guards_green": controlled_result["guards_passed"] is True,
                "controlled_singleton": controlled_result["target_check"] == TASK_DEFECTS[task_id],
                "source_leak_free": not leakage_scan(controlled),
                "clone_a_leak_free": not leakage_scan(clone_a),
                "clone_b_leak_free": not leakage_scan(clone_b),
                "clone_identity": clone_identity,
                "feedback_opaque": finding_id == OPAQUE_FINDING_IDS[task_id],
            }
            rows.append({
                "task_id": task_id,
                "target_check": TASK_DEFECTS[task_id],
                "checks": checks,
                "ok": all(checks.values()),
                "clean_materialization": clean_materialization,
                "controlled_materialization": controlled_materialization,
                "clone_fingerprint": clone_fingerprint,
                "clean_evaluator_payload_sha256": clean_result["evaluator_payload_sha256"],
                "controlled_evaluator_payload_sha256": controlled_result["evaluator_payload_sha256"],
                "qualifier_sha256": clean_result["qualifier_sha256"],
                "feedback_sha256": hashlib.sha256(json.dumps(feedback, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            })
    payload = {
        "schema_version": 5,
        "suite_id": "mechanism-first-v5-efficacy-freeze-admission",
        "ok": len(rows) == 12 and all(row["ok"] for row in rows),
        "task_count": len(rows),
        "provider_model_calls": 0,
        "tasks": rows,
        "frozen_code_sha256": {
            "src/agentharness/efficacy_v5.py": digest(ROOT / "src/agentharness/efficacy_v5.py"),
            "src/agentharness/benchmark_heldout_evaluator_v5.py": digest(ROOT / "src/agentharness/benchmark_heldout_evaluator_v5.py"),
            "benchmarks/grading-env/run_mechanism_first_v4.py": digest(ROOT / "benchmarks/grading-env/run_mechanism_first_v4.py"),
            "benchmarks/grading-env/run_mechanism_first_v5.py": digest(ROOT / "benchmarks/grading-env/run_mechanism_first_v5.py"),
            "benchmarks/grading-env/MECHANISM_FIRST_V5_PREREG.template.json": digest(ROOT / "benchmarks/grading-env/MECHANISM_FIRST_V5_PREREG.template.json"),
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "task_count": len(rows), "provider_model_calls": 0}, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
