#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TARGET_REPO = Path(
    os.environ.get("STAGE1_TARGET_REPO", "/home/fabio/AgentHarness-stage1-freeze-04db03d")
)
if not TARGET_REPO.exists():
    raise SystemExit(f"Target repo does not exist: {TARGET_REPO}")

sys.path.insert(0, str(TARGET_REPO / "src"))
from agentharness import benchmark_cells as bc  # noqa: E402

TASKS = [
    "support-ticket-api",
    "inventory-adjustment-api",
    "webhook-ingestion-service",
    "report-export-job",
    "leave-request-api",
    "incident-escalation-api",
    "refund-approval-api",
    "csv-member-import",
]
CONDITIONS = ["A-baseline", "B-agentharness"]
REPLICATES = ["r1", "r2", "r3"]
MAX_RERUNS_AFTER_INVALID = 1
SEED = int(os.environ.get("STAGE1_SEED", "20260701"))

PROVIDER_UNAVAILABLE_MARKERS = (
    "HTTP 429",
    "usage limit has been reached",
    "rate limit",
    "temporarily unavailable",
)


def _is_provider_unavailable_record(record: dict[str, object]) -> bool:
    final_error = str(record.get("final_error") or "")
    if any(marker.lower() in final_error.lower() for marker in PROVIDER_UNAVAILABLE_MARKERS):
        return True
    cell_dir = Path(str(record["cell_dir"]))
    attempts_dir = cell_dir / "outputs" / "agent-invocations"
    if not attempts_dir.is_dir():
        return False
    for stdout_path in sorted(attempts_dir.glob("*.stdout")):
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        if any(marker.lower() in text.lower() for marker in PROVIDER_UNAVAILABLE_MARKERS):
            return True
    for stderr_path in sorted(attempts_dir.glob("*.stderr")):
        text = stderr_path.read_text(encoding="utf-8", errors="replace")
        if any(marker.lower() in text.lower() for marker in PROVIDER_UNAVAILABLE_MARKERS):
            return True
    return False


RUNS_ROOT = Path(
    os.environ.get(
        "STAGE1_RUNS_ROOT",
        str(TARGET_REPO / "benchmarks" / "runs" / f"stage-1-diagnostics-seed-{SEED}"),
    )
)
AGENT_TIMEOUT_SECONDS = int(os.environ.get("STAGE1_AGENT_TIMEOUT_SECONDS", "1800"))
PYTEST_TIMEOUT_SECONDS = int(os.environ.get("STAGE1_PYTEST_TIMEOUT_SECONDS", "180"))
RUNS_ROOT.mkdir(parents=True, exist_ok=True)


class FixedHermesInvoker(bc.HermesCliInvoker):
    def __init__(self) -> None:
        super().__init__(
            hermes_command=os.environ.get("STAGE1_HERMES_COMMAND") or "hermes",
            toolsets=os.environ.get("STAGE1_HERMES_TOOLSETS", "terminal,file"),
            max_retries=3,
            retry_backoff_seconds=30.0,
        )

    def _invoke(
        self,
        *,
        prompt: str,
        attempt_name: str,
        prompt_kind: str,
        outputs_dir: Path,
        workspace: Path,
    ):
        command = [
            self._hermes_command,
            "chat",
            "-Q",
            "--source",
            "tool",
            "--ignore-rules",
            "--yolo",
            "--toolsets",
            self._toolsets,
            "--provider",
            os.environ.get("STAGE1_PROVIDER", "openai-codex"),
            "-m",
            os.environ.get("STAGE1_MODEL", "gpt-5.4"),
            "--max-turns",
            os.environ.get("STAGE1_MAX_TURNS", "40"),
            "-q",
            prompt,
        ]
        last_attempt = None
        for retry_index in range(1, self._max_retries + 1):
            suffix = "" if self._max_retries == 1 else f".try{retry_index}"
            stdout_path = outputs_dir / f"{attempt_name}{suffix}.stdout"
            stderr_path = outputs_dir / f"{attempt_name}{suffix}.stderr"
            started = bc._utc_now()
            t0 = time.time()
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
                stdout_text = completed.stdout
                stderr_text = completed.stderr
                exit_code = completed.returncode
            except subprocess.TimeoutExpired as exc:
                stdout_text = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr_text = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                stderr_text += f"\n[run_stage1_diagnostics] agent invocation timed out after {AGENT_TIMEOUT_SECONDS} seconds\n"
                exit_code = 124
            duration = time.time() - t0
            finished = bc._utc_now()
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            session_match = bc.SESSION_ID_RE.search(stdout_text)
            session_id = session_match.group("session_id") if session_match else None
            last_attempt = bc.AgentAttempt(
                attempt_name=attempt_name,
                prompt_kind=prompt_kind,
                command=command,
                exit_code=exit_code,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                working_directory=workspace,
                session_id=session_id,
                started_at=started,
                finished_at=finished,
                duration_seconds=duration,
            )
            if exit_code == 0 and session_id:
                return last_attempt
            faux_completed = subprocess.CompletedProcess(command, exit_code, stdout_text, stderr_text)
            if retry_index < self._max_retries and bc._is_retryable_invocation_failure(faux_completed):
                time.sleep(self._retry_backoff_seconds * retry_index)
        assert last_attempt is not None
        return last_attempt


