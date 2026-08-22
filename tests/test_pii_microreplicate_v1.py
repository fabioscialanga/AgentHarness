from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from agentharness.efficacy_v4 import canonical_hash
from agentharness.benchmark_heldout_evaluator_v4 import evaluate_heldout

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "benchmarks/grading-env/run_pii_microreplicate_v1.py"
SPEC = importlib.util.spec_from_file_location("run_pii_microreplicate_v1", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def qualification_manifest(path: Path) -> Path:
    manifest = json.loads(runner.TEMPLATE_PATH.read_text(encoding="utf-8"))
    manifest.update(
        execution_mode="qualification",
        preregistration_status="frozen",
        frozen_at="2026-08-22T00:00:00Z",
        repository_commit=runner.git("rev-parse", "HEAD"),
    )
    for relative in manifest["frozen_file_sha256"]:
        manifest["frozen_file_sha256"][relative] = runner.sha256_file(REPO_ROOT / relative)
    manifest["hermes_command_sha256"] = runner.sha256_file(Path(manifest["hermes_command"]))
    manifest.pop("manifest_payload_sha256", None)
    manifest["manifest_payload_sha256"] = canonical_hash(manifest)
    runner.atomic_write(path, manifest, exclusive=True)
    return path


def test_template_timeout_matches_runtime() -> None:
    manifest = json.loads(runner.TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert manifest["invocation_timeout_seconds"] == runner.AGENT_INVOCATION_TIMEOUT_SECONDS


def test_micro_qualification_is_two_call_cloned_start_and_production_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        manifest = qualification_manifest(root / "manifest.json")
        run_root = root / "run"
        invoker = runner.SyntheticRepairInvoker()
        result = runner.MicroPilot(
            manifest,
            run_root,
            invoker=invoker,
            usage=runner.synthetic_usage,
            synthetic=True,
        ).run()
        assert result == {"status": "collection_complete", "provider_calls": 2}
        assert invoker.calls == [
            (runner.TASK_ID, "A-baseline"),
            (runner.TASK_ID, "B-agentharness"),
        ]
        commit = json.loads((run_root / "private-block/block-result.commit.json").read_text())
        by_condition = {cell["condition"]: cell for cell in commit["cells"]}
        assert by_condition["A-baseline"]["target_passed"] is False
        assert by_condition["B-agentharness"]["target_passed"] is True
        assert len(list(run_root.rglob("provider-invocation.repair.started.json"))) == 2
        assert len(list(run_root.rglob("provider-invocation.repair.completed.json"))) == 2
        assert len(list(run_root.rglob("*.import-audit.json"))) == 4
        with pytest.raises(runner.IntegrityFailure, match="rejects qualification"):
            runner.finalize(manifest, run_root)


def test_micro_import_audit_and_marker_tamper_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        manifest = qualification_manifest(root / "manifest.json")
        run_root = root / "run"
        runner.MicroPilot(
            manifest,
            run_root,
            invoker=runner.SyntheticRepairInvoker(),
            usage=runner.synthetic_usage,
            synthetic=True,
        ).run()
        audit_path = run_root / "private-block/cell-B/outputs/post-repair-safety-pytest.import-audit.json"
        payload = json.loads(audit_path.read_text())
        payload["violations"] = [{"module": "pii_redactor", "path": "/home/fabio/pii_redactor/__init__.py"}]
        runner.atomic_write(audit_path, payload)
        with pytest.raises(runner.IntegrityFailure, match="import isolation failed"):
            runner.validate_import_audits(run_root / "private-block/cell-B", synthetic=False)
        marker = run_root / "private-block/cell-A/provider-invocation.repair.completed.json"
        payload = json.loads(marker.read_text())
        payload["status"] = "failed"
        runner.atomic_write(marker, payload)
        with pytest.raises(runner.IntegrityFailure, match="unsuccessful"):
            runner.validate_provider_markers(run_root)


def test_pii_heldout_ignores_inherited_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        workspace = root / "controlled"
        runner.materialize_controlled_start(
            task_id=runner.TASK_ID,
            repo_root=REPO_ROOT,
            destination=workspace,
        )
        outside = root / "outside"
        outside.mkdir()
        shutil.copytree(
            REPO_ROOT / "benchmarks/grading-env/task-expansion-batch3/references/pii-redaction-pipeline/pii_redactor",
            outside / "pii_redactor",
        )
        monkeypatch.setenv("PYTHONPATH", str(outside))
        audit_path = root / "heldout-import-audit.json"
        digest = runner.write_heldout_import_audit(workspace, audit_path)
        assert digest == runner.sha256_file(audit_path)
        payload = json.loads(audit_path.read_text())
        assert all(Path(path).resolve().is_relative_to(workspace.resolve()) for path in payload["origins"].values())
        heldout = evaluate_heldout(workspace, runner.TASK_ID)
        assert heldout["target_passed"] is False


def test_micro_interpretation_is_safety_gated() -> None:
    assert runner.interpret_pair(a_target=False, a_guards=True, b_target=True, b_guards=False) == (
        0,
        0,
        "treatment_not_repaired",
    )
    assert runner.interpret_pair(a_target=False, a_guards=True, b_target=True, b_guards=True) == (
        0,
        1,
        "localized_incremental_benefit",
    )


def test_production_finalizer_positive_path_is_provider_free(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        manifest_path = qualification_manifest(root / "manifest.json")
        run_root = root / "run"
        runner.MicroPilot(
            manifest_path,
            run_root,
            invoker=runner.SyntheticRepairInvoker(),
            usage=runner.synthetic_usage,
            synthetic=True,
        ).run()
        manifest = json.loads(manifest_path.read_text())
        manifest["execution_mode"] = "real"
        manifest.pop("manifest_payload_sha256", None)
        manifest["manifest_payload_sha256"] = canonical_hash(manifest)
        runner.atomic_write(manifest_path, manifest)
        runner.atomic_write(run_root / "preregistration.frozen.json", manifest)
        manifest_hash = runner.sha256_file(manifest_path)
        state_path = run_root / "campaign-state.private.json"
        state = json.loads(state_path.read_text())
        state["execution_mode"] = "real"
        state["manifest_file_sha256"] = manifest_hash
        runner.atomic_write(state_path, state)
        audit_path = run_root / "collection-audit.final.json"
        audit = json.loads(audit_path.read_text())
        audit["execution_mode"] = "real"
        audit["analysis_authorized"] = True
        audit["manifest_file_sha256"] = manifest_hash
        runner.atomic_write(audit_path, audit)
        real_git = runner.git

        def clean_git(*args: str) -> str:
            if args[:2] == ("status", "--porcelain"):
                return ""
            return real_git(*args)

        monkeypatch.setattr(runner, "git", clean_git)
        result = runner.finalize(manifest_path, run_root)
        assert result["verdict"] == "VALID"
        assert result["A_binary_endpoint"] == 0
        assert result["B_binary_endpoint"] == 1
        assert result["interpretation"] == "localized_incremental_benefit"
