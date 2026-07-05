from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CellResult = dict[str, Any]


def classify_level2_cell(result: CellResult) -> str:
    execution_status = str(result.get("benchmark_execution_status") or "")
    outcome_status = str(result.get("benchmark_outcome_status") or "")
    if execution_status == "provider_unavailable":
        return "provider_unavailable"
    if execution_status == "harness_invalid":
        return "harness_invalid"
    if execution_status == "valid" and outcome_status == "success":
        return "success"
    return "real_failure"


def longest_contiguous_category(results: list[CellResult], category: str) -> int:
    longest = 0
    current = 0
    for result in results:
        if classify_level2_cell(result) == category:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def compute_level2_gate(results: list[CellResult]) -> dict[str, Any]:
    categorized: list[CellResult] = []
    counts: Counter[str] = Counter()
    task_successes: dict[str, int] = defaultdict(int)
    by_task: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "provider_unavailable": 0, "harness_invalid": 0, "real_failure": 0})

    for result in results:
        category = classify_level2_cell(result)
        counts[category] += 1
        task_id = str(result.get("task_id") or "")
        by_task[task_id][category] += 1
        if category == "success":
            task_successes[task_id] += 1
        categorized.append(
            {
                "cell": result.get("cell"),
                "task_id": task_id,
                "condition": result.get("condition"),
                "replicate_id": result.get("replicate_id"),
                "category": category,
                "benchmark_execution_status": result.get("benchmark_execution_status"),
                "benchmark_outcome_status": result.get("benchmark_outcome_status"),
                "score": result.get("score"),
            }
        )

    total_cells = len(results)
    total_invalid = total_cells - counts["success"]
    tasks_with_success = sum(1 for success_count in task_successes.values() if success_count > 0)
    longest_provider_block = longest_contiguous_category(results, "provider_unavailable")
    gate_checks = {
        "total_invalid_le_3": total_invalid <= 3,
        "harness_invalid_le_1": counts["harness_invalid"] <= 1,
        "no_provider_block_ge_3": longest_provider_block < 3,
        "tasks_with_success_ge_6": tasks_with_success >= 6,
        "summary_present": True,
    }
    passes_gate = all(gate_checks.values())

    by_task_rows = []
    for task_id in sorted(by_task):
        row = {"task_id": task_id, **by_task[task_id], "succeeded_at_least_once": by_task[task_id]["success"] > 0}
        by_task_rows.append(row)

    return {
        "total_cells": total_cells,
        "counts": {
            "success": counts["success"],
            "provider_unavailable": counts["provider_unavailable"],
            "harness_invalid": counts["harness_invalid"],
            "real_failure": counts["real_failure"],
            "total_invalid": total_invalid,
        },
        "tasks_with_success": tasks_with_success,
        "longest_provider_unavailable_block": longest_provider_block,
        "gate_checks": gate_checks,
        "passes_gate": passes_gate,
        "cells": categorized,
        "by_task": by_task_rows,
    }


def load_results(path: Path) -> list[CellResult]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list at {path}")
    return payload
