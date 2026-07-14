from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import VerifyRunResult
from .verify import verify_run


SCHEMA_VERSION = "1.0"
DEFAULT_IGNORED_NAMES = frozenset(
    {
        ".agentharness",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)


@dataclass
class DirectCheckResult:
    run_id: str
    original_workspace: Path
    snapshot_workspace: Path
    artifact_dir: Path
    run_path: Path
    claims_path: Path
    report_path: Path
    command: str
    changed_files: list[str]
    verification: VerifyRunResult

    @property
    def ok(self) -> bool:
        return self.verification.ok

    @property
    def isolation(self) -> dict[str, Any]:
        return {
            "mode": "workspace-copy",
            "command_cwd_is_snapshot": True,
            "original_workspace_write_protected": False,
            "network_isolated": False,
            "host_filesystem_isolated": False,
            "warning": (
                "The command ran with its cwd inside a persistent workspace copy, not in a container. "
                "Relative writes stay in the copy, but the original workspace and host filesystem are not security-isolated."
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": self.ok,
            "run_id": self.run_id,
            "command": self.command,
            "original_workspace": str(self.original_workspace),
            "snapshot_workspace": str(self.snapshot_workspace),
            "artifact_dir": str(self.artifact_dir),
            "run_path": str(self.run_path),
            "claims_path": str(self.claims_path),
            "report_path": str(self.report_path),
            "changed_files": self.changed_files,
            "isolation": self.isolation,
            "verification": self.verification.to_dict(),
        }


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"check-{timestamp}-{uuid.uuid4().hex[:8]}"


def _is_safe_run_id(run_id: str) -> bool:
    candidate = run_id.strip()
    return bool(candidate and candidate not in {".", ".."} and "/" not in candidate and "\\" not in candidate)


def _relative_to_or_none(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def _validate_artifact_dir(workspace: Path, artifact_dir: Path) -> None:
    relative = _relative_to_or_none(artifact_dir, workspace)
    if relative is None:
        return
    if not relative.parts or relative.parts[0] != ".agentharness":
        raise ValueError(
            "An artifact directory inside the workspace must live under .agentharness to avoid recursive snapshots"
        )


def _iter_external_symlinks(workspace: Path, ignored_names: frozenset[str]) -> Iterable[Path]:
    for root, dirnames, filenames in os.walk(workspace, followlinks=False):
        root_path = Path(root)
        dirnames[:] = [name for name in dirnames if name not in ignored_names]
        for name in [*dirnames, *filenames]:
            path = root_path / name
            if not path.is_symlink():
                continue
            try:
                link_target = Path(os.readlink(path))
                if link_target.is_absolute():
                    yield path
                    continue
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                yield path
                continue
            if _relative_to_or_none(resolved, workspace) is None:
                yield path


def _snapshot_workspace(workspace: Path, snapshot: Path) -> None:
    external_symlinks = list(_iter_external_symlinks(workspace, DEFAULT_IGNORED_NAMES))
    if external_symlinks:
        rendered = ", ".join(str(path.relative_to(workspace)) for path in external_symlinks[:5])
        raise ValueError(f"Workspace contains symlinks that escape the snapshot boundary: {rendered}")

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in DEFAULT_IGNORED_NAMES}

    shutil.copytree(workspace, snapshot, symlinks=True, ignore=ignore)


def _git_changed_files(workspace: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return []

    entries = completed.stdout.split("\0")
    changed: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if path and not path.startswith(".agentharness/"):
            changed.append(path)
        if "R" in status or "C" in status:
            index += 1
    return sorted(set(changed))


def _build_claims(
    *,
    run_id: str,
    command: str,
    allowed_paths: Iterable[str],
    forbidden_paths: Iterable[str],
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = [
        {
            "id": "command_succeeds",
            "type": "tests_executed",
            "statement": f"The required command succeeds: {command}",
            "expected": {"required_commands": [command]},
        }
    ]
    allowed = [item for item in allowed_paths if item]
    if allowed:
        claims.append(
            {
                "id": "changes_stay_in_scope",
                "type": "files_changed",
                "statement": "All changed files stay within the allowed paths",
                "expected": {"allowed_paths": allowed},
            }
        )
    forbidden = [item for item in forbidden_paths if item]
    if forbidden:
        claims.append(
            {
                "id": "forbidden_paths_untouched",
                "type": "forbidden_paths",
                "statement": "No changed file matches a forbidden path",
                "expected": {"forbidden_paths": forbidden},
            }
        )
    return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "claims": claims}


def check_workspace(
    workspace: str | Path,
    command: str,
    *,
    run_id: str | None = None,
    output_dir: str | Path | None = None,
    working_dir: str | None = None,
    timeout_seconds: int = 60,
    allowed_paths: Iterable[str] = (),
    forbidden_paths: Iterable[str] = (),
) -> DirectCheckResult:
    original_workspace = Path(workspace).resolve()
    if not original_workspace.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {original_workspace}")
    if not command.strip():
        raise ValueError("Command must not be empty")
    if timeout_seconds < 1:
        raise ValueError("Timeout must be at least one second")

    resolved_run_id = (run_id or _new_run_id()).strip()
    if not _is_safe_run_id(resolved_run_id):
        raise ValueError("Run id must be a non-empty path-safe name without separators")

    if output_dir is None:
        artifact_dir = original_workspace / ".agentharness" / "runs" / resolved_run_id
    else:
        artifact_dir = Path(output_dir).resolve()
    _validate_artifact_dir(original_workspace, artifact_dir)
    if artifact_dir.exists():
        raise FileExistsError(f"Artifact directory already exists: {artifact_dir}")

    changed_files = _git_changed_files(original_workspace)
    artifact_dir.mkdir(parents=True)
    snapshot_workspace = artifact_dir / "workspace"
    _snapshot_workspace(original_workspace, snapshot_workspace)

    run_path = artifact_dir / "run.json"
    claims_path = artifact_dir / "claims.json"
    report_path = artifact_dir / "verify-report.json"
    run_payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": resolved_run_id,
        "workspace": str(snapshot_workspace),
        "task": f"Verify that command succeeds: {command}",
        "execution": {
            "mode": "workspace-copy",
            "network_isolated": False,
            "host_filesystem_isolated": False,
        },
        "artifacts": {
            "changed_files": changed_files,
            "commands": [
                {
                    "cmd": command,
                    "exit_code": 0,
                    "working_dir": working_dir or ".",
                }
            ],
            "outputs": [],
        },
    }
    claims_payload = _build_claims(
        run_id=resolved_run_id,
        command=command,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
    )
    run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
    claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

    verification = verify_run(
        run_path,
        claims_path,
        write_report=True,
        report_path=report_path,
        reexecute_mode="auto",
        reexecution_timeout=timeout_seconds,
    )
    return DirectCheckResult(
        run_id=resolved_run_id,
        original_workspace=original_workspace,
        snapshot_workspace=snapshot_workspace,
        artifact_dir=artifact_dir,
        run_path=run_path,
        claims_path=claims_path,
        report_path=report_path,
        command=command,
        changed_files=changed_files,
        verification=verification,
    )
