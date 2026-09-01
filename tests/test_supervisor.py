from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest
import yaml

from agentharness.supervisor import (
    SupervisorError,
    get_job_status,
    load_job_config,
    resume_job,
    start_job,
    stop_job,
)


def write_config(workspace: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "job_id": "fixture",
        "workspace": str(workspace),
        "command": [sys.executable, "-c", "from pathlib import Path; Path('result.txt').write_text('ok')"],
        "timeout_seconds": 5,
        "retry": {"max_attempts": 1, "backoff_seconds": 0, "retry_on_exit_codes": [1]},
        "artifacts": ["result.txt"],
    }
    payload.update(overrides)
    path = workspace / "job.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_config_rejects_shell_string_and_artifact_escape(tmp_path: Path) -> None:
    path = write_config(tmp_path, command="echo unsafe")
    with pytest.raises(SupervisorError, match="list of strings"):
        load_job_config(path)
    path = write_config(tmp_path, artifacts=["../outside"])
    with pytest.raises(SupervisorError, match="escapes workspace"):
        load_job_config(path)


def test_foreground_success_hashes_artifact(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    state = start_job(path, detach=False, run_id="success")
    assert state["status"] == "succeeded"
    assert len(state["attempts"]) == 1
    assert state["artifacts"] == [{
        "path": str(tmp_path / "result.txt"),
        "relative_path": "result.txt",
        "size_bytes": 2,
        "sha256": hashlib.sha256(b"ok").hexdigest(),
    }]


def test_preflight_failure_does_not_run_main(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        preflight=[sys.executable, "-c", "raise SystemExit(7)"],
    )
    state = start_job(path, detach=False, run_id="preflight")
    assert state["status"] == "preflight_failed"
    assert state["attempts"] == []
    assert not (tmp_path / "result.txt").exists()


def test_retry_then_success(tmp_path: Path) -> None:
    code = (
        "from pathlib import Path; p=Path('counter'); n=int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n+1)); Path('result.txt').write_text('ok') if n else None; raise SystemExit(0 if n else 1)"
    )
    path = write_config(
        tmp_path,
        command=[sys.executable, "-c", code],
        retry={"max_attempts": 2, "backoff_seconds": 0, "retry_on_exit_codes": [1]},
    )
    state = start_job(path, detach=False, run_id="retry")
    assert state["status"] == "succeeded"
    assert [item["exit_code"] for item in state["attempts"]] == [1, 0]


def test_timeout_is_terminal_and_kills_child(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        command=[sys.executable, "-c", "import time; time.sleep(5)"],
        timeout_seconds=1,
        artifacts=[],
    )
    state = start_job(path, detach=False, run_id="timeout")
    assert state["status"] == "timed_out"
    assert state["attempts"][0]["timed_out"] is True
    assert state["child_pid"] is None


def test_missing_artifact_fails_verification(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        artifacts=["missing.json"],
    )
    state = start_job(path, detach=False, run_id="missing")
    assert state["status"] == "verification_failed"
    assert state["missing_artifacts"] == ["missing.json"]


def test_success_check_failure_is_distinct(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        success_check=[sys.executable, "-c", "raise SystemExit(3)"],
    )
    state = start_job(path, detach=False, run_id="verify")
    assert state["status"] == "verification_failed"
    assert state["verification"]["exit_code"] == 3


def test_resume_after_preflight_failure_same_run(tmp_path: Path) -> None:
    marker = tmp_path / "ready"
    path = write_config(
        tmp_path,
        preflight=[sys.executable, "-c", "from pathlib import Path; raise SystemExit(0 if Path('ready').exists() else 4)"],
    )
    first = start_job(path, detach=False, run_id="resume")
    assert first["status"] == "preflight_failed"
    assert len(first["preflight_history"]) == 1
    assert first["preflight_history"][0]["exit_code"] == 4
    marker.write_text("yes", encoding="utf-8")
    resumed = resume_job(path, detach=False)
    assert resumed["run_id"] == "resume"
    assert resumed["status"] == "succeeded"
    assert len(resumed["preflight_history"]) == 2
    assert [item["exit_code"] for item in resumed["preflight_history"]] == [4, 0]
    assert resumed["preflight_history"][0]["stdout_path"] != resumed["preflight_history"][1]["stdout_path"]


def wait_for(path: Path, statuses: set[str], timeout: float = 8) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        last = get_job_status(path)
        if last.get("status") in statuses:
            return last
        time.sleep(0.05)
    raise AssertionError(f"status did not reach {statuses}: {last}")


def test_detached_status_and_stop(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_seconds=60,
        artifacts=[],
    )
    launched = start_job(path, detach=True, run_id="detached")
    assert launched["status"] == "created"
    running = wait_for(path, {"running"})
    assert running["worker_alive"] is True
    stop_job(path)
    stopped = wait_for(path, {"stopped"})
    assert stopped["worker_alive"] is False


def test_run_id_cannot_escape_state_directory(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    with pytest.raises(SupervisorError, match="run_id must be path-safe"):
        start_job(path, detach=False, run_id="../../outside")
    assert not (tmp_path.parent / "outside").exists()


def test_fast_detached_worker_cannot_be_clobbered_to_created(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    start_job(path, detach=True, run_id="fast")
    state = wait_for(path, {"succeeded", "failed", "verification_failed"})
    assert state["status"] == "succeeded"
    assert state["worker_alive"] is False
    attempts = state["attempts"]
    assert isinstance(attempts, list) and len(attempts) == 1


def test_stop_on_terminal_state_does_not_signal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = write_config(tmp_path)
    state = start_job(path, detach=False, run_id="terminal-stop")
    assert state["status"] == "succeeded"
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr("agentharness.supervisor.os.killpg", lambda pid, sig: calls.append((pid, sig)))
    returned = stop_job(path)
    assert returned["status"] == "succeeded"
    assert calls == []
