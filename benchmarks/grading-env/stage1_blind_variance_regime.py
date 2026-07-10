#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentharness.stage2_analysis import build_dataset_from_progress  # noqa: E402

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


def _sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Blindly estimate Stage 1 noise regime without reading A-B contrasts.")
    parser.add_argument("progress_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = build_dataset_from_progress(args.progress_json)
    valid_rows = [row for row in rows if row.get("benchmark_execution_status") == "valid"]
    if not valid_rows:
        raise SystemExit("No valid rows available for blind variance estimation")

    task_scores: dict[str, list[float]] = {}
    task_condition_scores: dict[tuple[str, str], list[float]] = {}
    for row in valid_rows:
        task_scores.setdefault(str(row["task_id"]), []).append(float(row["score"]))
        key = (str(row["task_id"]), str(row["condition"]))
        task_condition_scores.setdefault(key, []).append(float(row["score"]))

    task_means = {task_id: sum(scores) / len(scores) for task_id, scores in task_scores.items()}
    between_task_sd = math.sqrt(_sample_variance(list(task_means.values())))

    within_group_vars: list[float] = []
    within_group_sds: list[float] = []
    group_counts: dict[str, int] = {}
    for (task_id, condition), scores in sorted(task_condition_scores.items()):
        group_counts[f"{task_id}::{condition}"] = len(scores)
        if len(scores) >= 2:
            variance = _sample_variance(scores)
            within_group_vars.append(variance)
            within_group_sds.append(math.sqrt(variance))

    if not within_group_vars:
        raise SystemExit("Need at least one task-condition with 2+ valid replicates")

    pooled_within_sd = math.sqrt(sum(within_group_vars) / len(within_group_vars))
    mean_group_sd = sum(within_group_sds) / len(within_group_sds)

    profile_distances: list[dict[str, float | str]] = []
    for profile in NOISE_PROFILES:
        synthetic_within_sd = math.sqrt(
            float(profile["replicate_noise_sd"]) ** 2 + float(profile["observation_noise_sd"]) ** 2
        )
        distance = math.sqrt(
            (between_task_sd - float(profile["task_noise_sd"])) ** 2
            + (pooled_within_sd - synthetic_within_sd) ** 2
        )
        profile_distances.append(
            {
                "noise_profile": str(profile["name"]),
                "task_noise_sd": float(profile["task_noise_sd"]),
                "synthetic_within_sd": synthetic_within_sd,
                "distance": distance,
            }
        )
    profile_distances.sort(key=lambda item: float(item["distance"]))

    payload = {
        "method_guardrail": "blind variance regime estimation from score dispersion only; no A-B contrast computed",
        "valid_rows_used": len(valid_rows),
        "valid_tasks_used": len(task_means),
        "between_task_sd": between_task_sd,
        "within_task_condition_pooled_sd": pooled_within_sd,
        "within_task_condition_mean_sd": mean_group_sd,
        "task_mean_scores": task_means,
        "task_condition_valid_counts": group_counts,
        "nearest_noise_profile": profile_distances[0]["noise_profile"],
        "profile_distances": profile_distances,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "nearest_noise_profile": payload["nearest_noise_profile"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
