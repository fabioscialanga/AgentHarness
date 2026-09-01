from __future__ import annotations

import glob
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

TERMINAL_STATUSES = {
    "preflight_failed",
    "succeeded",
    "failed",
    "verification_failed",
    "timed_out",
    "stopped",
}
ACTIVE_STATUSES = {"created", "running", "retrying"}
RESUMABLE_STATUSES = TERMINAL_STATUSES - {"succeeded"}


class SupervisorError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _command(value: object, name: str, *, required: bool = False) -> tuple[str, ...] | None:
    if value is None and not required:
        return None
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise SupervisorError(f"{name} must be a non-empty list of strings")
    return tuple(value)


def _relative_pattern(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SupervisorError("artifacts must contain non-empty relative paths or glob patterns")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SupervisorError(f"artifact path escapes workspace: {value}")
    return value


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or not all(ch.isalnum() or ch in "-_" for ch in value):
        raise SupervisorError(f"{name} must be path-safe and contain only letters, digits, '-' or '_'")
    return value


@dataclass(frozen=True)
class JobConfig:
    path: Path
    file_sha256: str
    job_id: str
    workspace: Path
    command: tuple[str, ...]
    preflight: tuple[str, ...] | None
    success_check: tuple[str, ...] | None
    timeout_seconds: int
    max_attempts: int
    backoff_seconds: float
    retry_on_exit_codes: tuple[int, ...]
    artifacts: tuple[str, ...]
    state_dir: Path


def load_job_config(path: str | Path) -> JobConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise SupervisorError(f"config does not exist: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SupervisorError("config must be a YAML object with schema_version: 1")
    job_id = _safe_id(payload.get("job_id"), "job_id")
    workspace_value = payload.get("workspace")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise SupervisorError("workspace is required")
    workspace = Path(workspace_value).expanduser()
    if not workspace.is_absolute():
        workspace = (config_path.parent / workspace).resolve()
    else:
        workspace = workspace.resolve()
    if not workspace.is_dir():
        raise SupervisorError(f"workspace does not exist: {workspace}")
    retry = payload.get("retry", {})
    if not isinstance(retry, dict):
        raise SupervisorError("retry must be an object")
    max_attempts = int(retry.get("max_attempts", 1))
    backoff_seconds = float(retry.get("backoff_seconds", 0))
    retry_codes = retry.get("retry_on_exit_codes", [1])
    if max_attempts < 1 or backoff_seconds < 0:
        raise SupervisorError("retry max_attempts must be >=1 and backoff_seconds must be >=0")
    if not isinstance(retry_codes, list) or not all(isinstance(item, int) for item in retry_codes):
        raise SupervisorError("retry_on_exit_codes must be a list of integers")
    timeout_seconds = int(payload.get("timeout_seconds", 3600))
    if timeout_seconds < 1:
        raise SupervisorError("timeout_seconds must be >=1")
    artifacts_value = payload.get("artifacts", [])
    if not isinstance(artifacts_value, list):
        raise SupervisorError("artifacts must be a list")
    state_value = payload.get("state_dir")
    if state_value is None:
        state_dir = workspace / ".agentharness" / "supervisor" / job_id
    elif not isinstance(state_value, str) or not state_value:
        raise SupervisorError("state_dir must be a path string")
    else:
        state_dir = Path(state_value).expanduser()
        if not state_dir.is_absolute():
            state_dir = (config_path.parent / state_dir).resolve()
        else:
            state_dir = state_dir.resolve()
    return JobConfig(
        path=config_path,
        file_sha256=_sha256(config_path),
        job_id=job_id,
        workspace=workspace,
        command=_command(payload.get("command"), "command", required=True) or (),
        preflight=_command(payload.get("preflight"), "preflight"),
        success_check=_command(payload.get("success_check"), "success_check"),
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        retry_on_exit_codes=tuple(retry_codes),
        artifacts=tuple(_relative_pattern(item) for item in artifacts_value),
        state_dir=state_dir,
    )


def _current_path(config: JobConfig) -> Path:
    return config.state_dir / "current.json"


def _run_dir(config: JobConfig, run_id: str) -> Path:
    return config.state_dir / "runs" / run_id


def _state_path(config: JobConfig, run_id: str) -> Path:
    return _run_dir(config, run_id) / "state.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupervisorError(f"cannot read supervisor state: {path}") from exc
    if not isinstance(value, dict):
        raise SupervisorError(f"invalid supervisor state: {path}")
    return value


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        stat = Path(f"/proc/{pid}/stat")
        if stat.is_file() and stat.read_text(encoding="utf-8").split()[2] == "Z":
            return False
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError, IndexError):
        return False
    return True


def get_job_status(config_path: str | Path) -> dict[str, Any]:
    config = load_job_config(config_path)
    current = _current_path(config)
    if not current.is_file():
        return {"job_id": config.job_id, "status": "not_started", "config_path": str(config.path)}
    pointer = _read_json(current)
    run_id = pointer.get("run_id")
    if not isinstance(run_id, str):
        raise SupervisorError("current run pointer is invalid")
    state = _read_json(_state_path(config, run_id))
    state["worker_alive"] = _pid_alive(state.get("supervisor_pid"))
    return state


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _worker_environment() -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(Path(item).resolve()) for item in sys.path if item]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.extend(item for item in existing.split(os.pathsep) if item)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    return env


