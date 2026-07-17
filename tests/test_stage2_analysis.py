from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agentharness.stage2_analysis import (
    CLUSTER_BOOTSTRAP_SEED_DEFAULT,
    MME_DEFAULT,
    Stage2AnalysisError,
    TASK_WEIGHTING_RULE,
    WILD_BOOTSTRAP_SEED_DEFAULT,
    apply_invalid_policy,
    build_dataset_from_progress,
    decision_headline,
    load_analysis_dataset,
    manipulation_checks,
    primary_analysis,
    run_full_analysis,
    synthetic_dataset,
    validate_campaign_dataset,
    write_json,
)


HAS_ANALYSIS_DEPS = all(importlib.util.find_spec(name) is not None for name in ("pandas", "scipy"))


@unittest.skipUnless(HAS_ANALYSIS_DEPS, "Stage 2 analysis tests require pandas+scipy")
class Stage2AnalysisTests(unittest.TestCase):
    def test_synthetic_primary_effect_recovers_known_effect(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=False)
        result = primary_analysis(rows, mme=MME_DEFAULT, include_mixedlm=False)
        self.assertAlmostEqual(result.effect_b_minus_a, 0.18, places=6)
        self.assertEqual(result.task_weighting_rule, TASK_WEIGHTING_RULE)
        self.assertTrue(result.ci_entirely_above_zero)
        self.assertTrue(result.mme_cleared)

    def test_primary_mme_boundary_is_strictly_inconclusive(self) -> None:
        rows = synthetic_dataset(
            n_tasks=8,
            replicates=20,
            true_effect=MME_DEFAULT,
            task_step=0.0,
            replicate_step=0.0,
            include_invalids=False,
        )
        result = primary_analysis(rows, mme=MME_DEFAULT, include_mixedlm=False)
        self.assertAlmostEqual(result.ci_lower, MME_DEFAULT)
        self.assertAlmostEqual(result.ci_upper, MME_DEFAULT)
        self.assertFalse(result.mme_cleared)
        self.assertEqual(decision_headline(result), "inconclusive")

    def test_campaign_dataset_validator_accepts_exact_24_by_2_by_14_shape(self) -> None:
        task_ids = [f"task-{index}" for index in range(1, 25)]
        rows: list[dict[str, object]] = []
        for task_id in task_ids:
            for condition, score in (("A-baseline", 2 / 6), ("B-agentharness", 3 / 6)):
                for replicate in range(1, 15):
                    rows.append(
                        {
                            "task_id": task_id,
                            "condition": condition,
                            "replicate_id": f"r{replicate}",
                            "score": score,
                            "category": "success",
                            "benchmark_execution_status": "valid",
                            "benchmark_outcome_status": "success",
                            "treatment_delivered": True,
                            "feedback_delivered": condition == "B-agentharness",
                            "treatment_prompt_sha256_pre": "a" * 64,
                            "treatment_prompt_sha256_post": "a" * 64,
                            "treatment_prompt_immutable": True,
                            "feedback_sha256_pre": "b" * 64 if condition == "B-agentharness" else None,
                            "feedback_sha256_post": "b" * 64 if condition == "B-agentharness" else None,
                            "feedback_immutable": condition == "B-agentharness",
                            "heldout_endpoint_denominator": 6,
                            "heldout_endpoint_valid": True,
                        }
                    )
        validate_campaign_dataset(
            rows,
            expected_task_ids=task_ids,
            expected_replicates_per_condition=14,
        )

        with self.assertRaisesRegex(Stage2AnalysisError, "Replicate set mismatch"):
            validate_campaign_dataset(
                rows[:-1],
                expected_task_ids=task_ids,
                expected_replicates_per_condition=14,
            )

        non_quantized = [dict(row) for row in rows]
        non_quantized[0]["score"] = 0.2
        with self.assertRaisesRegex(Stage2AnalysisError, "not quantized to sixths"):
            validate_campaign_dataset(
                non_quantized,
                expected_task_ids=task_ids,
                expected_replicates_per_condition=14,
            )

    def test_invalid_sensitivity_zero_is_weaker_than_exclusion(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=True)
        excluded = primary_analysis(
            apply_invalid_policy(rows, "exclude_infrastructure_invalids"),
            mme=MME_DEFAULT,
            include_mixedlm=False,
        )
        zeroed = primary_analysis(
            apply_invalid_policy(rows, "count_infrastructure_invalids_as_zero"),
            mme=MME_DEFAULT,
            include_mixedlm=False,
        )
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
        self.assertEqual(report["analysis_spec"]["task_weighting_rule"], TASK_WEIGHTING_RULE)
        self.assertEqual(report["analysis_spec"]["decision_rule"]["no_meaningful_effect"], "primary ci upper bound strictly below mme")
        self.assertIn("cluster_bootstrap", report)
        self.assertIn("wild_cluster_bootstrap", report)
        self.assertEqual(len(report["leave_one_task_out"]), 8)

    def test_decision_rule_emits_improvement_supported_when_ci_lower_exceeds_mme(self) -> None:
        rows = synthetic_dataset(true_effect=0.18, include_invalids=False)
        result = primary_analysis(rows, mme=MME_DEFAULT, include_mixedlm=False)
        self.assertGreater(result.ci_lower, MME_DEFAULT)
        self.assertEqual(decision_headline(result), "improvement_supported")

    def test_decision_rule_emits_no_meaningful_effect_when_ci_upper_below_mme(self) -> None:
        rows = synthetic_dataset(
            true_effect=0.0,
            include_invalids=False,
            seed=1,
            task_noise_sd=0.05,
            replicate_noise_sd=0.04,
            observation_noise_sd=0.04,
        )
        report = run_full_analysis(rows, cluster_resamples=800, wild_resamples=800, include_mixedlm=False)
        self.assertEqual(report["decision"]["headline"], "no_meaningful_effect")
        self.assertLess(report["primary_analysis"]["ci_upper"], MME_DEFAULT)

    def test_decision_rule_emits_inconclusive_when_ci_crosses_mme(self) -> None:
        rows = synthetic_dataset(
            true_effect=0.12,
            include_invalids=False,
            seed=1,
            task_noise_sd=0.14,
            replicate_noise_sd=0.10,
            observation_noise_sd=0.10,
        )
        report = run_full_analysis(rows, cluster_resamples=800, wild_resamples=800, include_mixedlm=False)
        self.assertEqual(report["decision"]["headline"], "inconclusive")
        self.assertLessEqual(report["primary_analysis"]["ci_lower"], MME_DEFAULT)
        self.assertGreaterEqual(report["primary_analysis"]["ci_upper"], MME_DEFAULT)

    def test_true_zero_effect_does_not_return_improvement_supported(self) -> None:
        rows = synthetic_dataset(
            true_effect=0.0,
            include_invalids=False,
            seed=101,
            task_noise_sd=0.10,
            replicate_noise_sd=0.08,
            observation_noise_sd=0.08,
        )
        report = run_full_analysis(rows, cluster_resamples=800, wild_resamples=800, include_mixedlm=False)
        self.assertNotEqual(report["decision"]["headline"], "improvement_supported")

    def test_true_effect_below_mme_does_not_return_improvement_supported(self) -> None:
        rows = synthetic_dataset(
            true_effect=0.05,
            include_invalids=False,
            seed=202,
            task_noise_sd=0.10,
            replicate_noise_sd=0.08,
            observation_noise_sd=0.08,
        )
        report = run_full_analysis(rows, cluster_resamples=800, wild_resamples=800, include_mixedlm=False)
        self.assertNotEqual(report["decision"]["headline"], "improvement_supported")
        self.assertLess(report["primary_analysis"]["mme"], 0.11)

    def test_negative_true_effect_returns_no_meaningful_effect(self) -> None:
        rows = synthetic_dataset(
            true_effect=-0.15,
            include_invalids=False,
            seed=1,
            task_noise_sd=0.08,
            replicate_noise_sd=0.06,
            observation_noise_sd=0.06,
        )
        report = run_full_analysis(rows, cluster_resamples=800, wild_resamples=800, include_mixedlm=False)
        self.assertEqual(report["decision"]["headline"], "no_meaningful_effect")
        self.assertLess(report["primary_analysis"]["effect_b_minus_a"], 0.0)

    def test_null_false_positive_rate_is_calibrated(self) -> None:
        supported = 0
        simulations = 100
        for seed in range(10_000, 10_000 + simulations):
            rows = synthetic_dataset(
                true_effect=0.0,
                include_invalids=False,
                seed=seed,
                task_noise_sd=0.10,
                replicate_noise_sd=0.08,
                observation_noise_sd=0.08,
            )
            report = run_full_analysis(
                rows,
                cluster_resamples=300,
                wild_resamples=300,
                include_mixedlm=False,
            )
            supported += int(report["decision"]["headline"] == "improvement_supported")
        false_positive_rate = supported / simulations
        self.assertLessEqual(false_positive_rate, 0.10)

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
                    "treatment_delivered": True,
                    "feedback_delivered": True,
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
