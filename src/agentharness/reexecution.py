from __future__ import annotations

import hashlib
import importlib.util
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


DEFAULT_ALLOWED_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("uv", "run", "pytest"),
    ("uv", "run", "python", "-m", "pytest"),
)
DEFAULT_ALLOWED_ENV_NAMES: tuple[str, ...] = (
    "PATH",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "PROGRAMDATA",
)


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str = "auto"
    timeout_seconds: int = 60
    working_dir_mode: str = "workspace-relative"
    allowed_command_prefixes: tuple[tuple[str, ...], ...] = DEFAULT_ALLOWED_COMMAND_PREFIXES
    allowed_env_names: tuple[str, ...] = DEFAULT_ALLOWED_ENV_NAMES

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "timeout_seconds": self.timeout_seconds,
            "working_dir_mode": self.working_dir_mode,
            "allowed_command_prefixes": [list(item) for item in self.allowed_command_prefixes],
            "allowed_env_names": list(self.allowed_env_names),
        }


@dataclass
class ReexecutionResult:
    attempted: bool
    allowed: bool
    completed: bool
    command: str
    command_tokens: list[str] = field(default_factory=list)
    reason: str | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    cwd: str | None = None
    timeout_seconds: int | None = None
    timed_out: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None

    def evidence_paths(self) -> list[str]:
        return [item for item in (self.stdout_path, self.stderr_path) if item]

    def evidence_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if self.stdout_path:
            records.append(
                {
                    "role": "stdout",
                    "path": self.stdout_path,
                    "sha256": self.stdout_sha256,
                }
            )
        if self.stderr_path:
            records.append(
                {
                    "role": "stderr",
                    "path": self.stderr_path,
                    "sha256": self.stderr_sha256,
                }
            )
        return records

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "allowed": self.allowed,
            "completed": self.completed,
            "command": self.command,
            "command_tokens": self.command_tokens,
            "reason": self.reason,
            "exit_code": self.exit_code,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


def default_execution_policy(*, mode: str = "auto", timeout_seconds: int = 60) -> ExecutionPolicy:
    return ExecutionPolicy(mode=mode, timeout_seconds=timeout_seconds)


def normalize_command_tokens(tokens: list[str]) -> list[str]:
    if not tokens:
        return []

    normalized = list(tokens)
    executable_name = Path(normalized[0]).name
    if executable_name.startswith("python"):
        normalized[0] = "python"
    else:
        normalized[0] = executable_name
    return normalized


def parse_command_tokens(command: str) -> tuple[list[str], str | None]:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return [], str(exc)

    if not tokens:
        return [], "command is empty"
    return tokens, None


def prepare_execution_tokens(tokens: list[str]) -> list[str]:
    normalized = normalize_command_tokens(tokens)
    if normalized[:3] == ["uv", "run", "pytest"] and importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", *tokens[3:]]
    if normalized[:5] == ["uv", "run", "python", "-m", "pytest"]:
        return [sys.executable, "-m", "pytest", *tokens[5:]]
    if normalized[:3] == ["python", "-m", "pytest"] and importlib.util.find_spec("pytest") is not None:
        declared_interpreter = Path(tokens[0])
        interpreter = str(declared_interpreter) if declared_interpreter.is_absolute() else sys.executable
        return [interpreter, "-m", "pytest", *tokens[3:]]
    if normalized and normalized[0] == "pytest" and importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", *tokens[1:]]
    return tokens


def is_command_allowed(command: str, policy: ExecutionPolicy) -> tuple[bool, list[str], str | None]:
    if policy.mode == "never":
        return False, [], "reexecution is disabled by policy"

    tokens, parse_error = parse_command_tokens(command)
    if parse_error:
        return False, [], f"command could not be parsed safely: {parse_error}"

    normalized = normalize_command_tokens(tokens)
    for allowed_prefix in policy.allowed_command_prefixes:
        if tuple(normalized[: len(allowed_prefix)]) == allowed_prefix:
            return True, tokens, None
    return False, tokens, "command is not allowed by reexecution policy"


def resolve_reexecution_cwd(
    workspace: Path,
    working_dir: str | None,
    policy: ExecutionPolicy,
) -> tuple[Path | None, str | None]:
    workspace_root = workspace.resolve()
    if policy.working_dir_mode == "workspace-root":
        if working_dir and working_dir.strip() not in {"", "."}:
            return None, "working_dir override is not allowed by reexecution policy"
        return workspace_root, None

    if policy.working_dir_mode == "workspace-relative":
        candidate = (working_dir or ".").strip() or "."
        working_path = Path(candidate)
        if working_path.is_absolute():
            return None, "working_dir must stay relative to the declared workspace"
        resolved = (workspace_root / working_path).resolve()
        try:
            resolved.relative_to(workspace_root)
        except ValueError:
            return None, "working_dir escapes the declared workspace"
        if not resolved.is_dir():
            return None, "working_dir does not exist inside the declared workspace"
        return resolved, None

    return None, f"unsupported working_dir_mode: {policy.working_dir_mode}"


