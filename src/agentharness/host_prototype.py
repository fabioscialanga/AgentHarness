"""Read-only host event entry point; no hook is installed by this module."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .autopilot import decide_stop
from .config import load_config
from .host_adapters import normalize_stop

WATCHED = ("pyproject.toml", "SECURITY.md", ".github/workflows")


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


def _fingerprint(root: Path, paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode("utf-8"))
        target = root / path
        if target.is_file() and not target.is_symlink():
            digest.update(target.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _record_once(root: Path, fingerprint: str) -> bool:
    state = root / ".agentharness" / "host-prototype.json"
    try:
        if state.is_file() and json.loads(state.read_text(encoding="utf-8")).get("fingerprint") == fingerprint:
            return False
    except (OSError, ValueError, AttributeError):
        pass
    temporary = None
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=state.parent, prefix=".host-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump({"fingerprint": fingerprint}, handle)
        os.replace(temporary, state)
    except OSError:
        return True  # Advisory feedback is best-effort if local state is unwritable.
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
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
    if not _record_once(root, _fingerprint(root, paths)):
        return {}
    # The hook response is a UI warning only; it never blocks or continues a turn.
    return {"systemMessage": decision.message}


def response_json(project: str | Path, host: str, payload: Any) -> str:
    return json.dumps(handle_stop(project, host, payload), ensure_ascii=False)
