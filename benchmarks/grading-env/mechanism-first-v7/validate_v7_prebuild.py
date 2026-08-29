from __future__ import annotations

"""Provider-free, hash-bound V7 prebuild validator (not an independent audit)."""

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
        raise SystemExit(f"V7 prebuild: NO-GO: {message}")


def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        command, cwd=ROOT, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
    )


def main() -> int:
    pointer = json.loads((HERE / "V7_PREBUILD_STATUS.json").read_text(encoding="utf-8"))
    require(pointer.get("schema_version") == 7, "pointer schema")
    require(pointer.get("status") == "qualified_provider_free_prebuild", "pointer status")
    require(pointer.get("provider_calls") == pointer.get("model_calls") == 0, "pointer call accounting")
    artifacts = pointer.get("artifacts")
    require(isinstance(artifacts, dict) and bool(artifacts), "artifact roster")
    for relative, expected in artifacts.items():
        path = ROOT / relative
        require(path.is_file() and digest(path) == expected, f"artifact hash mismatch: {relative}")

    review = json.loads((HERE / "V7_INDEPENDENT_PRE_DATA_REVIEW.json").read_text(encoding="utf-8"))
    require(review.get("decision") == "GO" and review.get("provider_calls") == review.get("model_calls") == 0, "independent review not GO")
    require(review.get("blocking_findings") == [], "independent review blockers")
    report = json.loads((HERE / "V7_PROVIDER_FREE_PREBUILD_REPORT.json").read_text(encoding="utf-8"))
    require(report.get("schema_version") == 7 and report.get("ok") is True, "report status")
    require(report.get("audit_character") == "maintainer_provider_free_prebuild_not_independent_audit", "audit characterization")
    require(report.get("provider_calls") == report.get("model_calls") == 0, "report call accounting")

    qualification = run([sys.executable, "benchmarks/grading-env/mechanism-first-v6/qualify_v6_provider_free.py"], 600)
    require(qualification.returncode == 0, f"V6 source-native qualification failed: {qualification.stderr[-300:]}")
    live = json.loads(qualification.stdout)
    frozen = json.loads((ROOT / "benchmarks/grading-env/mechanism-first-v6/V6_PROVIDER_FREE_QUALIFICATION_REPORT.json").read_text(encoding="utf-8"))
    require(live == frozen and live.get("ok") is True and live.get("task_count") == 6, "V6 qualification binding")
    require(live.get("provider_calls") == live.get("model_calls") == 0, "qualification call accounting")

    tests = run([sys.executable, "-m", "pytest", "-q", "tests/test_mechanism_first_v7.py"], 600)
    require(tests.returncode == 0, f"V7 tests failed: {(tests.stdout + tests.stderr)[-500:]}")
    require("13 passed" in tests.stdout, "V7 test count changed")

    template = json.loads((ROOT / "benchmarks/grading-env/MECHANISM_FIRST_V7_PREREG.template.json").read_text(encoding="utf-8"))
    require(template.get("max_turns") == 6, "turn budget")
    require(template.get("maximum_provider_calls") == 15, "provider budget")
    require(template.get("quota_threshold_percent") == 76, "quota threshold")
    require(template.get("provider") == "openai-codex" and template.get("model") == "gpt-5.6-sol", "runtime binding")
    print("V7 provider-free prebuild: GO (hash-bound; V6 qualification + 13 V7 tests; provider/model calls 0; not independent audit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
