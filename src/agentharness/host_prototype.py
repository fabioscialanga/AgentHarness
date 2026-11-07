"""Read-only host event entry point; no hook is installed by this module."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .autopilot import decide_stop
from .config import load_config
from .host_adapters import normalize_stop

WATCHED = ("pyproject.toml", "SECURITY.md", ".github/workflows")
MAX_FILE_BYTES = 1024 * 1024
LOCK_STALE_SECONDS = 10


def changed_paths(project: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project), "diff", "--name-only", "HEAD", "--", *WATCHED],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    return tuple(sorted(set(completed.stdout.splitlines())))


def _safe_target(root: Path, path: str) -> Path | None:
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        return None
    relative = PurePosixPath(path)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in path.split("/")):
        return None
    if path not in {"pyproject.toml", "SECURITY.md"}:
        if len(relative.parts) != 3 or relative.parts[:2] != (".github", "workflows"):
            return None
    target = root.joinpath(*relative.parts)
    try:
        target.resolve(strict=False).relative_to(root)
    except (OSError, ValueError, RuntimeError):
        return None
    return target


def _fingerprint(root: Path, paths: tuple[str, ...]) -> str | None:
    digest = hashlib.sha256()
    for path in paths:
        target = _safe_target(root, path)
        if target is None:
            return None
        digest.update(path.encode("utf-8"))
        try:
            if target.is_symlink():
                return None
            exists = target.exists()
        except OSError:
            return None
        if not exists:
            digest.update(b"<missing>")
            continue
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(target, flags)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                    return None
                remaining = MAX_FILE_BYTES + 1
                while remaining:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    digest.update(chunk)
                if remaining == 0:
                    return None
        except (OSError, ValueError):
            return None
    return digest.hexdigest()


def _record_once(root: Path, fingerprint: str) -> bool:
    state = root / ".agentharness" / "host-prototype.json"
    lock = root / ".agentharness" / ".host-prototype.lock"
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock.mkdir()
        except FileExistsError:
            if time.time() - lock.stat().st_mtime <= LOCK_STALE_SECONDS:
                return False
            lock.rmdir()
            lock.mkdir()
    except OSError:
        return False
    temporary = None
    try:
        if state.is_symlink():
            return False
        try:
            if state.is_file() and json.loads(state.read_text(encoding="utf-8")).get("fingerprint") == fingerprint:
                return False
        except (OSError, ValueError, AttributeError):
            pass
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=state.parent, prefix=".host-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump({"fingerprint": fingerprint}, handle)
        os.replace(temporary, state)
    except OSError:
        return False
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass
        try:
            lock.rmdir()
        except OSError:
            pass
    return True


def handle_stop(
    project: str | Path,
    host: str,
    payload: Any,
    *,
    discover: Callable[[Path], tuple[str, ...]] = changed_paths,
) -> dict[str, str]:
    event = normalize_stop(host, payload)
    config, _ = load_config(project)
    if not config["enabled"] or event.repeated_stop:
        return {}
    root = Path(project).resolve()
    paths = discover(root)
    decision = decide_stop(paths)
    if decision is None:
        return {}
    fingerprint = _fingerprint(root, paths)
    if fingerprint is None or not _record_once(root, fingerprint):
        return {}
    if not load_config(root)[0]["enabled"]:
        return {}
    # The hook response is a UI warning only; it never blocks or continues a turn.
    return {"systemMessage": decision.message}


def response_json(project: str | Path, host: str, payload: Any) -> str:
    return json.dumps(handle_stop(project, host, payload), ensure_ascii=False)
