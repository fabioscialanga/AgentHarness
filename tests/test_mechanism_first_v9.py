from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

import pytest

from agentharness import efficacy_v5 as v5
from agentharness import efficacy_v9 as v9
from agentharness.benchmark_cells import (
    AgentAttempt,
    HermesCliInvoker,
    _build_baseline_repair_prompt,
    compute_solution_hash,
)

ROOT = Path(__file__).resolve().parents[1]
GRADING = ROOT / "benchmarks/grading-env"
CALIBRATION = (
    "rotating-key-token-verifier",
    "ack-token-work-queue",
    "epoch-guarded-leader-heartbeat",
)
EVALUATION = (
    "rotating-key-token-verifier",
    "ack-token-work-queue",
    "epoch-guarded-leader-heartbeat",
    "length-prefixed-frame-parser",
    "two-tier-read-through-cache",
    "portable-command-receipt-ledger",
)


def module_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def load_runner(name: str = "v9_runner_test"):
    return load_path(GRADING / "run_mechanism_first_v9.py", name)


@pytest.fixture
def configured_runner():
    module = load_runner()
    engine = module.engine
    keys = (
        "TEMPLATE_PATH", "SCHEMA_VERSION", "PROTOCOL_TAG", "REPLICATE_ID", "RESULT_FILENAME",
        "MAX_TURNS", "REQUIRE_MODEL_REPAIR_RESPONSE", "PILOT_ID", "CALIBRATION_TASKS",
        "EVALUATION_TASKS", "CONDITIONS", "CONDITION_ORDERS", "OPAQUE_FINDING_IDS",
        "CALIBRATION_CALLS", "EVALUATION_CALLS", "MAXIMUM_CALLS", "canonical_hash",
        "clone_pair", "tree_fingerprint", "materialize_controlled_start",
        "materialize_clean_reference", "evaluate_heldout", "evaluate_review",
        "validate_opaque_feedback", "validate_marker_accounting", "calibration_admission",
        "quota_admission", "finalize_results",
    )
    saved = {key: getattr(engine, key) for key in keys}
    module.configure()
    try:
        yield module
    finally:
        for key, value in saved.items():
            setattr(engine, key, value)


def test_exact_v9_rosters_are_unobserved_and_alternating():
    assert v9.CALIBRATION_TASKS == CALIBRATION
    assert v9.EVALUATION_TASKS == EVALUATION
    observed = {
        "envelope-context-decryptor", "attenuated-capability-verifier",
        "transactional-release-pointer", "streaming-csv-quoted-records",
        "context-complete-authorization-cache",
    }
    assert not observed.intersection(EVALUATION)
    assert v9.CONDITION_ORDERS == tuple(
        v9.CONDITIONS if i % 2 == 0 else tuple(reversed(v9.CONDITIONS))
        for i in range(6)
    )


def test_configure_binds_schema9_eight_turns_and_controller_receipt(configured_runner):
    module = configured_runner
    manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
    module.engine.validate_manifest_shape(manifest)
    assert module.engine.SCHEMA_VERSION == 9 and module.engine.PROTOCOL_TAG == "v9"
    assert module.engine.MAX_TURNS == manifest["max_turns"] == 8
    assert module.engine.REQUIRE_MODEL_REPAIR_RESPONSE is False
    assert manifest["cell_contract"]["require_model_repair_response"] is False
    assert module.engine.MAXIMUM_CALLS == 15


def test_old_default_still_requires_model_response():
    v4 = load_path(GRADING / "run_mechanism_first_v4.py", "v4_v9_default")
    assert v4.REQUIRE_MODEL_REPAIR_RESPONSE is True
    assert v4.MAX_TURNS == 40


