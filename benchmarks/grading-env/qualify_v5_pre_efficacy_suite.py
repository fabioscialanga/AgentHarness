from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ROSTER = (
    "qualify_v5_rotating_token.py",
    "qualify_v5_envelope_crypto.py",
    "qualify_v5_capability.py",
    "qualify_v5_atomic_batch.py",
    "qualify_v5_ack_queue.py",
    "qualify_v5_frame_parser.py",
    "qualify_v5_csv_stream.py",
    "qualify_v5_epoch_leader.py",
    "qualify_v5_1_auth_cache.py",
    "qualify_v5_2_release_pointer.py",
    "qualify_v5_2_tiered_cache.py",
    "qualify_v5_2_portable_receipts.py",
)


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def public_tree(task_id: str) -> tuple[str, int]:
    root = ROOT / "benchmarks" / task_id
    if not root.is_dir():
        raise RuntimeError(f"missing public bundle: benchmarks/{task_id}")
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    if not files or not (root / "SPEC.md").is_file():
        raise RuntimeError(f"incomplete public bundle: {task_id}")
    accumulator = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        accumulator.update(len(relative).to_bytes(8, "big"))
        accumulator.update(relative)
        accumulator.update(len(data).to_bytes(8, "big"))
        accumulator.update(data)
    return accumulator.hexdigest(), len(files)


def declared_probes(payload: dict[str, Any]) -> int:
    value = payload.get("total_scored_probes_per_implementation")
    if value is None:
        value = payload.get("total_probes_per_implementation")
    if not isinstance(value, int) or value <= 0:
        counts = payload.get("probe_counts")
        if isinstance(counts, dict) and counts and all(isinstance(item, int) and item > 0 for item in counts.values()):
            value = sum(counts.values())
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError("missing positive probe total")
    return value


def validate_payload(payload: dict[str, Any], qualifier_name: str) -> dict[str, Any]:
    if payload.get("ok") is not True:
        raise RuntimeError(f"{qualifier_name}: qualification is not GO")
    efficacy = payload.get("efficacy_cells")
    efficacy_is_zero = efficacy is False or (isinstance(efficacy, int) and not isinstance(efficacy, bool) and efficacy == 0)
    if payload.get("target_model_calls") != 0 or not efficacy_is_zero:
        raise RuntimeError(f"{qualifier_name}: target/efficacy activity detected")
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError(f"{qualifier_name}: missing task_id")
    rows = payload.get("matrix")
    if not isinstance(rows, list) or len(rows) < 6:
        raise RuntimeError(f"{qualifier_name}: incomplete matrix")
    if rows[0].get("implementation") != "reference" or rows[0].get("failed") != []:
        raise RuntimeError(f"{qualifier_name}: reference is not clean")
    for row in rows:
        if row.get("common_failed", []) != []:
            raise RuntimeError(f"{qualifier_name}: common controls failed for {row.get('implementation')}")
    for row in rows[1:]:
        failed = row.get("failed")
        if not isinstance(failed, list) or len(failed) != 1:
            raise RuntimeError(f"{qualifier_name}: non-singleton row {row.get('implementation')}")
    probe_total = declared_probes(payload)
    tree_sha, public_files = public_tree(task_id)
    return {
        "task_id": task_id,
        "qualifier": f"benchmarks/grading-env/{qualifier_name}",
        "probe_total_per_implementation": probe_total,
        "matrix_rows": len(rows),
        "reference_failed": [],
        "variant_failures": {row["implementation"]: row["failed"] for row in rows[1:]},
        "public_bundle_tree_sha256": tree_sha,
        "public_bundle_files": public_files,
        "target_model_calls": 0,
        "efficacy_cells": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    report_path = args.report.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    tasks: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    for qualifier_name in ROSTER:
        qualifier = ROOT / "benchmarks/grading-env" / qualifier_name
        if not qualifier.is_file():
            raise SystemExit(f"pre-efficacy suite: NO-GO: missing {qualifier_name}")
        completed = subprocess.run(
            [sys.executable, str(qualifier)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(f"pre-efficacy suite: NO-GO: {qualifier_name} exit {completed.returncode}")
        try:
            payload = json.loads(completed.stdout)
            summary = validate_payload(payload, qualifier_name)
        except Exception as exc:
            raise SystemExit(f"pre-efficacy suite: NO-GO: {qualifier_name}: {exc}") from exc
        if summary["task_id"] in task_ids:
            raise SystemExit(f"pre-efficacy suite: NO-GO: duplicate task_id {summary['task_id']}")
        task_ids.add(summary["task_id"])
        raw_path = output_dir / f"{summary['task_id']}.json"
        raw_path.write_bytes(completed.stdout)
        summary.update(
            {
                "qualifier_sha256": digest(qualifier),
                "result_file": raw_path.relative_to(ROOT).as_posix(),
                "result_sha256": digest(raw_path),
                "stderr_sha256": digest_bytes(completed.stderr),
            }
        )
        tasks.append(summary)

    if len(tasks) != 12:
        raise SystemExit(f"pre-efficacy suite: NO-GO: expected 12 tasks, got {len(tasks)}")
    report = {
        "schema_version": 1,
        "suite_id": "mechanism-first-v5-pre-efficacy-12",
        "status": "GO",
        "task_count": len(tasks),
        "task_ids": [task["task_id"] for task in tasks],
        "total_declared_probes_per_reference_pass": sum(task["probe_total_per_implementation"] for task in tasks),
        "tasks": tasks,
        "qualification_only": True,
        "target_model_calls": 0,
        "efficacy_cells_observed": 0,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": "GO",
                "task_count": len(tasks),
                "total_declared_probes_per_reference_pass": report["total_declared_probes_per_reference_pass"],
                "report": report_path.relative_to(ROOT).as_posix(),
                "report_sha256": digest(report_path),
                "target_model_calls": 0,
                "efficacy_cells_observed": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
