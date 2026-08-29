from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentharness import efficacy_v7 as v7

ROOT = Path(__file__).resolve().parents[1]
GRADING = ROOT / "benchmarks/grading-env"
CALIBRATION = (
    "streaming-csv-quoted-records",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)
EVALUATION = (
    "envelope-context-decryptor",
    "attenuated-capability-verifier",
    "transactional-release-pointer",
    "streaming-csv-quoted-records",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)


def load_runner(name: str = "v7_runner_test"):
    path = GRADING / "run_mechanism_first_v7.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


@pytest.fixture
def configured_runner():
    module = load_runner()
    engine = module.engine
    keys = (
        "TEMPLATE_PATH", "SCHEMA_VERSION", "PROTOCOL_TAG", "REPLICATE_ID", "RESULT_FILENAME",
        "MAX_TURNS", "PILOT_ID", "CALIBRATION_TASKS", "EVALUATION_TASKS", "CONDITIONS",
        "CONDITION_ORDERS", "OPAQUE_FINDING_IDS", "CALIBRATION_CALLS", "EVALUATION_CALLS",
        "MAXIMUM_CALLS", "evaluate_heldout", "validate_marker_accounting",
        "calibration_admission", "finalize_results",
    )
    saved = {key: getattr(engine, key) for key in keys}
    module.configure()
    try:
        yield module
    finally:
        for key, value in saved.items():
            setattr(engine, key, value)


def test_v4_default_remains_40_and_v7_configure_sets_6(configured_runner):
    assert configured_runner.engine.MAX_TURNS == 6
    manifest = json.loads(configured_runner.TEMPLATE_PATH.read_text(encoding="utf-8"))
    configured_runner.engine.validate_manifest_shape(manifest)
    assert manifest["max_turns"] == 6
    assert configured_runner.engine.SCHEMA_VERSION == 7
    assert configured_runner.engine.MAXIMUM_CALLS == 15
    assert configured_runner.engine.RESULT_FILENAME == "MECHANISM_FIRST_V7_RESULT.json"


