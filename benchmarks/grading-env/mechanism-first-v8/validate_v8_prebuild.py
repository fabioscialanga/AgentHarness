from __future__ import annotations

"""Provider-free, hash-bound V8 prebuild validator."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise SystemExit(f"V8 prebuild: NO-GO: {message}")


def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(command, cwd=ROOT, env=environment, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)


def main() -> int:
    pointer = json.loads((HERE / "V8_PREBUILD_STATUS.json").read_text(encoding="utf-8"))
    require(pointer.get("schema_version") == 8, "pointer schema")
    require(pointer.get("status") == "qualified_provider_free_prebuild", "pointer status")
    require(pointer.get("provider_calls") == pointer.get("model_calls") == 0, "pointer call accounting")
    artifacts = pointer.get("artifacts")
    require(isinstance(artifacts, dict) and bool(artifacts), "artifact roster")
    for relative, expected in artifacts.items():
        path = ROOT / relative
        require(path.is_file() and digest(path) == expected, f"artifact hash mismatch: {relative}")

    review = json.loads((HERE / "V8_INDEPENDENT_PRE_DATA_REVIEW.json").read_text(encoding="utf-8"))
    require(review.get("decision") == "GO" and review.get("provider_calls") == review.get("model_calls") == 0, "independent review not GO")
    require(review.get("blocking_findings") == [], "independent review blockers")
    report = json.loads((HERE / "V8_PROVIDER_FREE_PREBUILD_REPORT.json").read_text(encoding="utf-8"))
    require(report.get("schema_version") == 8 and report.get("ok") is True, "report status")
    require(report.get("provider_calls") == report.get("model_calls") == 0, "report call accounting")

    q6 = run([sys.executable, "benchmarks/grading-env/mechanism-first-v6/qualify_v6_provider_free.py"], 600)
    require(q6.returncode == 0, f"V6 qualification failed: {(q6.stdout + q6.stderr)[-400:]}")
    q6_live = json.loads(q6.stdout)
    q6_frozen = json.loads((ROOT / "benchmarks/grading-env/mechanism-first-v6/V6_PROVIDER_FREE_QUALIFICATION_REPORT.json").read_text(encoding="utf-8"))
    require(q6_live == q6_frozen and q6_live.get("ok") is True, "V6 qualification binding")

    auth = run([sys.executable, "benchmarks/grading-env/qualify_v5_1_auth_cache.py"], 600)
    require(auth.returncode == 0, f"authorization-cache qualification failed: {(auth.stdout + auth.stderr)[-400:]}")
    auth_live = json.loads(auth.stdout)
    require(auth_live.get("ok") is True and auth_live.get("total_scored_probes_per_implementation") == 50, "authorization-cache qualification")
    require(auth_live.get("target_model_calls") == 0 and auth_live.get("efficacy_cells") is False, "authorization-cache call accounting")

    tests = run([sys.executable, "-m", "pytest", "-q", "tests/test_mechanism_first_v8.py"], 600)
    require(tests.returncode == 0, f"V8 tests failed: {(tests.stdout + tests.stderr)[-500:]}")
    require("17 passed" in tests.stdout, "V8 test count changed")

    template = json.loads((ROOT / "benchmarks/grading-env/MECHANISM_FIRST_V8_PREREG.template.json").read_text(encoding="utf-8"))
    require(template.get("max_turns") == 8, "turn budget")
    require(template.get("maximum_provider_calls") == 15, "provider budget")
    require(template.get("quota_threshold_percent") == 76, "quota threshold")
    require(template.get("provider") == "openai-codex" and template.get("model") == "gpt-5.6-sol", "runtime binding")
    print("V8 provider-free prebuild: GO (V6 + authorization-cache qualification; 17 tests; calls 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
