from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentharness.level2_reliability import classify_level2_cell, compute_level2_gate, load_results


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

    def test_load_results_requires_json_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "results.json"
            path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Expected a JSON list"):
                load_results(path)


if __name__ == "__main__":
    unittest.main()
