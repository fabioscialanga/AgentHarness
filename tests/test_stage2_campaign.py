from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentharness.stage2_analysis import write_json

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "benchmarks" / "grading-env" / "run_stage2_efficacy_campaign.py"
FREEZE = REPO_ROOT / "benchmarks" / "grading-env" / "STAGE2_EFFICACY_FREEZE_2026-07-18_ACCOUNT2.json"
SPEC = importlib.util.spec_from_file_location("stage2_campaign_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
FINALIZER_SCRIPT = REPO_ROOT / "benchmarks" / "grading-env" / "finalize_stage2_efficacy.py"
FINALIZER_SPEC = importlib.util.spec_from_file_location("stage2_campaign_finalizer", FINALIZER_SCRIPT)
assert FINALIZER_SPEC is not None and FINALIZER_SPEC.loader is not None
finalizer = importlib.util.module_from_spec(FINALIZER_SPEC)
FINALIZER_SPEC.loader.exec_module(finalizer)


def fake_git(*args: str) -> str:
    if args == ("ls-files", "--error-unmatch", runner.NORMATIVE_MANIFEST_RELATIVE):
        return ""
    if args == ("status", "--porcelain"):
        return ""
    if args in (
        ("rev-parse", "HEAD"),
        ("rev-parse", "origin/main"),
        ("rev-parse", f"refs/tags/{runner.AMENDED_FREEZE_TAG}^{{commit}}"),
    ):
        return "frozen-commit"
    raise AssertionError(args)


def _base_final_row(*, task_id: str, condition: str, replicate_id: str, block_id: str, slot: int, score: float) -> dict[str, Any]:
    cell_id = f"{block_id}-s{slot}"
    return {
        "task_id": task_id,
        "condition": condition,
        "replicate_id": replicate_id,
        "block_id": block_id,
        "campaign_cell_id": cell_id,
        "slot": slot,
        "execution_attempt_no": 1,
        "score": score,
        "benchmark_execution_status": "valid",
        "benchmark_outcome_status": "success" if score >= 0.999 else "real_failure",
        "benchmark_classification_reason": None,
        "heldout_endpoint_denominator": 6,
        "heldout_endpoint_valid": True,
        "heldout_endpoint_error": None,
        "treatment_delivered": True,
        "feedback_delivered": condition == "B-agentharness",
        "treatment_prompt_sha256_pre": "a" * 64,
        "treatment_prompt_sha256_post": "a" * 64,
        "treatment_prompt_immutable": True,
        "feedback_sha256_pre": "b" * 64 if condition == "B-agentharness" else None,
        "feedback_sha256_post": "b" * 64 if condition == "B-agentharness" else None,
        "feedback_immutable": condition == "B-agentharness",
        "solution_hash_changed_between_attempt_and_repair": condition == "B-agentharness",
        "verify_run_ok": condition == "B-agentharness",
        "agent_duration_seconds": 100.0 + (20.0 if condition == "B-agentharness" else 0.0),
        "agent_invocation_count": 2,
    }


def manifest_synthetic_progress(manifest: dict[str, Any], *, true_effect: float, seed: int) -> list[dict[str, Any]]:
    """Build a full 120-cell progress list bound exactly to the frozen block roster.

    Only scores vary (deterministically, per task); block/task/replicate/condition/slot
    identities are taken verbatim from the manifest so normative binding is preserved.
    """
    rng = random.Random(seed)
    tasks = list(manifest["tasks"])
    task_base = {task: 0.55 + 0.01 * index + rng.uniform(-0.02, 0.02) for index, task in enumerate(tasks)}
    rows: list[dict[str, Any]] = []
    for block in manifest["blocks"]:
        block_id = str(block["block_id"])
        task_id = str(block["task_id"])
        replicate_id = str(block["replicate_id"])
        base = task_base[task_id]
        for slot, condition in enumerate(block["condition_order"], start=1):
            raw = base + (true_effect if condition == "B-agentharness" else 0.0)
            score = round(max(0.0, min(1.0, raw)) * 6) / 6
            final = _base_final_row(
                task_id=task_id, condition=condition, replicate_id=replicate_id,
                block_id=block_id, slot=slot, score=score,
            )
            rows.append(
                {
                    "task_id": task_id,
                    "condition": condition,
                    "replicate_id": replicate_id,
                    "block_id": block_id,
                    "campaign_cell_id": final["campaign_cell_id"],
                    "final": final,
                }
            )
    return rows


def bind_synthetic_credential_amendment(
    *,
    run_root: Path,
    state: dict[str, Any],
    seal: dict[str, Any],
    manifest: dict[str, Any],
    repository_commit: str,
) -> None:
    audit = {
        "schema_version": 1,
        "amendment": "17.36-credential-tranche-continuation",
        "outcome_blind": True,
        "migration_complete": True,
        "analysis_authorized": False,
        "new_manifest_payload_sha256": manifest["manifest_payload_sha256"],
        "new_manifest_file_sha256": finalizer.sha256(FREEZE),
        "new_repository_commit": repository_commit,
        "preserved_pair_complete_blocks": [f"b{i:03d}" for i in range(1, 19)],
        "boundary_block_restarted": "b019",
        "account_fingerprints_sha256": {
            "codex-account-tranche-1": "1" * 64,
            "codex-account-tranche-2": "2" * 64,
        },
    }
    audit_path = run_root / finalizer.AMENDMENT_AUDIT_NAME
    write_json(audit_path, audit)
    audit_sha = finalizer.sha256(audit_path)
    state["credential_tranche_amendment_sha256"] = audit_sha
    seal["credential_tranche_amendment_sha256"] = audit_sha
    write_json(run_root / "campaign-state.private.json", state)
    write_json(run_root / "dataset-seal.json", seal)


class Stage2CampaignRunnerTests(unittest.TestCase):
    def test_frozen_manifest_has_exact_20_by_3_by_2_shape(self) -> None:
        manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["tasks"]), 20)
        self.assertEqual(manifest["replicates"], ["r1", "r2", "r3"])
        self.assertEqual(len(manifest["blocks"]), 60)
        self.assertEqual(manifest["expected_cells"], 120)
        self.assertEqual(
            len({(row["task_id"], row["replicate_id"]) for row in manifest["blocks"]}),
            60,
        )
        self.assertEqual(
            {row["block_id"] for row in manifest["blocks"]},
            {f"b{index:03d}" for index in range(1, 61)},
        )
        self.assertTrue(
            all(
                sorted(row["condition_order"]) == ["A-baseline", "B-agentharness"]
                for row in manifest["blocks"]
            )
        )

    def test_preflight_accepts_frozen_hashes_on_clean_synced_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            campaign = runner.Stage2Campaign(
                manifest_path=FREEZE,
                run_root=Path(tmp_dir) / "run",
            )
            with mock.patch.object(runner, "git", side_effect=fake_git), mock.patch.dict(
                os.environ,
                {"HERMES_HOME": "/home/fabio/.hermes/profiles/stage2codex2"},
            ):
                result = campaign.preflight()
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_count"], 20)
        self.assertEqual(result["block_count"], 60)
        self.assertEqual(result["cell_count"], 120)
        self.assertEqual(len(result["manifest_file_sha256"]), 64)

    def test_preflight_rejects_unpinned_hermes_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            campaign = runner.Stage2Campaign(
                manifest_path=FREEZE,
                run_root=Path(tmp_dir) / "run",
            )
            with mock.patch.object(runner, "git", side_effect=fake_git), mock.patch.dict(
                os.environ,
                {"HERMES_HOME": "/home/fabio/.hermes"},
            ):
                with self.assertRaises(runner.ProvenanceMismatch):
                    campaign.preflight()

    def test_preflight_rejects_non_normative_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            alt_manifest = Path(tmp_dir) / "alt-manifest.json"
            alt_manifest.write_text(FREEZE.read_text(encoding="utf-8"), encoding="utf-8")
            campaign = runner.Stage2Campaign(manifest_path=alt_manifest, run_root=Path(tmp_dir) / "run")
            with self.assertRaises(runner.ProvenanceMismatch):
                campaign.preflight()

    def test_preflight_rejects_run_root_inside_repository(self) -> None:
        campaign = runner.Stage2Campaign(
            manifest_path=FREEZE,
            run_root=REPO_ROOT / "benchmarks" / "grading-env" / "_disallowed_in_repo_run_root",
        )
        with self.assertRaises(runner.IntegrityFailure):
            campaign.preflight()

    def test_block_journal_requires_pair_completeness_and_commits_exact_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=run_root)
            block = campaign.manifest["blocks"][0]
            block_id = str(block["block_id"])
            row_a = _base_final_row(
                task_id=str(block["task_id"]), condition=str(block["condition_order"][0]),
                replicate_id=str(block["replicate_id"]), block_id=block_id, slot=1, score=1.0,
            )
            row_b = _base_final_row(
                task_id=str(block["task_id"]), condition=str(block["condition_order"][1]),
                replicate_id=str(block["replicate_id"]), block_id=block_id, slot=2, score=1.0,
            )
            with self.assertRaises(runner.IntegrityFailure):
                campaign._commit_block(block, {1: row_a})
            rows = campaign._commit_block(block, {1: row_a, 2: row_b})
            self.assertEqual(len(rows), 2)
            journal_path = campaign._journal_path(block_id)
            self.assertTrue(journal_path.is_file())
            self.assertEqual(stat.S_IMODE(journal_path.stat().st_mode), 0o600)
            with self.assertRaises(runner.IntegrityFailure):
                campaign._commit_block(block, {1: row_a, 2: row_b})

    def test_load_committed_blocks_rebuilds_progress_in_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=run_root)
            blocks = campaign.manifest["blocks"]
            second_block, first_block = blocks[5], blocks[2]
            for block in (second_block, first_block):
                block_id = str(block["block_id"])
                row_a = _base_final_row(
                    task_id=str(block["task_id"]), condition=str(block["condition_order"][0]),
                    replicate_id=str(block["replicate_id"]), block_id=block_id, slot=1, score=0.5,
                )
                row_b = _base_final_row(
                    task_id=str(block["task_id"]), condition=str(block["condition_order"][1]),
                    replicate_id=str(block["replicate_id"]), block_id=block_id, slot=2, score=0.5,
                )
                campaign._commit_block(block, {1: row_a, 2: row_b})
            committed = campaign._load_committed_blocks()
            self.assertEqual(set(committed.keys()), {str(first_block["block_id"]), str(second_block["block_id"])})
            progress = campaign._rebuild_progress(committed)
            self.assertEqual(len(progress), 4)
            observed_block_order = [row["block_id"] for row in progress]
            self.assertEqual(
                observed_block_order,
                [str(first_block["block_id"])] * 2 + [str(second_block["block_id"])] * 2,
            )

    def test_reconcile_crashed_attempts_archives_incomplete_cell_and_counts_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=run_root)
            block = campaign.manifest["blocks"][0]
            cell_id = f"{block['block_id']}-s1"
            cell_dir = campaign._cell_dir(cell_id)
            cell_dir.mkdir(parents=True)
            (cell_dir / "partial-output.txt").write_text("interrupted", encoding="utf-8")
            state = campaign._initial_state(
                {
                    "manifest_sha256": campaign.manifest["manifest_payload_sha256"],
                    "manifest_file_sha256": "irrelevant",
                    "repository_commit": "irrelevant",
                }
            )
            campaign._reconcile_crashed_attempts(state)
            self.assertFalse(cell_dir.exists())
            counters = state["counters"]
            self.assertEqual(counters["crash_recoveries"].get(cell_id), 1)
            quarantine_root = run_root / "quarantine" / cell_id
            archived = list(quarantine_root.iterdir())
            self.assertEqual(len(archived), 1)
            self.assertTrue(archived[0].name.endswith("crash_recovery"))
            self.assertEqual(stat.S_IMODE(quarantine_root.stat().st_mode), 0o700)

    def test_reconcile_completed_invocations_without_commit_consumes_harness_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=run_root)
            block = campaign.manifest["blocks"][0]
            cell_id = f"{block['block_id']}-s1"
            cell_dir = campaign._cell_dir(cell_id)
            meta_dir = cell_dir / "outputs" / "agent-invocations"
            meta_dir.mkdir(parents=True)
            write_json(meta_dir / "attempt-1-initial.meta.json", {"duration_seconds": 1.0})
            write_json(meta_dir / "attempt-2-repair.meta.json", {"duration_seconds": 1.0})
            state = campaign._initial_state(
                {
                    "manifest_sha256": campaign.manifest["manifest_payload_sha256"],
                    "manifest_file_sha256": "irrelevant",
                    "repository_commit": "irrelevant",
                }
            )
            state["current_cell"] = {
                "cell_id": cell_id,
                "block_id": str(block["block_id"]),
                "task_id": str(block["task_id"]),
                "replicate_id": str(block["replicate_id"]),
                "condition": str(block["condition_order"][0]),
                "slot": 1,
                "attempt_no": 1,
            }
            state["counters"]["physical_cell_attempts"][cell_id] = 1
            campaign._reconcile_crashed_attempts(state)
            self.assertEqual(state["counters"]["harness_reruns"].get(cell_id), 1)
            self.assertIsNone(state["counters"]["crash_recoveries"].get(cell_id))
            archived = list((run_root / "quarantine" / cell_id).iterdir())
            self.assertEqual(len(archived), 1)
            self.assertTrue(archived[0].name.endswith("harness_invalid_recovery"))
            self.assertIsNone(state["current_cell"])

    def test_reconcile_exhausted_rerun_replays_without_agent_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=run_root)
            block = campaign.manifest["blocks"][0]
            cell_id = f"{block['block_id']}-s1"
            cell_dir = campaign._cell_dir(cell_id)
            meta_dir = cell_dir / "outputs" / "agent-invocations"
            meta_dir.mkdir(parents=True)
            write_json(meta_dir / "attempt-1-initial.meta.json", {"duration_seconds": 1.0})
            write_json(meta_dir / "attempt-2-repair.meta.json", {"duration_seconds": 1.0})
            state = campaign._initial_state(
                {
                    "manifest_sha256": campaign.manifest["manifest_payload_sha256"],
                    "manifest_file_sha256": "irrelevant",
                    "repository_commit": "irrelevant",
                }
            )
            state["current_cell"] = {
                "cell_id": cell_id,
                "block_id": str(block["block_id"]),
                "task_id": str(block["task_id"]),
                "replicate_id": str(block["replicate_id"]),
                "condition": str(block["condition_order"][0]),
                "slot": 1,
                "attempt_no": 2,
            }
            state["counters"]["physical_cell_attempts"][cell_id] = 2
            state["counters"]["harness_reruns"][cell_id] = 1
            replay_result = _base_final_row(
                task_id=str(block["task_id"]),
                condition=str(block["condition_order"][0]),
                replicate_id=str(block["replicate_id"]),
                block_id=str(block["block_id"]),
                slot=1,
                score=0.5,
            )
            with mock.patch.object(
                runner, "replay_uncommitted_successful_invocations", return_value=replay_result
            ) as replay_mock, mock.patch.object(
                campaign, "_assert_amended_account_identity"
            ) as account_guard:
                campaign._reconcile_crashed_attempts(state)
            account_guard.assert_called_once_with()
            replay_mock.assert_called_once_with(cell_dir)
            committed = json.loads((cell_dir / "cell-result.commit.json").read_text(encoding="utf-8"))
            self.assertTrue(committed["recovered_without_agent_reinvocation"])
            self.assertEqual(committed["execution_attempt_no"], 2)
            self.assertFalse((run_root / "quarantine" / cell_id / "attempt-02-harness_invalid_recovery").exists())
            self.assertIsNone(state["current_cell"])

    def test_validate_current_cell_rejects_tampered_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=Path(tmp_dir) / "run")
            block = campaign.manifest["blocks"][0]
            tampered = {
                "cell_id": f"{block['block_id']}-s1",
                "block_id": str(block["block_id"]),
                "task_id": str(block["task_id"]),
                "replicate_id": str(block["replicate_id"]),
                "condition": "B-agentharness" if block["condition_order"][0] == "A-baseline" else "A-baseline",
                "slot": 1,
                "attempt_no": 1,
            }
            with self.assertRaises(runner.IntegrityFailure):
                campaign._validate_current_cell(tampered)

    def test_atomic_write_private_mode_survives_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "private.json"
            runner.atomic_write(path, {"a": 1}, mode=0o600)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            runner.atomic_write(path, {"a": 2}, mode=0o600)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["a"], 2)

    def test_exclusive_lock_second_acquire_raises_concurrent_runner_exit_31(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = Path(tmp_dir) / "campaign.lock"
            with runner.exclusive_lock(lock_path):
                with self.assertRaises(runner.ConcurrentRunner) as ctx:
                    with runner.exclusive_lock(lock_path):
                        pass
                self.assertEqual(ctx.exception.exit_code, runner.CONCURRENT_RUNNER)
                self.assertEqual(runner.CONCURRENT_RUNNER, 31)

    def test_cost_aggregation_includes_quarantined_attempts_without_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            campaign = runner.Stage2Campaign(manifest_path=FREEZE, run_root=run_root)
            cell_id = "b001-s1"
            quarantine_meta = run_root / "quarantine" / cell_id / "attempt-01-harness_invalid_rerun" / "outputs" / "agent-invocations"
            quarantine_meta.mkdir(parents=True)
            write_json(quarantine_meta / "attempt-1-initial.meta.json", {"duration_seconds": 12.5})
            final_dir = run_root / "private-cells" / cell_id
            final_meta = final_dir / "outputs" / "agent-invocations"
            final_meta.mkdir(parents=True)
            write_json(final_meta / "attempt-1-initial.meta.json", {"duration_seconds": 7.5})
            write_json(final_meta / "attempt-2-repair.meta.json", {"duration_seconds": 5.0})
            cost = campaign._aggregate_cell_cost(cell_id, final_dir)
            self.assertEqual(cost["agent_invocation_count"], 3)
            self.assertAlmostEqual(cost["agent_duration_seconds"], 25.0)
            self.assertEqual(len(set(cost["agent_invocation_attempt_ids"])), 3)

    def test_account_identity_guard_rejects_mid_cell_credential_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir) / "profile"
            home.mkdir()
            auth_path = home / "auth.json"
            write_json(
                auth_path,
                {
                    "providers": {
                        "openai-codex": {"tokens": {"account_id": "account-before"}}
                    }
                },
            )
            campaign = runner.Stage2Campaign(
                manifest_path=FREEZE, run_root=Path(tmp_dir) / "run"
            )
            campaign.manifest["hermes_home"] = str(home)
            campaign.quota.expected_account_fingerprint = runner.codex_account_fingerprint(auth_path)
            campaign._assert_amended_account_identity()
            write_json(
                auth_path,
                {
                    "providers": {
                        "openai-codex": {"tokens": {"account_id": "account-after"}}
                    }
                },
            )
            with self.assertRaises(runner.ProvenanceMismatch):
                campaign._assert_amended_account_identity()

    def test_finalizer_rejects_when_sealed_dataset_diverges_from_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            run_root.mkdir()
            manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
            progress = manifest_synthetic_progress(manifest, true_effect=0.25, seed=41)
            progress_path = run_root / "progress.private.json"
            write_json(progress_path, progress)
            rebuilt = finalizer.build_dataset_from_progress(progress_path)
            tampered = [dict(row) for row in rebuilt]
            tampered[0]["score"] = 0.0 if tampered[0]["score"] != 0.0 else 1.0
            dataset_path = run_root / "analysis-dataset.sealed.json"
            write_json(dataset_path, tampered)
            write_json(
                run_root / "campaign-state.private.json",
                {
                    "status": "complete",
                    "manifest_sha256": manifest["manifest_payload_sha256"],
                    "manifest_file_sha256": finalizer.sha256(FREEZE),
                    "repository_commit": "frozen-commit",
                },
            )
            write_json(
                run_root / "dataset-seal.json",
                {
                    "dataset_sha256": finalizer.sha256(dataset_path),
                    "progress_sha256": finalizer.sha256(progress_path),
                    "manifest_file_sha256": finalizer.sha256(FREEZE),
                    "repository_commit": "frozen-commit",
                    "blocks": 60,
                },
            )
            bind_synthetic_credential_amendment(
                run_root=run_root,
                state=json.loads((run_root / "campaign-state.private.json").read_text()),
                seal=json.loads((run_root / "dataset-seal.json").read_text()),
                manifest=manifest,
                repository_commit="frozen-commit",
            )
            with mock.patch.object(finalizer, "git", return_value="frozen-commit"):
                with self.assertRaises(ValueError):
                    finalizer.finalize(manifest_path=FREEZE, run_root=run_root)

    def test_finalizer_runs_end_to_end_only_on_sealed_complete_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            run_root.mkdir()
            manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
            progress = manifest_synthetic_progress(manifest, true_effect=0.25, seed=17)
            progress_path = run_root / "progress.private.json"
            write_json(progress_path, progress)
            dataset_path = run_root / "analysis-dataset.sealed.json"
            write_json(dataset_path, finalizer.build_dataset_from_progress(progress_path))
            write_json(
                run_root / "campaign-state.private.json",
                {
                    "status": "complete",
                    "manifest_sha256": manifest["manifest_payload_sha256"],
                    "manifest_file_sha256": finalizer.sha256(FREEZE),
                    "repository_commit": "frozen-commit",
                },
            )
            write_json(
                run_root / "dataset-seal.json",
                {
                    "dataset_sha256": finalizer.sha256(dataset_path),
                    "progress_sha256": finalizer.sha256(progress_path),
                    "manifest_file_sha256": finalizer.sha256(FREEZE),
                    "repository_commit": "frozen-commit",
                    "blocks": 60,
                },
            )
            bind_synthetic_credential_amendment(
                run_root=run_root,
                state=json.loads((run_root / "campaign-state.private.json").read_text()),
                seal=json.loads((run_root / "dataset-seal.json").read_text()),
                manifest=manifest,
                repository_commit="frozen-commit",
            )
            with mock.patch.object(finalizer, "git", return_value="frozen-commit"):
                result = finalizer.finalize(manifest_path=FREEZE, run_root=run_root)
            self.assertTrue((run_root / "STAGE2_EFFICACY_RESULT.json").is_file())
            seal_path = run_root / "STAGE2_EFFICACY_FINALIZATION_SEAL.json"
            self.assertTrue(seal_path.is_file())
            seal_payload = json.loads(seal_path.read_text(encoding="utf-8"))
            self.assertTrue(seal_payload["authorized"])
            self.assertEqual(seal_payload["repository_commit"], "frozen-commit")
            self.assertEqual(stat.S_IMODE(seal_path.stat().st_mode), 0o600)
            self.assertIn(
                result["headline"],
                {"improvement_supported", "inconclusive", "no_meaningful_effect"},
            )
            self.assertEqual(len(result["output_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
