from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentharness.level2_reliability import (
    auditable_results_for_solution_hash_guard,
    classify_level2_cell,
    compute_level2_gate,
    load_results,
    should_abort_provider_outage,
    trailing_contiguous_category,
)


class Level2ReliabilityTests(unittest.TestCase):
    def test_classify_level2_cell_maps_execution_and_outcome_statuses(self) -> None:
        self.assertEqual(
            classify_level2_cell({"benchmark_execution_status": "provider_unavailable", "benchmark_outcome_status": "real_failure"}),
            "provider_unavailable",
        )
        self.assertEqual(
            classify_level2_cell({"benchmark_execution_status": "harness_invalid", "benchmark_outcome_status": "real_failure"}),
            "harness_invalid",
        )
        self.assertEqual(
            classify_level2_cell({"benchmark_execution_status": "valid", "benchmark_outcome_status": "success"}),
            "success",
        )
        self.assertEqual(
            classify_level2_cell({"benchmark_execution_status": "valid", "benchmark_outcome_status": "real_failure"}),
            "real_failure",
        )

    def test_classify_level2_cell_treats_provider_reason_inside_harness_invalid_as_provider_unavailable(self) -> None:
        result = {
            "task_id": "leave-request-api",
            "benchmark_execution_status": "harness_invalid",
            "benchmark_outcome_status": "invalid",
            "benchmark_classification_reason": "provider_unavailable: HTTP 429 usage limit has been reached",
        }
        self.assertEqual(classify_level2_cell(result), "provider_unavailable")

    def test_compute_level2_gate_passes_on_clean_representative_slice(self) -> None:
        results = []
        for idx in range(6):
            results.append(
                {
                    "cell": f"cell-{idx}-r1",
                    "task_id": f"task-{idx}",
                    "condition": "B-agentharness",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "success",
                    "score": 1.0,
                }
            )
        results.extend(
            [
                {
                    "cell": "cell-6-r1",
                    "task_id": "task-6",
                    "condition": "B-agentharness",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "provider_unavailable",
                    "benchmark_outcome_status": "real_failure",
                    "score": 0.0,
                },
                {
                    "cell": "cell-6-r2",
                    "task_id": "task-6",
                    "condition": "B-agentharness",
                    "replicate_id": "r2",
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "success",
                    "score": 1.0,
                },
                {
                    "cell": "cell-7-r1",
                    "task_id": "task-7",
                    "condition": "B-agentharness",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "harness_invalid",
                    "benchmark_outcome_status": "real_failure",
                    "score": 0.0,
                },
                {
                    "cell": "cell-7-r2",
                    "task_id": "task-7",
                    "condition": "B-agentharness",
                    "replicate_id": "r2",
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "success",
                    "score": 1.0,
                },
            ]
        )
        summary = compute_level2_gate(results)
        self.assertTrue(summary["passes_gate"])
        self.assertEqual(summary["counts"]["total_invalid"], 2)
        self.assertEqual(summary["tasks_with_success"], 8)
        self.assertEqual(summary["longest_provider_unavailable_block"], 1)

    def test_compute_level2_gate_counts_provider_reason_inside_harness_invalid_separately(self) -> None:
        gate = compute_level2_gate(
            [
                {
                    "task_id": "leave-request-api",
                    "condition": "A-baseline",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "harness_invalid",
                    "benchmark_outcome_status": "invalid",
                    "benchmark_classification_reason": "provider_unavailable: HTTP 429 usage limit has been reached",
                    "score": 0.0,
                },
                {
                    "task_id": "leave-request-api",
                    "condition": "B-agentharness",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "harness_invalid",
                    "benchmark_outcome_status": "invalid",
                    "benchmark_classification_reason": "Missing invocation evidence",
                    "score": 0.0,
                },
                {
                    "task_id": "support-ticket-api",
                    "condition": "A-baseline",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "success",
                    "score": 1.0,
                },
            ]
        )
        self.assertEqual(gate["counts"]["provider_unavailable"], 1)
        self.assertEqual(gate["counts"]["harness_invalid"], 1)
        self.assertEqual(gate["counts"]["success"], 1)

    def test_compute_level2_gate_fails_on_contiguous_provider_block(self) -> None:
        results = []
        for idx in range(3):
            results.append(
                {
                    "cell": f"provider-{idx}",
                    "task_id": f"task-{idx}",
                    "condition": "B-agentharness",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "provider_unavailable",
                    "benchmark_outcome_status": "real_failure",
                    "score": 0.0,
                }
            )
        for idx in range(3, 8):
            results.append(
                {
                    "cell": f"success-{idx}",
                    "task_id": f"task-{idx}",
                    "condition": "B-agentharness",
                    "replicate_id": "r1",
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "success",
                    "score": 1.0,
                }
            )
        summary = compute_level2_gate(results)
        self.assertFalse(summary["passes_gate"])
        self.assertFalse(summary["gate_checks"]["no_provider_block_ge_3"])
        self.assertEqual(summary["longest_provider_unavailable_block"], 3)

    def test_live_abort_only_triggers_on_trailing_provider_streak(self) -> None:
        provider = {
            "benchmark_execution_status": "provider_unavailable",
            "benchmark_outcome_status": "invalid",
        }
        success = {
            "benchmark_execution_status": "valid",
            "benchmark_outcome_status": "success",
        }
        results = [provider, provider, success, provider, provider]
        self.assertEqual(trailing_contiguous_category(results, "provider_unavailable"), 2)
        self.assertFalse(should_abort_provider_outage(results, threshold=3))
        results.append(provider)
        self.assertTrue(should_abort_provider_outage(results, threshold=3))

    def test_live_abort_rejects_nonpositive_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            should_abort_provider_outage([], threshold=0)

    def test_solution_hash_guard_excludes_untrusted_provider_and_harness_cells(self) -> None:
        results = [
            {
                "task_id": "task-provider",
                "benchmark_execution_status": "provider_unavailable",
                "benchmark_outcome_status": "invalid",
            },
            {
                "task_id": "task-harness",
                "benchmark_execution_status": "harness_invalid",
                "benchmark_outcome_status": "invalid",
            },
            {
                "task_id": "task-real",
                "benchmark_execution_status": "valid",
                "benchmark_outcome_status": "real_failure",
            },
        ]
        filtered = auditable_results_for_solution_hash_guard(results)
        self.assertEqual([result["task_id"] for result in filtered], ["task-real"])

    def test_load_results_requires_json_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "results.json"
            path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Expected a JSON list"):
                load_results(path)


if __name__ == "__main__":
    unittest.main()
