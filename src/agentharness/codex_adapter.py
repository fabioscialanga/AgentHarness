"""Opt-in, project-local Codex Stop hook lifecycle."""

from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

MARKER = "AgentHarness Stop adapter"
MAX_CONFIG_BYTES = 1024 * 1024


class AdapterError(ValueError):
    pass


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdapterError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> tuple[dict, bytes | None]:
    if path.is_symlink():
        raise AdapterError("hooks.json is a symbolic link")
    if not path.exists():
        return {"hooks": {}}, None
    if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
        raise AdapterError("hooks.json is not a regular file or exceeds 1 MiB")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise AdapterError("hooks.json exceeds 1 MiB")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read hooks.json: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        raise AdapterError("unsupported hooks.json structure")
    stop = data["hooks"].get("Stop", [])
    if not isinstance(stop, list) or any(not isinstance(group, dict) or not isinstance(group.get("hooks"), list) for group in stop):
        raise AdapterError("unsupported Stop hook structure")
    return data, raw


def _owned(group: object) -> bool:
    return isinstance(group, dict) and any(
        isinstance(handler, dict) and handler.get("statusMessage") == MARKER
        for handler in group.get("hooks", []) if isinstance(group.get("hooks"), list)
    )


def _command(project: Path, executable: Path) -> dict:
    args = ["-m", "agentharness", "host-event", "--host", "codex", "--project", str(project)]
    unix = " ".join(shlex.quote(item) for item in [str(executable), *args])
    # Codex runs commandWindows through PowerShell. The call operator is needed
    # when the executable path is quoted, including paths with spaces.
    powershell = "& " + " ".join("'" + item.replace("'", "''") + "'" for item in [str(executable), *args])
    return {"type": "command", "command": unix, "commandWindows": powershell, "timeout": 5, "statusMessage": MARKER}


def _validate_owned(group: dict, project: Path) -> None:
    handlers = group.get("hooks")
    if set(group) != {"hooks"} or not isinstance(handlers, list) or len(handlers) != 1:
        raise AdapterError("AgentHarness hook was modified; refusing removal")
    handler = handlers[0]
    if not isinstance(handler, dict) or set(handler) != {"type", "command", "commandWindows", "timeout", "statusMessage"}:
        raise AdapterError("AgentHarness hook was modified; refusing removal")
    if handler["type"] != "command" or handler["timeout"] != 5 or handler["statusMessage"] != MARKER:
        raise AdapterError("AgentHarness hook was modified; refusing removal")
    try:
        tokens = shlex.split(handler["command"])
        if len(tokens) != 8 or handler != _command(project, Path(tokens[0])):
            raise AdapterError("AgentHarness hook was modified; refusing removal")
    except (TypeError, ValueError) as exc:
        raise AdapterError("AgentHarness hook was modified; refusing removal") from exc


def change_codex_hook(project: str | Path, *, install: bool, executable: str | Path | None = None) -> bool:
    """Return True only when hooks.json changed. Caller handles user consent."""
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise AdapterError("project is not a directory")
    codex = root / ".codex"
    if codex.is_symlink():
        raise AdapterError(".codex is a symbolic link")
    path = codex / "hooks.json"
    lock = codex / ".agentharness-hooks.lock"
    if not codex.exists() and not install:
        return False
    if install:
        codex.mkdir(exist_ok=True)
    try:
        lock.mkdir()
    except OSError as exc:
        raise AdapterError("cannot acquire adapter lock") from exc
    temporary: str | None = None
    try:
        data, original = _read(path)
        stop = data["hooks"].get("Stop", [])
        owned = [index for index, group in enumerate(stop) if _owned(group)]
        if len(owned) > 1:
            raise AdapterError("multiple AgentHarness hooks found")
        if install:
            if owned:
                _validate_owned(stop[owned[0]], root)
                return False
            python = Path(executable or sys.executable).resolve(strict=True)
            if not python.is_file():
                raise AdapterError("Python executable is not a file")
            stop.append({"hooks": [_command(root, python)]})
            data["hooks"]["Stop"] = stop
        else:
            if not owned:
                return False
            _validate_owned(stop[owned[0]], root)
            stop.pop(owned[0])
            if stop:
                data["hooks"]["Stop"] = stop
            else:
                del data["hooks"]["Stop"]
        if original is None and not install:
            return False
        replacement = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile("wb", dir=codex, prefix=".hooks-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(replacement)
        # Optimistic check catches concurrent external edits before replacement.
        if _read(path)[1] != original:
            raise AdapterError("hooks.json changed concurrently")
        os.replace(temporary, path)
        temporary = None
        return True
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        try:
            lock.rmdir()
        except OSError:
            pass
