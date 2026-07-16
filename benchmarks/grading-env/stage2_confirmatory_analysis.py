#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentharness.stage2_analysis import (
    CLUSTER_BOOTSTRAP_RESAMPLES_DEFAULT,
    CLUSTER_BOOTSTRAP_SEED_DEFAULT,
    MME_DEFAULT,
    WILD_BOOTSTRAP_RESAMPLES_DEFAULT,
    WILD_BOOTSTRAP_SEED_DEFAULT,
    load_analysis_dataset,
    run_full_analysis,
    validate_campaign_dataset,
    write_json,
)

TASK_IDS = [
    "csv-member-import",
    "incident-escalation-api",
    "inventory-adjustment-api",
    "leave-request-api",
    "refund-approval-api",
    "report-export-job",
    "support-ticket-api",
    "webhook-ingestion-service",
]
REPLICATES_PER_CONDITION = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen GPT-5.6 confirmatory Stage 2 analysis."
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_analysis_dataset(args.dataset)
    validate_campaign_dataset(
        rows,
        expected_task_ids=TASK_IDS,
        expected_replicates_per_condition=REPLICATES_PER_CONDITION,
    )
    report = run_full_analysis(
        rows,
        mme=MME_DEFAULT,
        cluster_seed=CLUSTER_BOOTSTRAP_SEED_DEFAULT,
        cluster_resamples=CLUSTER_BOOTSTRAP_RESAMPLES_DEFAULT,
        wild_seed=WILD_BOOTSTRAP_SEED_DEFAULT,
        wild_resamples=WILD_BOOTSTRAP_RESAMPLES_DEFAULT,
    )
    output_dir = args.output_dir
    write_json(output_dir / "dataset-summary.json", report["dataset_summary"])
    write_json(output_dir / "primary-analysis.json", report["primary_analysis"])
    write_json(output_dir / "cluster-bootstrap.json", report["cluster_bootstrap"])
    write_json(output_dir / "wild-cluster-bootstrap.json", report["wild_cluster_bootstrap"])
    write_json(output_dir / "leave-one-task-out.json", report["leave_one_task_out"])
    write_json(output_dir / "sensitivity-invalids.json", report["sensitivity_invalids"])
    write_json(output_dir / "manipulation-checks.json", report["manipulation_checks"])
    write_json(output_dir / "final-report.json", report)
    print(
        json.dumps(
            {
                "ok": True,
                "rows": len(rows),
                "tasks": len(TASK_IDS),
                "replicates_per_condition": REPLICATES_PER_CONDITION,
                "output_dir": str(output_dir),
                "headline": report["decision"]["headline"],
                "public_claim_classification": report["decision"][
                    "public_claim_classification"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
