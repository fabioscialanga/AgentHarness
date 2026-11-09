"""Explicit local CP3-B timing probe; never called by hooks."""

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


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="m3-cp3b-perf-") as temporary:
        root = Path(temporary)
        git(root, "init", "-q")
        git(root, "config", "user.name", "Synthetic")
        git(root, "config", "user.email", "synthetic@example.invalid")
        git(root, "config", "core.autocrlf", "false")
        (root / ".gitignore").write_text(".agentharness/\n.pytest_cache/\n__pycache__/\n", encoding="utf-8", newline="\n")
        project = root / "pyproject.toml"
        project.write_text('[project]\nname="sample"\ndependencies=["a>=1"]\n', encoding="utf-8", newline="\n")
        (root / "tests").mkdir()
        (root / "tests/test_dep.py").write_text("def test_dep():\n    assert True\n", encoding="utf-8", newline="\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline")
        project.write_text('[project]\nname="sample"\ndependencies=["a>=2"]\n', encoding="utf-8", newline="\n")
        control = dep_evidence.ApprovedDepControl(root, dep_evidence.local_environment_id())
        start = time.perf_counter_ns()
        bound = dep_evidence.check_dep_workspace(root, control, run_id="perf")
        check_ms = (time.perf_counter_ns() - start) / 1_000_000
        if bound.binding_path is None:
            raise RuntimeError(f"binding failed: {bound.reason}")
        detection = risk_dep.detect_dependency_change(root)
        original_git = risk_dep._git
        original_read = dep_evidence._ReadBudget.read
        rows = []
        for _ in range(10):
            calls = 0
            git_ms = 0.0
            read_bytes = 0

            def measured_git(*args, **kwargs):
                nonlocal calls, git_ms
                began = time.perf_counter_ns()
                try:
                    return original_git(*args, **kwargs)
                finally:
                    calls += 1
                    git_ms += (time.perf_counter_ns() - began) / 1_000_000

            def measured_read(self, path, root_path, limit):
                nonlocal read_bytes
                data = original_read(self, path, root_path, limit)
                read_bytes += len(data)
                return data

            risk_dep._git = measured_git
            dep_evidence._ReadBudget.read = measured_read
            began = time.perf_counter_ns()
            try:
                decision = dep_evidence.match_dep_evidence(root, detection, control)
            finally:
                risk_dep._git = original_git
                dep_evidence._ReadBudget.read = original_read
            if decision.status != "covered":
                raise RuntimeError(f"matching failed: {decision}")
            rows.append({"elapsed_ms": round((time.perf_counter_ns() - began) / 1_000_000, 3),
                         "git_calls": calls, "git_ms": round(git_ms, 3), "artifact_bytes_read": read_bytes})
        times = sorted(row["elapsed_ms"] for row in rows)
        return {"schema_version": "m3.cp3b-perf.v0", "platform": sys.platform,
                "check_and_binding_ms": round(check_ms, 3), "match_runs": len(rows),
                "match_p50_ms": statistics.median(times), "match_p95_ms": times[9],
                "match_git_calls_total": sum(row["git_calls"] for row in rows),
                "match_artifact_bytes_total": sum(row["artifact_bytes_read"] for row in rows),
                "rows": rows}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