def _spawn_worker(config: JobConfig, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    log_path = _run_dir(config, run_id) / "supervisor.log"
    read_fd, write_fd = os.pipe()
    try:
        with log_path.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agentharness.supervisor_worker",
                    "--config",
                    str(config.path),
                    "--run-id",
                    run_id,
                    "--start-fd",
                    str(read_fd),
                ],
                cwd=config.workspace,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=_worker_environment(),
                pass_fds=(read_fd,),
                start_new_session=True,
            )
        os.close(read_fd)
        read_fd = -1
        state["supervisor_pid"] = process.pid
        state["supervisor_log"] = str(log_path)
        state["updated_at"] = _utc_now()
        _atomic_json(_state_path(config, run_id), state)
        os.write(write_fd, b"1")
        return state
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        os.close(write_fd)


def start_job(config_path: str | Path, *, detach: bool = True, run_id: str | None = None) -> dict[str, Any]:
    config = load_job_config(config_path)
    existing = get_job_status(config.path)
    if _pid_alive(existing.get("supervisor_pid")):
        raise SupervisorError(f"job is already active: {config.job_id}")
    selected = _safe_id(run_id, "run_id") if run_id is not None else _new_run_id()
    run_dir = _run_dir(config, selected)
    if run_dir.exists():
        raise SupervisorError(f"run already exists: {selected}")
    run_dir.mkdir(parents=True)
    state: dict[str, Any] = {
        "schema_version": 1,
        "job_id": config.job_id,
        "run_id": selected,
        "status": "created",
        "config_path": str(config.path),
        "config_sha256": config.file_sha256,
        "workspace": str(config.workspace),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "supervisor_pid": None,
        "child_pid": None,
        "attempts": [],
        "preflight": None,
        "preflight_history": [],
        "verification": None,
        "artifacts": [],
    }
    _atomic_json(_state_path(config, selected), state)
    _atomic_json(_current_path(config), {"job_id": config.job_id, "run_id": selected})
    if not detach:
        return run_job_worker(config.path, selected)
    return _spawn_worker(config, selected, state)


def _execute(
    command: tuple[str, ...],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    state: dict[str, Any],
    state_path: Path,
) -> tuple[int | None, bool, int]:
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
        state["child_pid"] = process.pid
        state["updated_at"] = _utc_now()
        _atomic_json(state_path, state)
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            exit_code = None
    state["child_pid"] = None
    return exit_code, timed_out, int((time.monotonic() - started) * 1000)


