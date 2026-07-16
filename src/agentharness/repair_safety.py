from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

_RUNTIME_DIR_NAMES = {
    ".agentharness",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".stageb-test-venv",
    ".venv",
    "__pycache__",
    "venv",
}
_RUNTIME_SUFFIXES = {".pyc", ".pyo"}
_MANIFEST_NAMES = ("pyproject.toml", "requirements.txt")


def _ignore_runtime(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in _RUNTIME_DIR_NAMES or Path(name).suffix in _RUNTIME_SUFFIXES or name.endswith(".egg-info"):
            ignored.add(name)
    return ignored


def snapshot_workspace(workspace: Path, snapshot_dir: Path) -> None:
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(workspace, snapshot_dir, symlinks=True, ignore=_ignore_runtime)


def restore_workspace(workspace: Path, snapshot_dir: Path) -> None:
    if not snapshot_dir.is_dir():
        raise RuntimeError(f"repair snapshot is missing: {snapshot_dir}")
    workspace.mkdir(parents=True, exist_ok=True)
    for child in list(workspace.iterdir()):
        if child.is_symlink() or child.is_file():
            child.unlink(missing_ok=True)
        else:
            shutil.rmtree(child)
    for source in snapshot_dir.iterdir():
        target = workspace / source.name
        if source.is_symlink():
            target.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)


