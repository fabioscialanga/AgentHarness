"""Paired Windows/Linux comparison of conservative preflight and direct detection."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from agentharness import risk_dep
from m3_cp3d_prepare import _preflight_no_risk, _repo


def _summary(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    return round(statistics.median(ordered), 3), round(ordered[27], 3)


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    equivalent = '[project]\nname="sample"\ndependencies=["my-pkg>=1.0"]\n'
    risk = '[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n'
    with tempfile.TemporaryDirectory(prefix="m3-gating-comparison-") as temporary:
        root = Path(temporary)
        cases = {"no_change": _repo(root, "no_change", None)[0],
                 "equivalent": _repo(root, "equivalent", equivalent)[0],
                 "risk": _repo(root, "risk", risk)[0]}
        original = risk_dep._git
        output = {}
        for name, repo in cases.items():
            rows = {"preflight": {"time": [], "calls": []},
                    "direct_detection": {"time": [], "calls": []}}
            for _ in range(30):
                for mode in ("preflight", "direct_detection"):
                    calls = 0

                    def counted(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        return original(*args, **kwargs)

                    risk_dep._git = counted
                    began = time.perf_counter_ns()
                    try:
                        if mode == "preflight":
                            no_risk = _preflight_no_risk(repo)
                            if no_risk != (name != "risk"):
                                raise RuntimeError(f"preflight false classification: {name}")
                        else:
                            detected = risk_dep.detect_dependency_change(repo)
                            if (detected.status == "risk") != (name == "risk"):
                                raise RuntimeError(f"detection mismatch: {name}: {detected}")
                    finally:
                        rows[mode]["time"].append((time.perf_counter_ns() - began) / 1_000_000)
                        rows[mode]["calls"].append(calls)
                        risk_dep._git = original
            output[name] = {}
            for mode, data in rows.items():
                p50, p95 = _summary(data["time"])
                output[name][mode] = {"p50_ms": p50, "p95_ms": p95,
                                      "git_calls": sorted(set(data["calls"]))}
        return {"schema_version": "m3.cp3d-gating-comparison.v0", "platform": sys.platform,
                "runs_per_scenario": 30, "scope": "explicit local benchmark, no hook", "scenarios": output}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
