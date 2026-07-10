#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentharness.stage2_analysis import MME_DEFAULT, decision_headline, primary_analysis, synthetic_dataset, write_json  # noqa: E402


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
TRUE_EFFECT = 0.0
BASE_SEED = 810_000


def main() -> int:
    output_json = REPO_ROOT / "benchmarks/grading-env/STAGE2_NULL_IDENTIFIABILITY_FREEZE_2026-07-10.json"
    output_md = REPO_ROOT / "benchmarks/grading-env/STAGE2_NULL_IDENTIFIABILITY_FREEZE_2026-07-10.md"

    rows_out: list[dict[str, object]] = []
    for profile_index, profile in enumerate(NOISE_PROFILES):
        counts = {
            "improvement_supported": 0,
            "no_meaningful_effect": 0,
            "inconclusive": 0,
        }
        ci_upper_values: list[float] = []
        effect_values: list[float] = []
        for simulation_index in range(SIMULATIONS):
            seed = BASE_SEED + profile_index * 1_000 + simulation_index
            dataset = synthetic_dataset(
                true_effect=TRUE_EFFECT,
                include_invalids=False,
                seed=seed,
                task_noise_sd=float(profile["task_noise_sd"]),
                replicate_noise_sd=float(profile["replicate_noise_sd"]),
                observation_noise_sd=float(profile["observation_noise_sd"]),
            )
            primary = primary_analysis(dataset, mme=MME_DEFAULT, include_mixedlm=False)
            headline = decision_headline(primary)
            counts[headline] += 1
            ci_upper_values.append(primary.ci_upper)
            effect_values.append(primary.effect_b_minus_a)
        rows_out.append(
            {
                "noise_profile": profile["name"],
                "task_noise_sd": profile["task_noise_sd"],
                "replicate_noise_sd": profile["replicate_noise_sd"],
                "observation_noise_sd": profile["observation_noise_sd"],
                "simulations": SIMULATIONS,
                "true_effect": TRUE_EFFECT,
                "improvement_supported_rate": counts["improvement_supported"] / SIMULATIONS,
                "no_meaningful_effect_rate": counts["no_meaningful_effect"] / SIMULATIONS,
                "inconclusive_rate": counts["inconclusive"] / SIMULATIONS,
                "mean_observed_effect": sum(effect_values) / SIMULATIONS,
                "mean_ci_upper": sum(ci_upper_values) / SIMULATIONS,
            }
        )

    payload = {
        "mme": MME_DEFAULT,
        "true_effect": TRUE_EFFECT,
        "simulations_per_profile": SIMULATIONS,
        "task_weighting_rule": "equal_weight_per_task_unweighted_by_valid_cell_count",
        "decision_rule": {
            "improvement_supported": "primary ci lower bound strictly above mme",
            "no_meaningful_effect": "primary ci upper bound strictly below mme",
            "inconclusive": "all remaining cases",
        },
        "noise_profiles": NOISE_PROFILES,
        "rows": rows_out,
    }
    write_json(output_json, payload)

    lines = [
        "# Stage 2 null-identifiability freeze — 2026-07-10",
        "",
        f"- true_effect: {TRUE_EFFECT:.2f}",
        f"- MME: {MME_DEFAULT:.2f}",
        f"- simulations per profile: {SIMULATIONS}",
        "- interpretation target: how often the frozen decision can say no_meaningful_effect rather than only inconclusive when the true effect is exactly zero",
        "",
        "| noise_profile | no_meaningful_rate | inconclusive_rate | improvement_supported_rate | mean_ci_upper |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows_out:
        lines.append(
            "| {noise_profile} | {no_meaningful_effect_rate:.3f} | {inconclusive_rate:.3f} | {improvement_supported_rate:.3f} | {mean_ci_upper:.3f} |".format(**row)
        )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(output_json), "markdown": str(output_md), "profiles": len(rows_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
