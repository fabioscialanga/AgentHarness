"""M3 CP3-A: deterministic PEP 621 dependency detection, independent of hosts.

This module does not inspect evidence, execute tests, or emit host messages.
Unsupported syntax and unreliable filesystem/Git state produce abstention.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


RULE_ID = "DEP-PEP621-V0"
STATE_VERSION = "m3-state-v0"
MAX_PYPROJECT_BYTES = 1024 * 1024
MAX_DIFF_BYTES = 1024 * 1024
GIT_TIMEOUT_SECONDS = 1.0
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_REQUIREMENT = re.compile(rf"\s*({_NAME})(?:\[([^\]]+)\])?\s*(.*?)\s*\Z")
_CLAUSE = re.compile(r"(==|!=|<=|>=|<|>)\s*([0-9]+(?:\.[0-9]+)*)\Z")
_NORMALIZE = re.compile(r"[-_.]+")


class _Abstain(Exception):
    def __init__(self, reason: str):
        self.reason = reason


@dataclass(frozen=True)
class StateIdentity:
    version: str
    base_commit: str
    target_commit: str
    kind: Literal["working-tree", "committed"]
    diff_digest: str
    state_id: str


@dataclass(frozen=True)
class RiskCandidate:
    rule_id: str
    scope: tuple[str, ...]
    change_id: str
    description: str


@dataclass(frozen=True)
class DetectionResult:
    status: Literal["risk", "no_change", "abstain"]
    state: StateIdentity | None = None
    candidate: RiskCandidate | None = None
    reason: str | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _frame(tag: str, data: bytes) -> bytes:
    return tag.encode("ascii") + b"\0" + len(data).to_bytes(8, "big") + data


def _git(root: Path, *args: str, max_bytes: int = MAX_DIFF_BYTES) -> bytes:
    """Read bounded Git output through a temporary file and a hard timeout."""
    environment = os.environ.copy()
    environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"})
    with tempfile.TemporaryFile() as output:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), *args], stdout=output,
                stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT_SECONDS,
                check=False, env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise _Abstain("git_timeout") from exc
        except OSError as exc:
            raise _Abstain("git_unavailable") from exc
        if completed.returncode != 0:
            raise _Abstain("git_invalid")
        if output.tell() > max_bytes:
            raise _Abstain("git_output_budget")
        output.seek(0)
        return output.read(max_bytes + 1)


def _safe_file(root: Path) -> bytes | None:
    path = root / "pyproject.toml"
    try:
        if path.is_symlink():
            raise _Abstain("symlink")
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _Abstain("file_unreadable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise _Abstain("file_not_regular")
    if info.st_size > MAX_PYPROJECT_BYTES:
        raise _Abstain("file_budget")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise _Abstain("file_not_regular")
            data = handle.read(MAX_PYPROJECT_BYTES + 1)
    except OSError as exc:
        raise _Abstain("file_unreadable") from exc
    if len(data) > MAX_PYPROJECT_BYTES:
        raise _Abstain("file_budget")
    return data


def _normal_name(value: str) -> str:
    if not re.fullmatch(_NAME, value, flags=re.ASCII):
        raise _Abstain("unsupported_requirement")
    return _NORMALIZE.sub("-", value).lower()


def _normal_version(value: str) -> str:
    parts = [str(int(piece)) for piece in value.split(".")]
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def normalize_requirement(value: str) -> tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Normalize only the explicitly approved PEP 508 subset."""
    if not isinstance(value, str):
        raise ValueError("requirement must be a string")
    match = _REQUIREMENT.fullmatch(value)
    if not match:
        raise ValueError("unsupported PEP 508 syntax")
    name, raw_extras, raw_clauses = match.groups()
    try:
        normalized_name = _normal_name(name)
        extras = tuple(sorted({_normal_name(piece.strip()) for piece in raw_extras.split(",")})) if raw_extras else ()
    except _Abstain as exc:
        raise ValueError(exc.reason) from exc
    clauses: list[tuple[str, str]] = []
    if raw_clauses:
        for raw in raw_clauses.split(","):
            clause = _CLAUSE.fullmatch(raw.strip())
            if not clause:
                raise ValueError("unsupported PEP 508 syntax")
            operator, version = clause.groups()
            clauses.append((operator, _normal_version(version)))
    return normalized_name, extras, tuple(sorted(set(clauses)))


