from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from agentharness.benchmark_cells import (
    AgentAttempt,
    AgentInvocationResult,
    _feedback_claim_ids,
    _inspect_verify_feedback_report,
    repair_passes_used,
    write_provenance,
)
from agentharness.efficacy_v2 import (
    SCHEMA_GATE_ID,
    TASKS,
    TASK_PARTITIONS,
    clone_tree_identical,
    filter_evaluation_report,
    partition_ids,
    review_feedback_from_report,
    score_heldout_report,
    validate_suite_partition,
    verify_clone_pair,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "benchmarks/grading-env/run_exploratory_actionable_repair_v2.py"
MANIFEST_PATH = REPO_ROOT / "benchmarks/grading-env/EXPLORATORY_ACTIONABLE_REPAIR_V2_CLONED_START_PREREG.json"
SPEC = importlib.util.spec_from_file_location("efficacy_v2_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def report_for(task: str, statuses: dict[str, str] | None = None) -> dict[str, object]:
    statuses = statuses or {}
    ids = list(partition_ids(task, "review")) + list(partition_ids(task, "heldout")) + [SCHEMA_GATE_ID]
    return {
        "results": [
            {"case_id": case_id, "status": statuses.get(case_id, "passed"), "reason": f"detail:{case_id}"}
            for case_id in ids
        ]
    }


def attempt(root: Path, prompt_kind: str, name: str) -> AgentAttempt:
    root.mkdir(parents=True, exist_ok=True)
    stdout, stderr = root / f"{name}.stdout", root / f"{name}.stderr"
    stdout.write_text(f"session_id: {name}\n", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    return AgentAttempt(
        attempt_name=name, prompt_kind=prompt_kind, command=["fake"], exit_code=0,
        stdout_path=stdout, stderr_path=stderr, working_directory=root,
        session_id=name, started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z", duration_seconds=1.0,
    )


def test_batch1_roster_and_frozen_partitions_match_every_suite() -> None:
    assert TASKS == (
        "appointment-booking-api", "shipment-event-api",
        "jsonl-event-aggregation", "invoice-payment-reconciliation",
    )
    for task in TASKS:
        suite = json.loads((REPO_ROOT / "benchmarks" / task / "HELDOUT_EVALUATION_SUITE.template.json").read_text())
        validate_suite_partition(task, suite)
        review, heldout = set(partition_ids(task, "review")), set(partition_ids(task, "heldout"))
        assert len(review) == 2 and len(heldout) == 3
        assert not review & heldout
        assert review | heldout | {SCHEMA_GATE_ID} == {case["id"] for case in suite["cases"]}


def test_manifest_is_complete_counterbalanced_and_explicitly_unfrozen() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    runner.validate_manifest_shape(manifest)
    assert [block["condition_order"][0] for block in manifest["blocks"]] == [
        "A-baseline", "B-agentharness", "A-baseline", "B-agentharness"
    ]
    assert manifest["repository_commit"].startswith("FREEZE_REQUIRED:")
    assert manifest["manifest_payload_sha256"].startswith("FREEZE_REQUIRED:")
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(runner.IntegrityFailure, match="external frozen preregistration"):
            runner.preflight(MANIFEST_PATH, Path(tmp) / "run")


def test_manifest_rejects_task_roster_swap_even_when_block_ids_are_valid() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["blocks"][0]["task_id"], manifest["blocks"][1]["task_id"] = (
        manifest["blocks"][1]["task_id"], manifest["blocks"][0]["task_id"],
    )
    with pytest.raises(runner.IntegrityFailure, match="task roster/order"):
        runner.validate_manifest_shape(manifest)


def test_freeze_manifest_materializes_external_immutable_preregistration() -> None:
    def fake_git(*args: str) -> str:
        if args[:2] == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        raise AssertionError(args)

    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner, "git", side_effect=fake_git):
        output = Path(tmp) / "preregistration.frozen.json"
        receipt = runner.freeze_manifest(template_path=MANIFEST_PATH, output_path=output)
        frozen = json.loads(output.read_text())
        assert frozen["repository_commit"] == "a" * 40
        assert frozen["preregistration_status"] == "frozen"
        assert not runner._contains_placeholder(frozen)
        payload = dict(frozen)
        expected = payload.pop("manifest_payload_sha256")
        assert runner.canonical_hash(payload) == expected
        assert receipt["sha256"] == runner.sha256_file(output)
        with pytest.raises(runner.IntegrityFailure, match="overwrite"):
            runner.freeze_manifest(template_path=MANIFEST_PATH, output_path=output)


def test_review_filter_and_feedback_never_leak_heldout() -> None:
    task = TASKS[0]
    statuses = {partition_ids(task, "review")[0]: "failed", partition_ids(task, "heldout")[0]: "failed"}
    raw = report_for(task, statuses)
    filtered = filter_evaluation_report(raw, task_id=task, partition="review")
    serialized = json.dumps(filtered)
    assert {row["case_id"] for row in filtered["results"]} == set(partition_ids(task, "review"))
    assert all(case_id not in serialized for case_id in partition_ids(task, "heldout"))
    feedback = review_feedback_from_report(raw, task_id=task)
    feedback_text = json.dumps(feedback)
    assert [item["claim_id"] for item in feedback["feedback"]["items"]] == [partition_ids(task, "review")[0]]
    item = feedback["feedback"]["items"][0]
    assert isinstance(item, dict)
    assert item["requirement"] and item["observed"] and item["remediation"]
    assert all(case_id not in feedback_text for case_id in partition_ids(task, "heldout"))


def test_score_is_over_three_and_schema_is_gate_not_scored() -> None:
    task = TASKS[1]
    heldout = partition_ids(task, "heldout")
    assert score_heldout_report(report_for(task, {heldout[0]: "failed"}), task_id=task) == pytest.approx(2 / 3)
    assert score_heldout_report(report_for(task), task_id=task) == 1.0
    with pytest.raises(ValueError, match="schema_gate"):
        score_heldout_report(report_for(task, {SCHEMA_GATE_ID: "failed"}), task_id=task)
    incomplete = report_for(task)
    incomplete["results"] = [row for row in incomplete["results"] if row["case_id"] != heldout[0]]
    with pytest.raises(ValueError, match="incomplete"):
        score_heldout_report(incomplete, task_id=task)
    gated = report_for(task)
    gated["gating_errors"] = ["evaluator unavailable"]
    with pytest.raises(ValueError, match="gating_errors"):
        score_heldout_report(gated, task_id=task)


def test_resume_refuses_incomplete_block_after_any_provider_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        block = root / "private-blocks" / "p001"
        block.mkdir(parents=True)
        runner.atomic_write(block / "provider-invocation.initial.started.json", {"phase": "initial"})
        collector = object.__new__(runner.ExploratoryClonedStartPilot)
        collector.run_root = root
        collector.state_path = root / "campaign-state.private.json"
        state = {"current_block": {"block_id": "p001"}, "resume_count": 1}
        with pytest.raises(runner.IntegrityFailure, match="non-resumable"):
            collector._reconcile(state)


def test_sandbox_wrapper_mounts_only_current_cell_and_private_auth() -> None:
    script = (REPO_ROOT / "benchmarks/grading-env/run_hermes_stage2codex2_docker.sh").read_text()
    proxy = (REPO_ROOT / "benchmarks/grading-env/codex_egress_proxy.py").read_text()
    probe = (REPO_ROOT / "benchmarks/grading-env/codex_egress_probe.py").read_text()
    assert "dst=/experiment" in script and "dst=/hermes-home" in script
    agent_block = script.rsplit("docker run --rm \\", 1)[1]
    assert '--name "$agent"' in agent_block
    assert '--network "$network"' in agent_block
    assert "--read-only" in agent_block and "--cap-drop ALL" in agent_block
    assert "--security-opt no-new-privileges" in agent_block
    assert "docker network create --internal" in script and 'HTTP_PROXY=http://egress-proxy:8080' in script
    assert "SOURCE_PROFILE/auth.json" in script and "SOURCE_PROFILE/config.yaml" in script
    assert 'private_profile="$profile_base/$token"' in script
    assert 'rm -rf -- "$private_profile"' in script
    assert "/var/run/docker.sock" not in script
    assert 'ALLOWED_HOSTS = ("chatgpt.com", "auth.openai.com", "api.openai.com")' in proxy
    assert 'raw.githubusercontent.com' in probe and 'direct Internet bypass unexpectedly reachable' in probe


def test_clone_pair_is_byte_and_metadata_identical_before_operations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "initial"
        source.mkdir()
        (source / "empty").mkdir()
        executable = source / "run.sh"
        executable.write_bytes(b"#!/bin/sh\nprintf ok\n")
        executable.chmod(0o751)
        (source / "payload.bin").write_bytes(b"\x00\xff\x10")
        clone_tree_identical(source, root / "A")
        clone_tree_identical(source, root / "B")
        fingerprint = verify_clone_pair(source, root / "A", root / "B")
        assert fingerprint
        (root / "B" / "payload.bin").write_bytes(b"changed")
        with pytest.raises(ValueError, match="not_byte_identical"):
            verify_clone_pair(source, root / "A", root / "B")


def test_one_real_initial_origin_plus_two_local_repairs_no_synthetic_attempts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        initial = AgentInvocationResult(attempts=[attempt(root / "initial", "initial", "real-initial")])
        cell_a = AgentInvocationResult(attempts=[attempt(root / "A", "repair", "repair-A")])
        cell_b = AgentInvocationResult(attempts=[attempt(root / "B", "repair", "repair-B")])
        assert len(initial.attempts) == 1
        assert repair_passes_used(initial) == 0
        assert repair_passes_used(cell_a) == repair_passes_used(cell_b) == 1
        assert all(item.prompt_kind == "repair" for result in (cell_a, cell_b) for item in result.attempts)
        assert sum(len(result.attempts) for result in (initial, cell_a, cell_b)) == 3


def test_collect_block_wires_one_initial_two_isolated_repairs_and_commits() -> None:
    task = TASKS[0]

    class FakeInvoker:
        def run_initial_generation(self, manifest: dict[str, object], outputs: Path, workspace: Path) -> AgentInvocationResult:
            (workspace / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
            return AgentInvocationResult(attempts=[attempt(outputs, "initial", "initial")])

    def fake_execute(cell_dir: Path, _invoker: object) -> dict[str, object]:
        manifest = json.loads((cell_dir / "cell_manifest.json").read_text())
        outputs = cell_dir / "outputs"
        outputs.mkdir()
        (outputs / "evaluation-report.json").write_text(json.dumps(report_for(task)) + "\n")
        return {
            "task_id": task,
            "condition": manifest["condition"],
            "treatment_delivered": True,
            "heldout_endpoint_valid": True,
            "benchmark_execution_status": "valid",
            "benchmark_classification_reason": "behavior_correct",
            "attempt_count": 1,
            "feedback_items_accounted": True,
        }

    review_status = {partition_ids(task, "review")[0]: "failed"}
    feedback = review_feedback_from_report(report_for(task, review_status), task_id=task)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pilot = runner.ExploratoryClonedStartPilot(MANIFEST_PATH, root)
        state: dict[str, object] = {"resume_count": 0, "current_block": None, "status": "ready"}
        block = json.loads(MANIFEST_PATH.read_text())["blocks"][0]
        with (
            mock.patch.object(pilot, "_invoker", return_value=FakeInvoker()),
            mock.patch.object(runner, "_quota_gate", return_value=None),
            mock.patch.object(runner, "execute_cell", side_effect=fake_execute),
            mock.patch.object(runner, "review_evaluation_on_temporary_clone", return_value=feedback),
        ):
            pilot._collect_block(state, block)
        block_dir = root / "private-blocks" / "p001"
        commit = json.loads((block_dir / "block-result.commit.json").read_text())
        assert len(commit["cells"]) == 2
        assert (block_dir / "provider-invocation.initial.started.json").is_file()
        assert all((block_dir / f"cell-{label}" / "provider-invocation.repair.started.json").is_file() for label in ("A", "B"))
        manifest_a = json.loads((block_dir / "cell-A" / "cell_manifest.json").read_text())
        manifest_b = json.loads((block_dir / "cell-B" / "cell_manifest.json").read_text())
        assert "review_feedback_path" not in manifest_a
        assert Path(manifest_b["review_feedback_path"]).parent == block_dir / "cell-B" / "inputs"


def test_v2_provenance_contains_initial_origin_and_only_local_repair() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "solution.py").write_text("VALUE = 1\n")
        repair = attempt(root / "attempts", "repair", "repair-A")
        initial_origin = {"path": "/private/origin.json", "solution_hash": "abc", "tree_fingerprint": "def"}
        manifest = {
            "task_id": TASKS[0], "condition": "A-baseline", "replicate_id": "v2-r1",
            "run_id": "v2-test", "initial_origin": initial_origin,
        }
        provenance = write_provenance(
            provenance_path=root / "provenance.json", manifest=manifest, workspace=workspace,
            invocation_result=AgentInvocationResult(
                attempts=[repair],
                attempt_solution_hashes={"attempt_1_initial": "abc", "attempt_2_repair": "xyz"},
            ),
            pytest_result={"exit_code": 0},
        )
        assert provenance["initial_origin"] == initial_origin
        assert provenance["attempt_count"] == 1
        assert [item["prompt_kind"] for item in provenance["attempts"]] == ["repair"]


def test_zero_review_findings_is_valid_and_yields_empty_expected_ids() -> None:
    task = TASKS[2]
    feedback = review_feedback_from_report(report_for(task), task_id=task)
    assert feedback["feedback"]["items"] == []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "feedback.json"
        path.write_text(json.dumps(feedback))
        inspection = _inspect_verify_feedback_report(path)
        assert inspection["report_valid"] is True
        assert _feedback_claim_ids(path) == []


def test_unknown_case_id_is_rejected_before_filtering() -> None:
    raw = report_for(TASKS[0])
    raw["results"].append({"case_id": "secret_extra", "status": "failed"})
    with pytest.raises(ValueError, match="unknown_ids"):
        filter_evaluation_report(raw, task_id=TASKS[0], partition="review")


def test_finalizer_rejects_repository_or_audit_mismatch() -> None:
    def frozen(value: object) -> object:
        if isinstance(value, str) and value.startswith("FREEZE_REQUIRED:"):
            return "synthetic-frozen-value"
        if isinstance(value, list):
            return [frozen(item) for item in value]
        if isinstance(value, dict):
            return {key: frozen(item) for key, item in value.items()}
        return value

    manifest = frozen(json.loads(MANIFEST_PATH.read_text()))
    assert isinstance(manifest, dict)
    manifest["preregistration_status"] = "frozen"
    manifest["repository_commit"] = "expected"
    manifest.pop("manifest_payload_sha256", None)
    manifest["manifest_payload_sha256"] = runner.canonical_hash(manifest)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "run"
        root.mkdir()
        external_manifest = Path(tmp) / "preregistration.frozen.json"
        runner.atomic_write(external_manifest, manifest)
        (root / "preregistration.frozen.json").write_bytes(external_manifest.read_bytes())
        manifest_sha = runner.sha256_file(external_manifest)
        runner.atomic_write(root / "campaign-state.private.json", {
            "status": "complete", "repository_commit": "different",
            "manifest_file_sha256": manifest_sha,
        })
        runner.atomic_write(root / "collection-audit.final.json", {
            "collection_complete": True, "analysis_authorized": True,
            "repository_commit": manifest["repository_commit"],
            "manifest_file_sha256": manifest_sha,
            "block_commit_sha256": {},
        })
        with pytest.raises(runner.IntegrityFailure, match="repository binding mismatch"):
            runner.finalize(manifest_path=external_manifest, run_root=root)


def test_block_commit_rejects_asymmetric_initial_origin_and_invocation_count() -> None:
    task = TASKS[0]
    base_cell = {
        "task_id": task,
        "initial_origin_sha256": "origin",
        "initial_solution_hash": "solution",
        "clone_pre_repair_fingerprint": "tree",
        "repair_passes_used": 1,
        "attempt_count": 1,
        "score": 2 / 3,
    }
    commit = {
        "block_id": "p001",
        "task_id": task,
        "initial_origin_sha256": "origin",
        "initial_solution_hash": "solution",
        "clone_fingerprint": "tree",
        "cells": [
            {**base_cell, "condition": "A-baseline"},
            {**base_cell, "condition": "B-agentharness"},
        ],
    }
    assert len(runner.validate_block_commit(commit, block_id="p001", expected_task=task)) == 2
    asymmetric = json.loads(json.dumps(commit))
    asymmetric["cells"][1]["initial_solution_hash"] = "different"
    with pytest.raises(runner.IntegrityFailure, match="pair initial origin mismatch"):
        runner.validate_block_commit(asymmetric, block_id="p001", expected_task=task)
    extra_invocation = json.loads(json.dumps(commit))
    extra_invocation["cells"][0]["attempt_count"] = 2
    with pytest.raises(runner.IntegrityFailure, match="unexpected local invocation count"):
        runner.validate_block_commit(extra_invocation, block_id="p001", expected_task=task)
