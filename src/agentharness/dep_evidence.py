"""M3 CP3-B local DEP binding and read-only evidence matching.

Only an explicit call to ``check_dep_workspace`` executes an existing check.
``match_dep_evidence`` never executes artifact commands or calls an LLM.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from .direct_check import DEFAULT_IGNORED_NAMES, DirectCheckResult, check_workspace
from .reexecution import prepare_execution_tokens
from .risk_dep import DetectionResult, detect_dependency_change


MAPPING_ID = "DEP-PEP621-PYTEST-V0"
APPROVED_COMMAND = "python -m pytest -q tests/test_dep.py"
RISK_ID = "dep-pep621-dependency-change"
FRESHNESS_POLICY = "DEP_LOCAL_24H_V0"
MAX_RUN_DIRS = 128
MAX_JSON_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_PATHS = 256
MAX_SOURCE_BYTES = 1024 * 1024
MATCH_DEADLINE_SECONDS = 1.0
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ARTIFACT_KEY = re.compile(r"\.agentharness/runs/[A-Za-z0-9._-]+/.+\Z")


class _Unknown(Exception):
    def __init__(self, reason: str):
        self.reason = reason


@dataclass(frozen=True)
class ApprovedDepControl:
    """Explicit approval for the fixed DEP fixture command in one project."""

    project: Path
    environment_id: str
    command: str = APPROVED_COMMAND
    cwd: str = "."
    mapping_id: str = MAPPING_ID
    scope: tuple[str, ...] = ("pyproject.toml", "tests/test_dep.py")

    def validate(self, project: Path) -> None:
        if self.project.resolve() != project.resolve():
            raise ValueError("control belongs to another project")
        if self.command != APPROVED_COMMAND or self.cwd != "." or self.mapping_id != MAPPING_ID:
            raise ValueError("DEP control is not the approved mapping")
        if self.scope != ("pyproject.toml", "tests/test_dep.py"):
            raise ValueError("DEP scope is not the approved mapping")
        if not isinstance(self.environment_id, str) or not self.environment_id or len(self.environment_id) > 200:
            raise ValueError("environment_id is required")


def _effective_interpreter() -> Path | None:
    tokens = prepare_execution_tokens(["python", "-m", "pytest"])
    path = Path(tokens[0]) if tokens else None
    return path.absolute() if path is not None and path.is_absolute() and path.is_file() else None


def local_environment_id(executable: str | Path | None = None) -> str | None:
    """Identify the executable actually selected by the existing reexecutor.

    A relative PATH fallback cannot be attested and returns None. The digest
    binds invocation path and executable bytes, including distinct venv paths.
    """
    path = Path(executable) if executable is not None else _effective_interpreter()
    if path is None or not path.is_absolute() or not path.is_file():
        return None
    try:
        if path.stat().st_size > 32 * 1024 * 1024:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(64 * 1024):
                digest.update(block)
        identity = f"m3-python-v0\0{os.path.normcase(str(path.absolute()))}\0{digest.hexdigest()}"
        return "m3-python-v0:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    except OSError:
        return None


@dataclass(frozen=True)
class BoundCheckResult:
    check: DirectCheckResult | None
    binding_path: Path | None
    reason: str | None


@dataclass(frozen=True)
class EvidenceDecision:
    status: Literal["covered", "uncovered", "failed", "unknown"]
    reason: str | None = None
    run_ids: tuple[str, ...] = ()


def approved_dep_control_from_run(project: str | Path, run_id: str) -> ApprovedDepControl:
    """Read one explicitly selected local binding; never infer approval from a command.

    This only selects the fixed mapping. ``match_dep_evidence`` still validates
    state, environment, provenance, hashes, outputs and contradictions.
    """
    root = Path(project).resolve()
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("control_run_invalid")
    agent_dir = root / ".agentharness"
    runs = agent_dir / "runs"
    run_dir = runs / run_id
    if agent_dir.is_symlink() or runs.is_symlink() or run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError("control_run_unavailable")
    binding_path = run_dir / "m3-binding-v0.json"
    if not binding_path.is_file() or binding_path.is_symlink():
        raise ValueError("control_binding_unavailable")
    try:
        binding = _shape(_safe_json(binding_path, run_dir, _ReadBudget()))
    except _Unknown as exc:
        raise ValueError(f"control_binding_{exc.reason}") from exc
    if (binding["provenance"] != "local-capture" or binding["risk_id"] != RISK_ID
            or binding["run_id"] != run_id
            or binding["scope"] != {"risk_paths": ["pyproject.toml"],
                                    "evidence_paths": ["pyproject.toml", "tests/test_dep.py"]}):
        raise ValueError("control_binding_unapproved")
    mapped = binding["check"]
    control = ApprovedDepControl(root, mapped["environment_id"], command=mapped["command"],
                                 cwd=mapped["cwd"], mapping_id=mapped["mapping_id"])
    try:
        control.validate(root)
    except ValueError as exc:
        raise ValueError("control_binding_unapproved") from exc
    return control


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise _Unknown("time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _Unknown("time") from exc
    if parsed.tzinfo is None:
        raise _Unknown("time")
    return parsed.astimezone(timezone.utc)


def _safe_regular(path: Path, root: Path) -> None:
    try:
        relative = path.relative_to(root)
        current = root
        if current.is_symlink():
            raise _Unknown("unsafe_path")
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise _Unknown("unsafe_path")
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        mode = path.lstat().st_mode
    except (OSError, ValueError) as exc:
        raise _Unknown("unsafe_path") from exc
    if not stat.S_ISREG(mode):
        raise _Unknown("unsafe_path")


class _ReadBudget:
    def __init__(self) -> None:
        self.bytes = 0
        self.deadline = time.monotonic() + MATCH_DEADLINE_SECONDS

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise _Unknown("timeout")

    def read(self, path: Path, root: Path, limit: int) -> bytes:
        self.check_time()
        _safe_regular(path, root)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise _Unknown("unreadable") from exc
        if size > limit or self.bytes + size > MAX_TOTAL_BYTES:
            raise _Unknown("budget")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as handle:
                data = handle.read(min(limit, MAX_TOTAL_BYTES - self.bytes) + 1)
        except OSError as exc:
            raise _Unknown("unreadable") from exc
        if len(data) > limit or self.bytes + len(data) > MAX_TOTAL_BYTES:
            raise _Unknown("budget")
        self.bytes += len(data)
        self.check_time()
        return data


def _manifest(root: Path, *, limit: int = MAX_TOTAL_BYTES, budget: _ReadBudget | None = None) -> str:
    """Hash the input snapshot using the same exclusions as direct_check."""
    if root.is_symlink() or not root.is_dir():
        raise _Unknown("snapshot_invalid")
    entries: list[tuple[str, str]] = []
    total = 0
    def walk_error(exc: OSError) -> None:
        raise _Unknown("snapshot_unreadable") from exc

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        if budget is not None:
            budget.check_time()
        dirs[:] = sorted(name for name in dirs if name not in DEFAULT_IGNORED_NAMES)
        if any((Path(directory) / name).is_symlink() for name in dirs):
            raise _Unknown("snapshot_symlink")
        for name in sorted(files):
            if name in DEFAULT_IGNORED_NAMES:
                continue
            path = Path(directory) / name
            if path.is_symlink():
                raise _Unknown("snapshot_symlink")
            try:
                info = path.lstat()
            except OSError as exc:
                raise _Unknown("snapshot_unreadable") from exc
            if not stat.S_ISREG(info.st_mode):
                raise _Unknown("snapshot_invalid")
            if info.st_size > MAX_SOURCE_BYTES or total + info.st_size > limit:
                raise _Unknown("snapshot_budget")
            if len(entries) >= MAX_MANIFEST_PATHS:
                raise _Unknown("snapshot_budget")
            if budget is not None:
                data = budget.read(path, root, MAX_SOURCE_BYTES)
            else:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                try:
                    fd = os.open(path, flags)
                    with os.fdopen(fd, "rb") as handle:
                        data = handle.read(MAX_SOURCE_BYTES + 1)
                except OSError as exc:
                    raise _Unknown("snapshot_unreadable") from exc
            if len(data) > MAX_SOURCE_BYTES:
                raise _Unknown("snapshot_budget")
            total += len(data)
            entries.append((path.relative_to(root).as_posix(), _sha(data)))
    payload = "\n".join(f"{name}\0{digest}" for name, digest in entries).encode("utf-8")
    return _sha(payload)


def _shape(binding: Any) -> dict[str, Any]:
    """Validate the frozen binding-v0 serialization constraints without deps."""
    if not isinstance(binding, dict):
        raise _Unknown("schema")
    required = {"schema_version", "provenance", "risk_id", "rule_id", "run_id", "state", "scope", "check",
                "snapshot_sha256", "artifact_sha256", "captured_at", "evaluated_at", "reexecution_finished_at"}
    if set(binding) != required:
        raise _Unknown("schema")
    if binding["schema_version"] != "m3.binding.v0" or binding["provenance"] not in {"local-capture", "benchmark-oracle"}:
        raise _Unknown("schema")
    if not isinstance(binding["risk_id"], str) or not binding["risk_id"] or binding["rule_id"] != "DEP-PEP621-V0":
        raise _Unknown("schema")
    if not isinstance(binding["run_id"], str) or not _RUN_ID.fullmatch(binding["run_id"]):
        raise _Unknown("schema")
    state = binding["state"]
    if not isinstance(state, dict) or set(state) != {"base_commit", "target_commit", "diff_sha256", "state_id", "kind"}:
        raise _Unknown("schema")
    if not all(isinstance(state[key], str) and _HEX40.fullmatch(state[key]) for key in ("base_commit", "target_commit")):
        raise _Unknown("schema")
    if not all(isinstance(state[key], str) and _HEX64.fullmatch(state[key]) for key in ("diff_sha256", "state_id")):
        raise _Unknown("schema")
    if state["kind"] not in {"working-tree", "committed"}:
        raise _Unknown("schema")
    scope = binding["scope"]
    if not isinstance(scope, dict) or set(scope) != {"risk_paths", "evidence_paths"}:
        raise _Unknown("schema")
    for key in ("risk_paths", "evidence_paths"):
        if not isinstance(scope[key], list) or not scope[key] or any(not isinstance(x, str) for x in scope[key]):
            raise _Unknown("schema")
    check = binding["check"]
    if not isinstance(check, dict) or set(check) != {"mapping_id", "command", "cwd", "environment_id"}:
        raise _Unknown("schema")
    if check["mapping_id"] != MAPPING_ID or any(not isinstance(check[key], str) or not check[key] for key in ("command", "cwd", "environment_id")):
        raise _Unknown("schema")
    if not isinstance(binding["snapshot_sha256"], str) or not _HEX64.fullmatch(binding["snapshot_sha256"]):
        raise _Unknown("schema")
    artifacts = binding["artifact_sha256"]
    if not isinstance(artifacts, dict) or len(artifacts) < 3 or len(artifacts) > MAX_MANIFEST_PATHS:
        raise _Unknown("schema")
    if any(not isinstance(key, str) or not _ARTIFACT_KEY.fullmatch(key) or not isinstance(value, str) or not _HEX64.fullmatch(value)
           for key, value in artifacts.items()):
        raise _Unknown("schema")
    if any(part in {"", ".", ".."} for key in artifacts for part in key.split("/")):
        raise _Unknown("unsafe_path")
    if any("\\" in key or ":" in key for key in artifacts):
        raise _Unknown("unsafe_path")
    _utc(binding["captured_at"])
    _utc(binding["evaluated_at"])
    if binding["reexecution_finished_at"] is not None:
        _utc(binding["reexecution_finished_at"])
    return binding


def _artifact_map(run_dir: Path, project: Path, budget: _ReadBudget) -> dict[str, str]:
    files = []
    for path in run_dir.rglob("*"):
        if path.is_symlink():
            raise _Unknown("unsafe_path")
        if path.is_file() and path.name != "m3-binding-v0.json":
            files.append(path)
        if len(files) > MAX_MANIFEST_PATHS:
            raise _Unknown("budget")
    result = {}
    for path in sorted(files):
        relative = path.relative_to(project).as_posix()
        if "/workspace/" in relative and "/workspace/.agentharness/evidence/" not in relative:
            continue
        result[relative] = _sha(budget.read(path, run_dir, MAX_JSON_BYTES))
    return result


def _execution(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        claim = next(item for item in report["results"] if item.get("claim_type") == "tests_executed")
        execution = claim["audit"]["commands"][0]["reexecution"]
    except (KeyError, IndexError, StopIteration, TypeError) as exc:
        raise _Unknown("unverified") from exc
    if not isinstance(execution, dict):
        raise _Unknown("unverified")
    return claim, execution


def _report_outputs(execution: dict[str, Any], run_dir: Path, budget: _ReadBudget) -> None:
    for role in ("stdout", "stderr"):
        value = execution.get(f"{role}_path")
        expected = execution.get(f"{role}_sha256")
        if not isinstance(value, str) or not isinstance(expected, str) or not _HEX64.fullmatch(expected):
            raise _Unknown("unverified")
        path = Path(value)
        try:
            path.relative_to(run_dir)
        except ValueError as exc:
            raise _Unknown("unsafe_path") from exc
        if _sha(budget.read(path, run_dir, MAX_JSON_BYTES)) != expected:
            raise _Unknown("tampered")


def _safe_json(path: Path, root: Path, budget: _ReadBudget) -> dict[str, Any]:
    try:
        value = json.loads(budget.read(path, root, MAX_JSON_BYTES))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _Unknown("schema") from exc
    if not isinstance(value, dict):
        raise _Unknown("schema")
    return value


def _binding_payload(project: Path, detection: DetectionResult, control: ApprovedDepControl,
                     check: DirectCheckResult, snapshot_digest: str) -> dict[str, Any]:
    budget = _ReadBudget()
    artifacts = _artifact_map(check.artifact_dir, project, budget)
    report = _safe_json(check.report_path, check.artifact_dir, budget)
    _, execution = _execution(report)
    reported_executable = execution.get("executable_path")
    effective = _effective_interpreter()
    if effective is None or not isinstance(reported_executable, str) or not Path(reported_executable).is_absolute():
        raise _Unknown("environment_unverified")
    if os.path.normcase(os.path.abspath(reported_executable)) != os.path.normcase(str(effective)):
        raise _Unknown("environment_unverified")
    if local_environment_id(effective) != control.environment_id:
        raise _Unknown("environment_unverified")
    state = detection.state
    assert state is not None
    return {
        "schema_version": "m3.binding.v0", "provenance": "local-capture", "risk_id": RISK_ID,
        "rule_id": detection.candidate.rule_id, "run_id": check.run_id,
        "state": {"base_commit": state.base_commit, "target_commit": state.target_commit,
                  "diff_sha256": state.diff_digest, "state_id": state.state_id, "kind": state.kind},
        "scope": {"risk_paths": list(detection.candidate.scope), "evidence_paths": list(control.scope)},
        "check": {"mapping_id": control.mapping_id, "command": control.command,
                  "cwd": control.cwd, "environment_id": control.environment_id},
        "snapshot_sha256": snapshot_digest, "artifact_sha256": artifacts,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "reexecution_finished_at": execution.get("finished_at"),
    }


def check_dep_workspace(project: str | Path, control: ApprovedDepControl, *, run_id: str | None = None,
                        timeout_seconds: int = 60) -> BoundCheckResult:
    """Run the existing explicit check and bind it only if three snapshots agree."""
    root = Path(project).resolve()
    control.validate(root)
    if local_environment_id() != control.environment_id:
        return BoundCheckResult(None, None, "environment_unverified")
    before = detect_dependency_change(root)
    if before.status != "risk":
        return BoundCheckResult(None, None, f"detection:{before.status}:{before.reason or 'none'}")
    try:
        initial_manifest = _manifest(root)
    except _Unknown as exc:
        return BoundCheckResult(None, None, exc.reason)
    observed: dict[str, str] = {}

    def observer(snapshot: Path) -> None:
        try:
            observed["digest"] = _manifest(snapshot)
        except _Unknown as exc:
            observed["error"] = exc.reason

    check = check_workspace(root, control.command, run_id=run_id, timeout_seconds=timeout_seconds,
                            snapshot_observer=observer)
    after = detect_dependency_change(root)
    if after.status != "risk" or after.state != before.state:
        return BoundCheckResult(check, None, "state_changed")
    try:
        final_manifest = _manifest(root)
        if observed.get("error"):
            raise _Unknown(observed["error"])
        if not observed.get("digest") or initial_manifest != observed["digest"] or initial_manifest != final_manifest:
            raise _Unknown("snapshot_changed")
        if not (check.snapshot_workspace / "tests/test_dep.py").is_file():
            raise _Unknown("scope_missing")
        payload = _binding_payload(root, before, control, check, initial_manifest)
        _shape(payload)
        destination = check.artifact_dir / "m3-binding-v0.json"
        if destination.exists() or destination.is_symlink():
            raise _Unknown("binding_exists")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=check.artifact_dir,
                                         prefix=".m3-binding-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return BoundCheckResult(check, destination, None)
    except (_Unknown, OSError, ValueError) as exc:
        return BoundCheckResult(check, None, exc.reason if isinstance(exc, _Unknown) else "binding_error")


def _candidate(run_dir: Path, project: Path, detection: DetectionResult,
               control: ApprovedDepControl, budget: _ReadBudget, now: datetime) -> tuple[str, str | None] | None:
    run_path = run_dir / "run.json"
    binding_path = run_dir / "m3-binding-v0.json"
    if run_dir.is_symlink():
        raise _Unknown("unsafe_path")
    if not run_path.exists() and not binding_path.exists():
        return None
    run = _safe_json(run_path, run_dir, budget)
    artifact_record = run.get("artifacts")
    commands = artifact_record.get("commands", []) if isinstance(artifact_record, dict) else []
    declared = commands[0].get("cmd") if isinstance(commands, list) and commands and isinstance(commands[0], dict) else None
    if not binding_path.exists():
        return ("unknown", "unverified") if declared == control.command else None
    binding = _shape(_safe_json(binding_path, run_dir, budget))
    if binding["risk_id"] != RISK_ID and declared != control.command:
        return None
    if binding["provenance"] != "local-capture":
        return "unknown", "unverified"
    if binding["run_id"] != run_dir.name or run.get("run_id") != run_dir.name:
        return "unknown", "tampered"
    mapped = binding["check"]
    if mapped != {"mapping_id": control.mapping_id, "command": control.command,
                  "cwd": control.cwd, "environment_id": control.environment_id}:
        return "unknown", "irrelevant"
    scope = binding["scope"]
    if not set(detection.candidate.scope).issubset(scope["risk_paths"]) or not set(control.scope).issubset(scope["evidence_paths"]):
        return "unknown", "irrelevant"
    state = detection.state
    bound = binding["state"]
    if bound["base_commit"] != state.base_commit or bound["target_commit"] != state.target_commit or bound["kind"] != state.kind:
        return "unknown", "stale"
    if bound["diff_sha256"] != state.diff_digest or bound["state_id"] != state.state_id:
        return "unknown", "state_changed"
    hashes = binding["artifact_sha256"]
    for required in ("run.json", "claims.json", "verify-report.json"):
        if f".agentharness/runs/{run_dir.name}/{required}" not in hashes:
            return "unknown", "tampered"
    for relative, expected in hashes.items():
        path = project / relative
        try:
            path.relative_to(run_dir)
        except ValueError:
            return "unknown", "unsafe_path"
        if _sha(budget.read(path, run_dir, MAX_JSON_BYTES)) != expected:
            return "unknown", "tampered"
    report = _safe_json(run_dir / "verify-report.json", run_dir, budget)
    if report.get("run_id") != run_dir.name or report.get("run_sha256") != hashes[f".agentharness/runs/{run_dir.name}/run.json"]:
        return "unknown", "tampered"
    if report.get("claims_sha256") != hashes[f".agentharness/runs/{run_dir.name}/claims.json"]:
        return "unknown", "tampered"
    if _manifest(run_dir / "workspace", budget=budget) != binding["snapshot_sha256"]:
        return "unknown", "tampered"
    for relative in control.scope:
        _safe_regular(run_dir / "workspace" / relative, run_dir / "workspace")
    claim, execution = _execution(report)
    if declared != control.command or execution.get("command") != control.command:
        return "unknown", "irrelevant"
    reported_executable = execution.get("executable_path")
    effective = _effective_interpreter()
    if effective is None or not isinstance(reported_executable, str) or not Path(reported_executable).is_absolute():
        return "unknown", "environment_unverified"
    if os.path.normcase(os.path.abspath(reported_executable)) != os.path.normcase(str(effective)):
        return "unknown", "environment_unverified"
    if local_environment_id(effective) != control.environment_id:
        return "unknown", "environment_unverified"
    if not execution.get("completed") or execution.get("timed_out") or claim.get("truth_source") != "reexecuted":
        return "unknown", "unverified"
    _report_outputs(execution, run_dir, budget)
    finished = execution.get("finished_at")
    if finished != binding["reexecution_finished_at"]:
        return "unknown", "tampered"
    age = now - _utc(finished)
    if age < -timedelta(minutes=5):
        return "unknown", "time"
    if age > timedelta(hours=24):
        return "unknown", "expired"
    exit_code = execution.get("exit_code")
    if exit_code == 0 and claim.get("status") == "supported" and report.get("ok") is True:
        return "covered", None
    if isinstance(exit_code, int) and exit_code != 0 and claim.get("status") == "unsupported":
        return "failed", None
    return "unknown", "unverified"


def match_dep_evidence(project: str | Path, detection: DetectionResult,
                       control: ApprovedDepControl, *, now: datetime | None = None) -> EvidenceDecision:
    """Classify local evidence without executing it. Unknown never becomes covered."""
    if detection.status != "risk" or detection.candidate is None or detection.state is None:
        raise ValueError("matching requires a detected DEP risk")
    root = Path(project).resolve()
    control.validate(root)
    if (detection.captured_root != root or detection.captured_monotonic is None
            or not 0 <= time.monotonic() - detection.captured_monotonic <= 2.0):
        return EvidenceDecision("unknown", "capture_unverified")
    if local_environment_id() != control.environment_id:
        return EvidenceDecision("unknown", "environment_unverified")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("now must include a timezone")
    budget = _ReadBudget()
    try:
        # The caller's detection is the initial capture. A final independent
        # capture below rejects changes while artifacts are being inspected.
        runs = root / ".agentharness" / "runs"
        if not runs.exists():
            entries = []
        elif runs.is_symlink() or not runs.is_dir():
            raise _Unknown("unsafe_path")
        else:
            entries = sorted(runs.iterdir())
        if len(entries) > MAX_RUN_DIRS:
            raise _Unknown("budget")
        candidates: list[tuple[str, str, str | None]] = []
        for path in entries:
            budget.check_time()
            if path.is_symlink() or not path.is_dir() or not _RUN_ID.fullmatch(path.name):
                raise _Unknown("unsafe_path")
            try:
                classification = _candidate(path, root, detection, control, budget, clock)
            except _Unknown as exc:
                classification = ("unknown", exc.reason)
            if classification:
                candidates.append((path.name, *classification))
        if not candidates:
            result = EvidenceDecision("uncovered", "absent")
        else:
            valid = [(run, status) for run, status, _ in candidates if status in {"covered", "failed"}]
            unknown = [(run, reason) for run, status, reason in candidates if status == "unknown"]
            current_unknown = [(run, reason) for run, reason in unknown if reason not in {"stale", "state_changed", "expired"}]
            if {status for _, status in valid} == {"covered", "failed"}:
                result = EvidenceDecision("unknown", "contradictory", tuple(run for run, _, _ in candidates))
            elif current_unknown:
                result = EvidenceDecision("unknown", current_unknown[0][1], tuple(run for run, _, _ in candidates))
            elif valid:
                result = EvidenceDecision(valid[0][1], None, tuple(run for run, _ in valid))
            else:
                result = EvidenceDecision("unknown", unknown[0][1], tuple(run for run, _, _ in candidates))
        final = detect_dependency_change(root)
        if final.status != "risk" or final.state != detection.state:
            return EvidenceDecision("unknown", "state_changed")
        if local_environment_id() != control.environment_id:
            return EvidenceDecision("unknown", "environment_unverified")
        return result
    except _Unknown as exc:
        return EvidenceDecision("unknown", exc.reason)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, IndexError):
        return EvidenceDecision("unknown", "unverified")
