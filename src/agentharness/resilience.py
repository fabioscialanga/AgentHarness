from __future__ import annotations

import hashlib
import json
import random
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .observability import EventLogger, default_trace_path, utc_now_iso


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    max_backoff_seconds: float = 30.0
    jitter_seconds: float = 0.0
    retry_on_exit_codes: tuple[int, ...] = (1,)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RetryPolicy":
        data = payload or {}
        retry_codes = data.get("retry_on_exit_codes", [1])
        if not isinstance(retry_codes, list):
            retry_codes = [1]
        return cls(
            max_attempts=max(1, int(data.get("max_attempts", 1))),
            backoff_seconds=max(0.0, float(data.get("backoff_seconds", 0.0))),
            max_backoff_seconds=max(0.0, float(data.get("max_backoff_seconds", 30.0))),
            jitter_seconds=max(0.0, float(data.get("jitter_seconds", 0.0))),
            retry_on_exit_codes=tuple(int(item) for item in retry_codes),
        )

    def should_retry(self, exit_code: int, attempt_number: int) -> bool:
        return attempt_number < self.max_attempts and exit_code in self.retry_on_exit_codes

    def sleep_seconds(self, attempt_number: int) -> float:
        base = self.backoff_seconds * (2 ** max(0, attempt_number - 1))
        delay = min(base, self.max_backoff_seconds)
        if self.jitter_seconds:
            delay += random.uniform(0.0, self.jitter_seconds)
        return round(delay, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "backoff_seconds": self.backoff_seconds,
            "max_backoff_seconds": self.max_backoff_seconds,
            "jitter_seconds": self.jitter_seconds,
            "retry_on_exit_codes": list(self.retry_on_exit_codes),
        }


@dataclass(frozen=True)
class PlanTarget:
    name: str
    command: str
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: int = 60
    working_dir: str = "."

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanTarget":
        return cls(
            name=str(payload.get("name", "")).strip(),
            command=str(payload.get("command", "")).strip(),
            retry=RetryPolicy.from_dict(payload.get("retry")),
            timeout_seconds=max(1, int(payload.get("timeout_seconds", 60))),
            working_dir=str(payload.get("working_dir", ".") or "."),
        )


@dataclass(frozen=True)
class PlanStep:
    id: str
    description: str
    success_exit_codes: tuple[int, ...]
    targets: tuple[PlanTarget, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanStep":
        codes = payload.get("success_exit_codes", [0])
        if not isinstance(codes, list) or not codes:
            codes = [0]
        targets_payload = payload.get("targets", [])
        if not isinstance(targets_payload, list):
            targets_payload = []
        return cls(
            id=str(payload.get("id", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            success_exit_codes=tuple(int(item) for item in codes),
            targets=tuple(PlanTarget.from_dict(item) for item in targets_payload if isinstance(item, dict)),
        )


@dataclass(frozen=True)
class ResiliencePlan:
    plan_id: str
    workspace: Path
    steps: tuple[PlanStep, ...]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, base_dir: Path) -> "ResiliencePlan":
        workspace_value = payload.get("workspace", ".")
        workspace = Path(workspace_value)
        if not workspace.is_absolute():
            workspace = (base_dir / workspace).resolve()
        steps_payload = payload.get("steps", [])
        if not isinstance(steps_payload, list):
            steps_payload = []
        return cls(
            plan_id=str(payload.get("plan_id", "")).strip(),
            workspace=workspace.resolve(),
            steps=tuple(PlanStep.from_dict(item) for item in steps_payload if isinstance(item, dict)),
            raw=payload,
        )


@dataclass
class AttemptRecord:
    target_name: str
    attempt: int
    command: str
    cwd: str
    exit_code: int | None
    succeeded: bool
    stdout_path: str
    stderr_path: str
    started_at: str
    finished_at: str
    duration_ms: int
    retry_scheduled: bool
    next_delay_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "attempt": self.attempt,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "succeeded": self.succeeded,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "retry_scheduled": self.retry_scheduled,
            "next_delay_seconds": self.next_delay_seconds,
        }


@dataclass
class StepExecutionResult:
    step_id: str
    description: str
    ok: bool
    winner: str | None
    attempts: list[AttemptRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "ok": self.ok,
            "winner": self.winner,
            "attempts": [item.to_dict() for item in self.attempts],
            "notes": self.notes,
        }


@dataclass
class ResilientRunResult:
    plan_id: str
    plan_path: Path
    workspace: Path
    ok: bool
    steps: list[StepExecutionResult]
    tool_version: str
    executed_at: str
    plan_sha256: str
    trace_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_path": str(self.plan_path),
            "workspace": str(self.workspace),
            "ok": self.ok,
            "steps": [item.to_dict() for item in self.steps],
            "tool_version": self.tool_version,
            "executed_at": self.executed_at,
            "plan_sha256": self.plan_sha256,
            "trace_path": self.trace_path,
        }


