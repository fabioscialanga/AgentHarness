from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "benchmarks" / "grading-env" / "STAGE2_EFFICACY_FREEZE_2026-07-17.json"
SEED = 20260717
TASKS = [
    "access-policy-evaluator",
    "appointment-booking-api",
    "csv-member-import",
    "dependency-impact-planner",
    "double-entry-ledger-api",
    "incident-escalation-api",
    "inventory-adjustment-api",
    "invoice-payment-reconciliation",
    "jsonl-event-aggregation",
    "lease-coordination-api",
    "leave-request-api",
    "pii-redaction-pipeline",
    "refund-approval-api",
    "report-export-job",
    "safe-archive-extraction",
    "shipment-event-api",
    "signed-artifact-verifier",
    "support-ticket-api",
    "versioned-document-api",
    "webhook-ingestion-service",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def frozen_paths() -> list[Path]:
    paths = [
        REPO_ROOT / "benchmarks" / "grading-env" / "run_stage2_efficacy_campaign.py",
        REPO_ROOT / "benchmarks" / "grading-env" / "finalize_stage2_efficacy.py",
        REPO_ROOT / "benchmarks" / "grading-env" / "stage2_run_analysis.py",
        REPO_ROOT / "benchmarks" / "grading-env" / "stage2-analysis-requirements.txt",
        REPO_ROOT / "src" / "agentharness" / "benchmark_cells.py",
        REPO_ROOT / "src" / "agentharness" / "evaluation.py",
        REPO_ROOT / "src" / "agentharness" / "stage2_analysis.py",
    ]
    paths.extend(sorted((REPO_ROOT / "src" / "agentharness").glob("benchmark_hidden_evaluator*.py")))
    for task in TASKS:
        task_dir = REPO_ROOT / "benchmarks" / task
        for name in ("SPEC.md", "CLAIMS_CONTRACT.template.json"):
            paths.append(task_dir / name)
        heldout = task_dir / "HELDOUT_EVALUATION_SUITE.template.json"
        if heldout.is_file():
            paths.append(heldout)
    unique = sorted(set(paths))
    missing = [path for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen files: {missing}")
    return unique


def build() -> dict[str, object]:
    rng = random.Random(SEED)
    pairs = [(task, replicate) for task in TASKS for replicate in ("r1", "r2", "r3")]
    rng.shuffle(pairs)
    blocks: list[dict[str, object]] = []
    for index, (task, replicate) in enumerate(pairs, start=1):
        conditions = ["A-baseline", "B-agentharness"]
        rng.shuffle(conditions)
        blocks.append(
            {
                "block_id": f"b{index:03d}",
                "task_id": task,
                "replicate_id": replicate,
                "condition_order": conditions,
            }
        )
    hashes = {
        path.relative_to(REPO_ROOT).as_posix(): sha256(path)
        for path in frozen_paths()
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "campaign_id": "stage2-efficacy-20x3-20260717",
        "preregistration_section": "17.31",
        "purpose": "smallest high-effect confirmatory test of AgentHarness utility on the frozen 20-task suite",
        "estimand": "equal-weight task mean of B-agentharness minus A-baseline held-out score",
        "provider": "openai-codex",
        "model": "gpt-5.6-sol",
        "toolsets": "terminal,file",
        "max_turns": 40,
        "codex_sse_idle_seconds": 60,
        "invocation_max_retries": 1,
        "retry_backoff_seconds": 30.0,
        "tasks": TASKS,
        "conditions": ["A-baseline", "B-agentharness"],
        "replicates": ["r1", "r2", "r3"],
        "expected_cells": 120,
        "expected_blocks": 60,
        "randomization_seed": SEED,
        "blocks": blocks,
        "primary_endpoint": "six_case_heldout_score",
        "heldout_denominator": 6,
        "mme": 0.10,
        "primary_ci": "two_sided_95_percent_student_t_df_19",
        "task_weighting": "equal_weight_per_task_unweighted_by_valid_cell_count",
        "decision_rule": {
            "improvement_supported": "primary_ci_lower_strictly_greater_than_0.10",
            "no_meaningful_effect": "primary_ci_upper_strictly_less_than_0.10",
            "otherwise": "inconclusive",
        },
        "robustness_gate": [
            "cluster_bootstrap_ci_above_zero",
            "wild_cluster_bootstrap_ci_above_zero",
            "all_leave_one_task_out_point_estimates_above_zero",
            "invalid_as_zero_point_estimate_above_zero",
        ],
        "secondary_confirmatory_family": {
            "holm_familywise_alpha": 0.05,
            "endpoints": ["complete_six_of_six_success", "total_agent_wall_clock_seconds"],
            "cannot_rescue_primary": True,
        },
        "power": {
            "assumptions": {
                "within_task_sd": 0.224,
                "heterogeneity_sd": 0.10,
                "simulations_per_point": 2000,
                "seed_rule": "20260710 + int(effect*1000) + replicates",
            },
            "effect_0.12": 0.061,
            "effect_0.18": 0.367,
            "effect_0.25": 0.863,
        },
        "invalid_policy": {
            "primary": "exclude_provider_unavailable_and_harness_invalid_only",
            "sensitivity": "count_provider_unavailable_and_harness_invalid_as_zero",
            "require_at_least_one_valid_replicate_per_task_condition": True,
        },
        "rerun_policy": {
            "harness_invalid_fresh_reruns": 1,
            "max_provider_attempts": 3,
            "provider_attempts_do_not_become_efficacy_rows": True,
        },
        "quota_policy": {
            "weekly_used_pause_percent": 85.0,
            "session_used_pause_percent": 80.0,
            "allow_single_authoritative_window": True,
            "single_window_pause_percent": 80.0,
            "usage_unavailable": "pause_fail_closed",
            "auth_reset_forbidden": True,
            "purchased_credits_forbidden": True,
            "provider_fallback_forbidden": True,
        },
        "analysis_parameters": {
            "cluster_seed": 20260703,
            "wild_seed": 20260704,
            "cluster_resamples": 10000,
            "wild_resamples": 10000,
            "mixedlm": "concordance_only",
        },
        "interim_policy": "no efficacy contrasts, scores, task outcomes, or arm summaries before all 60 blocks are committed",
        "frozen_file_sha256": hashes,
    }
    payload["manifest_payload_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "manifest_payload_sha256": payload["manifest_payload_sha256"], "cells": 120, "blocks": 60}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
