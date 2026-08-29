from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GRADING = ROOT / "benchmarks/grading-env"
ADMISSION = HERE / "V5_EFFICACY_FREEZE_ADMISSION_REPORT.json"
RUNNER_REPORT = HERE / "V5_EFFICACY_RUNNER_QUALIFICATION_REPORT.json"
TEMPLATE = GRADING / "MECHANISM_FIRST_V5_PREREG.template.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"V5 efficacy freeze: NO-GO: {message}")


def load_runner():
    path = GRADING / "run_mechanism_first_v5.py"
    spec = importlib.util.spec_from_file_location("v5_freeze_validator_runner", path)
    require(spec is not None and spec.loader is not None, "runner import failed")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(GRADING))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.configure()
    return module


def main() -> int:
    for path in (ADMISSION, RUNNER_REPORT, TEMPLATE):
        require(path.is_file(), f"missing artifact:{path.name}")
    module = load_runner()
    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    module.engine.validate_manifest_shape(manifest)
    require(manifest["study_class"] == "exploratory", "study class must remain exploratory")
    require(manifest["maximum_provider_calls"] == 26 and manifest["expected_initial_provider_calls"] == 0, "provider budget mismatch")
    require(manifest["decision_rule"]["GO"].startswith("B>A on at least 10 of 12"), "decision threshold mismatch")
    require(manifest["interpretation"]["quota_429"].startswith("Provider limitation"), "quota attribution missing")
    require(manifest.get("quota_telemetry") == {
        "provider": "openai-codex",
        "required_window_count": 2,
        "required_labels": ["Session", "Weekly"],
        "reducer": "maximum used_percent",
        "threshold_percent": 76,
        "invalid": "Missing, duplicate, extra, non-numeric, non-finite, or out-of-range windows fail closed before the next provider invocation.",
    }, "quota telemetry amendment mismatch")
    require(Path(manifest["hermes_command"]).is_file() and os.access(manifest["hermes_command"], os.X_OK), "provider wrapper unavailable")

    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))
    require(admission.get("ok") is True and admission.get("task_count") == 12 and admission.get("provider_model_calls") == 0, "admission report invalid")
    require([row.get("task_id") for row in admission.get("tasks", [])] == list(module.protocol.EVALUATION_TASKS), "admission roster mismatch")
    for row in admission["tasks"]:
        require(row.get("ok") is True and all(row.get("checks", {}).values()), f"task admission failed:{row.get('task_id')}")
        require(row.get("target_check") == module.protocol.TASK_DEFECTS[row["task_id"]], f"target binding mismatch:{row['task_id']}")
    for relative, expected in admission["frozen_code_sha256"].items():
        require(digest(ROOT / relative) == expected, f"admission code hash mismatch:{relative}")

    runner_report = json.loads(RUNNER_REPORT.read_text(encoding="utf-8"))
    require(runner_report.get("ok") is True and runner_report.get("provider_model_calls") == 0, "runner qualification invalid")
    require(runner_report.get("synthetic_repair_invocations") == 26 and all(runner_report.get("checks", {}).values()), "runner accounting invalid")
    for relative, expected in runner_report["code_sha256"].items():
        require(digest(ROOT / relative) == expected, f"runner code hash mismatch:{relative}")

    pre_gate = subprocess.run(
        [sys.executable, str(HERE / "validate_v5_pre_efficacy_suite.py")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    require(pre_gate.returncode == 0, "inherited pre-efficacy gate failed")

    frozen_files = manifest["frozen_file_sha256"]
    required = {
        "src/agentharness/efficacy_v5.py",
        "src/agentharness/benchmark_heldout_evaluator_v5.py",
        "benchmarks/grading-env/run_mechanism_first_v4.py",
        "benchmarks/grading-env/run_mechanism_first_v5.py",
        "benchmarks/grading-env/run_hermes_stage2codex2_docker.sh",
        "benchmarks/grading-env/mechanism-first-v5.2/V5_QUOTA_TELEMETRY_AMENDMENT.json",
        "benchmarks/grading-env/mechanism-first-v5.2/V5_QUOTA_TELEMETRY_AMENDMENT_REVIEW.json",
        "benchmarks/grading-env/mechanism-first-v5.2/V5_PRE_EFFICACY_CURRENT.json",
        "benchmarks/grading-env/mechanism-first-v5.2/V5_PRE_EFFICACY_SUITE_REPORT.json",
    }
    require(required <= set(frozen_files), "frozen file roster incomplete")
    require(all((ROOT / relative).is_file() for relative in frozen_files), "frozen file missing")
    print("V5 efficacy freeze: GO (12 tasks admitted, runner qualified, zero provider calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