def _project(data: bytes | None) -> dict[str, dict[str, tuple[tuple | str, ...]]]:
    if data is None:
        return {"runtime": {}, "optional": {}}
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise _Abstain("toml_invalid") from exc
    project = parsed.get("project", {})
    if not isinstance(project, dict):
        raise _Abstain("project_invalid")
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list) or any(not isinstance(item, str) for item in dynamic):
        raise _Abstain("project_invalid")
    if {"dependencies", "optional-dependencies"}.intersection(dynamic):
        raise _Abstain("dynamic_dependencies")

    def entries(raw: object) -> tuple[tuple | str, ...]:
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise _Abstain("dependency_shape")
        normalized: list[tuple | str] = []
        seen: dict[tuple[str, tuple[str, ...]], tuple[tuple[str, str], ...]] = {}
        for item in raw:
            try:
                requirement = normalize_requirement(item)
            except ValueError:
                normalized.append("opaque:" + item)
                continue
            identity = requirement[:2]
            prior = seen.get(identity)
            if prior is not None and prior != requirement[2]:
                raise _Abstain("duplicate_ambiguous")
            seen[identity] = requirement[2]
            normalized.append(requirement)
        return tuple(sorted(set(normalized), key=repr))

    runtime = entries(project.get("dependencies", []))
    raw_optional = project.get("optional-dependencies", {})
    if not isinstance(raw_optional, dict):
        raise _Abstain("dependency_shape")
    optional: dict[str, tuple[tuple | str, ...]] = {}
    for group, raw in raw_optional.items():
        try:
            normalized_group = _normal_name(group)
        except _Abstain as exc:
            raise _Abstain("optional_group_invalid") from exc
        if normalized_group in optional:
            raise _Abstain("optional_group_ambiguous")
        optional[normalized_group] = entries(raw)
    return {"runtime": {"": runtime}, "optional": optional}


def _compare(base: dict, target: dict) -> tuple[bool, str | None]:
    changed: list[str] = []
    for section in ("runtime", "optional"):
        before = base[section]
        after = target[section]
        for group in sorted(set(before) | set(after)):
            left = before.get(group, ())
            right = after.get(group, ())
            if left == right and (section == "runtime" or (group in before) == (group in after)):
                continue
            left_opaque = {item for item in left if isinstance(item, str)}
            right_opaque = {item for item in right if isinstance(item, str)}
            if left_opaque != right_opaque:
                raise _Abstain("unsupported_requirement_changed")
            changed.append("runtime" if section == "runtime" else f"optional:{group}")
    return bool(changed), ", ".join(changed) if changed else None


def _commit_file(root: Path, commit: str) -> bytes | None:
    try:
        listing = _git(root, "ls-tree", "-z", commit, "--", "pyproject.toml", max_bytes=256)
    except _Abstain as exc:
        if exc.reason == "git_invalid":
            return None
        raise
    if not listing:
        return None
    if not listing.endswith(b"\tpyproject.toml\0"):
        raise _Abstain("git_invalid")
    mode = listing.split(b" ", 1)[0]
    if mode not in {b"100644", b"100755"}:
        raise _Abstain("file_not_regular")
    return _git(root, "show", f"{commit}:pyproject.toml", max_bytes=MAX_PYPROJECT_BYTES)


