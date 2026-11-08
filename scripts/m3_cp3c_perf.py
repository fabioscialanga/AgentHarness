"""Explicit CP3-C local engine probe; no hook or automatic verification."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentharness import dep_evidence, risk_dep


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _quantile(values: list[float], numerator: int) -> float:
    ordered = sorted(values)
    return round(ordered[(len(ordered) - 1) * numerator // 100], 3)


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="m2-disabled-perf-") as disabled_project:
        disabled_times = []
        for _ in range(30):
            began = time.perf_counter_ns()
            process = subprocess.run(
                [sys.executable, "-m", "agentharness", "host-event", "--host", "codex",
                 "--project", disabled_project],
                input='{"hook_event_name":"Stop","stop_hook_active":false}',
                text=True, capture_output=True, check=True,
            )
            if process.stdout.strip() != "{}":
                raise RuntimeError("M2 disabled produced a message")
            disabled_times.append((time.perf_counter_ns() - began) / 1_000_000)
    with tempfile.TemporaryDirectory(prefix="m3-cp3c-perf-") as temporary:
        root = Path(temporary)
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "Synthetic")
        _git(root, "config", "user.email", "synthetic@example.invalid")
        _git(root, "config", "core.autocrlf", "false")
        (root / ".gitignore").write_text(".agentharness/\n.pytest_cache/\n__pycache__/\n", encoding="utf-8")
        project = root / "pyproject.toml"
        project.write_text('[project]\nname="sample"\ndependencies=["a>=1"]\n', encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests/test_dep.py").write_text("def test_dep():\n    assert True\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "baseline")
        project.write_text('[project]\nname="sample"\ndependencies=["a>=2"]\n', encoding="utf-8")
        control = dep_evidence.ApprovedDepControl(root, dep_evidence.local_environment_id())
        bound = dep_evidence.check_dep_workspace(root, control, run_id="perf")
        if bound.binding_path is None:
            raise RuntimeError(f"binding failed: {bound.reason}")
        baseline_git = risk_dep._git
        rows = []
        for _ in range(30):
            calls = 0
            git_ms = 0.0

            def measured(*args, **kwargs):
                nonlocal calls, git_ms
                began = time.perf_counter_ns()
                try:
                    return baseline_git(*args, **kwargs)
                finally:
                    calls += 1
                    git_ms += (time.perf_counter_ns() - began) / 1_000_000

            risk_dep._git = measured
            began = time.perf_counter_ns()
            try:
                detection = risk_dep.detect_dependency_change(root)
                detection_ms = (time.perf_counter_ns() - began) / 1_000_000
                decision = dep_evidence.match_dep_evidence(root, detection, control)
            finally:
                risk_dep._git = baseline_git
            if decision.status != "covered":
                raise RuntimeError(f"unexpected decision: {decision}")
            rows.append({"total_ms": round((time.perf_counter_ns() - began) / 1_000_000, 3),
                         "detection_ms": round(detection_ms, 3), "git_calls": calls,
                         "git_ms": round(git_ms, 3)})
        return {"schema_version": "m3.cp3c-perf.v0", "platform": sys.platform,
                "python": sys.version.split()[0], "runs": len(rows), "scenario": "explicit risk with valid evidence",
                "m2_disabled_subprocess_p50_ms": round(statistics.median(disabled_times), 3),
                "m2_disabled_subprocess_p95_ms": _quantile(disabled_times, 95),
                "p50_total_ms": round(statistics.median(row["total_ms"] for row in rows), 3),
                "p95_total_ms": _quantile([row["total_ms"] for row in rows], 95),
                "p50_detection_ms": round(statistics.median(row["detection_ms"] for row in rows), 3),
                "p50_git_ms": round(statistics.median(row["git_ms"] for row in rows), 3),
                "git_calls_per_run": sorted(set(row["git_calls"] for row in rows)), "rows": rows}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
