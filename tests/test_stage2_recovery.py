from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentharness.stage2_recovery import (
    EXCLUDED_LEGACY_TASKS,
    RECOVERY_QUALIFICATION,
    RECOVERY_SCOPE,
    RecoveryError,
    build_recovery,
    finalize_recovery,
    select_first_attempt,
    sha256_file,
    validate_replay_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT = REPO_ROOT / "benchmarks" / "grading-env" / "STAGE2_RECOVERY_AMENDMENT_2026-07-25.json"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def terminal_payload(*, gating_errors: list[str] | None = None) -> dict[str, object]:
    statuses = ["passed", "failed", "passed", "failed", "passed", "failed"]
    return {
        "ok": False,
        "gating_errors": [] if gating_errors is None else gating_errors,
        "results": [
            {"case_id": f"case-{index}", "status": status}
            for index, status in enumerate(statuses, start=1)
        ],
    }


class FakeEvaluation:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def to_dict(self) -> dict[str, object]:
        return self.payload


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.run_root = root / "original-run"
        self.output_root = root / "recovery-output"
        self.manifest_path = root / "manifest.json"
        self.amendment_path = root / "amendment.json"
        self.tasks = [f"recoverable-{index:02d}" for index in range(1, 17)] + sorted(EXCLUDED_LEGACY_TASKS)
        self.blocks: list[dict[str, Any]] = []
        for task_index, task in enumerate(self.tasks):
            for replicate in range(1, 4):
                number = task_index * 3 + replicate
                self.blocks.append(
                    {
                        "block_id": f"b{number:03d}",
                        "task_id": task,
                        "replicate_id": f"r{replicate}",
                        "condition_order": ["A-baseline", "B-agentharness"],
                    }
                )
        self.manifest = {
            "schema_version": 1,
            "campaign_id": "synthetic-stage2",
            "tasks": self.tasks,
            "blocks": self.blocks,
            "expected_cells": 120,
            "expected_blocks": 60,
            "mme": 0.10,
            "analysis_parameters": {
                "cluster_seed": 20260703,
                "cluster_resamples": 111,
                "wild_seed": 20260704,
                "wild_resamples": 222,
            },
        }
        write_json(self.manifest_path, self.manifest)
        self.amendment_path.write_bytes(AMENDMENT.read_bytes())
        self.progress: list[dict[str, object]] = []
        for block in self.blocks:
            rows = []
            for slot, condition in enumerate(block["condition_order"], start=1):
                cell_id = f"{block['block_id']}-s{slot}"
                final = self._final(
                    task=str(block["task_id"]),
                    condition=str(condition),
                    replicate=str(block["replicate_id"]),
                    block=str(block["block_id"]),
                    cell=cell_id,
                    slot=slot,
                )
                row = {
                    "task_id": block["task_id"],
                    "condition": condition,
                    "replicate_id": block["replicate_id"],
                    "block_id": block["block_id"],
                    "campaign_cell_id": cell_id,
                    "final": final,
                }
                self.progress.append(row)
                rows.append(final)
                self._attempt(cell_id, attempt=1, task=str(block["task_id"]), condition=str(condition))
            write_json(
                self.run_root / "block-journals" / f"{block['block_id']}.commit.json",
                {"block_id": block["block_id"], "rows": rows},
            )
        # The first retained cell has a quarantined attempt 1 and a final attempt 2.
        first = "b001-s1"
        final = self.run_root / "private-cells" / first
        for path in sorted(final.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        final.rmdir()
        self._attempt(first, attempt=1, task="recoverable-01", condition="A-baseline", quarantine=True, duration=3.5)
        self._attempt(first, attempt=2, task="recoverable-01", condition="A-baseline", duration=8.0)
        (self.run_root / "quarantine" / first / "attempt-00-account-tranche-boundary").mkdir(parents=True)

        progress_path = self.run_root / "progress.private.json"
        dataset_path = self.run_root / "analysis-dataset.sealed.json"
        write_json(progress_path, self.progress)
        write_json(dataset_path, [])
        repository_commit = "synthetic-frozen-commit"
        write_json(
            self.run_root / "campaign-state.private.json",
            {"status": "complete", "repository_commit": repository_commit},
        )
        write_json(
            self.run_root / "dataset-seal.json",
            {
                "manifest_file_sha256": sha256_file(self.manifest_path),
                "repository_commit": repository_commit,
                "progress_sha256": sha256_file(progress_path),
                "dataset_sha256": sha256_file(dataset_path),
                "rows": 120,
                "blocks": 60,
            },
        )

    @staticmethod
    def _final(*, task: str, condition: str, replicate: str, block: str, cell: str, slot: int) -> dict[str, object]:
        return {
            "task_id": task,
            "condition": condition,
            "replicate_id": replicate,
            "block_id": block,
            "campaign_cell_id": cell,
            "slot": slot,
            "execution_attempt_no": 1,
            "score": 0.0,
            "benchmark_execution_status": "harness_invalid",
            "benchmark_outcome_status": "invalid",
            "benchmark_classification_reason": "synthetic old endpoint gate",
            "heldout_endpoint_denominator": 6,
            "heldout_endpoint_valid": False,
            "treatment_delivered": True,
            "feedback_delivered": condition == "B-agentharness",
            "treatment_prompt_sha256_pre": "a" * 64,
            "treatment_prompt_sha256_post": "a" * 64,
            "treatment_prompt_immutable": True,
            "feedback_sha256_pre": "b" * 64 if condition == "B-agentharness" else None,
            "feedback_sha256_post": "b" * 64 if condition == "B-agentharness" else None,
            "feedback_immutable": condition == "B-agentharness",
            "solution_hash_changed_between_attempt_and_repair": False,
            "verify_run_ok": False,
            "agent_duration_seconds": 999.0,
        }

    def _attempt(
        self,
        cell: str,
        *,
        attempt: int,
        task: str,
        condition: str,
        quarantine: bool = False,
        duration: float = 1.25,
    ) -> None:
        base = (
            self.run_root / "quarantine" / cell / f"attempt-{attempt:02d}-harness_invalid_rerun"
            if quarantine
            else self.run_root / "private-cells" / cell
        )
        workspace = base / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "solution.txt").write_text("synthetic", encoding="utf-8")
        run_id = f"synthetic-stage2_{cell}_a{attempt}"
        write_json(
            base / "cell_manifest.json",
            {"run_id": run_id, "task_id": task, "condition": condition, "workspace": str(workspace)},
        )
        write_json(base / "run.json", {"run_id": run_id, "workspace": str(workspace), "artifacts": {}})
        write_json(
            base / "outputs" / "suite.json",
            {
                "schema_version": 1,
                "suite_id": f"{task}_heldout_eval",
                "run_id": run_id,
                "cases": [
                    {"id": f"case-{index}", "type": "text_contains", "path": "solution.txt", "expected": {"contains": ["synthetic"]}}
                    for index in range(1, 7)
                ],
            },
        )
        delivery = {
            "treatment_delivered": True,
            "repair_invocation_succeeded": True,
            "feedback_delivered": condition == "B-agentharness",
            "treatment_prompt_sha256_pre": "a" * 64,
            "treatment_prompt_sha256_post": "a" * 64,
            "treatment_prompt_immutable": True,
            "feedback_sha256_pre": "b" * 64 if condition == "B-agentharness" else None,
            "feedback_sha256_post": "b" * 64 if condition == "B-agentharness" else None,
            "feedback_immutable": condition == "B-agentharness",
        }
        write_json(
            base / "provenance.json",
            {
                "task_id": task,
                "condition": condition,
                "replicate_id": f"r{((int(cell[1:4]) - 1) % 3) + 1}",
                "run_id": run_id,
                "solution_hash": "c" * 64,
                "attempt_solution_hashes": {"attempt_1_initial": "d" * 64, "attempt_2_repair": "c" * 64},
                "solution_hash_changed_between_attempt_and_repair": True,
                "treatment_delivery": delivery,
            },
        )
        write_json(base / "outputs" / "agent-invocations" / "attempt-1.meta.json", {"duration_seconds": duration})


class Stage2RecoveryTests(unittest.TestCase):
    def test_ok_false_with_six_terminal_results_is_valid(self) -> None:
        score = validate_replay_payload(terminal_payload(), expected_ids=[f"case-{i}" for i in range(1, 7)])
        self.assertEqual(score, 0.5)

    def test_gating_error_is_invalid(self) -> None:
        with self.assertRaisesRegex(RecoveryError, "gating errors"):
            validate_replay_payload(
                terminal_payload(gating_errors=["synthetic envelope mismatch"]),
                expected_ids=[f"case-{i}" for i in range(1, 7)],
            )

    def test_first_attempt_selection_ignores_boundary_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            selected, number = select_first_attempt(fixture.run_root, "b001-s1")
            self.assertEqual(number, 1)
            self.assertEqual(selected.name, "attempt-01-harness_invalid_rerun")

    def test_builder_end_to_end_excludes_legacy_and_never_writes_original_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            before = tree_digest(fixture.run_root)

            result = build_recovery(
                run_root=fixture.run_root,
                output_root=fixture.output_root,
                manifest_path=fixture.manifest_path,
                amendment_path=fixture.amendment_path,
            )
            after = tree_digest(fixture.run_root)
            self.assertEqual(before, after)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(list((fixture.output_root / "traces").glob("*.jsonl"))), 96)
            progress = json.loads((fixture.output_root / "recovery-progress.private.json").read_text())
            self.assertEqual(len(progress), 96)
            self.assertFalse({row["task_id"] for row in progress} & EXCLUDED_LEGACY_TASKS)
            first = next(row for row in progress if row["campaign_cell_id"] == "b001-s1")
            self.assertEqual(first["final"]["execution_attempt_no"], 1)
            self.assertEqual(first["final"]["agent_duration_seconds"], 3.5)
            self.assertFalse(json.loads((fixture.output_root / "recovery-seal.json").read_text())["analysis_authorized"])

    def test_authorization_hash_mismatch_fails_closed_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery = root / "recovery"
            recovery.mkdir()
            dataset = recovery / "recovery-analysis-dataset.sealed.json"
            progress = recovery / "recovery-progress.private.json"
            write_json(dataset, [])
            write_json(progress, [])
            manifest = root / "manifest.json"
            write_json(manifest, {"tasks": []})
            seal = recovery / "recovery-seal.json"
            write_json(
                seal,
                {
                    "scope": RECOVERY_SCOPE,
                    "analysis_authorized": False,
                    "recovery_dataset_sha256": sha256_file(dataset),
                    "recovery_progress_sha256": sha256_file(progress),
                    "manifest_file_sha256": sha256_file(manifest),
                },
            )
            auth = root / "RECOVERY_ANALYSIS_AUTHORIZATION.json"
            write_json(
                auth,
                {
                    "scope": RECOVERY_SCOPE,
                    "analysis_authorized": True,
                    "recovery_dataset_sha256": "0" * 64,
                    "recovery_seal_sha256": sha256_file(seal),
                },
            )
            output = root / "analysis-output"
            with self.assertRaisesRegex(RecoveryError, "dataset hash mismatch"):
                finalize_recovery(
                    recovery_root=recovery,
                    output_root=output,
                    manifest_path=manifest,
                    authorization_path=auth,
                )
            self.assertFalse(output.exists())

    def test_authorized_finalizer_is_non_confirmatory_and_uses_frozen_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))

            def evaluator(*args: object, **kwargs: object) -> FakeEvaluation:
                del args
                trace = Path(str(kwargs["trace_path"]))
                trace.parent.mkdir(parents=True, exist_ok=True)
                trace.write_text("{}\n", encoding="utf-8")
                return FakeEvaluation(terminal_payload())

            build_recovery(
                run_root=fixture.run_root,
                output_root=fixture.output_root,
                manifest_path=fixture.manifest_path,
                amendment_path=fixture.amendment_path,
                evaluator=evaluator,
            )
            dataset = fixture.output_root / "recovery-analysis-dataset.sealed.json"
            seal = fixture.output_root / "recovery-seal.json"
            auth = Path(tmp) / "RECOVERY_ANALYSIS_AUTHORIZATION.json"
            write_json(
                auth,
                {
                    "scope": RECOVERY_SCOPE,
                    "analysis_authorized": True,
                    "recovery_dataset_sha256": sha256_file(dataset),
                    "recovery_seal_sha256": sha256_file(seal),
                },
            )
            fake_report = {"decision": {"public_claim_classification": "must-be-overridden"}}
            analysis_output = Path(tmp) / "authorized-analysis"
            with mock.patch("agentharness.stage2_recovery.run_full_analysis", return_value=fake_report) as run:
                result = finalize_recovery(
                    recovery_root=fixture.output_root,
                    output_root=analysis_output,
                    manifest_path=fixture.manifest_path,
                    authorization_path=auth,
                )
            self.assertEqual(result["status"], "PASS")
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs["mme"], 0.10)
            self.assertEqual(kwargs["cluster_resamples"], 111)
            self.assertEqual(kwargs["wild_resamples"], 222)
            report = json.loads((analysis_output / "STAGE2_RECOVERY_EXPLORATORY_RESULT.json").read_text())
            self.assertFalse(report["confirmatory"])
            self.assertFalse(report["public_claim_confirmatory"])
            self.assertEqual(report["qualification"], RECOVERY_QUALIFICATION)
            self.assertEqual(report["analysis"]["decision"]["public_claim_classification"], RECOVERY_QUALIFICATION)
            self.assertFalse(report["analysis"]["decision"]["confirmatory_public_claim_allowed"])


if __name__ == "__main__":
    unittest.main()
