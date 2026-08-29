from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentharness import efficacy_v5 as v5
from agentharness import efficacy_v8 as v8

ROOT = Path(__file__).resolve().parents[1]
GRADING = ROOT / "benchmarks/grading-env"
CALIBRATION = (
    "context-complete-authorization-cache",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)
EVALUATION = (
    "envelope-context-decryptor",
    "attenuated-capability-verifier",
    "transactional-release-pointer",
    "context-complete-authorization-cache",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)


def load_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def load_runner(name: str = "v8_runner_test"):
    return load_path(GRADING / "run_mechanism_first_v8.py", name)


@pytest.fixture
def configured_runner():
    module = load_runner()
    engine = module.engine
    keys = (
        "TEMPLATE_PATH", "SCHEMA_VERSION", "PROTOCOL_TAG", "REPLICATE_ID", "RESULT_FILENAME",
        "MAX_TURNS", "PILOT_ID", "CALIBRATION_TASKS", "EVALUATION_TASKS", "CONDITIONS",
        "CONDITION_ORDERS", "OPAQUE_FINDING_IDS", "CALIBRATION_CALLS", "EVALUATION_CALLS",
        "MAXIMUM_CALLS", "canonical_hash", "clone_pair", "tree_fingerprint",
        "materialize_controlled_start", "materialize_clean_reference", "evaluate_heldout",
        "evaluate_review", "validate_opaque_feedback", "validate_marker_accounting",
        "calibration_admission", "quota_admission", "finalize_results",
    )
    saved = {key: getattr(engine, key) for key in keys}
    module.configure()
    try:
        yield module
    finally:
        for key, value in saved.items():
            setattr(engine, key, value)


def test_exact_v8_rosters_targets_and_alternation():
    assert v8.CALIBRATION_TASKS == CALIBRATION
    assert v8.EVALUATION_TASKS == EVALUATION
    assert v8.TASK_DEFECTS["context-complete-authorization-cache"] == "auth_cache_resource_identity"
    assert v8.CONDITION_ORDERS == (
        ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
        ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
        ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
    )


def test_configure_is_schema8_protocol_v8_and_eight_equal_turns(configured_runner):
    module = configured_runner
    manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
    module.engine.validate_manifest_shape(manifest)
    assert module.engine.MAX_TURNS == manifest["max_turns"] == 8
    assert module.engine.SCHEMA_VERSION == 8 and module.engine.PROTOCOL_TAG == "v8"
    assert module.engine.MAXIMUM_CALLS == 15
    assert manifest["cell_contract"]["provider_calls_per_cell"] == 1
    assert "same eight-turn budget" in manifest["provenance"]["turn_budget_rationale"]


def test_v4_through_v7_defaults_unchanged():
    v4 = load_path(GRADING / "run_mechanism_first_v4.py", "v4_default_v8_regression")
    assert v4.MAX_TURNS == 40 and v4.SCHEMA_VERSION == 4
    v7 = load_path(GRADING / "run_mechanism_first_v7.py", "v7_default_v8_regression")
    saved = v7.engine.MAX_TURNS
    try:
        v7.configure()
        assert v7.engine.MAX_TURNS == 6 and v7.engine.SCHEMA_VERSION == 7
    finally:
        v7.engine.MAX_TURNS = saved


@pytest.mark.parametrize("task", EVALUATION)
def test_source_native_qualification_all_six(task: str, tmp_path: Path):
    clean, controlled = tmp_path / "clean", tmp_path / "controlled"
    clean_meta = v8.materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
    controlled_meta = v8.materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
    reference = v8.evaluate_heldout(clean, task, repo_root=ROOT)
    target = v8.evaluate_heldout(controlled, task, repo_root=ROOT)
    assert reference["target_passed"] is reference["guards_passed"] is True
    assert target["target_passed"] is False and target["guards_passed"] is True
    assert reference["schema_version"] == target["schema_version"] == 8
    assert reference["evaluator_schema_version"] == target["evaluator_schema_version"] == 5
    assert clean_meta["reference_relative"] == controlled_meta["reference_relative"] == v5.REFERENCE_RELATIVE[task]
    assert clean_meta["materialization_profile"] == controlled_meta["materialization_profile"] == v8.MATERIALIZATION_PROFILE
    assert v8.leakage_scan(clean) == v8.leakage_scan(controlled) == []
    for root in (clean, controlled):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert not any(isinstance(node, (ast.If, ast.IfExp)) and isinstance(node.test, ast.Constant)
                           and type(node.test.value) is bool for node in ast.walk(tree))


def test_clean_controlled_singletons_and_clone_identity(tmp_path: Path):
    task = "context-complete-authorization-cache"
    clean, controlled = tmp_path / "clean", tmp_path / "controlled"
    a, b = tmp_path / "a", tmp_path / "b"
    v8.materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
    v8.materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
    fingerprint = v8.clone_pair(controlled, a, b)
    assert v8.tree_fingerprint(a) == v8.tree_fingerprint(b) == fingerprint
    assert v8.tree_fingerprint(clean) != fingerprint


def test_v8_scanner_catches_auth_private_id_not_in_v6_roster(tmp_path: Path):
    root = tmp_path / "visible"
    root.mkdir()
    (root / "note.txt").write_text("auth_cache_resource_identity", encoding="utf-8")
    assert v8.leakage_scan(root) == [{"path": "note.txt", "token": "auth_cache_resource_identity"}]


def markers() -> list[dict[str, object]]:
    rows = [{"phase": "repair", "initial_provider_call": False,
             "invocation_id": f"v8-cal-{index:03d}:A-baseline:repair-1",
             "task_id": task, "condition": "A-baseline"}
            for index, task in enumerate(CALIBRATION, 1)]
    rows.extend({"phase": "repair", "initial_provider_call": False,
                 "invocation_id": f"v8-eval-{index:03d}:{condition}:repair-1",
                 "task_id": task, "condition": condition}
                for index, task in enumerate(EVALUATION, 1) for condition in v8.CONDITIONS)
    return rows