@dataclass
class PlanValidationError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_resilience_plan(path: str | Path) -> ResiliencePlan:
    plan_path = Path(path).resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanValidationError("Plan file must parse to a JSON object")
    plan = ResiliencePlan.from_dict(payload, base_dir=plan_path.parent)
    _validate_plan(plan)
    return plan


def _validate_plan(plan: ResiliencePlan) -> None:
    if not plan.plan_id:
        raise PlanValidationError("plan_id is required")
    if not plan.workspace.is_dir():
        raise PlanValidationError(f"workspace does not exist: {plan.workspace}")
    if not plan.steps:
        raise PlanValidationError("steps must contain at least one step")
    for step in plan.steps:
        if not step.id:
            raise PlanValidationError("every step must have a non-empty id")
        if not step.targets:
            raise PlanValidationError(f"step '{step.id}' must define at least one target")
        for target in step.targets:
            if not target.name:
                raise PlanValidationError(f"step '{step.id}' contains a target without a name")
            if not target.command:
                raise PlanValidationError(f"target '{target.name}' in step '{step.id}' is missing command")
            working_dir = Path(target.working_dir)
            if working_dir.is_absolute():
                raise PlanValidationError(f"target '{target.name}' in step '{step.id}' must use a workspace-relative working_dir")
            resolved = (plan.workspace / working_dir).resolve()
            try:
                resolved.relative_to(plan.workspace)
            except ValueError as exc:
                raise PlanValidationError(
                    f"target '{target.name}' in step '{step.id}' escapes the workspace via working_dir"
                ) from exc
            if not resolved.is_dir():
                raise PlanValidationError(
                    f"target '{target.name}' in step '{step.id}' points to a missing working_dir: {target.working_dir}"
                )


def default_resilience_report_path(plan_path: str | Path) -> Path:
    resolved = Path(plan_path).resolve()
    return resolved.parent / f"{resolved.stem}.resilience-report.json"