def test_prompt_omits_receipt_contract_only_in_itt_mode(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = tmp_path / "SPEC.md"
    out = tmp_path / "pytest.stdout"
    err = tmp_path / "pytest.stderr"
    for path in (spec, out, err):
        path.write_text("x\n", encoding="utf-8")
    old = _build_baseline_repair_prompt(
        task_id="task", workspace=workspace, spec_path=spec,
        pytest_stdout_path=out, pytest_stderr_path=err,
    )
    itt = _build_baseline_repair_prompt(
        task_id="task", workspace=workspace, spec_path=spec,
        pytest_stdout_path=out, pytest_stderr_path=err, require_repair_response=False,
    )
    assert "repair-response.json" in old
    assert "repair-response.json" not in itt
    assert "Make targeted fixes" in itt


def test_real_cloned_repair_path_accepts_missing_model_receipt(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text("VALUE = 0\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        "[project]\nname='v9-fixture'\nversion='0.1.0'\ndependencies=[]\n",
        encoding="utf-8",
    )
    spec = tmp_path / "SPEC.md"
    claims = tmp_path / "CLAIMS_CONTRACT.template.json"
    spec.write_text("Set VALUE to one.\n", encoding="utf-8")
    claims.write_text("{}\n", encoding="utf-8")
    outputs = tmp_path / "outputs"
    stdout = tmp_path / "pytest.stdout"
    stderr = tmp_path / "pytest.stderr"
    stdout.write_text("1 failed\n", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    pytest_payload = {
        "command": ["python", "-m", "pytest", "-q"], "exit_code": 1,
        "stdout_path": str(stdout), "stderr_path": str(stderr),
    }
    manifest: dict[str, object] = {
        "task_id": "v9-fixture", "condition": "A-baseline", "run_id": "v9-fixture-a",
        "invocation_id": "v9-cal-001:A-baseline:repair-1",
        "spec_path": str(spec), "claims_template_path": str(claims),
        "initial_origin": {"solution_hash": compute_solution_hash(workspace)},
    }
    invoker = HermesCliInvoker(
        hermes_command="hermes", max_retries=1, require_model_repair_response=False,
    )

    def fake_invoke(*, prompt: str, attempt_name: str, prompt_kind: str,
                    outputs_dir: Path, workspace: Path) -> AgentAttempt:
        assert "repair-response.json" not in prompt
        (workspace / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
        out = outputs_dir / f"{attempt_name}.stdout"
        err = outputs_dir / f"{attempt_name}.stderr"
        out.write_text("session_id: v9_fake\n", encoding="utf-8")
        err.write_text("", encoding="utf-8")
        return AgentAttempt(
            attempt_name=attempt_name, prompt_kind=prompt_kind, command=["fake"], exit_code=0,
            stdout_path=out, stderr_path=err, working_directory=workspace,
            session_id="v9_fake", started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z", duration_seconds=1.0,
        )

    with (
        mock.patch.object(invoker, "_invoke", side_effect=fake_invoke),
        mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
        mock.patch("agentharness.benchmark_cells.manifest_install_state", return_value={
            "ok": True, "detail": "ok", "infrastructure_error": False,
        }),
    ):
        result = invoker.run_cloned_repair(manifest, outputs, workspace)
    delivery = cast(dict[str, object], result.treatment_delivery)
    assert delivery["controller_delivery_receipt_valid"] is True
    assert delivery["model_repair_response_required"] is False
    assert delivery["repair_response_valid"] is None
    assert delivery["repair_change_retained"] is True
    receipt_path = outputs / "controller-delivery-receipt.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["task_id"] == "v9-fixture"
    assert receipt["run_id"] == "v9-fixture-a"
    assert receipt["invocation_id"] == "v9-cal-001:A-baseline:repair-1"
    assert receipt["session_id"] == "v9_fake" and receipt["exit_code"] == 0
    assert receipt["invocation_evidence_present"] is True
    for key in ("invocation_stdout", "invocation_stderr"):
        artifact = Path(receipt[f"{key}_path"])
        assert artifact.is_file()
        assert receipt[f"{key}_sha256"] == module_sha256(artifact)
    assert not (workspace / ".agentharness" / "repair-response.json").exists()


def test_itt_accounting_accepts_no_model_receipt_symmetrically(configured_runner):
    engine = configured_runner.engine
    for task, condition in ((EVALUATION[0], "A-baseline"), (EVALUATION[0], "B-agentharness")):
        feedback = condition == "B-agentharness"
        result = SimpleNamespace(
            attempts=[{"exit_code": 0}],
            treatment_delivery={
                "repair_invocation_succeeded": True,
                "repair_invocation_evidence_present": True,
                "treatment_prompt_immutable": True,
                "controller_delivery_receipt_valid": True,
                "controller_delivery_receipt_path": "/synthetic/controller-delivery-receipt.json",
                "controller_delivery_receipt_sha256": "0" * 64,
                "model_repair_response_required": False,
                "model_response_required": False,
                "repair_response_valid": None,
                "feedback_items_accounted": None,
                "feedback_delivered": feedback,
                "feedback_immutable": True if feedback else None,
                "feedback_claim_ids": [v9.OPAQUE_FINDING_IDS[task]] if feedback else [],
            },
        )
        row = engine.accounting(result, condition, task)
        assert row["invocation_valid"] is True
        assert row["feedback_delivered"] is feedback


def test_itt_b_still_requires_feedback_delivery(configured_runner):
    engine = configured_runner.engine
    task = EVALUATION[0]
    result = SimpleNamespace(attempts=[{}], treatment_delivery={
        "repair_invocation_succeeded": True, "repair_invocation_evidence_present": True,
        "treatment_prompt_immutable": True,
        "controller_delivery_receipt_valid": True,
        "controller_delivery_receipt_path": "/synthetic/controller-delivery-receipt.json",
        "controller_delivery_receipt_sha256": "0" * 64,
        "model_repair_response_required": False,
        "model_response_required": False, "feedback_delivered": False,
        "feedback_immutable": False, "feedback_claim_ids": [v9.OPAQUE_FINDING_IDS[task]],
    })
    with pytest.raises(engine.InvocationFailure, match="feedback accounting"):
        engine.accounting(result, "B-agentharness", task)


@pytest.mark.parametrize("missing", (
    "repair_invocation_evidence_present",
    "controller_delivery_receipt_path",
    "controller_delivery_receipt_sha256",
))
def test_itt_accounting_rejects_incomplete_controller_receipt(configured_runner, missing: str):
    engine = configured_runner.engine
    delivery: dict[str, object] = {
        "repair_invocation_succeeded": True,
        "repair_invocation_evidence_present": True,
        "treatment_prompt_immutable": True,
        "controller_delivery_receipt_valid": True,
        "controller_delivery_receipt_path": "/synthetic/controller-delivery-receipt.json",
        "controller_delivery_receipt_sha256": "0" * 64,
        "model_repair_response_required": False,
        "model_response_required": False,
        "feedback_delivered": False,
        "feedback_immutable": None,
        "feedback_claim_ids": [],
    }
    delivery.pop(missing)
    result = SimpleNamespace(attempts=[{}], treatment_delivery=delivery)
    with pytest.raises(engine.InvocationFailure, match="controller delivery accounting"):
        engine.accounting(result, "A-baseline", EVALUATION[0])


@pytest.mark.parametrize("task", EVALUATION)
def test_source_native_clean_and_singleton_all_six(task: str, tmp_path: Path):
    clean, controlled = tmp_path / "clean", tmp_path / "controlled"
    clean_meta = v9.materialize_clean_reference(task_id=task, repo_root=ROOT, destination=clean)
    controlled_meta = v9.materialize_controlled_start(task_id=task, repo_root=ROOT, destination=controlled)
    reference = v9.evaluate_heldout(clean, task, repo_root=ROOT)
    target = v9.evaluate_heldout(controlled, task, repo_root=ROOT)
    assert reference["target_passed"] is reference["guards_passed"] is True
    assert target["target_passed"] is False and target["guards_passed"] is True
    assert reference["schema_version"] == target["schema_version"] == 9
    assert reference["evaluator_schema_version"] == target["evaluator_schema_version"] == 5
    assert clean_meta["reference_relative"] == controlled_meta["reference_relative"] == v5.REFERENCE_RELATIVE[task]
    assert v9.leakage_scan(clean) == v9.leakage_scan(controlled) == []
    for root in (clean, controlled):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert not any(
                isinstance(node, (ast.If, ast.IfExp)) and isinstance(node.test, ast.Constant)
                and type(node.test.value) is bool for node in ast.walk(tree)
            )


def test_clone_identity_and_scanner(tmp_path: Path):
    seed, a, b = tmp_path / "seed", tmp_path / "a", tmp_path / "b"
    v9.materialize_controlled_start(task_id=EVALUATION[0], repo_root=ROOT, destination=seed)
    fingerprint = v9.clone_pair(seed, a, b)
    assert v9.tree_fingerprint(a) == v9.tree_fingerprint(b) == fingerprint
    visible = tmp_path / "visible"
    visible.mkdir()
    (visible / "note.txt").write_text(v9.TASK_DEFECTS[EVALUATION[0]], encoding="utf-8")
    assert v9.leakage_scan(visible)


def marker_roster() -> list[dict[str, object]]:
    rows = [{"phase": "repair", "initial_provider_call": False,
             "invocation_id": f"v9-cal-{i:03d}:A-baseline:repair-1",
             "task_id": task, "condition": "A-baseline"}
            for i, task in enumerate(CALIBRATION, 1)]
    rows.extend({"phase": "repair", "initial_provider_call": False,
                 "invocation_id": f"v9-eval-{i:03d}:{condition}:repair-1",
                 "task_id": task, "condition": condition}
                for i, task in enumerate(EVALUATION, 1) for condition in v9.CONDITIONS)
    return rows


def test_marker_accounting_exact_three_plus_twelve():
    rows = marker_roster()
    assert len(rows) == 15
    v9.validate_marker_accounting(rows, evaluation_admitted=True)
    with pytest.raises(ValueError, match="provider_marker"):
        v9.validate_marker_accounting(rows[:-1], evaluation_admitted=True)


def qualification_manifest(module, tmp_path: Path) -> Path:
    manifest = json.loads(module.TEMPLATE_PATH.read_text(encoding="utf-8"))
    manifest["execution_mode"] = "qualification"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_full_synthetic_15_call_itt_path(configured_runner, monkeypatch, tmp_path: Path):
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
    assert len(cells) == 12
    assert all(cell["schema_version"] == 9 and cell["evaluator_schema_version"] == 5 for cell in cells)


def endpoint(task: str, condition: str, passed: bool) -> dict[str, object]:
    return {"task_id": task, "condition": condition, "invocation_valid": True,
            "heldout_valid": True, "target_evaluated": True, "guards_evaluated": True,
            "target_passed": passed, "guards_passed": True,
            "feedback_delivered": condition == "B-agentharness",
            "feedback_immutable": True, "feedback_accounted": True}


def test_quota_and_finalizer_threshold_preserve_exact_task_ids():
    assert v9.conservative_usage_percent([
        SimpleNamespace(label="Session", used_percent=12.0),
        SimpleNamespace(label="Weekly", used_percent=61.0),
    ]) == 61.0
    assert v9.quota_admission(70, 70) == (True, 76.0)
    rows = [endpoint(task, condition, condition == "B-agentharness" and i < 5)
            for i, task in enumerate(EVALUATION) for condition in v9.CONDITIONS]
    result = v9.finalize_results(rows)
    assert result["schema_version"] == 9 and result["verdict"] == "GO"
    pairs = cast(list[dict[str, object]], result["paired_binary_endpoints"])
    assert [pair["task_id"] for pair in pairs] == list(EVALUATION)


def test_findings_and_template_disclose_itt_and_outcome_awareness():
    assert tuple(v9.OPAQUE_FINDING_IDS.values()) == tuple(f"finding-v9-{i:03d}" for i in range(1, 7))
    for task in EVALUATION:
        payload = v9.opaque_review_feedback(task)
        assert payload["schema_version"] == 9
        assert v9.validate_opaque_feedback(payload, task_id=task) == v9.OPAQUE_FINDING_IDS[task]
    manifest = json.loads((GRADING / "MECHANISM_FIRST_V9_PREREG.template.json").read_text(encoding="utf-8"))
    text = json.dumps(manifest["provenance"], sort_keys=True)
    frozen = set(manifest["frozen_file_sha256"])
    required = {
        "src/agentharness/efficacy_v4.py",
        "src/agentharness/benchmark_cells.py",
        "src/agentharness/benchmarking.py",
        "src/agentharness/evaluation.py",
        "src/agentharness/repair_safety.py",
        "src/agentharness/reexecution.py",
        "benchmarks/grading-env/run_mechanism_first_v4.py",
        "benchmarks/grading-env/run_mechanism_first_v9.py",
        "benchmarks/grading-env/MECHANISM_FIRST_V9_PREREG.template.json",
        "benchmarks/grading-env/v5_2_receipt_process_driver.py",
    }
    for task in EVALUATION:
        required.update({
            f"benchmarks/{task}/SPEC.md",
            f"benchmarks/{task}/CLAIMS_CONTRACT.template.json",
        })
        reference = ROOT / v9.REFERENCE_RELATIVE[task]
        required.update(
            path.relative_to(ROOT).as_posix()
            for path in reference.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".db", ".sqlite", ".sqlite3"}
            and path.name != "README.md"
        )
    assert required <= frozen
    for required_text in ("CEILING", "INVALID", "outcome-aware", "ITT", "no claim", "overlap"):
        assert required_text.casefold() in text.casefold()
    assert manifest["maximum_provider_calls"] == 15
    assert manifest["decision_rule"]["GO"].startswith("B>A on at least 5 of 6")