def test_marker_accounting_v8_three_plus_twelve():
    roster = markers()
    assert len(roster) == 15
    v8.validate_marker_accounting(roster, evaluation_admitted=True)
    with pytest.raises(ValueError, match="provider_marker"):
        v8.validate_marker_accounting(roster[:-1], evaluation_admitted=True)
    with pytest.raises(ValueError, match="provider_marker"):
        v8.validate_marker_accounting([*roster, dict(roster[0])], evaluation_admitted=True)


def qualification_manifest(module, tmp_path: Path) -> Path:
    manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
    manifest["execution_mode"] = "qualification"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_full_synthetic_15_schema8_evaluator5(configured_runner, monkeypatch, tmp_path: Path):
    module = configured_runner
    run_root = tmp_path / "run"
    monkeypatch.setattr(module.engine, "preflight", lambda *_args, **_kwargs: {
        "manifest_file_sha256": "synthetic", "repository_commit": "synthetic",
    })
    pilot = module.engine.V4Pilot(
        qualification_manifest(module, tmp_path), run_root,
        invoker=module.engine.SyntheticRepairInvoker(calibration_repairs=0),
        usage=module.engine.synthetic_usage, synthetic=True,
    )
    assert pilot.run() == {"status": "collection_complete", "evaluation_calls": 12}
    state = json.loads((run_root / "campaign-state.private.json").read_text(encoding="utf-8"))
    assert state["repair_calls_started"] == state["repair_calls_completed"] == 15
    commits = sorted(run_root.glob("private-blocks/*/block-result.commit.json"))
    cells = [cell for path in commits for cell in json.loads(path.read_text(encoding="utf-8"))["cells"]]
    assert len(commits) == 6 and len(cells) == 12
    assert all(cell["schema_version"] == 8 and cell["evaluator_schema_version"] == 5 for cell in cells)


def test_ceiling_stops_at_three(configured_runner, monkeypatch, tmp_path: Path):
    module = configured_runner
    run_root = tmp_path / "run"
    monkeypatch.setattr(module.engine, "preflight", lambda *_args, **_kwargs: {
        "manifest_file_sha256": "synthetic", "repository_commit": "synthetic",
    })
    pilot = module.engine.V4Pilot(
        qualification_manifest(module, tmp_path), run_root,
        invoker=module.engine.SyntheticRepairInvoker(calibration_repairs=3),
        usage=module.engine.synthetic_usage, synthetic=True,
    )
    assert pilot.run() == {"status": "CEILING", "evaluation_calls": 0}
    state = json.loads((run_root / "campaign-state.private.json").read_text(encoding="utf-8"))
    assert state["repair_calls_started"] == state["repair_calls_completed"] == 3


def endpoint(task: str, condition: str, passed: bool) -> dict[str, object]:
    return {"task_id": task, "condition": condition, "invocation_valid": True,
            "heldout_valid": True, "target_evaluated": True, "guards_evaluated": True,
            "target_passed": passed, "guards_passed": True,
            "feedback_delivered": condition == "B-agentharness",
            "feedback_immutable": True, "feedback_accounted": True}


def test_quota_and_unchanged_five_of_six_threshold():
    assert v8.conservative_usage_percent([
        SimpleNamespace(label="Session", used_percent=12.0),
        SimpleNamespace(label="Weekly", used_percent=61.0),
    ]) == 61.0
    assert v8.quota_admission(70, 70) == (True, 76.0)
    assert v8.quota_admission(70.1, 70.1)[0] is False
    rows = [endpoint(task, condition, condition == "B-agentharness" and index < 5)
            for index, task in enumerate(EVALUATION) for condition in v8.CONDITIONS]
    result = v8.finalize_results(rows)
    assert result["schema_version"] == 8 and result["verdict"] == "GO" and result["b_gt_a"] == 5
    next(row for row in rows if row["task_id"] == EVALUATION[4] and row["condition"] == "B-agentharness")["target_passed"] = False
    assert v8.finalize_results(rows)["verdict"] == "NO-GO"


def test_finding_content_ids_and_public_inputs_have_no_private_tokens():
    assert all(v8.FINDING_CONTENT[task] == v5.FINDING_CONTENT[task] for task in EVALUATION)
    assert tuple(v8.OPAQUE_FINDING_IDS.values()) == tuple(f"finding-v8-{index:03d}" for index in range(1, 7))
    private = {token.casefold() for token in v8.FORBIDDEN_AGENT_TOKENS} | {
        finding.casefold() for finding in v8.OPAQUE_FINDING_IDS.values()
    }
    for task in EVALUATION:
        payload = v8.opaque_review_feedback(task)
        assert payload["schema_version"] == 8
        for name in ("SPEC.md", "CLAIMS_CONTRACT.template.json"):
            text = (ROOT / "benchmarks" / task / name).read_text(encoding="utf-8").casefold()
            assert not any(token in text for token in private)


def test_template_disclosures_budget_boundary_and_no_real_outcome_claim():
    manifest = json.loads((GRADING / "MECHANISM_FIRST_V8_PREREG.template.json").read_text(encoding="utf-8"))
    provenance = json.dumps(manifest["provenance"], sort_keys=True)
    for required in ("CEILING", "INVALID", "turn 6", "CSV diff", "two operational turns", "No real outcome", "exploratory"):
        assert required in provenance
    assert manifest["maximum_provider_calls"] == 15
    assert manifest["decision_rule"]["GO"].startswith("B>A on at least 5 of 6")
