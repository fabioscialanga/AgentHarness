"""Offline CP3-D preflight experiment; never imported by a host adapter."""

from __future__ import annotations

import json
import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentharness import dep_evidence, risk_dep


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)


def _preflight_no_risk(root: Path) -> bool:
    """Conservative working-tree fast path: any uncertainty uses full detection."""
    try:
        if root.is_symlink() or not root.is_dir():
            return False
        revision = risk_dep._git(root, "rev-parse", "--show-toplevel", "HEAD", max_bytes=4160).decode().splitlines()
        if len(revision) != 2 or Path(revision[0]).resolve() != root or not risk_dep._SHA.fullmatch(revision[1]):
            return False
        first = risk_dep._safe_file(root)
        if first is None:
            return False
        baseline = risk_dep._git(root, "show", f"{revision[1]}:pyproject.toml",
                                 max_bytes=risk_dep.MAX_PYPROJECT_BYTES)
        if first != baseline:
            changed, _ = risk_dep._compare(risk_dep._project(baseline), risk_dep._project(first))
            if changed:
                return False
        final = risk_dep._git(root, "rev-parse", "HEAD", max_bytes=64).decode().strip()
        return final == revision[1] and risk_dep._safe_file(root) == first
    except (OSError, UnicodeError, ValueError, RuntimeError, risk_dep._Abstain):
        return False


def evaluate(root: Path, control: dep_evidence.ApprovedDepControl | None = None, *, enabled: bool,
             diagnostic: dict[str, str] | None = None) -> str:
    """Explicit benchmark-only orchestrator; never executes tests or host hooks."""
    if not enabled:
        return "disabled"
    if _preflight_no_risk(root):
        return "no_dep_risk"
    detection = risk_dep.detect_dependency_change(root)
    if diagnostic is not None:
        diagnostic["detection_status"] = detection.status
        diagnostic["detection_reason"] = detection.reason or ""
    if detection.status != "risk":
        return detection.status
    if control is None:
        control = dep_evidence.ApprovedDepControl(root, dep_evidence.local_environment_id())
    return dep_evidence.match_dep_evidence(root, detection, control).status


def _repo(root: Path, name: str, changed: str | None) -> tuple[Path, dep_evidence.ApprovedDepControl]:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Synthetic")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitignore").write_text(".agentharness/\n.pytest_cache/\n__pycache__/\n", encoding="utf-8")
    project = repo / "pyproject.toml"
    project.write_text('[project]\nname="sample"\ndependencies=["My_Pkg>=1"]\n', encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests/test_dep.py").write_text("def test_dep():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    if changed is not None:
        project.write_text(changed, encoding="utf-8")
    return repo, dep_evidence.ApprovedDepControl(repo, dep_evidence.local_environment_id())


def _summary(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    return round(statistics.median(ordered), 3), round(ordered[27], 3)


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    equivalent = '[project]\nname="sample"\ndependencies=["my-pkg>=1.0"]\n'
    risk = '[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n'
    with tempfile.TemporaryDirectory(prefix="m3-cp3d-") as temporary:
        root = Path(temporary)
        cases = {
            "disabled": _repo(root, "disabled", risk),
            "no_change": _repo(root, "no_change", None),
            "equivalent": _repo(root, "equivalent", equivalent),
            "risk_absent": _repo(root, "risk_absent", risk),
            "risk_covered": _repo(root, "risk_covered", risk),
        }
        covered_root, covered_control = cases["risk_covered"]
        bound = dep_evidence.check_dep_workspace(covered_root, covered_control, run_id="benchmark")
        if bound.binding_path is None:
            raise RuntimeError(f"could not prepare valid local evidence: {bound.reason}")
        baseline = risk_dep._git
        result = {}
        for name, (repo, control) in cases.items():
            timings = []
            counts = []
            decisions = set()
            for _ in range(30):
                calls = 0

                def counted(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    return baseline(*args, **kwargs)

                risk_dep._git = counted
                began = time.perf_counter_ns()
                try:
                    decisions.add(evaluate(repo, control, enabled=name != "disabled"))
                finally:
                    timings.append((time.perf_counter_ns() - began) / 1_000_000)
                    counts.append(calls)
                    risk_dep._git = baseline
            expected = {"disabled": "disabled", "no_change": "no_dep_risk",
                        "equivalent": "no_dep_risk", "risk_absent": "uncovered",
                        "risk_covered": "covered"}[name]
            if decisions != {expected}:
                raise RuntimeError(f"{name}: {decisions}")
            p50, p95 = _summary(timings)
            result[name] = {"p50_ms": p50, "p95_ms": p95,
                            "git_calls": sorted(set(counts)), "decision": expected}
        return {"schema_version": "m3.cp3d-preparation.v0", "platform": sys.platform,
                "python": sys.version.split()[0], "runs_per_scenario": 30, "scenarios": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--one", type=Path)
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--audit", action="store_true", help="Emit benchmark-only decision diagnostics")
    args = parser.parse_args()
    if args.one is None:
        print(json.dumps(main(), indent=2))
    else:
        os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
        project = args.one.resolve()
        diagnostic: dict[str, str] = {}
        decision = evaluate(project, enabled=not args.disabled, diagnostic=diagnostic)
        print(json.dumps({"decision": decision, **diagnostic}) if args.audit else decision)