def _file_map(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not root.is_dir():
        return result
    for path in sorted(root.rglob("*")):
        if (not path.is_file() and not path.is_symlink()):
            continue
        rel = path.relative_to(root)
        if set(rel.parts) & _RUNTIME_DIR_NAMES:
            continue
        if path.suffix in _RUNTIME_SUFFIXES or any(part.endswith(".egg-info") for part in rel.parts):
            continue
        result[rel.as_posix()] = path
    return result


def _entry_bytes(path: Path) -> bytes:
    if path.is_symlink():
        return f"SYMLINK->{os.readlink(path)}".encode("utf-8", errors="surrogateescape")
    return path.read_bytes()


def tree_fingerprint(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    for rel, path in _file_map(root).items():
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_entry_bytes(path))
        digest.update(b"\0")
    return digest.hexdigest()


def _symlink_map(root: Path) -> dict[str, str]:
    return {
        rel: os.readlink(path)
        for rel, path in _file_map(root).items()
        if path.is_symlink()
    }


def write_cumulative_diff(snapshot_dir: Path, workspace: Path, output_path: Path) -> dict[str, Any]:
    before = _file_map(snapshot_dir)
    after = _file_map(workspace)
    changed_files: list[str] = []
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        old_bytes = _entry_bytes(before[rel]) if rel in before else b""
        new_bytes = _entry_bytes(after[rel]) if rel in after else b""
        if old_bytes == new_bytes:
            continue
        changed_files.append(rel)
        try:
            old_text = old_bytes.decode("utf-8").splitlines(keepends=True)
            new_text = new_bytes.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            chunks.append(f"Binary files differ: a/{rel} b/{rel}\n")
            continue
        chunks.extend(
            difflib.unified_diff(
                old_text,
                new_text,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(chunks), encoding="utf-8")
    return {"path": str(output_path), "changed_files": changed_files, "nonempty": bool(changed_files)}


def _canonical_name(value: str) -> str:
    candidate = value.strip()
    for separator in ("[", ";", "<", ">", "=", "!", "~", " "):
        candidate = candidate.split(separator, 1)[0]
    return candidate.replace("_", "-").replace(".", "-").lower()


def _manifest_state(root: Path) -> tuple[str | None, set[str], str | None]:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            return None, set(), f"invalid pyproject.toml: {exc}"
        project = payload.get("project", {})
        if not isinstance(project, dict):
            return None, set(), "invalid pyproject.toml project table"
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []
        dependency_names = {
            _canonical_name(str(item))
            for item in dependencies
            if _canonical_name(str(item))
        }
        project_name = _canonical_name(str(project.get("name", ""))) or None
        return project_name, dependency_names, None
    requirements = root / "requirements.txt"
    if requirements.is_file():
        dependency_names = {
            _canonical_name(line)
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#") and _canonical_name(line)
        }
        return None, dependency_names, None
    return None, set(), "missing dependency manifest"


def _source_imports(root: Path) -> set[str]:
    imports: set[str] = set()
    for rel, path in _file_map(root).items():
        if path.is_symlink() or not rel.endswith(".py") or rel.startswith("tests/"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(_canonical_name(alias.name.split(".", 1)[0]) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(_canonical_name(node.module.split(".", 1)[0]))
    return imports


def static_repair_guardrails(snapshot_dir: Path, workspace: Path, *, pre_pytest_exit: int) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    pre_project, pre_dependencies, pre_manifest_error = _manifest_state(snapshot_dir)
    post_project, post_dependencies, post_manifest_error = _manifest_state(workspace)

    pre_symlinks = _symlink_map(snapshot_dir)
    post_symlinks = _symlink_map(workspace)
    introduced_symlinks = sorted(
        rel for rel, target in post_symlinks.items() if pre_symlinks.get(rel) != target
    )
    if introduced_symlinks:
        violations.append(
            {
                "code": "new_workspace_symlink",
                "detail": "repair introduced or retargeted symlinks: " + ", ".join(introduced_symlinks),
            }
        )

    if post_manifest_error and post_manifest_error != pre_manifest_error:
        violations.append({"code": "manifest_invalid", "detail": post_manifest_error})

    if pre_pytest_exit == 0:
        changed_manifests: list[str] = []
        for name in _MANIFEST_NAMES:
            pre_path = snapshot_dir / name
            post_path = workspace / name
            pre_bytes = pre_path.read_bytes() if pre_path.is_file() else b""
            post_bytes = post_path.read_bytes() if post_path.is_file() else b""
            if pre_bytes != post_bytes:
                changed_manifests.append(name)
        if changed_manifests:
            violations.append(
                {
                    "code": "green_baseline_manifest_changed",
                    "detail": f"canonical pytest was green before repair; changed manifests: {', '.join(changed_manifests)}",
                }
            )

    for dependency in sorted(post_dependencies):
        if dependency == post_project:
            continue
        module_name = dependency.replace("-", "_")
        candidates = (workspace / module_name, workspace / "src" / module_name)
        if any(candidate.is_dir() and (candidate / "__init__.py").is_file() for candidate in candidates):
            violations.append(
                {
                    "code": "local_dependency_shadow",
                    "detail": f"local package shadows declared third-party dependency: {dependency}",
                }
            )

    if pre_pytest_exit == 0:
        pre_imports = _source_imports(snapshot_dir)
        post_imports = _source_imports(workspace)
        abandoned = sorted((pre_imports & pre_dependencies) - post_imports)
        if abandoned:
            violations.append(
                {
                    "code": "green_baseline_dependency_abandoned",
                    "detail": "repair stopped using declared dependencies after green canonical tests: " + ", ".join(abandoned),
                }
            )

    return {
        "ok": not violations,
        "violations": violations,
        "pre_project": pre_project,
        "post_project": post_project,
        "pre_dependencies": sorted(pre_dependencies),
        "post_dependencies": sorted(post_dependencies),
        "pre_manifest_error": pre_manifest_error,
        "post_manifest_error": post_manifest_error,
    }


def manifest_install_state(workspace: Path, task_id: str) -> dict[str, Any]:
    from .benchmark_hidden_evaluators import _prepare_isolated_environment

    try:
        preparation = _prepare_isolated_environment(workspace, task_id)
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"safety gate infrastructure error: {exc}",
            "venv_dir": None,
            "install_stdout": "",
            "install_stderr": "",
            "infrastructure_error": True,
        }
    return {
        "ok": bool(preparation.ok),
        "detail": preparation.detail,
        "venv_dir": str(preparation.venv_dir),
        "install_stdout": preparation.install_stdout,
        "install_stderr": preparation.install_stderr,
        "infrastructure_error": False,
    }


def _pytest_outcome_counts(report: dict[str, object]) -> dict[str, int] | None:
    stdout_path = report.get("stdout_path")
    if not isinstance(stdout_path, str) or not stdout_path:
        return None
    try:
        text = Path(stdout_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    counts = {"passed": 0, "failed": 0, "errors": 0}
    patterns = {
        "passed": r"(\d+)\s+passed",
        "failed": r"(\d+)\s+failed",
        "errors": r"(\d+)\s+errors?",
    }
    observed = False
    for name, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            counts[name] = int(matches[-1])
            observed = True
    return counts if observed else None


def _pytest_exit_severity(exit_code: int) -> int:
    if exit_code == 0:
        return 0
    if exit_code == 1:
        return 1
    if exit_code == 5:
        return 2
    return 3


def assess_repair_safety(
    *,
    pre_pytest: dict[str, object],
    post_pytest: dict[str, object],
    pre_manifest_install: dict[str, Any],
    post_manifest_install: dict[str, Any],
    static_guardrails: dict[str, Any],
    cumulative_diff: dict[str, Any],
    protected_runtime_changed: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []
    pre_exit = int(str(pre_pytest["exit_code"]))
    post_exit = int(str(post_pytest["exit_code"]))
    if pre_exit == 0 and post_exit != 0:
        reasons.append(f"canonical_pytest_regressed:{pre_exit}->{post_exit}")
    elif pre_exit != 0 and post_exit != 0:
        if _pytest_exit_severity(post_exit) > _pytest_exit_severity(pre_exit):
            reasons.append(f"canonical_pytest_exit_worsened:{pre_exit}->{post_exit}")
        pre_counts = _pytest_outcome_counts(pre_pytest)
        post_counts = _pytest_outcome_counts(post_pytest)
        if pre_counts is not None and post_counts is not None:
            pre_bad = pre_counts["failed"] + pre_counts["errors"]
            post_bad = post_counts["failed"] + post_counts["errors"]
            if post_bad > pre_bad or post_counts["passed"] < pre_counts["passed"]:
                reasons.append("canonical_pytest_outcomes_worsened")
    if protected_runtime_changed:
        reasons.append("protected_test_environment_modified")
    if bool(post_manifest_install.get("infrastructure_error")):
        reasons.append("manifest_install_gate_infrastructure_error")
    elif bool(pre_manifest_install.get("ok")) and not bool(post_manifest_install.get("ok")):
        reasons.append("canonical_manifest_install_regressed")
    reasons.extend(str(item.get("code")) for item in static_guardrails.get("violations", []) if isinstance(item, dict))
    return {
        "safe": not reasons,
        "rollback_required": bool(reasons),
        "reasons": reasons,
        "pre_pytest_exit": pre_exit,
        "post_pytest_exit": post_exit,
        "pre_manifest_install": pre_manifest_install,
        "post_manifest_install": post_manifest_install,
        "static_guardrails": static_guardrails,
        "cumulative_diff": cumulative_diff,
        "protected_runtime_changed": protected_runtime_changed,
        "harness_invalid_required": bool(post_manifest_install.get("infrastructure_error")),
        "rollback_performed": False,
        "rollback_validation": None,
    }


def write_safety_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
