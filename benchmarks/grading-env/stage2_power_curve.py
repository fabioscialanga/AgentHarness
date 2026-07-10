#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentharness.stage2_analysis import MME_DEFAULT, decision_headline, primary_analysis, synthetic_dataset, write_json  # noqa: E402


EFFECT_GRID = [0.05, 0.10, 0.12, 0.15, 0.18, 0.25]
NOISE_PROFILES = [
    {
        "name": "low_noise",
        "task_noise_sd": 0.05,
        "replicate_noise_sd": 0.04,
        "observation_noise_sd": 0.04,
    },
    {
        "name": "medium_noise",
        "task_noise_sd": 0.10,
        "replicate_noise_sd": 0.08,
        "observation_noise_sd": 0.08,
    },
    {
        "name": "high_noise",
        "task_noise_sd": 0.14,
        "replicate_noise_sd": 0.10,
        "observation_noise_sd": 0.10,
    },
]
SIMULATIONS = 200
BASE_SEED = 700_000


def main() -> int:
    output_json = REPO_ROOT / "benchmarks/grading-env/STAGE2_POWER_CURVE_FREEZE_2026-07-10.json"
    output_md = REPO_ROOT / "benchmarks/grading-env/STAGE2_POWER_CURVE_FREEZE_2026-07-10.md"

    rows_out: list[dict[str, object]] = []
    for profile_index, profile in enumerate(NOISE_PROFILES):
        for effect_index, true_effect in enumerate(EFFECT_GRID):
            counts = {
                "improvement_supported": 0,
                "no_meaningful_effect": 0,
                "inconclusive": 0,
            }
            ci_lower_values: list[float] = []
            ci_upper_values: list[float] = []
            effect_values: list[float] = []
            for simulation_index in range(SIMULATIONS):
                seed = BASE_SEED + profile_index * 10_000 + effect_index * 1_000 + simulation_index
                dataset = synthetic_dataset(
                    true_effect=true_effect,
                    include_invalids=False,
                    seed=seed,
                    task_noise_sd=float(profile["task_noise_sd"]),
                    replicate_noise_sd=float(profile["replicate_noise_sd"]),
                    observation_noise_sd=float(profile["observation_noise_sd"]),
                )
                primary = primary_analysis(dataset, mme=MME_DEFAULT, include_mixedlm=False)
                headline = decision_headline(primary)
                counts[headline] += 1
                ci_lower_values.append(primary.ci_lower)
                ci_upper_values.append(primary.ci_upper)
                effect_values.append(primary.effect_b_minus_a)
            rows_out.append(
                {
                    "noise_profile": profile["name"],
                    "task_noise_sd": profile["task_noise_sd"],
                    "replicate_noise_sd": profile["replicate_noise_sd"],
                    "observation_noise_sd": profile["observation_noise_sd"],
                    "true_effect": true_effect,
                    "simulations": SIMULATIONS,
                    "improvement_supported_rate": counts["improvement_supported"] / SIMULATIONS,
                    "no_meaningful_effect_rate": counts["no_meaningful_effect"] / SIMULATIONS,
                    "inconclusive_rate": counts["inconclusive"] / SIMULATIONS,
                    "mean_observed_effect": sum(effect_values) / SIMULATIONS,
                    "mean_ci_lower": sum(ci_lower_values) / SIMULATIONS,
                    "mean_ci_upper": sum(ci_upper_values) / SIMULATIONS,
                }
            )

    payload = {
        "mme": MME_DEFAULT,
        "effects": EFFECT_GRID,
        "noise_profiles": NOISE_PROFILES,
        "simulations_per_cell": SIMULATIONS,
        "task_weighting_rule": "equal_weight_per_task_unweighted_by_valid_cell_count",
        "decision_rule": {
            "improvement_supported": "primary ci lower bound strictly above mme",
            "no_meaningful_effect": "primary ci upper bound strictly below mme",
            "inconclusive": "all remaining cases",
        },
        "rows": rows_out,
    }
    write_json(output_json, payload)

    lines = [
        "# Stage 2 power-curve freeze — 2026-07-10",
        "",
        f"- MME: {MME_DEFAULT:.2f}",
        f"- simulations per cell: {SIMULATIONS}",
        "- decision rule: improvement_supported if CI lower > MME; no_meaningful_effect if CI upper < MME; inconclusive otherwise",
        "",
        "| noise_profile | true_effect | support_rate | no_meaningful_rate | inconclusive_rate | mean_ci_lower | mean_ci_upper |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows_out:
        lines.append(
            "| {noise_profile} | {true_effect:.2f} | {improvement_supported_rate:.3f} | {no_meaningful_effect_rate:.3f} | {inconclusive_rate:.3f} | {mean_ci_lower:.3f} | {mean_ci_upper:.3f} |".format(**row)
        )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(output_json), "markdown": str(output_md), "cells": len(rows_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
