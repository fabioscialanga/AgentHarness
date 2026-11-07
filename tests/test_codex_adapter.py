import json
import os

import pytest

from agentharness.cli import main
from agentharness.codex_adapter import AdapterError, MARKER, change_codex_hook


def _config(root):
    return root / ".codex" / "hooks.json"


def test_install_uninstall_preserve_other_hooks(tmp_path):
    path = _config(tmp_path)
    path.parent.mkdir()
    original = {"description": "keep", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo foreign"}]}], "SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}]}}
    path.write_text(json.dumps(original), encoding="utf-8")
    assert change_codex_hook(tmp_path, install=True)
    installed = json.loads(path.read_text(encoding="utf-8"))
    assert installed["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    assert installed["hooks"]["SessionStart"] == original["hooks"]["SessionStart"]
    assert MARKER in installed["hooks"]["Stop"][1]["hooks"][0]["statusMessage"]
    first = path.read_bytes()
    assert not change_codex_hook(tmp_path, install=True)
    assert path.read_bytes() == first
    assert change_codex_hook(tmp_path, install=False)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    second = path.read_bytes()
    assert not change_codex_hook(tmp_path, install=False)
    assert path.read_bytes() == second


def test_cli_requires_consent(tmp_path, capsys):
    assert main(["install", "--host", "codex", "--project", str(tmp_path)]) == 2
    assert not _config(tmp_path).exists()
    assert main(["install", "--host", "codex", "--project", str(tmp_path), "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["changed"]


@pytest.mark.parametrize("raw", [b"{bad", b'{"hooks":{},"hooks":{}}', b'{"hooks":[]}', b'{"hooks":{"Stop":{}}}'])
def test_invalid_config_untouched(tmp_path, raw):
    path = _config(tmp_path)
    path.parent.mkdir()
    path.write_bytes(raw)
    with pytest.raises(AdapterError):
        change_codex_hook(tmp_path, install=True)
    assert path.read_bytes() == raw


def test_modified_owned_hook_not_removed(tmp_path):
    change_codex_hook(tmp_path, install=True)
    path = _config(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo changed"
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(AdapterError):
        change_codex_hook(tmp_path, install=False)
    assert path.read_bytes() == before


def test_concurrent_change_detected(tmp_path, monkeypatch):
    change_codex_hook(tmp_path, install=True)
    path = _config(tmp_path)
    # Interpose before the optimistic read, not the final replacement.
    from agentharness import codex_adapter
    original_read = codex_adapter._read
    count = 0

    def concurrent_read(target):
        nonlocal count
        count += 1
        if count == 2:
            path.write_text('{"hooks":{"Stop":[]},"description":"external"}', encoding="utf-8")
        return original_read(target)

    monkeypatch.setattr(codex_adapter, "_read", concurrent_read)
    with pytest.raises(AdapterError, match="concurrently"):
        change_codex_hook(tmp_path, install=False)
    assert json.loads(path.read_text(encoding="utf-8"))["description"] == "external"


def test_replace_failure_preserves_original(tmp_path, monkeypatch):
    path = _config(tmp_path)
    path.parent.mkdir()
    path.write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        change_codex_hook(tmp_path, install=True)
    assert path.read_bytes() == before


def test_windows_and_unix_commands_quote_spaces(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    change_codex_hook(root, install=True)
    handler = json.loads(_config(root).read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
    assert "--project" in handler["command"]
    assert "'" in handler["commandWindows"]
    assert str(root) in handler["commandWindows"]


def test_lock_conflict_preserves_config(tmp_path):
    path = _config(tmp_path)
    path.parent.mkdir()
    path.write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")
    (path.parent / ".agentharness-hooks.lock").mkdir()
    before = path.read_bytes()
    with pytest.raises(AdapterError, match="lock"):
        change_codex_hook(tmp_path, install=True)
    assert path.read_bytes() == before


def test_symlinked_config_rejected(tmp_path):
    path = _config(tmp_path)
    path.parent.mkdir()
    target = tmp_path / "outside.json"
    target.write_text('{"hooks":{}}', encoding="utf-8")
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(AdapterError, match="symbolic link"):
        change_codex_hook(tmp_path, install=True)
    assert target.read_text(encoding="utf-8") == '{"hooks":{}}'