def test_v4_source_default_is_still_40():
    path = GRADING / "run_mechanism_first_v4.py"
    spec = importlib.util.spec_from_file_location("v4_default_v7_regression", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.MAX_TURNS == 40


def test_exact_v7_rosters():
    assert v7.CALIBRATION_TASKS == CALIBRATION
    assert v7.EVALUATION_TASKS == EVALUATION


def markers() -> list[dict[str, object]]:
    result = [
        {"phase": "repair", "initial_provider_call": False,
         "invocation_id": f"v7-cal-{index:03d}:A-baseline:repair-1",
         "task_id": task, "condition": "A-baseline"}
        for index, task in enumerate(CALIBRATION, 1)
    ]
    result.extend(
        {"phase": "repair", "initial_provider_call": False,
         "invocation_id": f"v7-eval-{index:03d}:{condition}:repair-1",
         "task_id": task, "condition": condition}
        for index, task in enumerate(EVALUATION, 1)
        for condition in v7.CONDITIONS
    )
    return result


def test_marker_full_roster_15_and_missing_or_duplicate_fail():
    roster = markers()
    assert len(roster) == 15
    v7.validate_marker_accounting(roster, evaluation_admitted=True)
    with pytest.raises(ValueError, match="provider_marker"):
        v7.validate_marker_accounting(roster[:-1], evaluation_admitted=True)
    with pytest.raises(ValueError, match="provider_marker"):
        v7.validate_marker_accounting([*roster, dict(roster[0])], evaluation_admitted=True)


@pytest.mark.parametrize("task", EVALUATION)
def test_inherited_source_native_singleton_qualification(task: str, tmp_path: Path):
    clean, controlled = tmp_path / "clean", tmp_path / "controlled"
    v7.materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
    v7.materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
    reference = v7.evaluate_heldout(clean, task, repo_root=ROOT)
    target = v7.evaluate_heldout(controlled, task, repo_root=ROOT)
    assert reference["target_passed"] is reference["guards_passed"] is True
    assert target["target_passed"] is False and target["guards_passed"] is True
    assert reference["schema_version"] == target["schema_version"] == 7
    assert reference["evaluator_schema_version"] == target["evaluator_schema_version"] == 5


def qualification_manifest(module, tmp_path: Path) -> Path:
    manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
    manifest["execution_mode"] = "qualification"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_full_synthetic_admit_completes_15_and_schema_cells(configured_runner, monkeypatch, tmp_path: Path):
    module = configured_runner
    manifest_path = qualification_manifest(module, tmp_path)
    run_root = tmp_path / "run"
    monkeypatch.setattr(module.engine, "preflight", lambda *_args, **_kwargs: {
        "manifest_file_sha256": "synthetic", "repository_commit": "synthetic",
    })
    pilot = module.engine.V4Pilot(
        manifest_path, run_root,
        invoker=module.engine.SyntheticRepairInvoker(calibration_repairs=0),
        usage=module.engine.synthetic_usage, synthetic=True,
    )
    assert pilot.run() == {"status": "collection_complete", "evaluation_calls": 12}
    state = json.loads((run_root / "campaign-state.private.json").read_text(encoding="utf-8"))
    assert state["repair_calls_started"] == state["repair_calls_completed"] == 15
    commits = sorted(run_root.glob("private-blocks/*/block-result.commit.json"))
    assert len(commits) == 6
    cells = [cell for path in commits for cell in json.loads(path.read_text(encoding="utf-8"))["cells"]]
    assert len(cells) == 12
    assert all(cell["schema_version"] == 7 and cell["evaluator_schema_version"] == 5 for cell in cells)


def test_ceiling_path_stops_after_three(configured_runner, monkeypatch, tmp_path: Path):
    module = configured_runner
    manifest_path = qualification_manifest(module, tmp_path)
    run_root = tmp_path / "run"
    monkeypatch.setattr(module.engine, "preflight", lambda *_args, **_kwargs: {
        "manifest_file_sha256": "synthetic", "repository_commit": "synthetic",
    })
    pilot = module.engine.V4Pilot(
        manifest_path, run_root,
        invoker=module.engine.SyntheticRepairInvoker(calibration_repairs=3),
        usage=module.engine.synthetic_usage, synthetic=True,
    )
    assert pilot.run() == {"status": "CEILING", "evaluation_calls": 0}
    state = json.loads((run_root / "campaign-state.private.json").read_text(encoding="utf-8"))
    assert state["repair_calls_started"] == state["repair_calls_completed"] == 3
    assert not list(run_root.glob("private-blocks/*"))


def endpoint(task: str, condition: str, passed: bool) -> dict[str, object]:
    return {
        "task_id": task, "condition": condition, "invocation_valid": True,
        "heldout_valid": True, "target_evaluated": True, "guards_evaluated": True,
        "target_passed": passed, "guards_passed": True,
        "feedback_delivered": condition == "B-agentharness",
        "feedback_immutable": True, "feedback_accounted": True,
    }


def test_quota_reducer_projection_and_unchanged_five_of_six_threshold():
    session = SimpleNamespace(label="Session", used_percent=12.0)
    weekly = SimpleNamespace(label="Weekly", used_percent=61.0)
    assert v7.conservative_usage_percent([session, weekly]) == 61.0
    assert v7.quota_admission(70, 70) == (True, 76.0)
    assert v7.quota_admission(70.1, 70.1)[0] is False
    rows = [endpoint(task, condition, condition == "B-agentharness" and index < 5)
            for index, task in enumerate(EVALUATION) for condition in v7.CONDITIONS]
    result = v7.finalize_results(rows)
    assert result["schema_version"] == 7 and result["verdict"] == "GO" and result["b_gt_a"] == 5
    for row in rows:
        if row["task_id"] == EVALUATION[4] and row["condition"] == "B-agentharness":
            row["target_passed"] = False
    assert v7.finalize_results(rows)["verdict"] == "NO-GO"
