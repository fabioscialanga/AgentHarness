from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "benchmarks/grading-env/run_mechanism_first_v5.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("v5_runner_qualification", RUNNER)
    if spec is None or spec.loader is None:
        raise SystemExit("V5 efficacy runner qualification: NO-GO: runner import failed")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(RUNNER.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.configure()
    engine = module.engine
    manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
    manifest.update(
        execution_mode="qualification",
        preregistration_status="frozen",
        repository_commit="synthetic-qualification",
        manifest_payload_sha256="synthetic-qualification",
    )
    with tempfile.TemporaryDirectory(prefix="v5-runner-qualification-") as raw:
        temporary = Path(raw)
        manifest_path = temporary / "manifest.json"
        run_root = temporary / "run"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        engine.preflight = lambda *_args, **_kwargs: {
            "manifest_file_sha256": "synthetic-qualification",
            "repository_commit": "synthetic-qualification",
            "execution_mode": "qualification",
        }
        result = engine.V4Pilot(
            manifest_path,
            run_root,
            invoker=engine.SyntheticRepairInvoker(calibration_repairs=0),
            usage=engine.synthetic_usage,
            synthetic=True,
        ).run()
        started = sorted(run_root.rglob("provider-invocation.repair.started.json"))
        completed = sorted(run_root.rglob("provider-invocation.repair.completed.json"))
        initial = sorted(run_root.rglob("provider-invocation.initial.*.json"))
        blocks = sorted((run_root / "private-blocks").glob("v5-eval-*"))
        calibration = sorted((run_root / "private-calibration").glob("v5-cal-*"))
        audit = json.loads((run_root / "collection-audit.final.json").read_text(encoding="utf-8"))
        checks = {
            "collection_complete": result == {"status": "collection_complete", "evaluation_calls": 24},
            "calibration_blocks_exact": len(calibration) == 2,
            "evaluation_blocks_exact": len(blocks) == 12,
            "repair_started_exact": len(started) == 26,
            "repair_completed_exact": len(completed) == 26,
            "initial_provider_calls_zero": not initial,
            "audit_provider_initial_calls_zero": audit.get("provider_initial_calls") == 0,
            "audit_repair_calls_exact": audit.get("repair_calls_started") == audit.get("repair_calls_completed") == 26,
            "analysis_not_authorized_for_synthetic": audit.get("analysis_authorized") is False,
            "synthetic_execution_mode": audit.get("execution_mode") == "qualification",
        }
    payload = {
        "schema_version": 5,
        "suite_id": "mechanism-first-v5-efficacy-runner-qualification",
        "ok": all(checks.values()),
        "provider_model_calls": 0,
        "synthetic_repair_invocations": 26,
        "checks": checks,
        "code_sha256": {
            "benchmarks/grading-env/run_mechanism_first_v4.py": digest(ROOT / "benchmarks/grading-env/run_mechanism_first_v4.py"),
            "benchmarks/grading-env/run_mechanism_first_v5.py": digest(RUNNER),
            "src/agentharness/efficacy_v5.py": digest(ROOT / "src/agentharness/efficacy_v5.py"),
            "src/agentharness/benchmark_heldout_evaluator_v5.py": digest(ROOT / "src/agentharness/benchmark_heldout_evaluator_v5.py"),
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "provider_model_calls": 0, "synthetic_repair_invocations": 26}, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
