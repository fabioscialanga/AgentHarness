"""Explicit Windows CLI probe; creates a check only during fixture setup."""

from __future__ import annotations

import contextlib
import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentharness import risk_dep
from agentharness.cli import main as cli_main
from agentharness.dep_evidence import ApprovedDepControl, check_dep_workspace, local_environment_id
from m3_cp3d_prepare import _repo


def _summary(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    return round(statistics.median(ordered), 3), round(ordered[27], 3)


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    risk = '[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n'
    equivalent = '[project]\nname="sample"\ndependencies=["my-pkg>=1.0"]\n'
    with tempfile.TemporaryDirectory(prefix="m3-dep-cli-perf-") as temporary:
        root = Path(temporary)
        cases = {"no_change": _repo(root, "no_change", equivalent)[0],
                 "risk_no_control": _repo(root, "risk_no_control", risk)[0],
                 "risk_uncovered": _repo(root, "risk_uncovered", risk)[0],
                 "risk_covered": _repo(root, "risk_covered", risk)[0]}
        covered = cases["risk_covered"]
        bound = check_dep_workspace(covered, ApprovedDepControl(covered, local_environment_id()), run_id="approved")
        if bound.binding_path is None:
            raise RuntimeError(f"could not prepare local evidence: {bound.reason}")
        original = risk_dep._git
        output = {}
        for name, project in cases.items():
            options = (["--control", "DEP-PEP621-PYTEST-V0"] if name in {"risk_uncovered", "risk_covered"} else [])
            argv = ["dep-assess", "--project", str(project), *options, "--json"]
            in_process = []
            process = []
            calls = []
            decisions = set()
            for _ in range(30):
                count = 0

                def measured(*args, **kwargs):
                    nonlocal count
                    count += 1
                    return original(*args, **kwargs)

                risk_dep._git = measured
                captured = io.StringIO()
                began = time.perf_counter_ns()
                try:
                    with contextlib.redirect_stdout(captured):
                        code = cli_main(argv)
                finally:
                    in_process.append((time.perf_counter_ns() - began) / 1_000_000)
                    calls.append(count)
                    risk_dep._git = original
                if code != 0:
                    raise RuntimeError(f"CLI failed in {name}")
                result = json.loads(captured.getvalue())
                decisions.add((result["detection"]["status"],
                               result["evidence"]["status"] if result["evidence"] else None))
                began = time.perf_counter_ns()
                completed = subprocess.run([sys.executable, "-m", "agentharness", *argv],
                                           capture_output=True, text=True, check=True)
                process.append((time.perf_counter_ns() - began) / 1_000_000)
                result = json.loads(completed.stdout)
                decisions.add((result["detection"]["status"],
                               result["evidence"]["status"] if result["evidence"] else None))
            if len(decisions) != 1:
                raise RuntimeError(f"unstable result in {name}: {decisions}")
            ip50, ip95 = _summary(in_process)
            pp50, pp95 = _summary(process)
            output[name] = {"detection": next(iter(decisions))[0], "evidence": next(iter(decisions))[1],
                            "in_process_p50_ms": ip50, "in_process_p95_ms": ip95,
                            "process_p50_ms": pp50, "process_p95_ms": pp95,
                            "git_calls": sorted(set(calls))}
        return {"schema_version": "m3.dep-assess-cli-perf.v0", "platform": sys.platform,
                "python": sys.version.split()[0], "runs_per_scenario": 30,
                "setup_check_excluded": True, "scenarios": output}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