def _record_command(
    config: JobConfig,
    state: dict[str, Any],
    state_path: Path,
    command: tuple[str, ...],
    name: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    run_dir = state_path.parent
    stdout_path = run_dir / f"{name}.stdout"
    stderr_path = run_dir / f"{name}.stderr"
    started_at = _utc_now()
    exit_code, timed_out, duration_ms = _execute(
        command,
        cwd=config.workspace,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
        state=state,
        state_path=state_path,
    )
    return {
        "command": list(command),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_path": str(stdout_path),
        "stdout_sha256": _sha256(stdout_path),
        "stderr_path": str(stderr_path),
        "stderr_sha256": _sha256(stderr_path),
    }


def _collect_artifacts(config: JobConfig) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for pattern in config.artifacts:
        matches = sorted(Path(item).resolve() for item in glob.glob(str(config.workspace / pattern), recursive=True))
        files: list[Path] = []
        for path in matches:
            try:
                path.relative_to(config.workspace)
            except ValueError:
                continue
            if path.is_file():
                files.append(path)
        if not files:
            missing.append(pattern)
            continue
        for path in files:
            records.append({
                "path": str(path),
                "relative_path": path.relative_to(config.workspace).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
    unique = {item["relative_path"]: item for item in records}
    return [unique[key] for key in sorted(unique)], missing


def run_job_worker(config_path: str | Path, run_id: str) -> dict[str, Any]:
    config = load_job_config(config_path)
    run_id = _safe_id(run_id, "run_id")
    state_path = _state_path(config, run_id)
    if not state_path.is_file():
        raise SupervisorError(f"run does not exist: {run_id}")
    state = _read_json(state_path)
    if state.get("config_sha256") != config.file_sha256:
        raise SupervisorError("config changed after run creation")
    lock_path = config.state_dir / "active.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            lock_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            lock_pid = 0
        if _pid_alive(lock_pid):
            raise SupervisorError(f"job is already active: {config.job_id}")
        lock_path.unlink(missing_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)
    stopped = False

    def handle_stop(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True
        child = state.get("child_pid")
        if isinstance(child, int):
            try:
                os.killpg(child, signal.SIGTERM)
            except ProcessLookupError:
                pass

    old_term = signal.signal(signal.SIGTERM, handle_stop)
    old_int = signal.signal(signal.SIGINT, handle_stop)
    try:
        state["supervisor_pid"] = os.getpid()
        state["started_at"] = state.get("started_at") or _utc_now()
        state["updated_at"] = _utc_now()
        _atomic_json(state_path, state)
        if config.preflight:
            history = state.get("preflight_history")
            if not isinstance(history, list):
                history = []
            preflight = _record_command(
                config,
                state,
                state_path,
                config.preflight,
                f"preflight-{len(history) + 1}",
                min(config.timeout_seconds, 300),
            )
            history.append(preflight)
            state["preflight_history"] = history
            state["preflight"] = preflight
            if stopped or preflight["timed_out"] or preflight["exit_code"] != 0:
                state["status"] = "stopped" if stopped else "preflight_failed"
                state["finished_at"] = _utc_now()
                state["updated_at"] = _utc_now()
                state["child_pid"] = None
                state["supervisor_pid"] = None
                _atomic_json(state_path, state)
                return state
        attempts = state.get("attempts")
        if not isinstance(attempts, list):
            attempts = []
            state["attempts"] = attempts
        start_number = len(attempts) + 1
        for attempt_number in range(start_number, config.max_attempts + 1):
            if stopped:
                break
            state["status"] = "running"
            state["updated_at"] = _utc_now()
            _atomic_json(state_path, state)
            attempt = _record_command(config, state, state_path, config.command, f"attempt-{attempt_number}", config.timeout_seconds)
            attempt["attempt"] = attempt_number
            attempts.append(attempt)
            state["attempts"] = attempts
            if attempt["timed_out"]:
                state["status"] = "timed_out"
                break
            if attempt["exit_code"] == 0:
                state["status"] = "succeeded"
                break
            if attempt_number < config.max_attempts and attempt["exit_code"] in config.retry_on_exit_codes:
                state["status"] = "retrying"
                state["updated_at"] = _utc_now()
                _atomic_json(state_path, state)
                if config.backoff_seconds:
                    deadline = time.monotonic() + config.backoff_seconds
                    while not stopped and time.monotonic() < deadline:
                        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
                continue
            state["status"] = "failed"
            break
        if stopped:
            state["status"] = "stopped"
        if state["status"] == "succeeded" and config.success_check:
            verification = _record_command(config, state, state_path, config.success_check, "success-check", min(config.timeout_seconds, 300))
            state["verification"] = verification
            if stopped:
                state["status"] = "stopped"
            elif verification["timed_out"] or verification["exit_code"] != 0:
                state["status"] = "verification_failed"
        if state["status"] == "succeeded":
            artifacts, missing = _collect_artifacts(config)
            state["artifacts"] = artifacts
            state["missing_artifacts"] = missing
            if missing:
                state["status"] = "verification_failed"
        state["finished_at"] = _utc_now()
        state["updated_at"] = _utc_now()
        state["child_pid"] = None
        state["supervisor_pid"] = None
        _atomic_json(state_path, state)
        return state
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
        lock_path.unlink(missing_ok=True)


def stop_job(config_path: str | Path) -> dict[str, Any]:
    config = load_job_config(config_path)
    state = get_job_status(config.path)
    if state.get("status") == "not_started":
        raise SupervisorError("job has not started")
    if state.get("status") not in ACTIVE_STATUSES:
        return state
    pid = state.get("supervisor_pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        if state.get("status") in ACTIVE_STATUSES:
            state["status"] = "stopped"
            state["finished_at"] = _utc_now()
            state["updated_at"] = _utc_now()
            _atomic_json(_state_path(config, str(state["run_id"])), state)
        return state
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 2.0
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return get_job_status(config.path)


def resume_job(config_path: str | Path, *, detach: bool = True) -> dict[str, Any]:
    config = load_job_config(config_path)
    state = get_job_status(config.path)
    status = state.get("status")
    if status not in RESUMABLE_STATUSES:
        raise SupervisorError(f"job is not resumable from status: {status}")
    attempts = state.get("attempts", [])
    if isinstance(attempts, list) and len(attempts) >= config.max_attempts and status != "preflight_failed":
        raise SupervisorError("retry budget exhausted; start a new run instead")
    run_id = str(state["run_id"])
    state["status"] = "created"
    state["finished_at"] = None
    state["updated_at"] = _utc_now()
    _atomic_json(_state_path(config, run_id), state)
    if not detach:
        return run_job_worker(config.path, run_id)
    return _spawn_worker(config, run_id, state)
