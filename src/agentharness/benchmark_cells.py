from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .benchmarking import render_json_template, write_rendered_json_template

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
    ) -> None:
        self._hermes_command = hermes_command or "hermes"
        self._toolsets = toolsets
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

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

        if condition == "A-baseline":
            repair_prompt = _build_baseline_repair_prompt(
                task_id=task_id,
                workspace=workspace,
                spec_path=spec_path,
                pytest_stdout_path=str(pytest_result["stdout_path"]),
                pytest_stderr_path=str(pytest_result["stderr_path"]),
            )
        else:
            verify_feedback_path = outputs_dir / "pre-repair-verify-run-report.json"
            provisional_run_path = outputs_dir / "pre-repair-run.json"
            provisional_claims_path = outputs_dir / "pre-repair-claims.json"
            write_run_json(
                run_path=provisional_run_path,
                manifest=manifest,
                workspace=workspace,
                pytest_exit=int(str(pytest_result["exit_code"])),
                pytest_stdout_path=Path(str(pytest_result["stdout_path"])),
                pytest_stderr_path=Path(str(pytest_result["stderr_path"])),
            )
            render_claims_json(run_id=run_id, claims_template_path=claims_template_path, claims_path=provisional_claims_path)
            run_verify_run(
                run_path=provisional_run_path,
                claims_path=provisional_claims_path,
                report_path=verify_feedback_path,
            )
            repair_prompt = _build_agentharness_repair_prompt(
                task_id=task_id,
                workspace=workspace,
                spec_path=spec_path,
                pytest_stdout_path=str(pytest_result["stdout_path"]),
                pytest_stderr_path=str(pytest_result["stderr_path"]),
                verify_feedback_path=verify_feedback_path,
            )

        attempts.append(
            self._invoke(
                prompt=repair_prompt,
                attempt_name="attempt-2-repair",
                prompt_kind="repair",
                outputs_dir=attempts_dir,
                workspace=workspace,
            )
        )
        attempt_solution_hashes["attempt_2_repair"] = (
            compute_solution_hash(workspace) if rel_solution_files(workspace) else None
        )
        return AgentInvocationResult(attempts=attempts, attempt_solution_hashes=attempt_solution_hashes)

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
            "-q",
            prompt,
        ]
        last_attempt: AgentAttempt | None = None
        for retry_index in range(1, self._max_retries + 1):
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
            session_match = SESSION_ID_RE.search(stdout_text)
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
        BENCHMARKS_DIR / task_id / "HELDOUT_EVALUATION_SUITE.template.json",
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
        "benchmark_execution_status": execution_status,
        "benchmark_outcome_status": outcome_status,
        "benchmark_classification_reason": classification_reason,
        "solution_hash": provenance["solution_hash"],
        "attempt_solution_hashes": provenance["attempt_solution_hashes"],
        "solution_hash_changed_between_attempt_and_repair": provenance["solution_hash_changed_between_attempt_and_repair"],
        "attempt_count": provenance["attempt_count"],
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
        "benchmark_execution_status": execution_status,
        "benchmark_outcome_status": outcome_status,
        "benchmark_classification_reason": classification_reason,
        "score": 0.0,
        "evaluation_summary": eval_payload["summary"],
        "solution_hash": provenance["solution_hash"],
        "attempt_count": provenance["attempt_count"],
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
            env={**_base_env(), "PYTHONPATH": str(workspace)},
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


