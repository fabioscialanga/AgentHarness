from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .benchmarking import render_json_template, write_rendered_json_template
from .repair_safety import (
    assess_repair_safety,
    manifest_install_state,
    restore_workspace,
    snapshot_workspace,
    static_repair_guardrails,
    tree_fingerprint,
    write_cumulative_diff,
    write_safety_report,
)
from .reexecution import default_execution_policy, sanitized_environment

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
DEFAULT_RUNS_ROOT = BENCHMARKS_DIR / "runs" / "stage-b-diagnostics"
GRADING_ENV_DIR = BENCHMARKS_DIR / "grading-env"
SESSION_ID_RE = re.compile(r"session_id:\s*(?P<session_id>\S+)")

AGENT_INVOCATION_TIMEOUT_SECONDS = int(os.environ.get("AGENTHARNESS_AGENT_TIMEOUT_SECONDS", "1800"))
ENV_SETUP_TIMEOUT_SECONDS = int(os.environ.get("AGENTHARNESS_ENV_SETUP_TIMEOUT_SECONDS", "300"))
PYTEST_TIMEOUT_SECONDS = int(os.environ.get("AGENTHARNESS_PYTEST_TIMEOUT_SECONDS", "600"))
VERIFY_RUN_TIMEOUT_SECONDS = int(os.environ.get("AGENTHARNESS_VERIFY_TIMEOUT_SECONDS", "300"))
BENCHMARK_EVAL_TIMEOUT_SECONDS = int(os.environ.get("AGENTHARNESS_BENCHMARK_TIMEOUT_SECONDS", "300"))
HELDOUT_EVAL_TIMEOUT_SECONDS = int(os.environ.get("AGENTHARNESS_EVALUATION_TIMEOUT_SECONDS", "300"))
EXPECTED_HELDOUT_CASES = 6

PROVIDER_UNAVAILABLE_MARKERS = (
    "HTTP 429",
    "usage limit has been reached",
    "rate limit",
    "temporarily unavailable",
    "quota",
    "produced no SSE events",
)

_EXCLUDED_PARTS = {".venv", ".pytest_cache", ".agentharness", ".stageb-test-venv", "__pycache__"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db"}


@dataclass
class AgentAttempt:
    attempt_name: str
    prompt_kind: str
    command: list[str]
    exit_code: int
    stdout_path: Path
    stderr_path: Path
    working_directory: Path
    session_id: str | None
    started_at: str
    finished_at: str
    duration_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_name": self.attempt_name,
            "prompt_kind": self.prompt_kind,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "working_directory": str(self.working_directory),
            "session_id": self.session_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class AgentInvocationResult:
    attempts: list[AgentAttempt]
    attempt_solution_hashes: dict[str, str | None] | None = None
    repair_safety: dict[str, object] | None = None
    treatment_delivery: dict[str, object] | None = None

    def to_dict(self) -> list[dict[str, object]]:
        return [attempt.to_dict() for attempt in self.attempts]


@dataclass
class ClassifiedCellFailure(Exception):
    execution_status: str
    classification_reason: str
    invocation_result: AgentInvocationResult | None = None


def _has_invocation_evidence(attempt: AgentAttempt) -> bool:
    if attempt.session_id:
        return True
    if attempt.stdout_path.is_file() and attempt.stdout_path.read_text(encoding="utf-8").strip():
        return True
    if attempt.stderr_path.is_file() and attempt.stderr_path.read_text(encoding="utf-8").strip():
        return True
    return False


def _successful_agent_attempt(attempt: AgentAttempt) -> bool:
    return attempt.exit_code == 0 and bool(attempt.session_id) and _has_invocation_evidence(attempt)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _classify_failed_agent_attempt(attempt: AgentAttempt, *, phase: str) -> tuple[str, str]:
    text = _attempt_output_text(attempt)
    completed = subprocess.CompletedProcess(
        args=attempt.command,
        returncode=attempt.exit_code,
        stdout=text,
        stderr="",
    )
    if _is_retryable_invocation_failure(completed):
        return (
            "harness_invalid",
            f"provider_unavailable: {phase} invocation did not complete successfully",
        )
    return (
        "harness_invalid",
        f"treatment_not_delivered: {phase} invocation did not complete successfully",
    )


class AgentInvoker(Protocol):
    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path) -> AgentInvocationResult:
        ...