def enforced_run_workspace_pytest(workspace: Path, report_path: Path) -> dict[str, object]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    python_path = bc.ensure_test_venv(workspace)
    stdout_path = report_path.with_suffix(".stdout")
    stderr_path = report_path.with_suffix(".stderr")
    started = bc._utc_now()
    t0 = time.time()
    command = [str(python_path), "-m", "pytest", "-q"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
            env={**bc._base_env(), "PYTHONPATH": str(workspace)},
            timeout=PYTEST_TIMEOUT_SECONDS,
        )
        stdout_text = completed.stdout
        stderr_text = completed.stderr
        exit_code = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout_text = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr_text = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr_text += f"\n[run_stage1_diagnostics] pytest timed out after {PYTEST_TIMEOUT_SECONDS} seconds\n"
        exit_code = 124
        timed_out = True
    duration = time.time() - t0
    finished = bc._utc_now()
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")
    payload = {
        "command": command,
        "exit_code": exit_code,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration,
        "timeout_seconds": PYTEST_TIMEOUT_SECONDS,
        "timed_out": timed_out,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    bc.run_workspace_pytest = enforced_run_workspace_pytest

    cells: list[dict[str, str]] = []
    for task in TASKS:
        for condition in CONDITIONS:
            for replicate in REPLICATES:
                cells.append({
                    "task_id": task,
                    "condition": condition,
                    "replicate_id": replicate,
                })
    random.Random(SEED).shuffle(cells)
    (RUNS_ROOT / "cell-order.json").write_text(json.dumps(cells, indent=2) + "\n", encoding="utf-8")

    invoker = FixedHermesInvoker()
    results: list[dict[str, object]] = []
    for index, spec in enumerate(cells, 1):
        cell_dir = RUNS_ROOT / spec["task_id"] / spec["condition"] / spec["replicate_id"]
        attempts: list[dict[str, object]] = []
        final_result = None
        final_error = None
        for run_index in range(1, MAX_RERUNS_AFTER_INVALID + 2):
            bc.prepare_fresh_cell(
                task_id=spec["task_id"],
                condition=spec["condition"],
                replicate_id=spec["replicate_id"],
                cell_dir=cell_dir,
            )
            try:
                result = bc.execute_cell(cell_dir, invoker)
                invalid = (
                    result.get("benchmark_execution_status") == "harness_invalid"
                    or result.get("evaluation_summary", {}).get("invalid", 0) > 0
                )
                attempts.append(
                    {
                        "run_index": run_index,
                        "result": result,
                        "invalid_triggered_rerun": bool(invalid),
                    }
                )
                final_result = result
                if invalid and run_index <= MAX_RERUNS_AFTER_INVALID:
                    continue
                break
            except Exception as exc:
                attempts.append(
                    {
                        "run_index": run_index,
                        "exception": repr(exc),
                        "invalid_triggered_rerun": run_index <= MAX_RERUNS_AFTER_INVALID,
                    }
                )
                final_error = repr(exc)
                if run_index <= MAX_RERUNS_AFTER_INVALID:
                    continue
                break
        record = {
            "order_index": index,
            "task_id": spec["task_id"],
            "condition": spec["condition"],
            "replicate_id": spec["replicate_id"],
            "cell_dir": str(cell_dir),
            "attempts": attempts,
        }
        if final_result is not None:
            record["final"] = final_result
        if final_error is not None and final_result is None:
            record["final_error"] = final_error
        results.append(record)
        (RUNS_ROOT / "progress.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    summary: dict[str, object] = {
        "seed": SEED,
        "runs_root": str(RUNS_ROOT),
        "cells_total": len(results),
        "by_condition": {},
        "by_task_condition": {},
        "invalid_cells": [],
        "provider_unavailable_cells": [],
        "ceiling_cells": [],
        "under_ceiling_cells": [],
    }
    for condition in CONDITIONS:
        finals = [r.get("final") for r in results if r["condition"] == condition and r.get("final")]
        scores = [float(f.get("score", 0.0)) for f in finals]
        invalids = [
            r
            for r in results
            if r["condition"] == condition
            and (
                not r.get("final")
                or r["final"].get("benchmark_execution_status") == "harness_invalid"
                or r["final"].get("evaluation_summary", {}).get("invalid", 0) > 0
            )
        ]
        provider_unavailable = [r for r in invalids if _is_provider_unavailable_record(r)]
        summary["by_condition"][condition] = {
            "n": len(finals),
            "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
            "medianish_sorted_scores": sorted(scores),
            "ceiling_count": sum(1 for s in scores if s >= 1.0),
            "under_ceiling_count": sum(1 for s in scores if s < 1.0),
            "harness_invalid_count": len(invalids),
            "provider_unavailable_count": len(provider_unavailable),
        }
    for task in TASKS:
        for condition in CONDITIONS:
            task_records = [r for r in results if r["task_id"] == task and r["condition"] == condition]
            finals = [r.get("final") for r in task_records if r.get("final")]
            scores = [float(f.get("score", 0.0)) for f in finals]
            invalid_records = [
                r
                for r in task_records
                if (
                    not r.get("final")
                    or r["final"].get("benchmark_execution_status") == "harness_invalid"
                    or r["final"].get("evaluation_summary", {}).get("invalid", 0) > 0
                )
            ]
            invalid_count = len(invalid_records)
            provider_unavailable_count = sum(1 for r in invalid_records if _is_provider_unavailable_record(r))
            key = f"{task}::{condition}"
            summary["by_task_condition"][key] = {
                "n": len(task_records),
                "scores": scores,
                "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
                "ceiling_count": sum(1 for s in scores if s >= 1.0),
                "harness_invalid_count": invalid_count,
                "provider_unavailable_count": provider_unavailable_count,
            }
    for r in results:
        f = r.get("final")
        if (
            not f
            or f.get("benchmark_execution_status") == "harness_invalid"
            or f.get("evaluation_summary", {}).get("invalid", 0) > 0
        ):
            summary["invalid_cells"].append(
                {
                    "task_id": r["task_id"],
                    "condition": r["condition"],
                    "replicate_id": r["replicate_id"],
                    "cell_dir": r["cell_dir"],
                }
            )
            if _is_provider_unavailable_record(r):
                summary["provider_unavailable_cells"].append(
                    {
                        "task_id": r["task_id"],
                        "condition": r["condition"],
                        "replicate_id": r["replicate_id"],
                        "cell_dir": r["cell_dir"],
                    }
                )
        elif float(f.get("score", 0.0)) >= 1.0:
            summary["ceiling_cells"].append(
                {
                    "task_id": r["task_id"],
                    "condition": r["condition"],
                    "replicate_id": r["replicate_id"],
                    "cell_dir": r["cell_dir"],
                    "score": f["score"],
                }
            )
        else:
            summary["under_ceiling_cells"].append(
                {
                    "task_id": r["task_id"],
                    "condition": r["condition"],
                    "replicate_id": r["replicate_id"],
                    "cell_dir": r["cell_dir"],
                    "score": f["score"],
                }
            )

    summary_path = RUNS_ROOT / "stage1-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "target_repo": str(TARGET_REPO),
                "runs_root": str(RUNS_ROOT),
                "cells_total": len(results),
                "summary_path": str(summary_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
