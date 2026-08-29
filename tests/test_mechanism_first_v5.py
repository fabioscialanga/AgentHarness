from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agentharness.efficacy_v5 import (
    CONDITIONS,
    EVALUATION_TASKS,
    OPAQUE_FINDING_IDS,
    TASK_DEFECTS,
    clone_pair,
    finalize_results,
    leakage_scan,
    materialize_clean_reference,
    materialize_controlled_start,
    opaque_review_feedback,
    validate_opaque_feedback,
)

ROOT = Path(__file__).resolve().parents[1]


def rows_for(*, b_failures: set[str] | None = None):
    failures = b_failures or set()
    rows = []
    for task in EVALUATION_TASKS:
        rows.append({
            "task_id": task,
            "condition": "A-baseline",
            "invocation_valid": True,
            "heldout_valid": True,
            "target_evaluated": True,
            "guards_evaluated": True,
            "target_passed": False,
            "guards_passed": True,
            "feedback_delivered": False,
        })
        rows.append({
            "task_id": task,
            "condition": "B-agentharness",
            "invocation_valid": True,
            "heldout_valid": True,
            "target_evaluated": True,
            "guards_evaluated": True,
            "target_passed": task not in failures,
            "guards_passed": True,
            "feedback_delivered": True,
            "feedback_immutable": True,
            "feedback_accounted": True,
        })
    return rows


def test_roster_orders_and_targets_are_frozen():
    assert len(EVALUATION_TASKS) == 12
    assert len(set(EVALUATION_TASKS)) == 12
    assert set(TASK_DEFECTS) == set(EVALUATION_TASKS)
    assert set(CONDITIONS) == {"A-baseline", "B-agentharness"}


def test_opaque_feedback_is_singleton_and_private_ids_do_not_leak():
    for task in EVALUATION_TASKS:
        payload = opaque_review_feedback(task)
        assert validate_opaque_feedback(payload, task_id=task) == OPAQUE_FINDING_IDS[task]
        assert TASK_DEFECTS[task] not in json.dumps(payload, sort_keys=True)
        feedback = payload["feedback"]
        assert isinstance(feedback, dict)
        items = feedback["items"]
        assert isinstance(items, list) and isinstance(items[0], dict)
        finding = items[0]
        assert all(str(finding[key]).strip() for key in ("claim_id", "status", "requirement", "observed", "remediation", "reason"))
    broken = opaque_review_feedback(EVALUATION_TASKS[0])
    broken_feedback = broken["feedback"]
    assert isinstance(broken_feedback, dict)
    broken_items = broken_feedback["items"]
    assert isinstance(broken_items, list) and isinstance(broken_items[0], dict)
    broken_items[0]["reason"] = ""
    with pytest.raises(ValueError, match="review_finding_text_invalid"):
        validate_opaque_feedback(broken, task_id=EVALUATION_TASKS[0])


def test_materialization_and_clone_are_leak_free_for_selector_and_direct_patch(tmp_path: Path):
    for index, task in enumerate(("rotating-key-token-verifier", "portable-command-receipt-ledger")):
        controlled = tmp_path / f"controlled-{index}"
        clean = tmp_path / f"clean-{index}"
        a, b = tmp_path / f"a-{index}", tmp_path / f"b-{index}"
        materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
        materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
        fingerprint = clone_pair(controlled, a, b)
        assert not leakage_scan(controlled)
        assert not leakage_scan(clean)
        assert fingerprint


def test_finalizer_go_is_exactly_ten_or_more_without_reverse_or_regression():
    assert finalize_results(rows_for())["verdict"] == "GO"
    assert finalize_results(rows_for(b_failures=set(EVALUATION_TASKS[:2])))["verdict"] == "GO"
    assert finalize_results(rows_for(b_failures=set(EVALUATION_TASKS[:3])))["verdict"] == "NO-GO"


def test_finalizer_fails_closed_on_incomplete_or_contaminated_cells():
    assert finalize_results(rows_for()[:-1])["verdict"] == "INVALID"
    rows = rows_for()
    rows[0]["feedback_delivered"] = True
    assert finalize_results(rows)["verdict"] == "INVALID"
    rows = rows_for()
    rows[1]["guards_evaluated"] = False
    assert finalize_results(rows)["verdict"] == "INVALID"


def test_v5_runner_configures_shared_engine_without_changing_source_defaults():
    path = ROOT / "benchmarks/grading-env/run_mechanism_first_v5.py"
    spec = importlib.util.spec_from_file_location("v5_runner_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
        module.configure()
        manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
        module.engine.validate_manifest_shape(manifest)
        assert module.engine.MAXIMUM_CALLS == 26
        assert module.engine.SCHEMA_VERSION == 5
        assert module.engine.RESULT_FILENAME == "MECHANISM_FIRST_V5_RESULT.json"
    finally:
        sys.path.pop(0)


def test_unknown_task_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown_v5_task"):
        materialize_controlled_start(task_id="unknown", repo_root=ROOT, destination=tmp_path / "x")
