"""Frozen pytest plugin that records project-package import origins at import time."""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

_ORIGINAL_IMPORT = builtins.__import__
_IMPORT_EVENTS: list[dict[str, str]] = []
_TRACKER_INSTALLED = False
_TRACKING_IMPORT = False
_INITIAL_SYS_PATH: list[str] = []
_REMOVED_SYS_PATH: list[str] = []


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _roster() -> tuple[str, ...]:
    raw = os.environ.get("AGENTHARNESS_PROJECT_PACKAGE_ROSTER", "")
    values = tuple(item for item in raw.split(",") if item and item.isidentifier())
    if not values:
        raise RuntimeError("canonical project package roster is empty")
    return values


def _record_loaded_modules() -> None:
    roster = set(_roster())
    known = {(row["module"], row["path"]) for row in _IMPORT_EVENTS}
    for name, module in tuple(sys.modules.items()):
        if name.split(".", 1)[0] not in roster:
            continue
        raw_path = getattr(module, "__file__", None)
        path = "<missing-origin>" if not raw_path else str(Path(raw_path).resolve(strict=False))
        key = (name, path)
        if key not in known:
            _IMPORT_EVENTS.append({"module": name, "path": path})
            known.add(key)


def _tracked_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    global _TRACKING_IMPORT
    if _TRACKING_IMPORT:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    try:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    finally:
        _TRACKING_IMPORT = True
        try:
            _record_loaded_modules()
        finally:
            _TRACKING_IMPORT = False


def _guard_identity() -> dict[str, str]:
    path = Path(__file__).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _sanitize_sys_path() -> None:
    global _INITIAL_SYS_PATH, _REMOVED_SYS_PATH
    workspace = Path(os.environ["AGENTHARNESS_WORKSPACE_ROOT"]).resolve(strict=True)
    grading = Path(os.environ["AGENTHARNESS_GRADING_ENV_DIR"]).resolve(strict=True)
    allowed_roots = (workspace, grading, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
    _INITIAL_SYS_PATH = list(sys.path)
    retained: list[str] = []
    removed: list[str] = []
    for entry in sys.path:
        candidate = Path(entry or os.getcwd()).resolve(strict=False)
        if any(_within(candidate, root) for root in allowed_roots):
            retained.append(entry)
        else:
            removed.append(entry)
    sys.path[:] = retained
    _REMOVED_SYS_PATH = removed


def _audit() -> dict[str, Any]:
    workspace = Path(os.environ["AGENTHARNESS_WORKSPACE_ROOT"]).resolve(strict=True)
    roster = _roster()
    _record_loaded_modules()
    observations = sorted(_IMPORT_EVENTS, key=lambda row: (row["module"], row["path"]))
    violations = [
        row
        for row in observations
        if row["path"] == "<missing-origin>" or not _within(Path(row["path"]), workspace)
    ]
    return {
        "schema_version": 2,
        "workspace": str(workspace),
        "project_packages": list(roster),
        "runtime": {
            "cwd": os.getcwd(),
            "pwd": os.environ.get("PWD"),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "safe_path": bool(sys.flags.safe_path),
            "initial_sys_path": list(_INITIAL_SYS_PATH),
            "removed_sys_path": list(_REMOVED_SYS_PATH),
        },
        "sys_path": list(sys.path),
        "guard_module": _guard_identity(),
        "import_tracker_installed": builtins.__import__ is _tracked_import,
        "observations": observations,
        "violations": violations,
    }


def _write_audit() -> dict[str, Any]:
    payload = _audit()
    destination = Path(os.environ["AGENTHARNESS_IMPORT_AUDIT_PATH"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return payload


def pytest_configure(config: pytest.Config) -> None:
    global _TRACKER_INSTALLED
    _roster()
    _sanitize_sys_path()
    builtins.__import__ = _tracked_import
    _TRACKER_INSTALLED = True
    _record_loaded_modules()


def pytest_collection_finish(session: pytest.Session) -> None:
    payload = _write_audit()
    if payload["violations"] or payload["import_tracker_installed"] is not True:
        pytest.exit("project module resolved outside canonical workspace", returncode=4)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    payload = _write_audit()
    if payload["violations"] or payload["import_tracker_installed"] is not True:
        session.exitstatus = 4


def pytest_unconfigure(config: pytest.Config) -> None:
    global _TRACKER_INSTALLED
    builtins.__import__ = _ORIGINAL_IMPORT
    _TRACKER_INSTALLED = False
