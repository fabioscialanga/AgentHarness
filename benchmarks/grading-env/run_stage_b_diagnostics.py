#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from agentharness.benchmark_cells import (
    DEFAULT_RUNS_ROOT,
    HermesCliInvoker,
    assert_nonshared_solution_hashes,
    execute_cell,
    prepare_fresh_cell,
)
from agentharness.level2_reliability import compute_level2_gate


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _runner_exception_result(*, cell_dir: Path, task_id: str, condition: str, replicate_id: str, exc: Exception) -> dict[str, object]:
    outputs_dir = cell_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = outputs_dir / "runner-exception.txt"
    trace_path.write_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), encoding="utf-8")
    try:
        cell_label = str(cell_dir.relative_to(Path.cwd()))
    except ValueError:
        cell_label = str(cell_dir)
    return {
        "cell": cell_label,
        "task_id": task_id,
        "condition": condition,
        "replicate_id": replicate_id,
        "pytest_exit_code": None,
        "verify_run_ok": False,
        "benchmark_execution_status": "harness_invalid",
        "benchmark_outcome_status": "real_failure",
        "score": 0.0,
        "evaluation_summary": {"passed": 0, "failed": 0, "invalid": 1},
        "solution_hash": f"runner_exception:{task_id}:{condition}:{replicate_id}",
        "attempt_count": 0,
        "classification_reason": f"Stage B runner exception: {exc}",
        "runner_exception_path": str(trace_path),
    }


def main() -> int:
    runs_root = Path(os.environ.get("STAGEB_RUNS_ROOT", str(DEFAULT_RUNS_ROOT)))
    task_ids = _parse_csv_env(
        "STAGEB_TASKS",
        [path.name for path in sorted(runs_root.iterdir()) if path.is_dir()] if runs_root.exists() else [],
    )
    if not task_ids:
        raise RuntimeError("No Stage B tasks resolved. Set STAGEB_TASKS or create a runs root with task directories.")

    conditions = _parse_csv_env("STAGEB_CONDITIONS", ["A-baseline", "B-agentharness"])
    replicates = _parse_csv_env("STAGEB_REPLICATES", ["r1", "r2"])
    invoker = HermesCliInvoker(
        hermes_command=os.environ.get("STAGEB_HERMES_COMMAND") or None,
        toolsets=os.environ.get("STAGEB_HERMES_TOOLSETS", "terminal,file"),
    )

    results: list[dict[str, object]] = []
    for task_id in task_ids:
        for condition in conditions:
            for replicate_id in replicates:
                cell_dir = runs_root / task_id / condition / replicate_id
                try:
                    prepare_fresh_cell(
                        task_id=task_id,
                        condition=condition,
                        replicate_id=replicate_id,
                        cell_dir=cell_dir,
                    )
                    results.append(execute_cell(cell_dir, invoker))
                except Exception as exc:
                    results.append(
                        _runner_exception_result(
                            cell_dir=cell_dir,
                            task_id=task_id,
                            condition=condition,
                            replicate_id=replicate_id,
                            exc=exc,
                        )
                    )

    assert_nonshared_solution_hashes(results)
    runs_root.mkdir(parents=True, exist_ok=True)
    output_path = runs_root / "stage-b-diagnostics-results.json"
    output_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    summary = compute_level2_gate(results)
    summary["results_path"] = str(output_path)
    summary_path = runs_root / "stage-b-diagnostics-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
