#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from agentharness.benchmark_cells import (
    DEFAULT_RUNS_ROOT,
    HermesCliInvoker,
    assert_nonshared_solution_hashes,
    execute_cell,
    prepare_fresh_cell,
)


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


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
                prepare_fresh_cell(
                    task_id=task_id,
                    condition=condition,
                    replicate_id=replicate_id,
                    cell_dir=cell_dir,
                )
                results.append(execute_cell(cell_dir, invoker))

    assert_nonshared_solution_hashes(results)
    runs_root.mkdir(parents=True, exist_ok=True)
    output_path = runs_root / "stage-b-diagnostics-results.json"
    output_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