class HermesCliInvoker:
    def __init__(
        self,
        hermes_command: str | None = None,
        toolsets: str = "terminal,file",
        max_retries: int = 3,
        retry_backoff_seconds: float = 30.0,
        provider: str | None = None,
        model: str | None = None,
        max_turns: int | str | None = None,
        admission_hook: Callable[[str, int], None] | None = None,
    ) -> None:
        self._hermes_command = hermes_command or "hermes"
        self._toolsets = toolsets
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._provider = provider
        self._model = model
        self._max_turns = str(max_turns) if max_turns is not None else None
        self._admission_hook = admission_hook

    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path) -> AgentInvocationResult:
        task_id = str(manifest["task_id"])
        condition = str(manifest["condition"])
        run_id = str(manifest["run_id"])
        spec_path = Path(str(manifest["spec_path"]))
        claims_template_path = Path(str(manifest["claims_template_path"]))

        attempts_dir = outputs_dir / "agent-invocations"
        attempts_dir.mkdir(parents=True, exist_ok=True)

        attempts: list[AgentAttempt] = []
        attempt_solution_hashes: dict[str, str | None] = {}
        initial_prompt = _build_initial_prompt(
            task_id=task_id,
            condition=condition,
            workspace=workspace,
            spec_path=spec_path,
            claims_template_path=claims_template_path,
        )
        attempts.append(
            self._invoke(
                prompt=initial_prompt,
                attempt_name="attempt-1-initial",
                prompt_kind="initial",
                outputs_dir=attempts_dir,
                workspace=workspace,
            )
        )
        attempt_solution_hashes["attempt_1_initial"] = (
            compute_solution_hash(workspace) if rel_solution_files(workspace) else None
        )

        pytest_report = outputs_dir / "pre-repair-pytest.json"
        try:
            pytest_result = run_workspace_pytest(workspace, pytest_report)
        except ClassifiedCellFailure as exc:
            raise ClassifiedCellFailure(
                exc.execution_status,
                exc.classification_reason,
                invocation_result=AgentInvocationResult(attempts=attempts),
            ) from exc

        snapshot_dir = outputs_dir / "pre-repair-workspace"
        snapshot_workspace(workspace, snapshot_dir)
        pre_manifest_install = manifest_install_state(workspace, task_id)
        protected_test_env = workspace / ".stageb-test-venv"
        pre_test_env_fingerprint = tree_fingerprint(protected_test_env)

        repair_prompt_path = outputs_dir / "pre-repair-treatment-prompt.txt"
        verify_feedback_path: Path | None = None
        feedback_sha256_pre: str | None = None
        try:
            if condition == "A-baseline":
                repair_prompt = _build_baseline_repair_prompt(
                    task_id=task_id,
                    workspace=workspace,
                    spec_path=spec_path,
                    pytest_stdout_path=str(pytest_result["stdout_path"]),
                    pytest_stderr_path=str(pytest_result["stderr_path"]),
                )
                _write_repair_treatment_prompt(prompt=repair_prompt, prompt_path=repair_prompt_path)
            else:
                verify_feedback_path = outputs_dir / "pre-repair-verify-run-report.json"
                provisional_run_path = outputs_dir / "pre-repair-run.json"
                provisional_claims_path = outputs_dir / "pre-repair-claims.json"
                write_run_json(
                    run_path=provisional_run_path,
                    manifest=manifest,
                    workspace=workspace,
                    pytest_command=_pytest_command_from_result(pytest_result),
                    pytest_exit=int(str(pytest_result["exit_code"])),
                    pytest_stdout_path=Path(str(pytest_result["stdout_path"])),
                    pytest_stderr_path=Path(str(pytest_result["stderr_path"])),
                )
                render_claims_json(run_id=run_id, claims_template_path=claims_template_path, claims_path=provisional_claims_path)
                verify_payload = run_verify_run(
                    run_path=provisional_run_path,
                    claims_path=provisional_claims_path,
                    report_path=verify_feedback_path,
                )
                _require_verify_feedback_delivery(verify_payload)
                feedback_sha256_pre = _sha256_file(verify_feedback_path)
                verify_feedback_path.chmod(0o444)
                repair_prompt = _build_agentharness_repair_prompt(
                    task_id=task_id,
                    workspace=workspace,
                    spec_path=spec_path,
                    pytest_stdout_path=str(pytest_result["stdout_path"]),
                    pytest_stderr_path=str(pytest_result["stderr_path"]),
                    verify_feedback_path=verify_feedback_path,
                )
                _write_repair_treatment_prompt(prompt=repair_prompt, prompt_path=repair_prompt_path)
        except ClassifiedCellFailure as exc:
            if exc.invocation_result is not None:
                raise
            raise ClassifiedCellFailure(
                exc.execution_status,
                exc.classification_reason,
                invocation_result=AgentInvocationResult(
                    attempts=list(attempts),
                    attempt_solution_hashes=attempt_solution_hashes.copy(),
                ),
            ) from exc

        treatment_prompt_sha256_pre = _sha256_file(repair_prompt_path)
        repair_prompt_path.chmod(0o444)
        repair_attempt = self._invoke(
            prompt=repair_prompt,
            attempt_name="attempt-2-repair",
            prompt_kind="repair",
            outputs_dir=attempts_dir,
            workspace=workspace,
        )
        attempts.append(repair_attempt)
        treatment_prompt_sha256_post = _sha256_file(repair_prompt_path)
        treatment_prompt_immutable = treatment_prompt_sha256_post == treatment_prompt_sha256_pre
        treatment_delivery: dict[str, object] = {
            "treatment_prompt_path": str(repair_prompt_path),
            "treatment_prompt_sha256_pre": treatment_prompt_sha256_pre,
            "treatment_prompt_sha256_post": treatment_prompt_sha256_post,
            "treatment_prompt_immutable": treatment_prompt_immutable,
            "repair_invocation_exit_code": repair_attempt.exit_code,
            "repair_invocation_session_id_present": bool(repair_attempt.session_id),
            "repair_invocation_evidence_present": _has_invocation_evidence(repair_attempt),
            "repair_invocation_succeeded": _successful_agent_attempt(repair_attempt),
            "feedback_delivered": False,
        }
        if condition == "B-agentharness":
            assert verify_feedback_path is not None and feedback_sha256_pre is not None
            feedback_sha256_post = _sha256_file(verify_feedback_path)
            feedback_immutable = feedback_sha256_post == feedback_sha256_pre
            treatment_delivery["feedback_path"] = str(verify_feedback_path)
            treatment_delivery["feedback_sha256_pre"] = feedback_sha256_pre
            treatment_delivery["feedback_sha256_post"] = feedback_sha256_post
            treatment_delivery["feedback_immutable"] = feedback_immutable
            treatment_delivery["feedback_delivered"] = feedback_immutable
        treatment_integrity = treatment_prompt_immutable and (
            condition == "A-baseline" or bool(treatment_delivery.get("feedback_immutable"))
        )
        if not treatment_integrity:
            raise ClassifiedCellFailure(
                "harness_invalid",
                "treatment_not_delivered: pre-repair treatment artifact changed during repair invocation",
                invocation_result=AgentInvocationResult(
                    attempts=attempts,
                    attempt_solution_hashes=attempt_solution_hashes.copy(),
                    treatment_delivery=treatment_delivery,
                ),
            )
        if not _successful_agent_attempt(repair_attempt):
            execution_status, reason = _classify_failed_agent_attempt(
                repair_attempt,
                phase="repair_treatment",
            )
            raise ClassifiedCellFailure(
                execution_status,
                reason,
                invocation_result=AgentInvocationResult(
                    attempts=attempts,
                    attempt_solution_hashes=attempt_solution_hashes.copy(),
                    treatment_delivery=treatment_delivery,
                ),
            )
        try:
            raw_repair_hash = compute_solution_hash(workspace) if rel_solution_files(workspace) else None
            attempt_solution_hashes["attempt_2_repair_raw"] = raw_repair_hash
            cumulative_diff = write_cumulative_diff(
                snapshot_dir,
                workspace,
                outputs_dir / "repair-cumulative.diff",
            )
            post_test_env_fingerprint = tree_fingerprint(protected_test_env)
            protected_runtime_changed = post_test_env_fingerprint != pre_test_env_fingerprint
            if protected_runtime_changed:
                post_pytest = pytest_result
                post_manifest_install = pre_manifest_install
            else:
                post_pytest = run_workspace_pytest(workspace, outputs_dir / "post-repair-safety-pytest.json")
                post_manifest_install = manifest_install_state(workspace, task_id)
            static_guardrails = static_repair_guardrails(
                snapshot_dir,
                workspace,
                pre_pytest_exit=int(str(pytest_result["exit_code"])),
            )
            repair_safety = assess_repair_safety(
                pre_pytest=pytest_result,
                post_pytest=post_pytest,
                pre_manifest_install=pre_manifest_install,
                post_manifest_install=post_manifest_install,
                static_guardrails=static_guardrails,
                cumulative_diff=cumulative_diff,
                protected_runtime_changed=protected_runtime_changed,
            )
        except Exception as exc:
            repair_safety = {
                "safe": False,
                "rollback_required": True,
                "reasons": ["repair_safety_gate_error"],
                "gate_error": f"{type(exc).__name__}: {exc}",
                "rollback_performed": False,
                "rollback_validation": None,
            }
            try:
                self._rollback_repair_workspace(
                    workspace=workspace,
                    snapshot_dir=snapshot_dir,
                    outputs_dir=outputs_dir,
                    pre_pytest=pytest_result,
                    repair_safety=repair_safety,
                )
            except Exception as rollback_exc:
                repair_safety["rollback_error"] = f"{type(rollback_exc).__name__}: {rollback_exc}"
            write_safety_report(repair_safety, outputs_dir / "repair-safety-gate.json")
            try:
                attempt_solution_hashes["attempt_2_repair"] = (
                    compute_solution_hash(workspace) if rel_solution_files(workspace) else None
                )
            except Exception as hash_exc:
                attempt_solution_hashes["attempt_2_repair"] = None
                repair_safety["final_hash_error"] = f"{type(hash_exc).__name__}: {hash_exc}"
                write_safety_report(repair_safety, outputs_dir / "repair-safety-gate.json")
            raise ClassifiedCellFailure(
                "harness_invalid",
                f"repair safety gate failed after repair; rollback attempted: {type(exc).__name__}: {exc}",
                invocation_result=AgentInvocationResult(
                    attempts=attempts,
                    attempt_solution_hashes=attempt_solution_hashes,
                    repair_safety=repair_safety,
                ),
            ) from exc

        if bool(repair_safety["rollback_required"]):
            try:
                self._rollback_repair_workspace(
                    workspace=workspace,
                    snapshot_dir=snapshot_dir,
                    outputs_dir=outputs_dir,
                    pre_pytest=pytest_result,
                    repair_safety=repair_safety,
                )
            except Exception as exc:
                repair_safety["rollback_error"] = f"{type(exc).__name__}: {exc}"
                write_safety_report(repair_safety, outputs_dir / "repair-safety-gate.json")
                raise ClassifiedCellFailure(
                    "harness_invalid",
                    f"repair rollback failed: {type(exc).__name__}: {exc}",
                    invocation_result=AgentInvocationResult(
                        attempts=attempts,
                        attempt_solution_hashes=attempt_solution_hashes,
                        repair_safety=repair_safety,
                    ),
                ) from exc
            validation = repair_safety.get("rollback_validation")
            if not isinstance(validation, dict) or not bool(validation.get("ok")):
                write_safety_report(repair_safety, outputs_dir / "repair-safety-gate.json")
                raise ClassifiedCellFailure(
                    "harness_invalid",
                    "repair rollback failed to restore the canonical pre-repair pytest state",
                    invocation_result=AgentInvocationResult(
                        attempts=attempts,
                        attempt_solution_hashes=attempt_solution_hashes,
                        repair_safety=repair_safety,
                    ),
                )
        if bool(repair_safety.get("harness_invalid_required")):
            attempt_solution_hashes["attempt_2_repair"] = (
                compute_solution_hash(workspace) if rel_solution_files(workspace) else None
            )
            write_safety_report(repair_safety, outputs_dir / "repair-safety-gate.json")
            raise ClassifiedCellFailure(
                "harness_invalid",
                "repair safety gate infrastructure error; workspace rolled back",
                invocation_result=AgentInvocationResult(
                    attempts=attempts,
                    attempt_solution_hashes=attempt_solution_hashes,
                    repair_safety=repair_safety,
                ),
            )
        write_safety_report(repair_safety, outputs_dir / "repair-safety-gate.json")
        attempt_solution_hashes["attempt_2_repair"] = (
            compute_solution_hash(workspace) if rel_solution_files(workspace) else None
        )
        return AgentInvocationResult(
            attempts=attempts,
            attempt_solution_hashes=attempt_solution_hashes,
            repair_safety=repair_safety,
            treatment_delivery=treatment_delivery,
        )

    def _rollback_repair_workspace(
        self,
        *,
        workspace: Path,
        snapshot_dir: Path,
        outputs_dir: Path,
        pre_pytest: dict[str, object],
        repair_safety: dict[str, object],
    ) -> None:
        restore_workspace(workspace, snapshot_dir)
        rollback_pytest = run_workspace_pytest(
            workspace,
            outputs_dir / "post-rollback-validation-pytest.json",
        )
        expected_exit = int(str(pre_pytest["exit_code"]))
        restored_exit = int(str(rollback_pytest["exit_code"]))
        repair_safety["rollback_performed"] = True
        repair_safety["rollback_validation"] = {
            "ok": restored_exit == expected_exit,
            "expected_pytest_exit": expected_exit,
            "restored_pytest_exit": restored_exit,
        }

    def _invoke(self, *, prompt: str, attempt_name: str, prompt_kind: str, outputs_dir: Path, workspace: Path) -> AgentAttempt:
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
        ]
        if self._provider:
            command.extend(["--provider", self._provider])
        if self._model:
            command.extend(["-m", self._model])
        if self._max_turns:
            command.extend(["--max-turns", self._max_turns])
        command.extend(["-q", prompt])
        last_attempt: AgentAttempt | None = None
        for retry_index in range(1, self._max_retries + 1):
            if self._admission_hook is not None:
                self._admission_hook(attempt_name, retry_index)
            suffix = "" if self._max_retries == 1 else f".try{retry_index}"
            stdout_path = outputs_dir / f"{attempt_name}{suffix}.stdout"
            stderr_path = outputs_dir / f"{attempt_name}{suffix}.stderr"
            started = _utc_now()
            t0 = time.time()
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=AGENT_INVOCATION_TIMEOUT_SECONDS,
                )
                stdout_text = completed.stdout
                stderr_text = completed.stderr
                exit_code = completed.returncode
            except subprocess.TimeoutExpired as exc:
                stdout_text = _decode_timeout_output(exc.stdout)
                stderr_text = _decode_timeout_output(exc.stderr)
                timeout_msg = f"\nAgent invocation timed out after {AGENT_INVOCATION_TIMEOUT_SECONDS} seconds."
                stderr_text = (stderr_text + timeout_msg).strip() + "\n"
                completed = subprocess.CompletedProcess(args=command, returncode=124, stdout=stdout_text, stderr=stderr_text)
                exit_code = 124
            duration = time.time() - t0
            finished = _utc_now()
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            session_match = SESSION_ID_RE.search(stdout_text) or SESSION_ID_RE.search(stderr_text)
            session_id = session_match.group("session_id") if session_match else None
            last_attempt = AgentAttempt(
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
            meta_path = outputs_dir / f"{attempt_name}{suffix}.meta.json"
            meta_path.write_text(
                json.dumps(last_attempt.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if completed.returncode == 0 and session_id:
                return last_attempt
            if retry_index < self._max_retries and _is_retryable_invocation_failure(completed):
                time.sleep(self._retry_backoff_seconds * retry_index)
        assert last_attempt is not None
        return last_attempt


def _is_retryable_invocation_failure(completed: subprocess.CompletedProcess[str]) -> bool:
    retry_markers = PROVIDER_UNAVAILABLE_MARKERS + ("timed out after",)
    haystacks = (completed.stdout.lower(), completed.stderr.lower())
    return any(marker.lower() in haystack for marker in retry_markers for haystack in haystacks)


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _attempt_output_text(attempt: AgentAttempt) -> str:
    chunks: list[str] = []
    for path in (attempt.stdout_path, attempt.stderr_path):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _classify_empty_workspace_failure(invocation_result: AgentInvocationResult) -> tuple[str, str]:
    for attempt in invocation_result.attempts:
        text = _attempt_output_text(attempt)
        if _is_retryable_invocation_failure(
            subprocess.CompletedProcess(args=attempt.command, returncode=attempt.exit_code, stdout=text, stderr="")
        ):
            return (
                "harness_invalid",
                "provider_unavailable: agent produced no solution files because every invocation attempt failed with retryable provider-side errors",
            )
    return (
        "harness_invalid",
        "Agent produced no solution files and no retryable provider-side failure markers were detected in invocation logs",
    )


def _write_invalid_cell_artifacts(
    *,
    cell_dir: Path,
    manifest: dict[str, object],
    outputs_dir: Path,
    invocation_result: AgentInvocationResult,
    execution_status: str,
    classification_reason: str,
) -> dict[str, object]:
    task_id = str(manifest["task_id"])
    condition = str(manifest["condition"])
    replicate_id = str(manifest["replicate_id"])
    run_id = str(manifest["run_id"])
    workspace = Path(str(manifest["workspace"]))
    suite_path = outputs_dir / "suite.json"
    write_rendered_json_template(
        heldout_suite_template_path(task_id),
        run_id=run_id,
        output_path=suite_path,
    )
    outcome_status = "invalid"
    benchmark_payload = {
        "task_id": task_id,
        "critical_ok": False,
        "execution_status": execution_status,
        "outcome_status": outcome_status,
        "classification_reason": classification_reason,
        "passed_checks": [],
        "failed_checks": [],
        "observations": [],
    }
    (outputs_dir / "benchmark-evaluate-task.json").write_text(json.dumps(benchmark_payload, indent=2) + "\n", encoding="utf-8")
    eval_payload = {
        "suite_id": f"{task_id}_heldout_eval",
        "run_id": run_id,
        "run_path": None,
        "suite_path": str(suite_path),
        "ok": False,
        "summary": {"passed": 0, "failed": 0, "invalid": 1},
        "results": [
            {
                "case_id": "cell_execution",
                "case_type": "execution_status",
                "status": "invalid",
                "reason": classification_reason,
                "evidence": [str(outputs_dir / "agent-invocations")],
            }
        ],
        "gating_errors": [classification_reason],
    }
    (outputs_dir / "evaluation-report.json").write_text(json.dumps(eval_payload, indent=2) + "\n", encoding="utf-8")
    verify_payload = {
        "ok": False,
        "error": classification_reason,
        "reason": "empty_workspace",
    }
    (outputs_dir / "verify-run-report.json").write_text(json.dumps(verify_payload, indent=2) + "\n", encoding="utf-8")
    provenance = {
        "task_id": task_id,
        "condition": condition,
        "replicate_id": replicate_id,
        "run_id": run_id,
        "workspace": str(workspace),
        "solution_hash": f"{execution_status}:{task_id}:{condition}:{replicate_id}",
        "attempt_solution_hashes": invocation_result.attempt_solution_hashes or {},
        "solution_hash_changed_between_attempt_and_repair": False,
        "attempt_count": len(invocation_result.attempts),
        "attempts": invocation_result.to_dict(),
        "repair_safety": invocation_result.repair_safety,
        "treatment_delivery": invocation_result.treatment_delivery,
        "pytest": None,
    }
    (cell_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "task_id": task_id,
        "condition": condition,
        "replicate_id": replicate_id,
        "run_id": run_id,
        "repair_passes_used": max(0, len(invocation_result.attempts) - 1),
        "final_pytest_exit_code": None,
        "scorable_score": 0.0,
        "verify_run_ok": False,
        "treatment_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "feedback_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("feedback_delivered")
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "benchmark_execution_status": execution_status,
        "benchmark_outcome_status": outcome_status,
        "benchmark_classification_reason": classification_reason,
        "solution_hash": provenance["solution_hash"],
        "attempt_solution_hashes": provenance["attempt_solution_hashes"],
        "solution_hash_changed_between_attempt_and_repair": provenance["solution_hash_changed_between_attempt_and_repair"],
        "attempt_count": provenance["attempt_count"],
        "repair_safety": provenance["repair_safety"],
        "repair_rollback_performed": bool(
            isinstance(provenance["repair_safety"], dict)
            and provenance["repair_safety"].get("rollback_performed")
        ),
    }
    (cell_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    try:
        cell_label = str(cell_dir.relative_to(REPO_ROOT))
    except ValueError:
        cell_label = str(cell_dir)
    return {
        "cell": cell_label,
        "task_id": task_id,
        "condition": condition,
        "replicate_id": replicate_id,
        "pytest_exit_code": None,
        "verify_run_ok": False,
        "treatment_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "feedback_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("feedback_delivered")
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "benchmark_execution_status": execution_status,
        "benchmark_outcome_status": outcome_status,
        "benchmark_classification_reason": classification_reason,
        "score": 0.0,
        "evaluation_summary": eval_payload["summary"],
        "solution_hash": provenance["solution_hash"],
        "attempt_count": provenance["attempt_count"],
        "repair_safety": provenance["repair_safety"],
        "repair_rollback_performed": bool(
            isinstance(provenance["repair_safety"], dict)
            and provenance["repair_safety"].get("rollback_performed")
        ),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def benchmark_task_dir(task_id: str) -> Path:
    task_dir = BENCHMARKS_DIR / task_id
    if not task_dir.is_dir():
        raise FileNotFoundError(f"Benchmark task directory not found for {task_id}: {task_dir}")
    return task_dir


def build_cell_manifest(*, task_id: str, condition: str, replicate_id: str, cell_dir: Path) -> dict[str, object]:
    run_id = f"stageb_{task_id.replace('-', '_')}_{'a' if condition == 'A-baseline' else 'b'}_{replicate_id}"
    return {
        "task_id": task_id,
        "condition": condition,
        "replicate_id": replicate_id,
        "run_id": run_id,
        "cell_dir": str(cell_dir),
        "workspace": str(cell_dir / "workspace"),
        "spec_path": str(cell_dir / "inputs" / "SPEC.md"),
        "claims_template_path": str(cell_dir / "inputs" / "CLAIMS_CONTRACT.template.json"),
        "repair_policy": "generic-self-review" if condition == "A-baseline" else "verify-run-guided",
        "diagnostic_stage": "B",
    }


def prepare_fresh_cell(*, task_id: str, condition: str, replicate_id: str, cell_dir: Path) -> dict[str, object]:
    if cell_dir.exists():
        shutil.rmtree(cell_dir)
    workspace = cell_dir / "workspace"
    inputs_dir = cell_dir / "inputs"
    outputs_dir = cell_dir / "outputs"
    workspace.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    task_dir = benchmark_task_dir(task_id)
    shutil.copy2(task_dir / "SPEC.md", inputs_dir / "SPEC.md")
    shutil.copy2(task_dir / "CLAIMS_CONTRACT.template.json", inputs_dir / "CLAIMS_CONTRACT.template.json")

    manifest = build_cell_manifest(task_id=task_id, condition=condition, replicate_id=replicate_id, cell_dir=cell_dir)
    (cell_dir / "cell_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def rel_solution_files(workspace: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).as_posix()
        parts = set(rel.split("/"))
        if parts & _EXCLUDED_PARTS:
            continue
        if any(rel.endswith(suffix) for suffix in _EXCLUDED_SUFFIXES):
            continue
        if ".egg-info/" in rel:
            continue
        paths.append(rel)
    return paths


def compute_solution_hash(workspace: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for rel in rel_solution_files(workspace):
        path = workspace / rel
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def ensure_test_venv(workspace: Path) -> Path:
    venv_dir = workspace / ".stageb-test-venv"
    py = venv_dir / "bin" / "python"
    if py.exists():
        return py
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, timeout=ENV_SETUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ClassifiedCellFailure(
            "harness_invalid",
            f"Python venv creation timed out after {ENV_SETUP_TIMEOUT_SECONDS} seconds for {workspace}",
        ) from exc
    command = [
        str(py),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(GRADING_ENV_DIR / "wheelhouse"),
        "-c",
        str(GRADING_ENV_DIR / "constraints-py312.txt"),
        "pytest",
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "email-validator",
        "httpx",
    ]
    env = _base_env()
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=ENV_SETUP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClassifiedCellFailure(
            "harness_invalid",
            f"Offline shared deps install timed out after {ENV_SETUP_TIMEOUT_SECONDS} seconds for {workspace}",
        ) from exc
    if completed.returncode != 0:
        raise ClassifiedCellFailure(
            "harness_invalid",
            f"Offline shared deps install failed for {workspace}: {completed.stderr}",
        )
    return py


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["AGENTHARNESS_GRADING_ENV_DIR"] = str(GRADING_ENV_DIR)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _canonical_pytest_env(workspace: Path) -> dict[str, str]:
    env = sanitized_environment(default_execution_policy())
    env["AGENTHARNESS_GRADING_ENV_DIR"] = str(GRADING_ENV_DIR.resolve())
    env["PYTHONPATH"] = str(workspace.resolve())
    return env


def run_workspace_pytest(workspace: Path, report_path: Path) -> dict[str, object]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    python_path = ensure_test_venv(workspace)
    stdout_path = report_path.with_suffix(".stdout")
    stderr_path = report_path.with_suffix(".stderr")
    started = _utc_now()
    t0 = time.time()
    try:
        completed = subprocess.run(
            [str(python_path), "-m", "pytest", "-q"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
            env=_canonical_pytest_env(workspace),
            timeout=PYTEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClassifiedCellFailure(
            "harness_invalid",
            f"Workspace pytest timed out after {PYTEST_TIMEOUT_SECONDS} seconds for {workspace}",
        ) from exc
    duration = time.time() - t0
    finished = _utc_now()
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    payload = {
        "command": [str(python_path), "-m", "pytest", "-q"],
        "exit_code": completed.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _pytest_command_from_result(result: dict[str, object]) -> list[str]:
    raw_command = result.get("command")
    if not isinstance(raw_command, list) or not raw_command:
        raise ClassifiedCellFailure("harness_invalid", "Canonical pytest result did not contain a command")
    return [str(item) for item in raw_command]


def write_run_json(
    *,
    run_path: Path,
    manifest: dict[str, object],
    workspace: Path,
    pytest_command: list[str],
    pytest_exit: int,
    pytest_stdout_path: Path,
    pytest_stderr_path: Path,
) -> None:
    run_payload = {
        "run_id": manifest["run_id"],
        "workspace": str(workspace),
        "task": manifest["task_id"],
        "artifacts": {
            "changed_files": rel_solution_files(workspace),
            "commands": [
                {
                    "cmd": shlex.join(pytest_command),
                    "exit_code": pytest_exit,
                    "stdout_path": str(pytest_stdout_path),
                    "stderr_path": str(pytest_stderr_path),
                    "working_dir": ".",
                    "environment": {
                        "PYTHONPATH": str(workspace.resolve()),
                        "AGENTHARNESS_GRADING_ENV_DIR": str(GRADING_ENV_DIR.resolve()),
                    },
                }
            ],
            "outputs": [
                {"type": "file", "path": "README.md"},
                {"type": "file", "path": "pyproject.toml"},
            ],
        },
    }
    run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")


def render_claims_json(*, run_id: str, claims_template_path: Path, claims_path: Path) -> None:
    rendered_claims = render_json_template(claims_template_path, run_id=run_id)
    claims_path.write_text(json.dumps(rendered_claims, indent=2) + "\n", encoding="utf-8")


def _inspect_verify_feedback_report(report_path: Path) -> dict[str, object]:
    payload: dict[str, object] | None = None
    if not report_path.is_file():
        return {
            "report_path": str(report_path),
            "report_exists": False,
            "report_nonempty": False,
            "report_valid": False,
            "report_error": "report_missing",
            "report_payload": None,
        }
    if report_path.stat().st_size <= 0:
        return {
            "report_path": str(report_path),
            "report_exists": True,
            "report_nonempty": False,
            "report_valid": False,
            "report_error": "report_empty",
            "report_payload": None,
        }
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "report_path": str(report_path),
            "report_exists": True,
            "report_nonempty": True,
            "report_valid": False,
            "report_error": f"report_invalid_json:{exc.msg}",
            "report_payload": None,
        }
    feedback = payload.get("feedback") if isinstance(payload, dict) else None
    if not isinstance(feedback, dict):
        return {
            "report_path": str(report_path),
            "report_exists": True,
            "report_nonempty": True,
            "report_valid": False,
            "report_error": "report_missing_feedback",
            "report_payload": payload,
        }
    feedback_items = feedback.get("items")
    if not isinstance(feedback_items, list) or not feedback_items:
        return {
            "report_path": str(report_path),
            "report_exists": True,
            "report_nonempty": True,
            "report_valid": False,
            "report_error": "report_missing_feedback",
            "report_payload": payload,
        }
    return {
        "report_path": str(report_path),
        "report_exists": True,
        "report_nonempty": True,
        "report_valid": True,
        "report_error": None,
        "report_payload": payload,
    }


def _write_repair_treatment_prompt(*, prompt: str, prompt_path: Path) -> None:
    if not prompt.strip():
        raise ClassifiedCellFailure("harness_invalid", "treatment_not_delivered")
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.unlink(missing_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    if prompt_path.stat().st_size <= 0:
        raise ClassifiedCellFailure("harness_invalid", "treatment_not_delivered")


def _require_verify_feedback_delivery(verify_payload: dict[str, object]) -> None:
    if not bool(verify_payload.get("report_valid")):
        raise ClassifiedCellFailure("harness_invalid", "treatment_not_delivered")


def run_verify_run(*, run_path: Path, claims_path: Path, report_path: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agentharness",
                "verify-run",
                "--run",
                str(run_path),
                "--claims",
                str(claims_path),
                "--json",
                "--write-report",
                "--report-path",
                str(report_path),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=_base_env(),
            timeout=VERIFY_RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        payload = {
            "ok": False,
            "error": f"verify-run timed out after {VERIFY_RUN_TIMEOUT_SECONDS} seconds",
            "stdout": _decode_timeout_output(exc.stdout),
            "stderr": _decode_timeout_output(exc.stderr),
        }
    else:
        if completed.stdout.strip().startswith("{"):
            payload = json.loads(completed.stdout)
        else:
            payload = {
                "ok": False,
                "error": "verify-run did not emit JSON",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
    payload.update(_inspect_verify_feedback_report(report_path))
    return payload


def run_hidden_benchmark(*, run_path: Path, task_id: str, output_path: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agentharness",
                "benchmark-evaluate-task",
                "--run",
                str(run_path),
                "--task-id",
                task_id,
                "--json",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=_base_env(),
            timeout=BENCHMARK_EVAL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        payload = {
            "task_id": task_id,
            "critical_ok": False,
            "execution_status": "harness_invalid",
            "outcome_status": "real_failure",
            "classification_reason": f"benchmark-evaluate-task timed out after {BENCHMARK_EVAL_TIMEOUT_SECONDS} seconds",
            "passed_checks": [],
            "failed_checks": [],
            "observations": [],
            "stdout": _decode_timeout_output(exc.stdout),
            "stderr": _decode_timeout_output(exc.stderr),
        }
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload
    if completed.stdout.strip().startswith("{"):
        payload = json.loads(completed.stdout)
    else:
        payload = {
            "task_id": task_id,
            "critical_ok": False,
            "execution_status": "harness_invalid",
            "outcome_status": "real_failure",
            "classification_reason": "benchmark-evaluate-task did not emit JSON",
            "passed_checks": [],
            "failed_checks": [],
            "observations": [],
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def heldout_suite_template_path(task_id: str) -> Path:
    legacy = BENCHMARKS_DIR / task_id / "HELDOUT_EVALUATION_SUITE.template.json"
    if legacy.is_file():
        return legacy
    hidden = REPO_ROOT / "benchmarks" / "grading-env" / "stage2-heldout-suites" / f"{task_id}.json"
    if hidden.is_file():
        return hidden
    raise FileNotFoundError(f"No frozen held-out suite envelope for task {task_id}")


def replay_uncommitted_successful_invocations(cell_dir: Path) -> dict[str, object]:
    """Replay persisted invocation evidence through scoring without invoking an agent."""
    manifest = json.loads((cell_dir / "cell_manifest.json").read_text(encoding="utf-8"))
    if str(manifest.get("condition")) != "A-baseline":
        raise ValueError("Persisted-invocation replay is restricted to A-baseline")
    workspace = Path(str(manifest["workspace"]))
    outputs_dir = cell_dir / "outputs"
    attempts_dir = outputs_dir / "agent-invocations"
    meta_payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(attempts_dir.glob("attempt-*.meta.json"))
    ]
    if len(meta_payloads) != 2:
        raise ValueError("Persisted-invocation replay requires exactly two attempts")

    persisted_streams: dict[str, tuple[str, str]] = {}
    recovered_sessions: list[str] = []
    for payload in meta_payloads:
        stdout_text = Path(str(payload["stdout_path"])).read_text(encoding="utf-8")
        stderr_text = Path(str(payload["stderr_path"])).read_text(encoding="utf-8")
        match = SESSION_ID_RE.search(stdout_text) or SESSION_ID_RE.search(stderr_text)
        if int(payload["exit_code"]) != 0 or match is None:
            raise ValueError("Persisted-invocation replay requires two successful evidenced attempts")
        persisted_streams[str(payload["attempt_name"])] = (stdout_text, stderr_text)
        recovered_sessions.append(match.group("session_id"))

    prompt_path = outputs_dir / "pre-repair-treatment-prompt.txt"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if not prompt_text:
        raise ValueError("Persisted-invocation replay requires a non-empty treatment prompt")
    prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    snapshot = outputs_dir / "pre-repair-workspace"
    initial_hash = compute_solution_hash(snapshot)
    repair_hash = compute_solution_hash(workspace)
    if initial_hash != repair_hash:
        raise ValueError("Persisted-invocation replay is restricted to no-change repair attempts")

    class _ReplayInvoker:
        def run_cell(
            self, manifest: dict[str, object], outputs_dir: Path, workspace: Path
        ) -> AgentInvocationResult:
            replay_attempts_dir = outputs_dir / "agent-invocations"
            replay_attempts_dir.mkdir(parents=True, exist_ok=True)
            attempts: list[AgentAttempt] = []
            for payload, session_id in zip(meta_payloads, recovered_sessions, strict=True):
                attempt_name = str(payload["attempt_name"])
                stdout_text, stderr_text = persisted_streams[attempt_name]
                stdout_path = replay_attempts_dir / f"{attempt_name}.stdout"
                stderr_path = replay_attempts_dir / f"{attempt_name}.stderr"
                stdout_path.write_text(stdout_text, encoding="utf-8")
                stderr_path.write_text(stderr_text, encoding="utf-8")
                corrected = dict(payload)
                corrected["stdout_path"] = str(stdout_path)
                corrected["stderr_path"] = str(stderr_path)
                corrected["session_id"] = session_id
                (replay_attempts_dir / f"{attempt_name}.meta.json").write_text(
                    json.dumps(corrected, indent=2) + "\n", encoding="utf-8"
                )
                attempts.append(
                    AgentAttempt(
                        attempt_name=attempt_name,
                        prompt_kind=str(payload["prompt_kind"]),
                        command=[str(item) for item in payload["command"]],
                        exit_code=int(payload["exit_code"]),
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        working_directory=workspace,
                        session_id=session_id,
                        started_at=str(payload["started_at"]),
                        finished_at=str(payload["finished_at"]),
                        duration_seconds=float(payload["duration_seconds"]),
                    )
                )
            replay_prompt = outputs_dir / "pre-repair-treatment-prompt.txt"
            replay_prompt.write_text(prompt_text, encoding="utf-8")
            replay_prompt.chmod(0o444)
            treatment_delivery: dict[str, object] = {
                "treatment_prompt_path": str(replay_prompt),
                "treatment_prompt_sha256_pre": prompt_hash,
                "treatment_prompt_sha256_post": prompt_hash,
                "treatment_prompt_immutable": True,
                "repair_invocation_exit_code": attempts[1].exit_code,
                "repair_invocation_session_id_present": True,
                "repair_invocation_evidence_present": True,
                "repair_invocation_succeeded": True,
                "feedback_delivered": False,
                "recovered_from_persisted_invocation_evidence": True,
            }
            return AgentInvocationResult(
                attempts=attempts,
                attempt_solution_hashes={
                    "attempt_1_initial": initial_hash,
                    "attempt_2_repair_raw": repair_hash,
                    "attempt_2_repair": repair_hash,
                },
                repair_safety={
                    "safe": True,
                    "rollback_required": False,
                    "reasons": ["persisted_no_change_replay"],
                    "rollback_performed": False,
                    "rollback_validation": None,
                },
                treatment_delivery=treatment_delivery,
            )

    return execute_cell(cell_dir, _ReplayInvoker())


def run_heldout_evaluation(*, task_id: str, run_id: str, run_path: Path, outputs_dir: Path) -> dict[str, object]:
    suite_path = outputs_dir / "suite.json"
    write_rendered_json_template(
        heldout_suite_template_path(task_id),
        run_id=run_id,
        output_path=suite_path,
    )
    report_path = outputs_dir / "evaluation-report.json"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agentharness",
                "evaluate",
                "--run",
                str(run_path),
                "--suite",
                str(suite_path),
                "--json",
                "--report-path",
                str(report_path),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=_base_env(),
            timeout=HELDOUT_EVAL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "summary": {"passed": 0, "failed": 0, "invalid": 1},
            "results": [],
            "stdout": _decode_timeout_output(exc.stdout),
            "stderr": _decode_timeout_output(exc.stderr),
            "error": f"held-out evaluation timed out after {HELDOUT_EVAL_TIMEOUT_SECONDS} seconds",
        }
    if completed.stdout.strip().startswith("{"):
        return json.loads(completed.stdout)
    return {
        "ok": False,
        "summary": {"passed": 0, "failed": 0, "invalid": 0},
        "results": [],
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def heldout_endpoint_error(payload: dict[str, object]) -> str | None:
    if payload.get("ok") is not True:
        return "heldout_evaluation_not_ok"
    results = payload.get("results", [])
    if not isinstance(results, list):
        return "heldout_results_not_a_list"
    if len(results) != EXPECTED_HELDOUT_CASES:
        return f"heldout_case_count_mismatch:{len(results)}!={EXPECTED_HELDOUT_CASES}"
    statuses = [item.get("status") if isinstance(item, dict) else None for item in results]
    if any(status not in {"passed", "failed"} for status in statuses):
        return "heldout_case_status_invalid"
    return None


def score_from_evaluation(payload: dict[str, object]) -> float:
    if heldout_endpoint_error(payload) is not None:
        return 0.0
    results = payload.get("results", [])
    assert isinstance(results, list)
    passed = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "passed")
    return passed / EXPECTED_HELDOUT_CASES


def write_provenance(
    *,
    provenance_path: Path,
    manifest: dict[str, object],
    workspace: Path,
    invocation_result: AgentInvocationResult,
    pytest_result: dict[str, object],
) -> dict[str, object]:
    provenance = {
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "replicate_id": manifest["replicate_id"],
        "run_id": manifest["run_id"],
        "workspace": str(workspace),
        "solution_hash": compute_solution_hash(workspace),
        "attempt_solution_hashes": invocation_result.attempt_solution_hashes or {},
        "solution_hash_changed_between_attempt_and_repair": _solution_hash_changed_between_attempt_and_repair(invocation_result),
        "attempt_count": len(invocation_result.attempts),
        "attempts": invocation_result.to_dict(),
        "repair_safety": invocation_result.repair_safety,
        "treatment_delivery": invocation_result.treatment_delivery,
        "pytest": pytest_result,
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def _solution_hash_changed_between_attempt_and_repair(invocation_result: AgentInvocationResult) -> bool:
    hashes = invocation_result.attempt_solution_hashes or {}
    return hashes.get("attempt_1_initial") != hashes.get("attempt_2_repair")


def _clear_cell_runtime_artifacts(cell_dir: Path, workspace: Path, task_id: str, run_id: str) -> None:
    paths_to_remove = [
        cell_dir / "outputs",
        cell_dir / "run.json",
        cell_dir / "claims.json",
        cell_dir / "provenance.json",
        cell_dir / "metadata.json",
        workspace / ".agentharness" / "evaluation" / task_id,
        workspace / ".agentharness" / "traces" / "evaluation",
        workspace / ".agentharness" / "traces" / "verify-run",
        workspace / ".agentharness" / "evidence" / run_id / "reexecuted",
    ]
    for path in paths_to_remove:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)


def _require_scoring_treatment_delivery(
    manifest: dict[str, object], invocation_result: AgentInvocationResult
) -> None:
    delivery = invocation_result.treatment_delivery
    condition = str(manifest["condition"])
    repair_attempts = [attempt for attempt in invocation_result.attempts if attempt.prompt_kind == "repair"]
    if not isinstance(delivery, dict):
        raise ClassifiedCellFailure(
            "harness_invalid",
            "treatment_not_delivered: missing repair provenance",
            invocation_result=invocation_result,
        )
    ok = (
        len(repair_attempts) == 1
        and _successful_agent_attempt(repair_attempts[0])
        and delivery.get("repair_invocation_succeeded") is True
        and delivery.get("treatment_prompt_immutable") is True
    )
    if condition == "B-agentharness":
        ok = ok and delivery.get("feedback_delivered") is True and delivery.get("feedback_immutable") is True
    else:
        ok = ok and delivery.get("feedback_delivered") is False
    if not ok:
        raise ClassifiedCellFailure(
            "harness_invalid",
            "treatment_not_delivered: scoring boundary rejected repair provenance",
            invocation_result=invocation_result,
        )


def execute_cell(cell_dir: Path, invoker: AgentInvoker) -> dict[str, object]:
    manifest = json.loads((cell_dir / "cell_manifest.json").read_text(encoding="utf-8"))
    workspace = Path(str(manifest["workspace"]))
    _clear_cell_runtime_artifacts(cell_dir, workspace, str(manifest["task_id"]), str(manifest["run_id"]))
    outputs_dir = cell_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    invocation_result: AgentInvocationResult | None = None

    try:
        invocation_result = invoker.run_cell(manifest, outputs_dir, workspace)
        if any(not _has_invocation_evidence(attempt) for attempt in invocation_result.attempts):
            raise ClassifiedCellFailure(
                "harness_invalid",
                f"Missing invocation evidence for {cell_dir}",
                invocation_result=invocation_result,
            )
        if not rel_solution_files(workspace):
            execution_status, classification_reason = _classify_empty_workspace_failure(invocation_result)
            return _write_invalid_cell_artifacts(
                cell_dir=cell_dir,
                manifest=manifest,
                outputs_dir=outputs_dir,
                invocation_result=invocation_result,
                execution_status=execution_status,
                classification_reason=classification_reason,
            )

        _require_scoring_treatment_delivery(manifest, invocation_result)
        pytest_result = run_workspace_pytest(workspace, outputs_dir / "final-pytest.json")
    except ClassifiedCellFailure as exc:
        return _write_invalid_cell_artifacts(
            cell_dir=cell_dir,
            manifest=manifest,
            outputs_dir=outputs_dir,
            invocation_result=exc.invocation_result or invocation_result or AgentInvocationResult(attempts=[]),
            execution_status=exc.execution_status,
            classification_reason=exc.classification_reason,
        )

    run_path = cell_dir / "run.json"
    claims_path = cell_dir / "claims.json"
    write_run_json(
        run_path=run_path,
        manifest=manifest,
        workspace=workspace,
        pytest_command=_pytest_command_from_result(pytest_result),
        pytest_exit=int(str(pytest_result["exit_code"])),
        pytest_stdout_path=Path(str(pytest_result["stdout_path"])),
        pytest_stderr_path=Path(str(pytest_result["stderr_path"])),
    )
    render_claims_json(
        run_id=str(manifest["run_id"]),
        claims_template_path=Path(str(manifest["claims_template_path"])),
        claims_path=claims_path,
    )
    verify_payload = run_verify_run(run_path=run_path, claims_path=claims_path, report_path=outputs_dir / "verify-run-report.json")
    benchmark_payload = run_hidden_benchmark(
        run_path=run_path,
        task_id=str(manifest["task_id"]),
        output_path=outputs_dir / "benchmark-evaluate-task.json",
    )
    eval_payload = run_heldout_evaluation(
        task_id=str(manifest["task_id"]),
        run_id=str(manifest["run_id"]),
        run_path=run_path,
        outputs_dir=outputs_dir,
    )
    endpoint_error = heldout_endpoint_error(eval_payload)
    endpoint_score = score_from_evaluation(eval_payload)
    benchmark_execution_status = benchmark_payload.get("execution_status")
    benchmark_outcome_status = benchmark_payload.get("outcome_status")
    benchmark_classification_reason = benchmark_payload.get("classification_reason")
    if endpoint_error is not None:
        benchmark_execution_status = "harness_invalid"
        benchmark_outcome_status = "invalid"
        benchmark_classification_reason = endpoint_error
    provenance = write_provenance(
        provenance_path=cell_dir / "provenance.json",
        manifest=manifest,
        workspace=workspace,
        invocation_result=invocation_result or AgentInvocationResult(attempts=[]),
        pytest_result=pytest_result,
    )
    metadata = {
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "replicate_id": manifest["replicate_id"],
        "run_id": manifest["run_id"],
        "repair_passes_used": max(0, len((invocation_result or AgentInvocationResult(attempts=[])).attempts) - 1),
        "final_pytest_exit_code": pytest_result["exit_code"],
        "scorable_score": endpoint_score,
        "heldout_endpoint_denominator": EXPECTED_HELDOUT_CASES,
        "heldout_endpoint_valid": endpoint_error is None,
        "heldout_endpoint_error": endpoint_error,
        "verify_run_ok": verify_payload.get("ok"),
        "treatment_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "feedback_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("feedback_delivered")
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "benchmark_execution_status": benchmark_execution_status,
        "benchmark_outcome_status": benchmark_outcome_status,
        "benchmark_classification_reason": benchmark_classification_reason,
        "solution_hash": provenance["solution_hash"],
        "attempt_solution_hashes": provenance["attempt_solution_hashes"],
        "solution_hash_changed_between_attempt_and_repair": provenance["solution_hash_changed_between_attempt_and_repair"],
        "attempt_count": provenance["attempt_count"],
        "repair_safety": provenance["repair_safety"],
        "repair_rollback_performed": bool(
            isinstance(provenance["repair_safety"], dict)
            and provenance["repair_safety"].get("rollback_performed")
        ),
    }
    (cell_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    try:
        cell_label = str(cell_dir.relative_to(REPO_ROOT))
    except ValueError:
        cell_label = str(cell_dir)
    return {
        "cell": cell_label,
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "replicate_id": manifest["replicate_id"],
        "pytest_exit_code": pytest_result["exit_code"],
        "verify_run_ok": verify_payload.get("ok"),
        "treatment_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "feedback_delivered": bool(
            isinstance(provenance["treatment_delivery"], dict)
            and provenance["treatment_delivery"].get("feedback_delivered")
            and provenance["treatment_delivery"].get("repair_invocation_succeeded")
        ),
        "benchmark_execution_status": benchmark_execution_status,
        "benchmark_outcome_status": benchmark_outcome_status,
        "benchmark_classification_reason": benchmark_classification_reason,
        "heldout_endpoint_denominator": EXPECTED_HELDOUT_CASES,
        "heldout_endpoint_valid": endpoint_error is None,
        "heldout_endpoint_error": endpoint_error,
        "score": endpoint_score,
        "evaluation_summary": eval_payload.get("summary", {}),
        "solution_hash": provenance["solution_hash"],
        "attempt_solution_hashes": provenance["attempt_solution_hashes"],
        "solution_hash_changed_between_attempt_and_repair": provenance["solution_hash_changed_between_attempt_and_repair"],
        "attempt_count": provenance["attempt_count"],
        "repair_safety": provenance["repair_safety"],
        "repair_rollback_performed": bool(
            isinstance(provenance["repair_safety"], dict)
            and provenance["repair_safety"].get("rollback_performed")
        ),
    }


def assert_nonshared_solution_hashes(results: list[dict[str, object]]) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    for result in results:
        task_id = str(result["task_id"])
        grouped[task_id].append(str(result["solution_hash"]))
    offenders = [task_id for task_id, hashes in grouped.items() if len(hashes) > 1 and len(set(hashes)) == 1]
    if offenders:
        joined = ", ".join(sorted(offenders))
        raise RuntimeError(f"Identical solution_hash across all cells for task(s): {joined}")


def _prompt_relative_path(*, workspace: Path, target: Path) -> str:
    return os.path.relpath(target, start=workspace)


def _prompt_absolute_path(target: Path) -> str:
    return str(target.resolve())


def _build_initial_prompt(*, task_id: str, condition: str, workspace: Path, spec_path: Path, claims_template_path: Path) -> str:
    spec_ref = _prompt_relative_path(workspace=workspace, target=spec_path)
    claims_ref = _prompt_relative_path(workspace=workspace, target=claims_template_path)
    return f"""
You are executing one benchmark cell for task {task_id}.
The current working directory is the only project workspace for this cell.
Read this spec first: {spec_ref}
Do not write outside the current working directory.
Create a runnable solution from scratch in the current working directory.
Create a README.md with run instructions.
Create a pyproject.toml.
Create automated tests and make a best effort to get pytest -q green.
Do not inspect any held-out evaluation suite.
The claims template exists at {claims_ref}, but do not use held-out evaluator material.
""".strip()


def _build_baseline_repair_prompt(*, task_id: str, workspace: Path, spec_path: Path, pytest_stdout_path: str | Path, pytest_stderr_path: str | Path) -> str:
    spec_ref = _prompt_relative_path(workspace=workspace, target=spec_path)
    pytest_stdout_ref = _prompt_relative_path(workspace=workspace, target=Path(str(pytest_stdout_path)))
    pytest_stderr_ref = _prompt_relative_path(workspace=workspace, target=Path(str(pytest_stderr_path)))
    return f"""
This is the one bounded repair pass for task {task_id}.
The current working directory is the only project workspace.
Spec: {spec_ref}
Consult the raw local test outputs:
- pytest stdout: {pytest_stdout_ref}
- pytest stderr: {pytest_stderr_ref}
Safety constraints for this bounded repair:
- treat the canonical pytest result above as authoritative
- treat environment_mismatch feedback as inconclusive; do not modify the solution to satisfy a different execution environment
- if canonical pytest is already green, do not change dependency versions, replace the persistence layer, or rewrite working architecture
- never create local packages that shadow declared third-party dependencies
- prefer a no-op over a speculative infrastructure workaround
- all changes across retries are cumulative and will be checked as one repair diff
Make targeted fixes inside the current working directory, rerun local tests if helpful, and stop.
Do not read any held-out evaluation suite.
""".strip()


def _build_agentharness_repair_prompt(
    *,
    task_id: str,
    workspace: Path,
    spec_path: Path,
    pytest_stdout_path: str | Path,
    pytest_stderr_path: str | Path,
    verify_feedback_path: Path,
) -> str:
    spec_ref = _prompt_relative_path(workspace=workspace, target=spec_path)
    pytest_stdout_ref = _prompt_relative_path(workspace=workspace, target=Path(str(pytest_stdout_path)))
    pytest_stderr_ref = _prompt_relative_path(workspace=workspace, target=Path(str(pytest_stderr_path)))
    verify_feedback_ref = _prompt_relative_path(workspace=workspace, target=verify_feedback_path)
    return f"""
This is the one bounded repair pass for task {task_id}.
The current working directory is the only project workspace.
Spec: {spec_ref}
Consult the structured AgentHarness verify-run feedback: {verify_feedback_ref}
Consult the raw local test outputs:
- pytest stdout: {pytest_stdout_ref}
- pytest stderr: {pytest_stderr_ref}
Safety constraints for this bounded repair:
- treat the canonical pytest result above as authoritative
- treat environment_mismatch feedback as inconclusive; do not modify the solution to satisfy a different execution environment
- if canonical pytest is already green, do not change dependency versions, replace the persistence layer, or rewrite working architecture
- never create local packages that shadow declared third-party dependencies
- prefer a no-op over a speculative infrastructure workaround
- all changes across retries are cumulative and will be checked as one repair diff
Make targeted fixes inside the current working directory, rerun local tests if helpful, and stop.
Do not read any held-out evaluation suite.
""".strip()
