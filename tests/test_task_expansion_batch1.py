from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentharness.benchmark_hidden_evaluators import evaluate_benchmark_task

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = REPO_ROOT / "benchmarks"
REFERENCES = BENCHMARKS / "grading-env" / "task-expansion-batch1" / "references"
MUTATION_SENSITIVITY = json.loads(
    (BENCHMARKS / "grading-env" / "task-expansion-batch1" / "MUTATION_SENSITIVITY.json").read_text(encoding="utf-8")
)["tasks"]

TASK_CHECKS = {
    "appointment-booking-api": [
        "appointment_create_and_filters",
        "appointment_interval_validation",
        "appointment_provider_conflicts",
        "appointment_reschedule_atomic",
        "appointment_cancel_releases_slot",
    ],
    "shipment-event-api": [
        "shipment_create_and_filters",
        "shipment_valid_transition_path",
        "shipment_skipped_transition_atomic",
        "shipment_event_idempotency",
        "shipment_time_and_terminal_invariants",
    ],
    "jsonl-event-aggregation": [
        "jsonl_grouped_counts",
        "jsonl_utc_date_normalization",
        "jsonl_invalid_and_duplicate_handling",
        "jsonl_summary_consistency",
        "jsonl_deterministic_outputs",
    ],
    "invoice-payment-reconciliation": [
        "reconciliation_rows_and_order",
        "reconciliation_cutoff_and_duplicates",
        "reconciliation_status_and_decimals",
        "reconciliation_unmatched_reporting",
        "reconciliation_summary_and_validation",
    ],
}


def _write_run(path: Path, workspace: Path, run_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workspace": str(workspace),
                "artifacts": {
                    "changed_files": ["app/main.py", "README.md", "pyproject.toml"],
                    "commands": [{"cmd": "pytest -q", "exit_code": 0}],
                    "outputs": [
                        {"type": "file", "path": "README.md"},
                        {"type": "file", "path": "pyproject.toml"},
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _evaluate_reference(task_id: str, *, mutant: str = "", hash_seed: str = "17"):
    temp = tempfile.TemporaryDirectory(prefix=f"batch1-{task_id}-")
    root = Path(temp.name)
    workspace = root / "workspace"
    shutil.copytree(REFERENCES / task_id, workspace)
    run_path = root / "run.json"
    _write_run(run_path, workspace, f"{task_id}-{mutant or 'positive'}-{hash_seed}")
    environment = {"PYTHONHASHSEED": hash_seed}
    if mutant:
        environment["AGENTHARNESS_MUTANT"] = mutant
    else:
        environment["AGENTHARNESS_MUTANT"] = ""
    with mock.patch.dict(os.environ, environment, clear=False):
        result = evaluate_benchmark_task(run_path, task_id)
    return temp, workspace, result


class TaskExpansionBatch1Tests(unittest.TestCase):
    def test_each_task_pack_has_exactly_five_functional_cases_plus_schema(self) -> None:
        for task_id, check_ids in TASK_CHECKS.items():
            with self.subTest(task_id=task_id):
                task_dir = BENCHMARKS / task_id
                self.assertTrue((task_dir / "SPEC.md").is_file())
                self.assertTrue((task_dir / "CLAIMS_CONTRACT.template.json").is_file())
                self.assertTrue((task_dir / "QUALITY_GATE.md").is_file())
                suite = json.loads((task_dir / "HELDOUT_EVALUATION_SUITE.template.json").read_text(encoding="utf-8"))
                self.assertEqual(len(suite["cases"]), 6)
                self.assertEqual([case["id"] for case in suite["cases"][:5]], check_ids)
                self.assertEqual(suite["cases"][5]["id"], "evaluation_result_schema")

    def test_positive_references_pass_all_checks(self) -> None:
        for task_id, check_ids in TASK_CHECKS.items():
            with self.subTest(task_id=task_id):
                temp, workspace, result = _evaluate_reference(task_id)
                try:
                    self.assertTrue(result.critical_ok, result.to_dict())
                    self.assertEqual(result.failed_checks, [])
                    self.assertEqual(result.passed_checks, check_ids)
                    summary = (workspace / ".agentharness" / "evaluation" / task_id / "summary.txt").read_text(encoding="utf-8")
                    for check_id in check_ids:
                        self.assertIn(f"{check_id}=pass", summary)
                finally:
                    temp.cleanup()

    def test_each_targeted_mutant_matches_frozen_sensitivity_matrix(self) -> None:
        for task_id, check_ids in TASK_CHECKS.items():
            for mutant in check_ids:
                with self.subTest(task_id=task_id, mutant=mutant):
                    temp, _workspace, result = _evaluate_reference(task_id, mutant=mutant)
                    try:
                        expected_failed = MUTATION_SENSITIVITY[task_id][mutant]["expected_failed_checks"]
                        expected_passed = [check_id for check_id in check_ids if check_id not in expected_failed]
                        self.assertEqual(result.failed_checks, expected_failed, result.to_dict())
                        self.assertEqual(result.passed_checks, expected_passed, result.to_dict())
                        self.assertFalse(result.critical_ok)
                        self.assertEqual(result.execution_status, "valid")
                        self.assertEqual(result.outcome_status, "real_failure")
                    finally:
                        temp.cleanup()

    def test_three_clean_room_runs_are_classification_deterministic(self) -> None:
        for task_id, check_ids in TASK_CHECKS.items():
            signatures = []
            for seed in ["7", "41", "103"]:
                temp, _workspace, result = _evaluate_reference(task_id, hash_seed=seed)
                try:
                    signatures.append((result.critical_ok, result.execution_status, result.outcome_status, result.classification_reason, tuple(result.passed_checks), tuple(result.failed_checks), tuple((item.id, item.status) for item in result.observations)))
                finally:
                    temp.cleanup()
            with self.subTest(task_id=task_id):
                self.assertEqual(signatures, [signatures[0]] * 3)
                self.assertEqual(list(signatures[0][4]), check_ids)


if __name__ == "__main__":
    unittest.main()