def _state(root: Path, base_commit: str | None, target_commit: str | None) -> tuple[StateIdentity, bytes | None, bytes | None, bool]:
    top = _git(root, "rev-parse", "--show-toplevel", max_bytes=4096).decode("utf-8", "strict").strip()
    if Path(top).resolve() != root:
        raise _Abstain("project_not_git_root")
    head = _git(root, "rev-parse", "HEAD", max_bytes=64).decode("ascii").strip()
    if not _SHA.fullmatch(head):
        raise _Abstain("git_invalid")
    if base_commit is None and target_commit is None:
        kind: Literal["working-tree", "committed"] = "working-tree"
        base = target = head
        before = _commit_file(root, head)
        after = _safe_file(root)
        staged = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--binary", "--cached", "HEAD")
        unstaged = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--binary")
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", "pyproject.toml", max_bytes=4096)
        if untracked and untracked != b"pyproject.toml\0":
            raise _Abstain("untracked_invalid")
        payload = _frame("staged", staged) + _frame("unstaged", unstaged)
        has_changes = bool(staged or unstaged or untracked)
        if untracked:
            if after is None:
                raise _Abstain("untracked_unreadable")
            payload += _frame("untracked-path", b"pyproject.toml") + _frame("untracked-regular", after)
        # Include the current file even when local Git flags or ignore rules
        # suppress a diff. Its content must never reuse another state's ID.
        payload += _frame("pyproject-present", b"1" if after is not None else b"0")
        if after is not None:
            payload += _frame("pyproject-sha256", _sha(after).encode("ascii"))
    else:
        if base_commit is None or target_commit is None:
            raise _Abstain("explicit_range_required")
        if not _SHA.fullmatch(base_commit) or not _SHA.fullmatch(target_commit):
            raise _Abstain("commit_invalid")
        kind = "committed"
        base, target = base_commit, target_commit
        before = _commit_file(root, base)
        after = _commit_file(root, target)
        patch = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--binary", base, target)
        has_changes = bool(patch)
        payload = _frame("committed-diff", patch)
        payload += _frame("pyproject-present", b"1" if after is not None else b"0")
        if after is not None:
            payload += _frame("pyproject-sha256", _sha(after).encode("ascii"))
    if len(payload) > MAX_DIFF_BYTES:
        raise _Abstain("diff_budget")
    digest = _sha(_frame(STATE_VERSION, payload))
    identity = _sha(_frame(STATE_VERSION, base.encode()) + _frame("target", target.encode()) + _frame("diff", digest.encode()))
    return StateIdentity(STATE_VERSION, base, target, kind, digest, identity), before, after, has_changes


def detect_dependency_change(
    project: str | Path, *, base_commit: str | None = None, target_commit: str | None = None,
) -> DetectionResult:
    """Detect material DEP changes, returning abstention on unreliable input.

    A committed range must be supplied explicitly as both full commit SHAs.
    No range on a clean HEAD is indeterminate: earlier commits are not inferred.
    """
    try:
        input_path = Path(project)
        if input_path.is_symlink():
            raise _Abstain("project_symlink")
        root = input_path.resolve(strict=True)
        if not root.is_dir():
            raise _Abstain("project_invalid")
        state, before, after, has_changes = _state(root, base_commit, target_commit)
        if state.kind == "working-tree" and before == after and not has_changes:
            # A clean HEAD cannot identify an earlier committed change without
            # an explicit base, even though it has no working-tree DEP change.
            return DetectionResult("abstain", state=state, reason="committed_base_unspecified")
        left = _project(before)
        right = _project(after)
        changed, description = _compare(left, right)
        if not changed:
            return DetectionResult("no_change", state=state)
        change_id = _sha(_frame(RULE_ID, state.state_id.encode()) + _frame("scope", b"pyproject.toml"))
        return DetectionResult(
            "risk", state=state,
            candidate=RiskCandidate(RULE_ID, ("pyproject.toml",), change_id,
                                    f"PEP 621 dependencies changed ({description})"),
        )
    except _Abstain as exc:
        return DetectionResult("abstain", reason=exc.reason)
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return DetectionResult("abstain", reason="state_unavailable")