def write_run_json(
    *,
    run_path: Path,
    manifest: dict[str, object],
    workspace: Path,
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
                    "cmd": "pytest -q",
                    "exit_code": pytest_exit,
                    "stdout_path": str(pytest_stdout_path),
                    "stderr_path": str(pytest_stderr_path),
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
        return {
            "ok": False,
            "error": f"verify-run timed out after {VERIFY_RUN_TIMEOUT_SECONDS} seconds",
            "stdout": _decode_timeout_output(exc.stdout),
            "stderr": _decode_timeout_output(exc.stderr),
        }
    if completed.stdout.strip().startswith("{"):
        return json.loads(completed.stdout)
    return {
        "ok": False,
        "error": "verify-run did not emit JSON",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


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


def run_heldout_evaluation(*, task_id: str, run_id: str, run_path: Path, outputs_dir: Path) -> dict[str, object]:
    suite_path = outputs_dir / "suite.json"
    write_rendered_json_template(
        BENCHMARKS_DIR / task_id / "HELDOUT_EVALUATION_SUITE.template.json",
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


def score_from_evaluation(payload: dict[str, object]) -> float:
    results = payload.get("results", [])
    if not isinstance(results, list) or not results:
        return 0.0
    passed = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "passed")
    return passed / len(results)


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
        "scorable_score": score_from_evaluation(eval_payload),
        "verify_run_ok": verify_payload.get("ok"),
        "benchmark_execution_status": benchmark_payload.get("execution_status"),
        "benchmark_outcome_status": benchmark_payload.get("outcome_status"),
        "benchmark_classification_reason": benchmark_payload.get("classification_reason"),
        "solution_hash": provenance["solution_hash"],
        "attempt_solution_hashes": provenance["attempt_solution_hashes"],
        "solution_hash_changed_between_attempt_and_repair": provenance["solution_hash_changed_between_attempt_and_repair"],
        "attempt_count": provenance["attempt_count"],
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
        "benchmark_execution_status": benchmark_payload.get("execution_status"),
        "benchmark_outcome_status": benchmark_payload.get("outcome_status"),
        "benchmark_classification_reason": benchmark_payload.get("classification_reason"),
        "score": score_from_evaluation(eval_payload),
        "evaluation_summary": eval_payload.get("summary", {}),
        "solution_hash": provenance["solution_hash"],
        "attempt_solution_hashes": provenance["attempt_solution_hashes"],
        "solution_hash_changed_between_attempt_and_repair": provenance["solution_hash_changed_between_attempt_and_repair"],
        "attempt_count": provenance["attempt_count"],
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
    workspace_ref = _prompt_absolute_path(workspace)
    spec_ref = _prompt_absolute_path(spec_path)
    claims_ref = _prompt_absolute_path(claims_template_path)
    common = f"""
You are executing one benchmark cell for task {task_id}.
The only project workspace for this cell is: {workspace_ref}
Use that exact absolute workspace path for every file read/write/create/modify operation.
Do not rely on your default current working directory.
Read this spec first: {spec_ref}
Do not write anywhere outside {workspace_ref}.
Create a runnable solution from scratch inside {workspace_ref}.
Create a README.md with run instructions.
Create a pyproject.toml.
Create automated tests and make a best effort to get pytest -q green.
Do not inspect any held-out evaluation suite.
The claims template exists at {claims_ref}, but do not use held-out evaluator material.
""".strip()
    if condition == "A-baseline":
        extra = """
Condition A, baseline:
- do not use AgentHarness project files, framework metadata, or verify-run feedback
- implement directly from the benchmark spec with reasonable engineering judgment
- keep the solution concise and practical
""".strip()
    else:
        extra = """
Condition B, AgentHarness package:
- follow a verification oriented implementation style
- keep README, tests, and dependency manifest explicit and reviewable
- you will later receive structured verify-run feedback for one bounded repair pass
""".strip()
    return common + "\n\n" + extra


def _build_baseline_repair_prompt(*, task_id: str, workspace: Path, spec_path: Path, pytest_stdout_path: str | Path, pytest_stderr_path: str | Path) -> str:
    workspace_ref = _prompt_absolute_path(workspace)
    spec_ref = _prompt_absolute_path(spec_path)
    pytest_stdout_ref = _prompt_absolute_path(Path(str(pytest_stdout_path)))
    pytest_stderr_ref = _prompt_absolute_path(Path(str(pytest_stderr_path)))
    return f"""
This is the one bounded repair pass for baseline condition A on task {task_id}.
Workspace absolute path: {workspace_ref}
Use that exact absolute workspace path for every file operation and do not rely on your default current working directory.
Spec: {spec_ref}
Review the implementation against the task spec, not against any framework guidance.
Use these raw local test outputs only as ordinary development feedback:
- pytest stdout: {pytest_stdout_ref}
- pytest stderr: {pytest_stderr_ref}
Make targeted fixes inside the workspace, rerun local tests if helpful, and stop.
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
    workspace_ref = _prompt_absolute_path(workspace)
    spec_ref = _prompt_absolute_path(spec_path)
    pytest_stdout_ref = _prompt_absolute_path(Path(str(pytest_stdout_path)))
    pytest_stderr_ref = _prompt_absolute_path(Path(str(pytest_stderr_path)))
    verify_feedback_ref = _prompt_absolute_path(verify_feedback_path)
    return f"""
This is the one bounded repair pass for AgentHarness condition B on task {task_id}.
Workspace absolute path: {workspace_ref}
Use that exact absolute workspace path for every file operation and do not rely on your default current working directory.
Spec: {spec_ref}
Use the structured verify-run feedback here: {verify_feedback_ref}
You may also consult the raw local test outputs:
- pytest stdout: {pytest_stdout_ref}
- pytest stderr: {pytest_stderr_ref}
Make targeted fixes inside the workspace, rerun local tests if helpful, and stop.
Do not read any held-out evaluation suite.
""".strip()
