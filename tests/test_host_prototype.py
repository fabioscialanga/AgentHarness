import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from agentharness.autopilot import decide_stop
from agentharness.cli import main
from agentharness.config import set_enabled
from agentharness.host_prototype import MAX_FILE_BYTES, _safe_target, changed_paths, handle_stop

STOP = {"hook_event_name": "Stop", "stop_hook_active": False}


def test_disabled_skips_discovery_and_output(tmp_path):
    calls = []
    discover = lambda root: calls.append(root) or ("pyproject.toml",)
    assert handle_stop(tmp_path, "codex", STOP, discover=discover) == {}
    set_enabled(tmp_path, True)
    set_enabled(tmp_path, False)
    assert handle_stop(tmp_path, "claude", STOP, discover=discover) == {}
    assert calls == []
    assert not (tmp_path / ".agentharness" / "host-prototype.json").exists()


def test_significant_stop_suggests_once_without_running_checks(tmp_path):
    set_enabled(tmp_path, True)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    discover = lambda root: ("pyproject.toml",)
    first = handle_stop(tmp_path, "claude", STOP, discover=discover)
    assert "systemMessage" in first
    assert handle_stop(tmp_path, "codex", STOP, discover=discover) == {}
    assert handle_stop(tmp_path, "codex", {**STOP, "stop_hook_active": True}, discover=discover) == {}
    (tmp_path / "pyproject.toml").write_text("[project]\nname='changed'\n", encoding="utf-8")
    assert "systemMessage" in handle_stop(tmp_path, "codex", STOP, discover=discover)


def test_non_significant_change_is_silent(tmp_path):
    set_enabled(tmp_path, True)
    assert decide_stop(("src/app.py",)) is None
    assert handle_stop(tmp_path, "codex", STOP, discover=lambda root: ("src/app.py",)) == {}


def test_cli_fail_open_for_invalid_event(tmp_path, monkeypatch, capsys):
    set_enabled(tmp_path, True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Other"})))
    assert main(["host-event", "--host", "codex", "--project", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "{}"


def test_cli_disable_prevents_subsequent_feedback(tmp_path, monkeypatch, capsys):
    set_enabled(tmp_path, True)
    set_enabled(tmp_path, False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(STOP)))
    assert main(["host-event", "--host", "claude", "--project", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "{}"


@pytest.mark.parametrize("path", ["../pyproject.toml", "/pyproject.toml", ".github/workflows/../x.yml", ".github/workflows/extra/x.yml", "pyproject.toml/./x", "pyproject.toml\\evil"])
def test_invalid_paths_are_silent(tmp_path, path):
    set_enabled(tmp_path, True)
    assert _safe_target(tmp_path, path) is None
    assert handle_stop(tmp_path, "codex", STOP, discover=lambda root: (path,)) == {}


def test_oversized_and_unreadable_files_are_silent(tmp_path, monkeypatch):
    set_enabled(tmp_path, True)
    target = tmp_path / "pyproject.toml"
    target.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    discover = lambda root: ("pyproject.toml",)
    assert handle_stop(tmp_path, "codex", STOP, discover=discover) == {}
    target.write_text("small", encoding="utf-8")
    def fail_open(*args, **kwargs):
        raise PermissionError("unreadable")
    monkeypatch.setattr(os, "open", fail_open)
    assert handle_stop(tmp_path, "codex", STOP, discover=discover) == {}


def test_file_removed_during_open_is_silent(tmp_path, monkeypatch):
    set_enabled(tmp_path, True)
    target = tmp_path / "pyproject.toml"
    target.write_text("temporary", encoding="utf-8")
    def remove_then_fail(*args, **kwargs):
        target.unlink()
        raise FileNotFoundError("removed during read")
    monkeypatch.setattr(os, "open", remove_then_fail)
    assert handle_stop(tmp_path, "codex", STOP, discover=lambda root: ("pyproject.toml",)) == {}


def test_state_write_failure_is_silent(tmp_path, monkeypatch):
    set_enabled(tmp_path, True)
    (tmp_path / "pyproject.toml").write_text("small", encoding="utf-8")
    def fail_replace(*args, **kwargs):
        raise PermissionError("state unwritable")
    monkeypatch.setattr(os, "replace", fail_replace)
    assert handle_stop(tmp_path, "codex", STOP, discover=lambda root: ("pyproject.toml",)) == {}


def test_git_timeout_is_silent(tmp_path, monkeypatch):
    set_enabled(tmp_path, True)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 2)
    monkeypatch.setattr(subprocess, "run", timeout)
    assert changed_paths(tmp_path) == ()
    assert handle_stop(tmp_path, "codex", STOP) == {}


def test_malformed_json_fails_open(tmp_path, monkeypatch, capsys):
    set_enabled(tmp_path, True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{invalid"))
    assert main(["host-event", "--host", "codex", "--project", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "{}"


def test_unexpected_handler_failure_fails_open(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr("agentharness.host_prototype.response_json", lambda *args: (_ for _ in ()).throw(RuntimeError("unexpected")))
    assert main(["host-event", "--host", "codex", "--project", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "{}"


def test_concurrent_stops_emit_once(tmp_path):
    set_enabled(tmp_path, True)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(pool.map(lambda _: handle_stop(tmp_path, "codex", STOP, discover=lambda root: ("pyproject.toml",)), range(24)))
    assert sum(bool(item) for item in outputs) == 1


def test_git_untracked_staged_and_committed_behavior(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    set_enabled(tmp_path, True)
    (tmp_path / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "initial"], check=True)
    target = tmp_path / "pyproject.toml"
    target.write_text("[project]\n", encoding="utf-8")
    assert changed_paths(tmp_path) == ()  # Untracked files are outside this prototype.
    subprocess.run(["git", "-C", str(tmp_path), "add", "pyproject.toml"], check=True)
    assert changed_paths(tmp_path) == ("pyproject.toml",)
    assert "systemMessage" in handle_stop(tmp_path, "codex", STOP)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "baseline"], check=True)
    assert changed_paths(tmp_path) == ()  # A committed change is no longer a diff from HEAD.
    assert handle_stop(tmp_path, "codex", STOP) == {}
