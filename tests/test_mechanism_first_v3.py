from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

import agentharness.benchmark_heldout_evaluator_v3 as heldout_v3
from agentharness.benchmark_heldout_evaluator_v3 import evaluate_heldout
from agentharness.benchmark_review_evaluator_v3 import evaluate_review
from agentharness.efficacy_v3 import (
    CONDITION_ORDERS, CONDITIONS, TASKS, assert_leak_free, canonical_hash,
    clone_pair, finalize_results, leakage_scan, materialize_clean_reference,
    materialize_controlled_start, validate_marker_accounting, validate_opaque_feedback,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = REPO_ROOT / "benchmarks/grading-env/task-expansion-batch1/references"
RUNNER_PATH = REPO_ROOT / "benchmarks/grading-env/run_mechanism_first_v3.py"
TEMPLATE = REPO_ROOT / "benchmarks/grading-env/MECHANISM_FIRST_V3_PREREG.template.json"
SPEC = importlib.util.spec_from_file_location("mechanism_v3_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def frozen_manifest(path: Path) -> Path:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload.update({"preregistration_status": "frozen", "frozen_at": "synthetic-test",
                    "repository_commit": runner.git("rev-parse", "HEAD"),
                    "execution_mode": "qualification"})
    for relative in payload["frozen_file_sha256"]:
        payload["frozen_file_sha256"][relative] = runner.sha256_file(REPO_ROOT / relative)
    payload["hermes_command_sha256"] = runner.sha256_file(Path(payload["hermes_command"]))
    payload.pop("manifest_payload_sha256", None)
    payload["manifest_payload_sha256"] = canonical_hash(payload)
    runner.atomic_write(path, payload)
    return path


def valid_rows(*, b_wins: int = 4, a_wins: int = 0) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, task in enumerate(TASKS):
        a_pass = index < a_wins
        b_pass = index < b_wins
        for condition, passed in (("A-baseline", a_pass), ("B-agentharness", b_pass)):
            rows.append({
                "task_id": task, "condition": condition, "invocation_valid": True,
                "heldout_valid": True, "target_evaluated": True, "guards_evaluated": True,
                "target_passed": passed, "guards_passed": True,
                "feedback_delivered": condition == "B-agentharness",
                "feedback_immutable": True, "feedback_accounted": True,
            })
    return rows


def test_materializer_is_leak_free_and_cloned_start_identical() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for task in TASKS:
            controlled = root / task / "controlled"
            materialize_controlled_start(task_id=task, references_root=REFERENCES, destination=controlled)
            assert leakage_scan(controlled) == []
            assert_leak_free(controlled)
            fingerprint = clone_pair(controlled, root / task / "A", root / task / "B")
            assert fingerprint
            assert leakage_scan(root / task / "A") == leakage_scan(root / task / "B") == []


def test_reference_and_controlled_start_qualification() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for task in TASKS:
            clean = root / f"{task}-reference"
            control = root / f"{task}-control"
            materialize_clean_reference(task_id=task, references_root=REFERENCES, destination=clean)
            materialize_controlled_start(task_id=task, references_root=REFERENCES, destination=control)
            assert evaluate_heldout(clean, task)["binary_endpoint"] == 1
            endpoint = evaluate_heldout(control, task)
            assert endpoint["target_passed"] is False and endpoint["guards_passed"] is True
            feedback = evaluate_review(control, task)
            assert validate_opaque_feedback(feedback, task_id=task).startswith("finding-v3-")
            assert len(feedback["feedback"]["items"]) == 1


def test_manifest_roster_order_and_freeze_first() -> None:
    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    runner.validate_manifest_shape(manifest)
    assert [tuple(block["condition_order"]) for block in manifest["blocks"]] == list(CONDITION_ORDERS)
    assert manifest["expected_initial_provider_calls"] == 0
    assert manifest["expected_repair_provider_calls"] == 8
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(runner.IntegrityFailure, match="external frozen"):
            runner.preflight(TEMPLATE, Path(tmp) / "run", synthetic=True)