def sanitized_environment(policy: ExecutionPolicy) -> dict[str, str]:
    env: dict[str, str] = {}
    for name in policy.allowed_env_names:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    path_separator = os.pathsep
    path_value = env.get("PATH", os.defpath)
    virtual_env = env.get("VIRTUAL_ENV")
    if virtual_env:
        scripts_dir = "Scripts" if os.name == "nt" else "bin"
        path_cls = PureWindowsPath if os.name == "nt" else PurePosixPath
        venv_bin = str(path_cls(virtual_env) / scripts_dir)
        if venv_bin not in path_value.split(path_separator):
            path_value = f"{venv_bin}{path_separator}{path_value}"
    env["PATH"] = path_value
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _controlled_command_environment(
    workspace: Path,
    policy: ExecutionPolicy,
    overrides: dict[str, str] | None,
) -> tuple[dict[str, str] | None, str | None]:
    env = sanitized_environment(policy)
    if not overrides:
        return env, None
    unsupported = sorted(set(overrides) - {"PYTHONPATH", "AGENTHARNESS_GRADING_ENV_DIR"})
    if unsupported:
        return None, f"command environment overrides are not allowed for: {', '.join(unsupported)}"
    workspace_root = workspace.resolve()
    resolved_entries: list[str] = []
    for raw_entry in overrides.get("PYTHONPATH", "").split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        candidate = entry.resolve() if entry.is_absolute() else (workspace_root / entry).resolve()
        try:
            candidate.relative_to(workspace_root)
        except ValueError:
            return None, "command PYTHONPATH must stay inside the declared workspace"
        resolved_entries.append(str(candidate))
    env["PYTHONPATH"] = os.pathsep.join(resolved_entries)
    grading_env_override = overrides.get("AGENTHARNESS_GRADING_ENV_DIR")
    if grading_env_override is not None:
        expected_grading_env = (Path(__file__).resolve().parents[2] / "benchmarks" / "grading-env").resolve()
        candidate_grading_env = Path(grading_env_override).resolve()
        if candidate_grading_env != expected_grading_env:
            return None, "command AGENTHARNESS_GRADING_ENV_DIR must match the repository grading environment"
        env["AGENTHARNESS_GRADING_ENV_DIR"] = str(expected_grading_env)
    return env, None


def _explicit_interpreter_error(workspace: Path, tokens: list[str]) -> str | None:
    if not tokens or not Path(tokens[0]).is_absolute():
        return None
    interpreter = Path(tokens[0]).absolute()
    workspace_root = workspace.resolve()
    try:
        relative = interpreter.relative_to(workspace_root)
    except ValueError:
        return "absolute interpreter must be located inside the declared workspace"
    allowed_venv_names = {".stageb-test-venv", ".venv", "venv"}
    if not relative.parts or relative.parts[0] not in allowed_venv_names:
        return "absolute interpreter must belong to an approved workspace virtual environment"
    if not interpreter.is_file():
        return "declared workspace interpreter does not exist"
    return None


def reexecute_command(
    workspace: Path,
    run_id: str,
    command: str,
    *,
    working_dir: str | None,
    policy: ExecutionPolicy,
    environment: dict[str, str] | None = None,
) -> ReexecutionResult:
    allowed, tokens, denial_reason = is_command_allowed(command, policy)
    interpreter_error = _explicit_interpreter_error(workspace, tokens) if allowed else None
    controlled_env, environment_error = (
        _controlled_command_environment(workspace, policy, environment) if allowed else (None, None)
    )
    if not allowed or interpreter_error or environment_error:
        return ReexecutionResult(
            attempted=False,
            allowed=False,
            completed=False,
            command=command,
            command_tokens=tokens,
            reason=denial_reason or interpreter_error or environment_error,
            timeout_seconds=policy.timeout_seconds,
        )

    cwd, cwd_error = resolve_reexecution_cwd(workspace, working_dir, policy)
    if cwd_error:
        return ReexecutionResult(
            attempted=False,
            allowed=False,
            completed=False,
            command=command,
            command_tokens=tokens,
            reason=cwd_error,
            timeout_seconds=policy.timeout_seconds,
        )
    if cwd is None:
        return ReexecutionResult(
            attempted=False,
            allowed=False,
            completed=False,
            command=command,
            command_tokens=tokens,
            reason="could not resolve a controlled working directory",
            timeout_seconds=policy.timeout_seconds,
        )

    evidence_dir = workspace.resolve() / ".agentharness" / "evidence" / run_id / "reexecuted"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    command_digest = hashlib.sha256(command.encode("utf-8")).hexdigest()[:12]
    stdout_path = evidence_dir / f"command-{command_digest}.stdout"
    stderr_path = evidence_dir / f"command-{command_digest}.stderr"

    started_epoch = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_epoch))
    execution_tokens = prepare_execution_tokens(tokens)
    try:
        completed = subprocess.run(
            execution_tokens,
            cwd=str(cwd),
            env=controlled_env or sanitized_environment(policy),
            capture_output=True,
            text=True,
            timeout=policy.timeout_seconds,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        finished_epoch = time.time()
        return ReexecutionResult(
            attempted=True,
            allowed=True,
            completed=False,
            command=command,
            command_tokens=tokens,
            reason=f"executable not available for reexecution: {exc}",
            cwd=str(cwd),
            timeout_seconds=policy.timeout_seconds,
            started_at=started_at,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished_epoch)),
            duration_ms=int((finished_epoch - started_epoch) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        finished_epoch = time.time()
        stdout_text = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr_text = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")
        return ReexecutionResult(
            attempted=True,
            allowed=True,
            completed=False,
            command=command,
            command_tokens=tokens,
            reason="reexecution timed out before a verdict was established",
            cwd=str(cwd),
            timeout_seconds=policy.timeout_seconds,
            timed_out=True,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_sha256=hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
            started_at=started_at,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished_epoch)),
            duration_ms=int((finished_epoch - started_epoch) * 1000),
        )

    finished_epoch = time.time()
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return ReexecutionResult(
        attempted=True,
        allowed=True,
        completed=True,
        command=command,
        command_tokens=tokens,
        exit_code=completed.returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_sha256=hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
        cwd=str(cwd),
        timeout_seconds=policy.timeout_seconds,
        started_at=started_at,
        finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished_epoch)),
        duration_ms=int((finished_epoch - started_epoch) * 1000),
    )
