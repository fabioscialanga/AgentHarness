from __future__ import annotations

"""V8 launcher: eight-turn bindings over the frozen V6 engine."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (str(HERE), str(SRC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_mechanism_first_v6 as v6_runner
from agentharness import efficacy_v8 as protocol

engine = v6_runner.engine
TEMPLATE_PATH = HERE / "MECHANISM_FIRST_V8_PREREG.template.json"


def materialize_controlled_start(*, task_id: str, repo_root: Path, destination: Path):
    return protocol.materialize_controlled_start(task_id=task_id, repo_root=repo_root, destination=destination)


def materialize_clean_reference(*, task_id: str, repo_root: Path, destination: Path):
    return protocol.materialize_clean_reference(task_id=task_id, repo_root=repo_root, destination=destination)


def evaluate_heldout(workspace: Path, task_id: str):
    return protocol.evaluate_heldout(workspace, task_id, repo_root=REPO_ROOT)


def evaluate_review(workspace: Path, task_id: str):
    return protocol.evaluate_review(workspace, task_id)


def configure() -> None:
    v6_runner.configure()
    engine.TEMPLATE_PATH = TEMPLATE_PATH
    engine.SCHEMA_VERSION = 8
    engine.PROTOCOL_TAG = "v8"
    engine.REPLICATE_ID = "v8-r1"
    engine.RESULT_FILENAME = "MECHANISM_FIRST_V8_RESULT.json"
    engine.MAX_TURNS = 8
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
    engine.finalize_results = protocol.finalize_results


def main() -> int:
    configure()
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
