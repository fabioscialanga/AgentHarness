import json
import os
import socket

import pytest

from agentharness.cli import main
from agentharness.config import ConfigError, config_path, load_config, set_enabled, status


def test_persistence_and_idempotence(tmp_path):
    assert status(tmp_path)["enabled"] is False
    assert status(tmp_path)["configured"] is False
    assert not config_path(tmp_path).exists()
    assert set_enabled(tmp_path, True)[1] is True
    before = config_path(tmp_path).read_bytes()
    assert set_enabled(tmp_path, True)[1] is False
    assert config_path(tmp_path).read_bytes() == before
    assert load_config(tmp_path)[0]["profile"] == "balanced"
    assert set_enabled(tmp_path, False)[1] is True
    assert set_enabled(tmp_path, False)[1] is False
    assert status(tmp_path)["enabled"] is False


def test_disable_preserves_config_and_evidence(tmp_path):
    set_enabled(tmp_path, True)
    evidence = tmp_path / ".agentharness" / "evidence" / "proof.txt"
    evidence.parent.mkdir()
    evidence.write_text("proof", encoding="utf-8")
    set_enabled(tmp_path, False)
    assert evidence.read_text(encoding="utf-8") == "proof"
    assert config_path(tmp_path).exists()


@pytest.mark.parametrize("content", ["[bad", "enabled: true\n", "schema_version: 2\n", "null\n"])
def test_malformed_config_is_rejected_without_overwrite(tmp_path, content):
    path = config_path(tmp_path)
    path.parent.mkdir()
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        set_enabled(tmp_path, True)
    assert path.read_text(encoding="utf-8") == content


def test_cli_json_and_no_network(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("network was used")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    assert main(["enable", "--project", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is True
    assert payload["changed"] is True
    assert payload["automatic_checks"] is False
    assert payload["llm_calls"] is False
    assert payload["recent_checks"] is None
    assert main(["status", "--project", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True
    assert main(["disable", "--project", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is False


def test_cli_rejects_invalid_config(tmp_path, capsys):
    path = config_path(tmp_path)
    path.parent.mkdir()
    path.write_text("schema_version: 99\n", encoding="utf-8")
    assert main(["status", "--project", str(tmp_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_nonexistent_project_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        status(tmp_path / "missing")


@pytest.mark.parametrize("link_parent", [False, True])
def test_symbolic_config_paths_are_rejected(tmp_path, link_parent):
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    try:
        if link_parent:
            (project / ".agentharness").symlink_to(outside, target_is_directory=True)
        else:
            (project / ".agentharness").mkdir()
            (outside / "config.yaml").write_text("secret", encoding="utf-8")
            (project / ".agentharness" / "config.yaml").symlink_to(outside / "config.yaml")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ConfigError):
        set_enabled(project, True)
    if not link_parent:
        assert (outside / "config.yaml").read_text(encoding="utf-8") == "secret"


def test_failed_atomic_replace_preserves_existing_state(tmp_path, monkeypatch):
    set_enabled(tmp_path, True)
    path = config_path(tmp_path)
    before = path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        set_enabled(tmp_path, False)
    assert path.read_bytes() == before
    assert list(path.parent.glob(".config-*.tmp")) == []


def test_existing_commands_remain_registered():
    from agentharness.cli import build_parser

    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices
    for command in ("check", "validate", "generate", "verify", "verify-run", "evaluate", "render-evaluation-suite", "benchmark-evaluate-task", "run-plan", "bootstrap"):
        assert command in commands