def test_qualification_freeze_uses_operational_path(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "qualification.frozen.json"

        def fake_git(*args: str) -> str:
            return "" if args[0] == "status" else "synthetic-head"

        monkeypatch.setattr(runner, "git", fake_git)
        frozen = runner.freeze_manifest(TEMPLATE, output, execution_mode="qualification")
        payload = json.loads(output.read_text())
        assert frozen["path"] == str(output.resolve())
        assert payload["execution_mode"] == "qualification"


def test_exact_marker_accounting_and_non_resumable_boundary() -> None:
    markers = [{"phase": "repair", "task_id": task, "condition": condition,
                "initial_provider_call": False} for task in TASKS for condition in CONDITIONS]
    validate_marker_accounting(markers)
    with pytest.raises(ValueError, match="roster"):
        validate_marker_accounting(markers[:-1])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = root / "campaign-state.private.json"
        runner.atomic_write(state, {"status": "running"})
        marker = root / "private-blocks/v3-001/cell-A/provider-invocation.repair.started.json"
        runner.atomic_write(marker, markers[0])
        pilot = object.__new__(runner.V3Pilot)
        pilot.run_root, pilot.state_path = root, state
        with pytest.raises(runner.IntegrityFailure, match="non-resumable"):
            pilot._reconcile()


def test_finalizer_go_no_go_and_invalid_rules() -> None:
    go = finalize_results(valid_rows())
    assert go["verdict"] == "GO" and go["b_target_recovery"] == 4
    no_go = finalize_results(valid_rows(b_wins=1))
    assert no_go["verdict"] == "NO-GO"
    regression = valid_rows()
    next(row for row in regression if row["condition"] == "B-agentharness")["guards_passed"] = False
    assert finalize_results(regression)["verdict"] == "NO-GO"
    invalid = valid_rows()
    next(row for row in invalid if row["condition"] == "B-agentharness")["feedback_accounted"] = False
    assert finalize_results(invalid)["verdict"] == "INVALID"


def test_heldout_exception_is_invalid_not_a_valid_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_workspace: Path) -> dict[str, bool]:
        raise RuntimeError("synthetic evaluator crash")

    monkeypatch.setitem(heldout_v3._EVALUATORS, TASKS[0], broken)
    with tempfile.TemporaryDirectory() as tmp:
        controlled = Path(tmp) / "controlled"
        materialize_controlled_start(task_id=TASKS[0], references_root=REFERENCES, destination=controlled)
        with pytest.raises(ValueError, match="heldout_evaluator_invalid"):
            evaluate_heldout(controlled, TASKS[0])


def test_synthetic_end_to_end_exactly_eight_and_heldout_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = frozen_manifest(root / "preregistration.frozen.json")
        run_root = root / "run"
        original_evaluate_heldout = runner.evaluate_heldout
        task_to_block = {task: f"v3-{index:03d}" for index, task in enumerate(TASKS, 1)}

        def guarded_heldout(workspace: Path, task_id: str) -> dict[str, object]:
            block = run_root / "private-blocks" / task_to_block[task_id]
            completions = list(block.glob("cell-*/provider-invocation.repair.completed.json"))
            assert len(completions) == 2
            assert all(json.loads(path.read_text())["status"] == "succeeded" for path in completions)
            return original_evaluate_heldout(workspace, task_id)

        monkeypatch.setattr(runner, "evaluate_heldout", guarded_heldout)
        pilot = runner.V3Pilot(
            manifest, run_root, invoker=runner.SyntheticRepairInvoker(),
            quota_gate=runner.synthetic_quota_gate, synthetic=True,
        )
        collection = pilot.run()
        assert collection["status"] == "collection_complete"
        assert not (run_root / "MECHANISM_FIRST_V3_RESULT.json").exists()
        with pytest.raises(runner.IntegrityFailure, match="rejects qualification"):
            runner.finalize(manifest_path=manifest, run_root=run_root)
        state = json.loads((run_root / "campaign-state.private.json").read_text())
        assert state["provider_initial_calls"] == 0 and state["repair_calls_started"] == 8
        assert state["repair_calls_completed"] == 8
        markers = pilot._markers()
        assert len(markers) == 8
        runner._validate_provider_markers(run_root, require_success=True)
        assert not list(run_root.rglob("provider-invocation.initial.started.json"))
        assert len(list(run_root.rglob("provider-invocation.repair.completed.json"))) == 8
        for path in run_root.glob("private-blocks/*/cell-B/inputs/review-feedback.json"):
            assert path.stat().st_mode & 0o777 == 0o600
        assert not list(run_root.glob("private-blocks/*/cell-A/**/*feedback*"))
        for path in run_root.glob("private-blocks/*/cell-A/cell_manifest.json"):
            cell = json.loads(path.read_text())
            assert cell["condition"] == "A-baseline"
            assert "review_feedback_path" not in cell
