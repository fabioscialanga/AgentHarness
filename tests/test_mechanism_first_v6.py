from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentharness.efficacy_v6 import (
    CALIBRATION_TASKS,
    CONDITION_ORDERS,
    EVALUATION_TASKS,
    TASK_CHECKS,
    TASK_DEFECTS,
    calibration_admission,
    clone_pair,
    conservative_usage_percent,
    leakage_scan,
    materialize_clean_reference,
    materialize_controlled_start,
    tree_manifest,
    validate_marker_accounting,
)
from agentharness.benchmark_heldout_evaluator_v5 import evaluate_heldout

ROOT = Path(__file__).resolve().parents[1]


def test_v6_roster_targets_and_alternating_orders_are_frozen():
    assert CALIBRATION_TASKS == EVALUATION_TASKS[:3]
    assert tuple(TASK_DEFECTS.values()) == (
        "envelope_context_binding", "capability_attenuation", "release_generation_cas",
        "csv_quoted_chunk_state", "frame_split_prefix_payload", "batch_all_or_none",
    )
    assert CONDITION_ORDERS == (
        ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
        ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
        ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
    )


@pytest.mark.parametrize("task", EVALUATION_TASKS)
def test_source_native_target_and_reference_evaluate_as_singletons(task: str, tmp_path: Path):
    clean, controlled = tmp_path / "clean", tmp_path / "controlled"
    materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
    materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
    assert leakage_scan(clean) == leakage_scan(controlled) == []
    clean_result = evaluate_heldout(clean, task, repo_root=ROOT)
    controlled_result = evaluate_heldout(controlled, task, repo_root=ROOT)
    assert clean_result["target_passed"] is True and clean_result["guards_passed"] is True
    assert controlled_result["target_passed"] is False and controlled_result["guards_passed"] is True
    assert set(controlled_result["sibling_checks"]) == set(TASK_CHECKS[task]) - {TASK_DEFECTS[task]}


def test_cloned_pair_is_byte_identical(tmp_path: Path):
    controlled = tmp_path / "controlled"
    a, b = tmp_path / "a", tmp_path / "b"
    materialize_controlled_start(task_id=EVALUATION_TASKS[-1], repo_root=ROOT, destination=controlled)
    clone_pair(controlled, a, b)
    assert tree_manifest(a) == tree_manifest(b) == tree_manifest(controlled)


def _calibration_rows(recovered: int):
    return [{
        "task_id": task, "condition": "A-baseline", "invocation_valid": True,
        "heldout_valid": True, "target_evaluated": True, "guards_evaluated": True,
        "target_passed": index < recovered, "guards_passed": True,
    } for index, task in enumerate(CALIBRATION_TASKS)]


@pytest.mark.parametrize(("recovered", "decision"), [(0, "ADMIT"), (1, "ADMIT"), (2, "CEILING"), (3, "CEILING")])
def test_calibration_gate_recovery_cases(recovered: int, decision: str):
    assert calibration_admission(_calibration_rows(recovered)) == decision


def test_calibration_gate_fails_closed_on_invalid_reference_or_guard():
    rows = _calibration_rows(0)
    rows[0]["guards_passed"] = False
    assert calibration_admission(rows) == "INVALID"


def test_quota_reducer_requires_exact_max_session_weekly_shape():
    session = SimpleNamespace(label="Session", used_percent=12.0)
    weekly = SimpleNamespace(label="Weekly", used_percent=61.0)
    assert conservative_usage_percent([session, weekly]) == 61.0
    assert conservative_usage_percent([weekly, session]) == 61.0
    for invalid in ([session], [session, session], [session, weekly, weekly],
                    [session, SimpleNamespace(label="Other", used_percent=1.0)],
                    [session, SimpleNamespace(label="Weekly", used_percent=True)]):
        with pytest.raises(ValueError, match="quota_window"):
            conservative_usage_percent(invalid)


def test_v6_runner_fully_configures_v4_engine_and_manifest():
    path = ROOT / "benchmarks/grading-env/run_mechanism_first_v6.py"
    spec = importlib.util.spec_from_file_location("v6_runner_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
        module.configure()
        manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
        module.engine.validate_manifest_shape(manifest)
        assert module.engine.MAXIMUM_CALLS == 15
        assert module.engine.SCHEMA_VERSION == 6
        assert module.engine.RESULT_FILENAME == "MECHANISM_FIRST_V6_RESULT.json"
    finally:
        sys.path.pop(0)


def test_full_marker_roster_distinguishes_reused_calibration_tasks():
    markers = []
    for index, task in enumerate(CALIBRATION_TASKS, 1):
        markers.append({
            "phase": "repair", "initial_provider_call": False,
            "invocation_id": f"v6-cal-{index:03d}:A-baseline:repair-1",
            "task_id": task, "condition": "A-baseline",
        })
    for index, task in enumerate(EVALUATION_TASKS, 1):
        for condition in ("A-baseline", "B-agentharness"):
            markers.append({
                "phase": "repair", "initial_provider_call": False,
                "invocation_id": f"v6-eval-{index:03d}:{condition}:repair-1",
                "task_id": task, "condition": condition,
            })
    assert len(markers) == 15
    validate_marker_accounting(markers, evaluation_admitted=True)
    with pytest.raises(ValueError, match="provider_marker"):
        validate_marker_accounting(markers[:-1], evaluation_admitted=True)


def test_full_synthetic_admit_path_completes_all_15_cells(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    path = ROOT / "benchmarks/grading-env/run_mechanism_first_v6.py"
    spec = importlib.util.spec_from_file_location("v6_runner_synthetic_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
        module.configure()
        manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
        manifest["execution_mode"] = "qualification"
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        run_root = tmp_path / "run"
        monkeypatch.setattr(module.engine, "preflight", lambda *_args, **_kwargs: {
            "manifest_file_sha256": "synthetic",
            "repository_commit": "synthetic",
        })
        pilot = module.engine.V4Pilot(
            manifest_path,
            run_root,
            invoker=module.engine.SyntheticRepairInvoker(calibration_repairs=0),
            usage=module.engine.synthetic_usage,
            synthetic=True,
        )
        assert pilot.run() == {"status": "collection_complete", "evaluation_calls": 12}
        state = json.loads((run_root / "campaign-state.private.json").read_text(encoding="utf-8"))
        audit = json.loads((run_root / "collection-audit.final.json").read_text(encoding="utf-8"))
        assert state["repair_calls_started"] == state["repair_calls_completed"] == 15
        assert audit["collection_complete"] is True
        assert audit["analysis_authorized"] is False
        assert len(list(run_root.rglob("provider-invocation.repair.started.json"))) == 15
        assert len(list(run_root.rglob("provider-invocation.repair.completed.json"))) == 15
    finally:
        sys.path.pop(0)