def write_resilience_report(result: ResilientRunResult, output_path: str | Path | None = None) -> Path:
    report_path = Path(output_path) if output_path else default_resilience_report_path(result.plan_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report_path


def _run_attempt(
    plan: ResiliencePlan,
    step: PlanStep,
    target: PlanTarget,
    attempt_number: int,
    logger: EventLogger | None,
) -> AttemptRecord:
    cwd = (plan.workspace / target.working_dir).resolve()
    evidence_dir = plan.workspace / ".agentharness" / "resilience" / plan.plan_id / step.id / target.name
    evidence_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{target.command}#{attempt_number}".encode("utf-8")).hexdigest()[:12]
    stdout_path = evidence_dir / f"attempt-{attempt_number}-{digest}.stdout"
    stderr_path = evidence_dir / f"attempt-{attempt_number}-{digest}.stderr"
    started_epoch = time.time()
    started_at = utc_now_iso()
    if logger:
        logger.emit(
            "resilience_attempt_started",
            plan_id=plan.plan_id,
            step_id=step.id,
            target_name=target.name,
            attempt=attempt_number,
            command=target.command,
            cwd=str(cwd),
        )
    completed = subprocess.run(
        shlex.split(target.command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=target.timeout_seconds,
        check=False,
        shell=False,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    finished_epoch = time.time()
    succeeded = completed.returncode in step.success_exit_codes
    retry_scheduled = target.retry.should_retry(completed.returncode, attempt_number) and not succeeded
    next_delay = target.retry.sleep_seconds(attempt_number) if retry_scheduled else None
    record = AttemptRecord(
        target_name=target.name,
        attempt=attempt_number,
        command=target.command,
        cwd=str(cwd),
        exit_code=completed.returncode,
        succeeded=succeeded,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        started_at=started_at,
        finished_at=utc_now_iso(),
        duration_ms=int((finished_epoch - started_epoch) * 1000),
        retry_scheduled=retry_scheduled,
        next_delay_seconds=next_delay,
    )
    if logger:
        logger.emit(
            "resilience_attempt_finished",
            plan_id=plan.plan_id,
            step_id=step.id,
            target_name=target.name,
            attempt=attempt_number,
            exit_code=completed.returncode,
            succeeded=succeeded,
            retry_scheduled=retry_scheduled,
            next_delay_seconds=next_delay,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
    return record


def run_resilience_plan(
    plan_path: str | Path,
    *,
    write_report: bool = False,
    report_path: str | Path | None = None,
    trace_path: str | Path | None = None,
) -> ResilientRunResult:
    resolved_plan_path = Path(plan_path).resolve()
    plan = load_resilience_plan(resolved_plan_path)
    logger: EventLogger | None = None
    if trace_path:
        logger = EventLogger.create(output_path=trace_path, run_id=plan.plan_id)
    elif plan.workspace.exists():
        auto_trace = default_trace_path(plan.workspace, "resilience")
        logger = EventLogger.create(output_path=auto_trace, run_id=plan.plan_id)

    if logger:
        logger.emit("resilience_plan_started", plan_id=plan.plan_id, plan_path=str(resolved_plan_path))

    step_results: list[StepExecutionResult] = []
    overall_ok = True
    for step in plan.steps:
        step_result = StepExecutionResult(
            step_id=step.id,
            description=step.description,
            ok=False,
            winner=None,
        )
        if logger:
            logger.emit("resilience_step_started", plan_id=plan.plan_id, step_id=step.id, description=step.description)
        for target in step.targets:
            attempt_number = 0
            while attempt_number < target.retry.max_attempts:
                attempt_number += 1
                attempt = _run_attempt(plan, step, target, attempt_number, logger)
                step_result.attempts.append(attempt)
                if attempt.succeeded:
                    step_result.ok = True
                    step_result.winner = target.name
                    step_result.notes.append(f"Target '{target.name}' succeeded on attempt {attempt_number}.")
                    break
                if attempt.retry_scheduled and attempt.next_delay_seconds:
                    step_result.notes.append(
                        f"Target '{target.name}' failed with exit_code {attempt.exit_code}; retrying in {attempt.next_delay_seconds:.3f}s."
                    )
                    time.sleep(attempt.next_delay_seconds)
                else:
                    step_result.notes.append(
                        f"Target '{target.name}' exhausted retries with exit_code {attempt.exit_code}; moving to next fallback target."
                    )
                    break
            if step_result.ok:
                break
        if not step_result.ok:
            overall_ok = False
            step_result.notes.append("No target established a successful outcome for this step.")
        step_results.append(step_result)
        if logger:
            logger.emit(
                "resilience_step_finished",
                plan_id=plan.plan_id,
                step_id=step.id,
                ok=step_result.ok,
                winner=step_result.winner,
                attempt_count=len(step_result.attempts),
            )
        if not step_result.ok:
            break

    result = ResilientRunResult(
        plan_id=plan.plan_id,
        plan_path=resolved_plan_path,
        workspace=plan.workspace,
        ok=overall_ok,
        steps=step_results,
        tool_version=__version__,
        executed_at=utc_now_iso(),
        plan_sha256=_sha256_file(resolved_plan_path),
        trace_path=str(logger.output_path) if logger else None,
    )
    if logger:
        logger.emit(
            "resilience_plan_finished",
            plan_id=plan.plan_id,
            ok=result.ok,
            step_count=len(step_results),
        )
    if write_report:
        write_resilience_report(result, report_path)
    return result
