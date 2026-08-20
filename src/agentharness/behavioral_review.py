from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .direct_check import (
    DEFAULT_IGNORED_NAMES,
    _git_changed_files,
    _is_safe_run_id,
    _new_run_id,
    _relative_to_or_none,
    _snapshot_workspace,
    _validate_artifact_dir,
)
from .models import ClaimResult, VerifyRunResult
from .reexecution import DEFAULT_ALLOWED_ENV_NAMES, ExecutionPolicy
from .verify import verify_run


SCHEMA_VERSION = "1.0"
_NODEID_PATTERN = re.compile(r"^[A-Za-z0-9_./:\[\],=+ -]+$")
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_SAFE_ID_LENGTH = 100


@dataclass(frozen=True)
class BehavioralCheckSpec:
    id: str
    behavior: str
    nodeid: str
    remediation: str


@dataclass(frozen=True)
class BehavioralReviewPlan:
    schema_version: str
    plan_id: str
    test_root: str
    checks: tuple[BehavioralCheckSpec, ...]


@dataclass(frozen=True)
class BehavioralFinding:
    check_id: str
    behavior: str
    status: str
    reason: str
    remediation: str
    evidence: tuple[str, ...]
    truth_source: str
    audit: dict[str, Any]

    @property
    def actionable(self) -> bool:
        return self.status == "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "behavior": self.behavior,
            "status": self.status,
            "actionable": self.actionable,
            "reason": self.reason,
            "remediation": self.remediation,
            "evidence": list(self.evidence),
            "truth_source": self.truth_source,
            "audit": self.audit,
        }


