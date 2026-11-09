"""Measure explicit CP3-D prototype as a new process; no host hook is installed."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentharness import dep_evidence
from m3_cp3d_prepare import _repo


def main() -> dict:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    equivalent = '[project]\nname="sample"\ndependencies=["my-pkg>=1.0"]\n'
    risk = '[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n'
    with tempfile.TemporaryDirectory(prefix="m3-cp3d-process-") as temporary:
        root = Path(temporary)
        cases = {"disabled": _repo(root, "disabled", risk),
                 "no_change": _repo(root, "no_change", None),
                 "equivalent": _repo(root, "equivalent", equivalent),
                 "risk_absent": _repo(root, "risk_absent", risk),
                 "risk_covered": _repo(root, "risk_covered", risk)}
        repo, control = cases["risk_covered"]
        bound = dep_evidence.check_dep_workspace(repo, control, run_id="benchmark")
        if bound.binding_path is None:
            raise RuntimeError(f"binding failed: {bound.reason}")
        script = Path(__file__).with_name("m3_cp3d_prepare.py")
        output = {}
        for name, (repo, _) in cases.items():
            values = []
            decisions: dict[str, int] = {}
            abstentions: dict[str, int] = {}
            for _ in range(30):
                began = time.perf_counter_ns()
                result = subprocess.run([sys.executable, str(script), "--one", str(repo), "--audit",
                                         *(["--disabled"] if name == "disabled" else [])],
                                        capture_output=True, text=True, check=True)
                values.append((time.perf_counter_ns() - began) / 1_000_000)
                audit = json.loads(result.stdout)
                decision = audit["decision"]
                decisions[decision] = decisions.get(decision, 0) + 1
                if decision == "abstain":
                    abstentions[audit.get("detection_reason", "unknown")] = abstentions.get(audit.get("detection_reason", "unknown"), 0) + 1
            ordered = sorted(values)
            output[name] = {"p50_ms": round(statistics.median(ordered), 3),
                            "p95_ms": round(ordered[27], 3), "decisions": decisions,
                            "abstention_reasons": abstentions}
        return {"schema_version": "m3.cp3d-process-perf.v0", "platform": sys.platform,
                "python": sys.version.split()[0], "runs_per_scenario": 30,
                "scope": "explicit prototype, new Python process, no Codex host", "scenarios": output}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
