from __future__ import annotations

"""V6 launcher: a complete constant/function binding over the frozen V4 engine."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (str(HERE), str(SRC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_mechanism_first_v4 as engine
from agentharness import efficacy_v6 as protocol

TEMPLATE_PATH = HERE / "MECHANISM_FIRST_V6_PREREG.template.json"


def materialize_controlled_start(*, task_id: str, repo_root: Path, destination: Path):
    return protocol.materialize_controlled_start(task_id=task_id, repo_root=repo_root, destination=destination)


def materialize_clean_reference(*, task_id: str, repo_root: Path, destination: Path):
    return protocol.materialize_clean_reference(task_id=task_id, repo_root=repo_root, destination=destination)


def evaluate_heldout(workspace: Path, task_id: str):
    return protocol.evaluate_heldout(workspace, task_id, repo_root=REPO_ROOT)


def evaluate_review(workspace: Path, task_id: str):
    return protocol.evaluate_review(workspace, task_id)


def real_usage(_phase: str) -> float:
    try:
        from agent.account_usage import fetch_account_usage
        usage = fetch_account_usage("openai-codex")
        windows = list(getattr(usage, "windows", []) or []) if getattr(usage, "available", False) else []
        return protocol.conservative_usage_percent(windows)
    except Exception as exc:
        raise engine.InvocationFailure(f"quota telemetry unavailable:{type(exc).__name__}") from exc


def configure() -> None:
    engine.TEMPLATE_PATH = TEMPLATE_PATH
    engine.SCHEMA_VERSION = 6
    engine.PROTOCOL_TAG = "v6"
    engine.REPLICATE_ID = "v6-r1"
    engine.RESULT_FILENAME = "MECHANISM_FIRST_V6_RESULT.json"
    engine.PILOT_ID = protocol.PILOT_ID
    engine.CALIBRATION_TASKS = protocol.CALIBRATION_TASKS
    engine.EVALUATION_TASKS = protocol.EVALUATION_TASKS
    engine.CONDITIONS = protocol.CONDITIONS
    engine.CONDITION_ORDERS = protocol.CONDITION_ORDERS
    engine.OPAQUE_FINDING_IDS = protocol.OPAQUE_FINDING_IDS
    engine.CALIBRATION_CALLS = len(protocol.CALIBRATION_TASKS)
    engine.EVALUATION_CALLS = 2 * len(protocol.EVALUATION_TASKS)
    engine.MAXIMUM_CALLS = engine.CALIBRATION_CALLS + engine.EVALUATION_CALLS
    engine.canonical_hash = protocol.canonical_hash
    engine.clone_pair = protocol.clone_pair
    engine.tree_fingerprint = protocol.tree_fingerprint
    engine.materialize_controlled_start = materialize_controlled_start
    engine.materialize_clean_reference = materialize_clean_reference
    engine.evaluate_heldout = evaluate_heldout
    engine.evaluate_review = evaluate_review
    engine.validate_opaque_feedback = protocol.validate_opaque_feedback
    engine.validate_marker_accounting = protocol.validate_marker_accounting
    engine.calibration_admission = protocol.calibration_admission
    engine.quota_admission = protocol.quota_admission
    engine.real_usage = real_usage
    engine.finalize_results = protocol.finalize_results


def main() -> int:
    configure()
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
