from __future__ import annotations

"""Fail-closed validator for the V6 provider-free prebuild pointer."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise SystemExit(f"V6 prebuild: NO-GO: {message}")


def main() -> int:
    pointer_path = HERE / "V6_PREBUILD_STATUS.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    require(pointer.get("schema_version") == 6 and pointer.get("status") == "qualified_provider_free_prebuild", "pointer identity")
    require(pointer.get("provider_calls") == pointer.get("model_calls") == 0, "pointer claims calls")
    artifacts = pointer.get("artifacts")
    require(isinstance(artifacts, dict), "artifact roster")
    for relative, expected in artifacts.items():
        path = ROOT / relative
        require(path.is_file() and digest(path) == expected, f"artifact hash mismatch: {relative}")
    report_path = HERE / "V6_PROVIDER_FREE_QUALIFICATION_REPORT.json"
    review = json.loads((HERE / "V6_INDEPENDENT_PRE_DATA_REVIEW.json").read_text(encoding="utf-8"))
    require(review.get("decision") == "GO" and review.get("provider_calls") == review.get("model_calls") == 0, "independent review not GO")
    require(review.get("blocking_findings") == [], "independent review blockers")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require(report.get("ok") is True and report.get("task_count") == 6, "qualification report not GO")
    require(report.get("provider_calls") == report.get("model_calls") == 0, "qualification report claims calls")
    require(report.get("public_input_leakage") == [], "public agent-visible input leakage")
    rows = report.get("rows")
    require(isinstance(rows, list) and len(rows) == 6, "qualification row roster")
    require(all(row.get("reference_target_passed") is True and row.get("reference_guards_passed") is True
                and row.get("controlled_failed_only_target") is True and row.get("leakage") == []
                and row.get("clones_byte_identical") is True for row in rows), "qualification invariant")
    completed = subprocess.run(
        [sys.executable, str(HERE / "qualify_v6_provider_free.py")], cwd=ROOT,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, check=False,
    )
    require(completed.returncode == 0, f"live qualifier failed: {completed.stderr[-300:]}")
    live = json.loads(completed.stdout)
    require(live == report, "live qualification differs from frozen report")
    template = json.loads((ROOT / "benchmarks/grading-env/MECHANISM_FIRST_V6_PREREG.template.json").read_text(encoding="utf-8"))
    require(template.get("maximum_provider_calls") == 15, "maximum call budget")
    require(template.get("expected_calibration_provider_calls") == 3 and template.get("expected_evaluation_provider_calls") == 12, "phase call budget")
    require(template.get("provider") == "openai-codex" and template.get("model") == "gpt-5.6-sol", "runtime binding")
    print("V6 provider-free prebuild qualification: GO (6 references + 6 singleton targets; provider/model calls 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
