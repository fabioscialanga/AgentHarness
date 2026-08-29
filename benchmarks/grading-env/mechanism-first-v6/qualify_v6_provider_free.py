from __future__ import annotations

"""Execute the complete V6 materialization/evaluator qualification; zero provider calls."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentharness import efficacy_v6 as protocol


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    rows: list[dict[str, object]] = []
    public_input_leakage: list[dict[str, str]] = []
    private_tokens = {
        "agentharness_mutant", "sequential_bug",
        *(check.casefold() for checks in protocol.TASK_CHECKS.values() for check in checks),
        *(claim.casefold() for claim in protocol.OPAQUE_FINDING_IDS.values()),
    }
    for task in protocol.EVALUATION_TASKS:
        for name in ("SPEC.md", "CLAIMS_CONTRACT.template.json"):
            path = ROOT / "benchmarks" / task / name
            text = path.read_text(encoding="utf-8").casefold()
            for token in sorted(private_tokens):
                if token in text:
                    public_input_leakage.append({"path": path.relative_to(ROOT).as_posix(), "token": token})
    with tempfile.TemporaryDirectory(prefix="v6-provider-free-") as temporary:
        base = Path(temporary)
        for index, task in enumerate(protocol.EVALUATION_TASKS):
            clean = base / f"clean-{index}"
            controlled = base / f"controlled-{index}"
            clone_a, clone_b = base / f"clone-a-{index}", base / f"clone-b-{index}"
            protocol.materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
            protocol.materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
            clone_fingerprint = protocol.clone_pair(controlled, clone_a, clone_b)
            reference = protocol.evaluate_heldout(clean, task, repo_root=ROOT)
            target = protocol.evaluate_heldout(controlled, task, repo_root=ROOT)
            row = {
                "task_id": task,
                "reference_target_passed": reference["target_passed"],
                "reference_guards_passed": reference["guards_passed"],
                "controlled_target_passed": target["target_passed"],
                "controlled_guards_passed": target["guards_passed"],
                "controlled_failed_only_target": target["target_passed"] is False and target["guards_passed"] is True,
                "leakage": protocol.leakage_scan(controlled) + protocol.leakage_scan(clean),
                "clones_byte_identical": protocol.tree_fingerprint(clone_a) == protocol.tree_fingerprint(clone_b) == clone_fingerprint,
            }
            rows.append(row)
    ok = not public_input_leakage and all(
        row["reference_target_passed"] is True
        and row["reference_guards_passed"] is True
        and row["controlled_failed_only_target"] is True
        and row["leakage"] == []
        and row["clones_byte_identical"] is True
        for row in rows
    )
    payload = {
        "schema_version": 6,
        "qualification": "provider-free",
        "provider_calls": 0,
        "model_calls": 0,
        "task_count": len(rows),
        "public_input_leakage": public_input_leakage,
        "ok": ok,
        "rows": rows,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
