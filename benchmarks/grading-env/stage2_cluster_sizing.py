#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import t

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_JSON = REPO_ROOT / "benchmarks/grading-env/STAGE2_CLUSTER_SIZING_FREEZE_2026-07-16.json"
OUTPUT_MD = REPO_ROOT / "benchmarks/grading-env/STAGE2_CLUSTER_SIZING_FREEZE_2026-07-16.md"

MME = 0.10
WITHIN_TASK_CONDITION_SD = 0.224
EFFECTS = [0.12, 0.18]
EFFECT_HETEROGENEITY_SDS = [0.08, 0.10, 0.14]
TASK_COUNTS = [8, 16, 20, 24, 28, 30, 32, 36]
REPLICATES_PER_CONDITION = [6, 8, 10, 12, 14, 20]
SIMULATIONS = 50_000
BASE_SEED = 2_026_071_605
DECISION_TOLERANCE = 1e-12
SELECTED_TASKS = 24
SELECTED_REPLICATES = 14
SELECTED_EFFECT = 0.18
SELECTED_CENTRAL_HETEROGENEITY_SD = 0.10


def simulated_power(*, tasks: int, replicates: int, effect: float, heterogeneity_sd: float) -> float:
    seed = (
        BASE_SEED
        + tasks * 1_000_000
        + replicates * 10_000
        + int(round(effect * 100)) * 100
        + int(round(heterogeneity_sd * 100))
    )
    rng = np.random.default_rng(seed)
    task_effects = rng.normal(effect, heterogeneity_sd, size=(SIMULATIONS, tasks))
    observation_noise_sd = (2.0**0.5) * WITHIN_TASK_CONDITION_SD / (replicates**0.5)
    observed_differences = task_effects + rng.normal(
        0.0, observation_noise_sd, size=(SIMULATIONS, tasks)
    )
    mean = observed_differences.mean(axis=1)
    standard_error = observed_differences.std(axis=1, ddof=1) / (tasks**0.5)
    lower = mean - t.ppf(0.975, tasks - 1) * standard_error
    return float(np.mean(lower - MME > DECISION_TOLERANCE))


def main() -> int:
    rows: list[dict[str, object]] = []
    for heterogeneity_sd in EFFECT_HETEROGENEITY_SDS:
        for tasks in TASK_COUNTS:
            for replicates in REPLICATES_PER_CONDITION:
                for effect in EFFECTS:
                    rows.append(
                        {
                            "tasks": tasks,
                            "replicates_per_condition": replicates,
                            "cells": tasks * replicates * 2,
                            "true_effect": effect,
                            "effect_heterogeneity_sd": heterogeneity_sd,
                            "within_task_condition_sd": WITHIN_TASK_CONDITION_SD,
                            "improvement_supported_power": simulated_power(
                                tasks=tasks,
                                replicates=replicates,
                                effect=effect,
                                heterogeneity_sd=heterogeneity_sd,
                            ),
                        }
                    )
    selected = next(
        row
        for row in rows
        if row["tasks"] == SELECTED_TASKS
        and row["replicates_per_condition"] == SELECTED_REPLICATES
        and row["true_effect"] == SELECTED_EFFECT
        and row["effect_heterogeneity_sd"] == SELECTED_CENTRAL_HETEROGENEITY_SD
    )
    payload = {
        "mme": MME,
        "within_task_condition_sd": WITHIN_TASK_CONDITION_SD,
        "simulations_per_design_cell": SIMULATIONS,
        "base_seed": BASE_SEED,
        "decision_rule": "improvement_supported iff primary 95% CI lower bound is strictly above MME",
        "model": {
            "task_effect": "Normal(true_effect, effect_heterogeneity_sd)",
            "condition_mean_difference_noise_sd": "sqrt(2) * within_task_condition_sd / sqrt(replicates_per_condition)",
            "inference": "paired task-level mean difference with t critical value and df=tasks-1",
        },
        "selection": {
            "status": "provisional_pending_task_expansion_and_quality_gates",
            "tasks": SELECTED_TASKS,
            "replicates_per_condition": SELECTED_REPLICATES,
            "cells": SELECTED_TASKS * SELECTED_REPLICATES * 2,
            "target_effect": SELECTED_EFFECT,
            "central_effect_heterogeneity_sd": SELECTED_CENTRAL_HETEROGENEITY_SD,
            "central_power": selected["improvement_supported_power"],
            "reason": "smallest task expansion among the frozen candidate grid that clears 0.80 central power at effect 0.18",
        },
        "rows": rows,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    selected_rows = [
        row
        for row in rows
        if row["tasks"] == SELECTED_TASKS
        and row["replicates_per_condition"] == SELECTED_REPLICATES
    ]
    lines = [
        "# Stage 2 cluster-aware sizing freeze — 2026-07-16",
        "",
        f"- MME: {MME:.2f}",
        f"- within-task-condition SD: {WITHIN_TASK_CONDITION_SD:.3f}",
        f"- simulations per design cell: {SIMULATIONS}",
        "- primary inference: paired task-level mean difference with small-cluster t CI",
        "- selection status: provisional pending expansion from 8 to 24 validated tasks",
        f"- selected candidate: {SELECTED_TASKS} tasks x {SELECTED_REPLICATES} replicates per condition = {SELECTED_TASKS * SELECTED_REPLICATES * 2} cells",
        "",
        "| effect heterogeneity SD | true effect | improvement-supported power |",
        "|---:|---:|---:|",
    ]
    for row in selected_rows:
        lines.append(
            f"| {row['effect_heterogeneity_sd']:.2f} | {row['true_effect']:.2f} | {row['improvement_supported_power']:.3f} |"
        )
    lines.extend(
        [
            "",
            "The 0.12 effect is not adequately powered in this candidate under any frozen heterogeneity profile.",
            "The campaign must not launch until 16 additional tasks pass the preregistered quality and neutrality gates.",
        ]
    )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(OUTPUT_JSON), "markdown": str(OUTPUT_MD), "selection": payload["selection"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
