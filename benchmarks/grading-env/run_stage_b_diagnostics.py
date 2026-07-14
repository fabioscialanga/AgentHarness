#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from agentharness.benchmark_cells import (
    DEFAULT_RUNS_ROOT,
    HermesCliInvoker,
    assert_nonshared_solution_hashes,
    execute_cell,
    prepare_fresh_cell,
)
from agentharness.level2_reliability import (
    auditable_results_for_solution_hash_guard,
    compute_level2_gate,
    should_abort_provider_outage,
    trailing_contiguous_category,
)


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _required_model_pin() -> tuple[str, str, str]:
    provider = (os.environ.get("STAGEB_PROVIDER") or os.environ.get("STAGE1_PROVIDER") or "").strip()
    model = (os.environ.get("STAGEB_MODEL") or os.environ.get("STAGE1_MODEL") or "").strip()
    max_turns = (os.environ.get("STAGEB_MAX_TURNS") or os.environ.get("STAGE1_MAX_TURNS") or "40").strip()
    if not provider or not model:
        raise RuntimeError(
            "Stage B requires an explicit provider/model pin. Set STAGEB_PROVIDER and STAGEB_MODEL "
            "(legacy STAGE1_PROVIDER/STAGE1_MODEL are also accepted)."
        )
    return provider, model, max_turns


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
    provider, model, max_turns = _required_model_pin()
    abort_provider_streak = int(os.environ.get("STAGEB_ABORT_PROVIDER_STREAK", "3"))
    if abort_provider_streak < 1:
        raise RuntimeError("STAGEB_ABORT_PROVIDER_STREAK must be at least 1")

    invoker = HermesCliInvoker(
        hermes_command=os.environ.get("STAGEB_HERMES_COMMAND") or None,
        toolsets=os.environ.get("STAGEB_HERMES_TOOLSETS", "terminal,file"),
        provider=provider,
        model=model,
        max_turns=max_turns,
    )

    planned_cells = [
        {"task_id": task_id, "condition": condition, "replicate_id": replicate_id}
        for task_id in task_ids
        for condition in conditions
        for replicate_id in replicates
    ]
    runs_root.mkdir(parents=True, exist_ok=True)
    provenance_path = runs_root / "stage-b-run-provenance.json"
    provenance = {
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "runs_root": str(runs_root.resolve()),
        "provider": provider,
        "model": model,
        "max_turns": max_turns,
        "abort_provider_streak": abort_provider_streak,
        "planned_cells": planned_cells,
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")

    results: list[dict[str, object]] = []
    aborted_early = False
    abort_reason: str | None = None
    progress_path = runs_root / "stage-b-diagnostics-progress.json"

    for cell_spec in planned_cells:
        task_id = cell_spec["task_id"]
        condition = cell_spec["condition"]
        replicate_id = cell_spec["replicate_id"]
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

        progress_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        if should_abort_provider_outage(results, abort_provider_streak):
            aborted_early = True
            abort_reason = (
                f"provider_unavailable streak reached {abort_provider_streak}; "
                "run downgraded to diagnostic-only"
            )
            break

    auditable_results = auditable_results_for_solution_hash_guard(results)
    if auditable_results:
        assert_nonshared_solution_hashes(auditable_results)

    output_path = runs_root / "stage-b-diagnostics-results.json"
    output_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    summary = compute_level2_gate(results)
    summary["results_path"] = str(output_path)
    summary["provenance_path"] = str(provenance_path)
    summary["planned_cells"] = len(planned_cells)
    summary["completed_cells"] = len(results)
    summary["remaining_cells"] = len(planned_cells) - len(results)
    summary["aborted_early"] = aborted_early
    summary["abort_reason"] = abort_reason
    summary["trailing_provider_unavailable_streak"] = trailing_contiguous_category(
        results, "provider_unavailable"
    )
    summary["gate_checks"]["completed_as_planned"] = not aborted_early
    if aborted_early:
        summary["passes_gate"] = False

    summary_path = runs_root / "stage-b-diagnostics-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
