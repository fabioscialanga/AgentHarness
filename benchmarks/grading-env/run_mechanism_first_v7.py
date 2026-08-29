from __future__ import annotations

"""V7 launcher: bounded-diagnosis bindings over the V6/V4 implementation."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (str(HERE), str(SRC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_mechanism_first_v6 as v6_runner
from agentharness import efficacy_v7 as protocol

engine = v6_runner.engine
TEMPLATE_PATH = HERE / "MECHANISM_FIRST_V7_PREREG.template.json"


def evaluate_heldout(workspace: Path, task_id: str):
    return protocol.evaluate_heldout(workspace, task_id, repo_root=REPO_ROOT)


def configure() -> None:
    v6_runner.configure()
    engine.TEMPLATE_PATH = TEMPLATE_PATH
    engine.SCHEMA_VERSION = 7
    engine.PROTOCOL_TAG = "v7"
    engine.REPLICATE_ID = "v7-r1"
    engine.RESULT_FILENAME = "MECHANISM_FIRST_V7_RESULT.json"
    engine.MAX_TURNS = 6
    engine.PILOT_ID = protocol.PILOT_ID
    engine.CALIBRATION_TASKS = protocol.CALIBRATION_TASKS
    engine.EVALUATION_TASKS = protocol.EVALUATION_TASKS
    engine.CONDITIONS = protocol.CONDITIONS
    engine.CONDITION_ORDERS = protocol.CONDITION_ORDERS
    engine.OPAQUE_FINDING_IDS = protocol.OPAQUE_FINDING_IDS
    engine.CALIBRATION_CALLS = len(protocol.CALIBRATION_TASKS)
    engine.EVALUATION_CALLS = 2 * len(protocol.EVALUATION_TASKS)
    engine.MAXIMUM_CALLS = engine.CALIBRATION_CALLS + engine.EVALUATION_CALLS
    engine.evaluate_heldout = evaluate_heldout
    engine.validate_marker_accounting = protocol.validate_marker_accounting
    engine.calibration_admission = protocol.calibration_admission
    engine.finalize_results = protocol.finalize_results


def main() -> int:
    configure()
    return engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
