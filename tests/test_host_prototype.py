import io
import json
import sys

from agentharness.autopilot import decide_stop
from agentharness.cli import main
from agentharness.config import set_enabled
from agentharness.host_prototype import handle_stop

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
