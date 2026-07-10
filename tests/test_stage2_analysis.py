from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agentharness.stage2_analysis import (
    CLUSTER_BOOTSTRAP_SEED_DEFAULT,
    MME_DEFAULT,
    WILD_BOOTSTRAP_SEED_DEFAULT,
    apply_invalid_policy,
    build_dataset_from_progress,
    load_analysis_dataset,
    manipulation_checks,
    primary_analysis,
    run_full_analysis,
    synthetic_dataset,
    write_json,
)


HAS_ANALYSIS_DEPS = all(importlib.util.find_spec(name) is not None for name in ("pandas", "scipy"))


@unittest.skipUnless(HAS_ANALYSIS_DEPS, "Stage 2 analysis tests require pandas+scipy")
class Stage2AnalysisTests(unittest.TestCase):
    def test_synthetic_primary_effect_recovers_known_effect(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=False)
        result = primary_analysis(rows, mme=MME_DEFAULT)
        self.assertAlmostEqual(result.effect_b_minus_a, 0.18, places=6)
        self.assertTrue(result.ci_entirely_above_zero)
        self.assertTrue(result.mme_cleared)

    def test_invalid_sensitivity_zero_is_weaker_than_exclusion(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=True)
        excluded = primary_analysis(apply_invalid_policy(rows, "exclude_infrastructure_invalids"), mme=MME_DEFAULT)
        zeroed = primary_analysis(apply_invalid_policy(rows, "count_infrastructure_invalids_as_zero"), mme=MME_DEFAULT)
        self.assertLess(zeroed.effect_b_minus_a, excluded.effect_b_minus_a)

    def test_manipulation_checks_measure_hash_change_in_both_conditions(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=False)
        checks = {row.condition: row for row in manipulation_checks(rows)}
        self.assertEqual(checks["A-baseline"].hash_changed_rate, 0.0)
        self.assertEqual(checks["B-agentharness"].hash_changed_rate, 1.0)
        self.assertEqual(checks["B-agentharness"].feedback_delivered_rate, 1.0)

    def test_run_full_analysis_returns_expected_sections(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=True)
        report = run_full_analysis(
            rows,
            mme=MME_DEFAULT,
            cluster_seed=CLUSTER_BOOTSTRAP_SEED_DEFAULT,
            cluster_resamples=1000,
            wild_seed=WILD_BOOTSTRAP_SEED_DEFAULT,
            wild_resamples=1000,
        )
        self.assertEqual(report["decision"]["headline"], "improvement_supported")
        self.assertIn("cluster_bootstrap", report)
        self.assertIn("wild_cluster_bootstrap", report)
        self.assertEqual(len(report["leave_one_task_out"]), 8)

    def test_build_dataset_from_progress_preserves_provider_classification_and_hash_flag(self) -> None:
        progress_payload = [
            {
                "task_id": "support-ticket-api",
                "condition": "A-baseline",
                "replicate_id": "r1",
                "final": {
                    "score": 0.0,
                    "benchmark_execution_status": "harness_invalid",
                    "benchmark_outcome_status": "invalid",
                    "benchmark_classification_reason": "provider_unavailable: Codex stream produced no SSE events",
                    "solution_hash_changed_between_attempt_and_repair": False,
                    "verify_run_ok": False,
                },
            },
            {
                "task_id": "support-ticket-api",
                "condition": "B-agentharness",
                "replicate_id": "r1",
                "final": {
                    "score": 0.8,
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "real_failure",
                    "benchmark_classification_reason": None,
                    "solution_hash_changed_between_attempt_and_repair": True,
                    "verify_run_ok": True,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            progress_path = Path(tmp_dir) / "progress.json"
            progress_path.write_text(json.dumps(progress_payload), encoding="utf-8")
            rows = build_dataset_from_progress(progress_path)
        self.assertEqual(rows[0]["category"], "provider_unavailable")
        self.assertFalse(rows[0]["solution_hash_changed_between_attempt_and_repair"])
        self.assertTrue(rows[1]["solution_hash_changed_between_attempt_and_repair"])
        self.assertTrue(rows[1]["feedback_delivered"])

    def test_load_analysis_dataset_round_trips(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=False)
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "dataset.json"
            write_json(path, rows)
            loaded = load_analysis_dataset(path)
        self.assertEqual(len(loaded), len(rows))
        self.assertEqual(loaded[0]["task_id"], rows[0]["task_id"])


if __name__ == "__main__":
    unittest.main()
