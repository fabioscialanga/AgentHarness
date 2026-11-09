"""Explicit local-capture evidence benchmark; never invoked by an adapter."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from agentharness import dep_evidence, risk_dep
from m3_cp3d_prepare import _repo


def _bind(repo: Path, control: dep_evidence.ApprovedDepControl, run_id: str) -> Path:
    result = dep_evidence.check_dep_workspace(repo, control, run_id=run_id)
    if result.binding_path is None:
        raise RuntimeError(f"binding failed: {run_id}: {result.reason}")
    binding = json.loads(result.binding_path.read_text(encoding="utf-8"))
    if binding["provenance"] != "local-capture":
        raise RuntimeError("non-production evidence")
    return result.binding_path.parent


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    risk = '[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n'
    with tempfile.TemporaryDirectory(prefix="m3-local-evidence-") as temporary:
        root = Path(temporary)
        cases = {name: _repo(root, name, risk) for name in
                 ("covered", "failed", "uncovered", "unknown_tampered", "unknown_stale", "unknown_contradictory")}
        covered_repo, covered_control = cases["covered"]
        _bind(covered_repo, covered_control, "passing")
        failed_repo, failed_control = cases["failed"]
        (failed_repo / "tests/test_dep.py").write_text("def test_dep():\n    assert False\n", encoding="utf-8")
        _bind(failed_repo, failed_control, "failing")
        tampered_repo, tampered_control = cases["unknown_tampered"]
        tampered_run = _bind(tampered_repo, tampered_control, "tampered")
        report = json.loads((tampered_run / "verify-report.json").read_text(encoding="utf-8"))
        execution = report["results"][0]["audit"]["commands"][0]["reexecution"]
        Path(execution["stdout_path"]).write_bytes(Path(execution["stdout_path"]).read_bytes() + b"tampered\n")
        stale_repo, stale_control = cases["unknown_stale"]
        _bind(stale_repo, stale_control, "stale")
        (stale_repo / "pyproject.toml").write_text(risk.replace(">=2", ">=3"), encoding="utf-8")
        contradictory_repo, contradictory_control = cases["unknown_contradictory"]
        external = root / "external-switch.txt"
        external.write_text("fail", encoding="utf-8")
        (contradictory_repo / "tests/test_dep.py").write_text(
            f"from pathlib import Path\ndef test_dep():\n    assert Path({str(external)!r}).read_text().strip() == 'pass'\n",
            encoding="utf-8",
        )
        _bind(contradictory_repo, contradictory_control, "contradict-fail")
        external.write_text("pass", encoding="utf-8")
        _bind(contradictory_repo, contradictory_control, "contradict-pass")

        original_git = risk_dep._git
        original_read = dep_evidence._ReadBudget.read
        expected = {"covered": "covered", "failed": "failed", "uncovered": "uncovered",
                    "unknown_tampered": "unknown", "unknown_stale": "unknown",
                    "unknown_contradictory": "unknown"}
        output = {}
        for name, (repo, control) in cases.items():
            timings = []
            calls = []
            bytes_read = []
            reasons: dict[str, int] = {}
            for _ in range(30):
                detection = risk_dep.detect_dependency_change(repo)
                count = 0
                read = 0

                def measured_git(*args, **kwargs):
                    nonlocal count
                    count += 1
                    return original_git(*args, **kwargs)

                def measured_read(self, path, root_path, limit):
                    nonlocal read
                    data = original_read(self, path, root_path, limit)
                    read += len(data)
                    return data

                risk_dep._git = measured_git
                dep_evidence._ReadBudget.read = measured_read
                began = time.perf_counter_ns()
                try:
                    decision = dep_evidence.match_dep_evidence(repo, detection, control)
                finally:
                    timings.append((time.perf_counter_ns() - began) / 1_000_000)
                    calls.append(count)
                    bytes_read.append(read)
                    risk_dep._git = original_git
                    dep_evidence._ReadBudget.read = original_read
                if decision.status != expected[name]:
                    raise RuntimeError(f"{name}: unexpected {decision}")
                reason = decision.reason or "none"
                reasons[reason] = reasons.get(reason, 0) + 1
            ordered = sorted(timings)
            output[name] = {"status": expected[name], "reasons": reasons,
                            "p50_match_ms": round(statistics.median(ordered), 3),
                            "p95_match_ms": round(ordered[27], 3),
                            "git_calls_per_match": sorted(set(calls)),
                            "artifact_bytes_per_match": sorted(set(bytes_read))}
        return {"schema_version": "m3.local-evidence-perf.v0", "platform": sys.platform,
                "python": sys.version.split()[0], "runs_per_scenario": 30,
                "provenance": "local-capture", "scenarios": output}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