@dataclass
class BehavioralReviewResult:
    run_id: str
    plan_id: str
    plan_path: Path
    plan_sha256: str
    test_bundle_sha256: str
    workspace_sha256: str
    original_workspace: Path
    snapshot_workspace: Path
    artifact_dir: Path
    source_plan_path: Path
    run_path: Path
    derived_checks_path: Path
    verify_report_path: Path
    review_report_path: Path
    derived_commands: dict[str, str]
    changed_files: list[str]
    verification: VerifyRunResult
    findings: tuple[BehavioralFinding, ...]

    @property
    def ok(self) -> bool:
        return self.verification.ok and all(item.status == "passed" for item in self.findings)

    @property
    def summary(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "diagnostic": 0}
        for item in self.findings:
            counts[item.status] = counts.get(item.status, 0) + 1
        counts["actionable"] = sum(item.actionable for item in self.findings)
        return counts

    @property
    def isolation(self) -> dict[str, Any]:
        return {
            "mode": "workspace-copy",
            "review_tests_external_to_original_workspace": True,
            "command_cwd_is_snapshot": True,
            "original_workspace_write_protected": False,
            "network_isolated": False,
            "host_filesystem_isolated": False,
            "warning": (
                "Trusted review tests ran inside a persistent workspace copy, not a security sandbox. "
                "Relative writes stay in the copy, but the original workspace and host filesystem are not security-isolated."
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": self.ok,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "plan_path": str(self.plan_path),
            "plan_sha256": self.plan_sha256,
            "test_bundle_sha256": self.test_bundle_sha256,
            "workspace_sha256": self.workspace_sha256,
            "original_workspace": str(self.original_workspace),
            "snapshot_workspace": str(self.snapshot_workspace),
            "artifact_dir": str(self.artifact_dir),
            "source_plan_path": str(self.source_plan_path),
            "run_path": str(self.run_path),
            "derived_checks_path": str(self.derived_checks_path),
            "verify_report_path": str(self.verify_report_path),
            "review_report_path": str(self.review_report_path),
            "derived_commands": self.derived_commands,
            "changed_files": self.changed_files,
            "summary": self.summary,
            "findings": [item.to_dict() for item in self.findings],
            "actionable_findings": [item.to_dict() for item in self.findings if item.actionable],
            "isolation": self.isolation,
            "verification": self.verification.to_dict(),
        }


def _required_string(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _load_behavioral_review_plan_bytes(path: str | Path) -> tuple[BehavioralReviewPlan, bytes]:
    plan_path = Path(path).resolve()
    if not plan_path.is_file():
        raise ValueError(f"Review plan does not exist or is not a file: {plan_path}")
    plan_bytes = plan_path.read_bytes()
    try:
        payload = json.loads(plan_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Review plan is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Review plan root must be a JSON object")

    schema_version = _required_string(payload, "schema_version", "plan")
    plan_id = _required_string(payload, "plan_id", "plan")
    test_root = _required_string(payload, "test_root", "plan")
    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ValueError("plan.checks must be a non-empty array")

    checks: list[BehavioralCheckSpec] = []
    for index, raw_check in enumerate(raw_checks):
        if not isinstance(raw_check, dict):
            raise ValueError(f"plan.checks[{index}] must be an object")
        context = f"plan.checks[{index}]"
        checks.append(
            BehavioralCheckSpec(
                id=_required_string(raw_check, "id", context),
                behavior=_required_string(raw_check, "behavior", context),
                nodeid=_required_string(raw_check, "nodeid", context),
                remediation=_required_string(raw_check, "remediation", context),
            )
        )
    return (
        BehavioralReviewPlan(
            schema_version=schema_version,
            plan_id=plan_id,
            test_root=test_root,
            checks=tuple(checks),
        ),
        plan_bytes,
    )


def load_behavioral_review_plan(path: str | Path) -> BehavioralReviewPlan:
    plan, _ = _load_behavioral_review_plan_bytes(path)
    return plan


def _iter_symlinks(root: Path) -> list[Path]:
    links: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in [*dirnames, *filenames]:
            candidate = directory_path / name
            if candidate.is_symlink():
                links.append(candidate)
    return links


def _nodeid_test_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def validate_behavioral_review_plan(
    plan: BehavioralReviewPlan,
    plan_path: str | Path,
    workspace: str | Path,
) -> Path:
    resolved_plan_path = Path(plan_path).resolve()
    workspace_root = Path(workspace).resolve()
    if plan.schema_version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported review plan schema_version: {plan.schema_version}")
    if (
        not _SAFE_ID_PATTERN.fullmatch(plan.plan_id)
        or plan.plan_id in {".", ".."}
        or len(plan.plan_id) > _MAX_SAFE_ID_LENGTH
    ):
        raise ValueError("plan.plan_id must be a path-safe identifier of at most 100 characters")
    if _relative_to_or_none(resolved_plan_path, workspace_root) is not None:
        raise ValueError("Review plan must be external to the workspace under review")

    test_root_value = Path(plan.test_root)
    if test_root_value.is_absolute() or ".." in test_root_value.parts:
        raise ValueError("plan.test_root must be a safe path relative to the review plan")
    test_root = (resolved_plan_path.parent / test_root_value).resolve()
    if not test_root.is_dir():
        raise ValueError(f"Review test_root does not exist or is not a directory: {test_root}")
    if _relative_to_or_none(test_root, workspace_root) is not None:
        raise ValueError("Review tests must be external to the workspace under review")
    if _relative_to_or_none(workspace_root, test_root) is not None:
        raise ValueError("Review test_root must not contain the workspace under review")
    links = _iter_symlinks(test_root)
    if links:
        rendered = ", ".join(str(item.relative_to(test_root)) for item in links[:5])
        raise ValueError(f"Review test bundle must not contain symlinks: {rendered}")

    ids: set[str] = set()
    nodeids: set[str] = set()
    for check in plan.checks:
        if (
            not _SAFE_ID_PATTERN.fullmatch(check.id)
            or check.id in {".", ".."}
            or len(check.id) > _MAX_SAFE_ID_LENGTH
        ):
            raise ValueError(f"Review check id is not path-safe: {check.id}")
        if check.id in ids:
            raise ValueError(f"Duplicate review check id: {check.id}")
        ids.add(check.id)
        if check.nodeid in nodeids:
            raise ValueError(f"Duplicate review check nodeid: {check.nodeid}")
        nodeids.add(check.nodeid)
        if "::" not in check.nodeid:
            raise ValueError(f"Review check nodeid must select one explicit test: {check.nodeid}")
        if not _NODEID_PATTERN.fullmatch(check.nodeid) or any(char in check.nodeid for char in ("\n", "\r", "`", "$", ";")):
            raise ValueError(f"Review check nodeid contains unsupported characters: {check.nodeid}")
        node_path = Path(_nodeid_test_file(check.nodeid))
        if node_path.is_absolute() or ".." in node_path.parts or not node_path.name.endswith(".py"):
            raise ValueError(f"Review check nodeid must reference a safe relative Python test file: {check.nodeid}")
        test_file = (test_root / node_path).resolve()
        if _relative_to_or_none(test_file, test_root) is None or not test_file.is_file():
            raise ValueError(f"Review check nodeid test file does not exist in test_root: {check.nodeid}")
    return test_root


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"Expected a real directory: {path}")
    return info.st_dev, info.st_ino


def _require_directory_identity(path: Path, expected: tuple[int, int]) -> None:
    if _directory_identity(path) != expected:
        raise ValueError(f"Artifact directory identity changed during review: {path}")


def _write_new_file_no_follow(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _write_new_json_no_follow(path: Path, payload: dict[str, Any]) -> None:
    _write_new_file_no_follow(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


BEHAVIORAL_TEST_IGNORED_NAMES = frozenset({"__pycache__", ".pytest_cache"})


def _fingerprint_tree(
    root: Path,
    *,
    excluded_top_level: tuple[str, ...] = (),
    ignored_names: frozenset[str] = frozenset(),
) -> str:
    """Hash the exact tree surface expected to be copied into execution."""
    digest = hashlib.sha256()
    entries = sorted(
        path
        for path in root.rglob("*")
        if (
            path.relative_to(root).parts
            and path.relative_to(root).parts[0] not in excluded_top_level
            and not any(part in ignored_names for part in path.relative_to(root).parts)
        )
    )
    for path in entries:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        stat_result = path.lstat()
        digest.update((stat_result.st_mode & 0o7777).to_bytes(4, "big"))
        if path.is_symlink():
            kind = b"symlink"
            content = os.readlink(path).encode("utf-8", errors="surrogateescape")
        elif path.is_dir():
            kind = b"directory"
            content = b""
        elif path.is_file():
            kind = b"file"
            content = path.read_bytes()
        else:
            kind = b"other"
            content = b""
        digest.update(len(kind).to_bytes(4, "big"))
        digest.update(kind)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _materialize_review_tests(test_root: Path, snapshot_workspace: Path, run_id: str) -> Path:
    destination = snapshot_workspace / ".agentharness" / "review-tests" / run_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(test_root, destination, symlinks=True)
    staged_links = _iter_symlinks(destination)
    if staged_links:
        raise ValueError("Staged review test bundle unexpectedly contains symlinks")
    return destination


def _derive_pytest_command(
    snapshot_workspace: Path,
    test_destination: Path,
    nodeid: str,
    test_bundle_sha256: str,
) -> str:
    runner_path = (Path(__file__).resolve().parent / "behavioral_pytest_runner.py").resolve()
    return shlex.join(
        [
            Path(sys.executable).name,
            "-P",
            str(runner_path),
            "--workspace",
            str(snapshot_workspace),
            "--test-root",
            str(test_destination),
            "--nodeid",
            nodeid,
            "--test-bundle-sha256",
            test_bundle_sha256,
        ]
    )


def _build_run_payload(
    *,
    run_id: str,
    snapshot_workspace: Path,
    plan: BehavioralReviewPlan,
    commands: dict[str, str],
    working_dirs: dict[str, str],
    changed_files: list[str],
    plan_sha256: str,
    test_bundle_sha256: str,
    workspace_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "workspace": str(snapshot_workspace),
        "task": f"Independent behavioral review plan: {plan.plan_id}",
        "execution": {
            "mode": "per-check-workspace-copy",
            "review_authority": "external-plan",
            "plan_sha256": plan_sha256,
            "test_bundle_sha256": test_bundle_sha256,
            "workspace_sha256": workspace_sha256,
            "network_isolated": False,
            "host_filesystem_isolated": False,
        },
        "artifacts": {
            "changed_files": changed_files,
            "commands": [
                {
                    "cmd": commands[check.id],
                    "exit_code": 0,
                    "working_dir": working_dirs[check.id],
                    "environment": {},
                }
                for check in plan.checks
            ],
            "outputs": [],
        },
    }


def _build_derived_checks_payload(
    *,
    run_id: str,
    plan: BehavioralReviewPlan,
    commands: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "authority": "agentharness-external-review-plan",
        "plan_id": plan.plan_id,
        "claims": [
            {
                "id": check.id,
                "type": "tests_executed",
                "statement": check.behavior,
                "expected": {"required_commands": [commands[check.id]]},
            }
            for check in plan.checks
        ],
    }


def _structured_behavioral_result(result: ClaimResult) -> dict[str, Any] | None:
    commands = result.audit.get("commands", []) if isinstance(result.audit, dict) else []
    if len(commands) != 1 or not isinstance(commands[0], dict):
        return None
    reexecution = commands[0].get("reexecution", {})
    if not isinstance(reexecution, dict):
        return None
    stdout_path = reexecution.get("stdout_path")
    if not isinstance(stdout_path, str) or not stdout_path:
        return None
    try:
        lines = Path(stdout_path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    prefix = "AGENTHARNESS_BEHAVIORAL_RESULT="
    records = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(records) != 1:
        return None
    try:
        payload = json.loads(records[0])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _finding_from_claim(check: BehavioralCheckSpec, result: ClaimResult) -> BehavioralFinding:
    structured = _structured_behavioral_result(result)
    structured_status = structured.get("status") if structured else None
    if structured_status == "passed" and result.status == "supported":
        status = "passed"
    elif structured_status == "failed":
        status = "failed"
    else:
        status = "diagnostic"
    if structured is None:
        reason = "Trusted runner did not produce exactly one valid structured result"
    else:
        reason = str(structured.get("reason") or result.reason)
    audit = dict(result.audit)
    audit["behavioral_result"] = structured
    return BehavioralFinding(
        check_id=check.id,
        behavior=check.behavior,
        status=status,
        reason=reason,
        remediation=check.remediation,
        evidence=tuple(result.evidence),
        truth_source=result.truth_source if structured is not None else "none",
        audit=audit,
    )


def _findings_from_verification(
    plan: BehavioralReviewPlan,
    verification: VerifyRunResult,
) -> tuple[BehavioralFinding, ...]:
    by_id = {item.claim_id: item for item in verification.results}
    findings: list[BehavioralFinding] = []
    for check in plan.checks:
        result = by_id.get(check.id)
        if result is None:
            findings.append(
                BehavioralFinding(
                    check_id=check.id,
                    behavior=check.behavior,
                    status="diagnostic",
                    reason="No verification result was produced for this review check",
                    remediation=check.remediation,
                    evidence=(),
                    truth_source="none",
                    audit={},
                )
            )
        else:
            findings.append(_finding_from_claim(check, result))
    return tuple(findings)


def review_workspace(
    workspace: str | Path,
    plan_path: str | Path,
    *,
    run_id: str | None = None,
    output_dir: str | Path | None = None,
    timeout_seconds: int = 60,
) -> BehavioralReviewResult:
    original_workspace = Path(workspace).resolve()
    if not original_workspace.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {original_workspace}")
    if timeout_seconds < 1:
        raise ValueError("Timeout must be at least one second")

    resolved_plan_path = Path(plan_path).resolve()
    plan, plan_bytes = _load_behavioral_review_plan_bytes(resolved_plan_path)
    test_root = validate_behavioral_review_plan(plan, resolved_plan_path, original_workspace)

    resolved_run_id = (run_id or _new_run_id().replace("check-", "review-", 1)).strip()
    if not _is_safe_run_id(resolved_run_id):
        raise ValueError("Run id must be a non-empty path-safe name without separators")
    if output_dir is None:
        artifact_dir = original_workspace / ".agentharness" / "runs" / resolved_run_id
    else:
        artifact_dir = Path(output_dir).resolve()
    _validate_artifact_dir(original_workspace, artifact_dir)
    if _relative_to_or_none(artifact_dir, test_root) is not None or _relative_to_or_none(test_root, artifact_dir) is not None:
        raise ValueError("Artifact directory and trusted review test_root must not overlap")
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise FileExistsError(f"Artifact directory already exists and is not empty: {artifact_dir}")

    plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    changed_files = _git_changed_files(original_workspace)
    workspace_sha256 = _fingerprint_tree(
        original_workspace, ignored_names=DEFAULT_IGNORED_NAMES
    )
    test_bundle_sha256 = _fingerprint_tree(test_root, ignored_names=BEHAVIORAL_TEST_IGNORED_NAMES)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_identity = _directory_identity(artifact_dir)
    snapshot_workspace = artifact_dir / "execution"
    snapshot_workspace.mkdir()
    snapshot_identity = _directory_identity(snapshot_workspace)

    commands: dict[str, str] = {}
    working_dirs: dict[str, str] = {}
    verification_results: list[ClaimResult] = []
    child_verifications: list[VerifyRunResult] = []
    runner_path = str((Path(__file__).resolve().parent / "behavioral_pytest_runner.py").resolve())
    execution_policy = ExecutionPolicy(
        mode="auto",
        timeout_seconds=timeout_seconds,
        working_dir_mode="workspace-relative",
        allowed_command_prefixes=(("python", "-P", runner_path),),
        allowed_env_names=tuple(name for name in DEFAULT_ALLOWED_ENV_NAMES if name != "PYTHONPATH"),
    )

    # Stage and execute one check at a time. A previous check can create sibling
    # paths because workspace-copy mode is not a sandbox, so delete any such path
    # and materialize the next copy just-in-time. Recheck both immutable inputs
    # before and after every check; mutation fails closed instead of yielding a
    # false pass for a later check.
    internal_root = artifact_dir / "per-check-verification"
    internal_root.mkdir()
    internal_identity = _directory_identity(internal_root)
    for check in plan.checks:
        _require_directory_identity(artifact_dir, artifact_identity)
        _require_directory_identity(snapshot_workspace, snapshot_identity)
        _require_directory_identity(internal_root, internal_identity)
        if _fingerprint_tree(original_workspace, ignored_names=DEFAULT_IGNORED_NAMES) != workspace_sha256:
            raise ValueError("Original workspace changed during behavioral review")
        if _fingerprint_tree(test_root, ignored_names=BEHAVIORAL_TEST_IGNORED_NAMES) != test_bundle_sha256:
            raise ValueError("Trusted review test bundle changed during behavioral review")

        check_root = snapshot_workspace / check.id
        if check_root.exists() or check_root.is_symlink():
            if check_root.is_dir() and not check_root.is_symlink():
                shutil.rmtree(check_root)
            else:
                check_root.unlink()
        check_workspace = check_root / "workspace"
        _snapshot_workspace(original_workspace, check_workspace)
        staged_workspace_hash = _fingerprint_tree(
            check_workspace, ignored_names=DEFAULT_IGNORED_NAMES
        )
        if staged_workspace_hash != workspace_sha256:
            raise ValueError("Per-check workspace copy does not match the reviewed workspace")
        staged_tests = _materialize_review_tests(test_root, check_workspace, resolved_run_id)
        if _fingerprint_tree(staged_tests, ignored_names=BEHAVIORAL_TEST_IGNORED_NAMES) != test_bundle_sha256:
            raise ValueError("Staged trusted review test bundle does not match its source")

        command = _derive_pytest_command(
            check_workspace, staged_tests, check.nodeid, test_bundle_sha256
        )
        commands[check.id] = command
        working_dirs[check.id] = check_workspace.relative_to(snapshot_workspace).as_posix()
        child_plan = BehavioralReviewPlan(
            schema_version=plan.schema_version,
            plan_id=plan.plan_id,
            test_root=plan.test_root,
            checks=(check,),
        )
        child_dir = internal_root / check.id
        child_dir.mkdir()
        child_identity = _directory_identity(child_dir)
        child_run_path = child_dir / "run.json"
        child_checks_path = child_dir / "claims.json"
        child_report_path = child_dir / "verify-report.json"
        child_run = _build_run_payload(
            run_id=resolved_run_id,
            snapshot_workspace=snapshot_workspace,
            plan=child_plan,
            commands={check.id: command},
            working_dirs={check.id: working_dirs[check.id]},
            changed_files=changed_files,
            plan_sha256=plan_sha256,
            test_bundle_sha256=test_bundle_sha256,
            workspace_sha256=workspace_sha256,
        )
        child_claims = _build_derived_checks_payload(
            run_id=resolved_run_id,
            plan=child_plan,
            commands={check.id: command},
        )
        _write_new_json_no_follow(child_run_path, child_run)
        _write_new_json_no_follow(child_checks_path, child_claims)
        child_run_sha256 = _sha256_file(child_run_path)
        child_claims_sha256 = _sha256_file(child_checks_path)
        child_verification = verify_run(
            child_run_path,
            child_checks_path,
            write_report=False,
            execution_policy=execution_policy,
        )
        _require_directory_identity(artifact_dir, artifact_identity)
        _require_directory_identity(snapshot_workspace, snapshot_identity)
        _require_directory_identity(internal_root, internal_identity)
        _require_directory_identity(child_dir, child_identity)
        if _sha256_file(child_run_path) != child_run_sha256 or _sha256_file(child_checks_path) != child_claims_sha256:
            raise ValueError("Per-check verification inputs changed during execution")
        if _fingerprint_tree(staged_tests, ignored_names=BEHAVIORAL_TEST_IGNORED_NAMES) != test_bundle_sha256:
            raise ValueError("Staged trusted review test bundle changed during execution")
        child_verification.report_written = str(child_report_path)
        _write_new_json_no_follow(child_report_path, child_verification.to_dict())
        child_verifications.append(child_verification)
        verification_results.extend(child_verification.results)

        if _fingerprint_tree(original_workspace, ignored_names=DEFAULT_IGNORED_NAMES) != workspace_sha256:
            raise ValueError("Original workspace changed during behavioral review")
        if _fingerprint_tree(test_root, ignored_names=BEHAVIORAL_TEST_IGNORED_NAMES) != test_bundle_sha256:
            raise ValueError("Trusted review test bundle changed during behavioral review")

    run_path = artifact_dir / "run.json"
    derived_checks_path = artifact_dir / "derived-checks.json"
    verify_report_path = artifact_dir / "derived-verify-report.json"
    review_report_path = artifact_dir / "behavioral-review-report.json"
    source_plan_path = artifact_dir / "source-review-plan.json"

    _require_directory_identity(artifact_dir, artifact_identity)
    _require_directory_identity(snapshot_workspace, snapshot_identity)
    _require_directory_identity(internal_root, internal_identity)
    _write_new_file_no_follow(source_plan_path, plan_bytes)
    run_payload = _build_run_payload(
        run_id=resolved_run_id,
        snapshot_workspace=snapshot_workspace,
        plan=plan,
        commands=commands,
        working_dirs=working_dirs,
        changed_files=changed_files,
        plan_sha256=plan_sha256,
        test_bundle_sha256=test_bundle_sha256,
        workspace_sha256=workspace_sha256,
    )
    checks_payload = _build_derived_checks_payload(run_id=resolved_run_id, plan=plan, commands=commands)
    _write_new_json_no_follow(run_path, run_payload)
    _write_new_json_no_follow(derived_checks_path, checks_payload)

    first_verification = child_verifications[0]
    verification = VerifyRunResult(
        run_id=resolved_run_id,
        run_path=run_path,
        claims_path=derived_checks_path,
        results=verification_results,
        run_sha256=_sha256_file(run_path),
        claims_sha256=_sha256_file(derived_checks_path),
        tool_version=first_verification.tool_version,
        evaluated_at=first_verification.evaluated_at,
        notes=[note for item in child_verifications for note in item.notes],
        gating_errors=[error for item in child_verifications for error in item.gating_errors],
        report_written=str(verify_report_path),
        audit_trail={
            "execution": "sequential-just-in-time-workspace-copies",
            "per_check_reports": [item.report_written for item in child_verifications],
        },
    )
    _write_new_json_no_follow(verify_report_path, verification.to_dict())
    findings = _findings_from_verification(plan, verification)
    result = BehavioralReviewResult(
        run_id=resolved_run_id,
        plan_id=plan.plan_id,
        plan_path=resolved_plan_path,
        plan_sha256=plan_sha256,
        test_bundle_sha256=test_bundle_sha256,
        workspace_sha256=workspace_sha256,
        original_workspace=original_workspace,
        snapshot_workspace=snapshot_workspace,
        artifact_dir=artifact_dir,
        source_plan_path=source_plan_path,
        run_path=run_path,
        derived_checks_path=derived_checks_path,
        verify_report_path=verify_report_path,
        review_report_path=review_report_path,
        derived_commands=commands,
        changed_files=changed_files,
        verification=verification,
        findings=findings,
    )
    _write_new_json_no_follow(review_report_path, result.to_dict())
    return result
