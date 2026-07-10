from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

from .level2_reliability import classify_level2_cell


MME_DEFAULT = 0.10
CLUSTER_BOOTSTRAP_SEED_DEFAULT = 20260703
WILD_BOOTSTRAP_SEED_DEFAULT = 20260704
CLUSTER_BOOTSTRAP_RESAMPLES_DEFAULT = 10_000
WILD_BOOTSTRAP_RESAMPLES_DEFAULT = 10_000


class Stage2AnalysisError(RuntimeError):
    pass


@dataclass
class PrimaryAnalysisResult:
    method: str
    n_rows: int
    n_tasks: int
    effect_b_minus_a: float
    standard_error: float
    df: float
    t_value: float
    p_value_two_sided: float
    ci_lower: float
    ci_upper: float
    mme: float
    mme_cleared: bool
    ci_entirely_above_zero: bool
    mixedlm_effect_b_minus_a: float | None = None
    mixedlm_converged: bool | None = None
    mixedlm_note: str | None = None


@dataclass
class BootstrapResult:
    method: str
    seed: int
    resamples: int
    n_tasks: int
    effect_b_minus_a: float
    ci_lower: float
    ci_upper: float
    bootstrap_mean: float
    mme: float
    mme_cleared: bool
    ci_entirely_above_zero: bool


@dataclass
class LeaveOneTaskOutRow:
    left_out_task: str
    effect_b_minus_a: float
    ci_lower: float
    ci_upper: float
    mme_cleared: bool
    ci_entirely_above_zero: bool


@dataclass
class ManipulationCheckResult:
    condition: str
    n_rows: int
    hash_changed_count: int
    hash_changed_rate: float
    feedback_delivered_count: int | None = None
    feedback_delivered_rate: float | None = None


@dataclass
class DatasetSummary:
    rows_total: int
    tasks_total: int
    conditions: list[str]
    counts_by_category: dict[str, int]
    counts_by_condition: dict[str, int]


def _normal_quantile(prob: float) -> float:
    return NormalDist().inv_cdf(prob)


try:
    from scipy.stats import t as scipy_t  # type: ignore
except Exception:  # pragma: no cover - exercised when scipy missing
    scipy_t = None


try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - exercised when pandas missing
    pd = None


try:
    import statsmodels.formula.api as smf  # type: ignore
except Exception:  # pragma: no cover - exercised when statsmodels missing
    smf = None


def _require_pandas() -> Any:
    if pd is None:
        raise Stage2AnalysisError("pandas is required for Stage 2 analysis scripts")
    return pd


def _t_quantile(prob: float, df: float) -> float:
    if scipy_t is not None:
        return float(scipy_t.ppf(prob, df))
    # Conservative normal fallback if scipy is unavailable.
    return _normal_quantile(prob)


def _t_sf(abs_t: float, df: float) -> float:
    if scipy_t is not None:
        return float(scipy_t.sf(abs_t, df))
    return 1.0 - NormalDist().cdf(abs_t)


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise Stage2AnalysisError("Cannot compute percentile of empty list")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def _is_invalid_category(category: str) -> bool:
    return category in {"provider_unavailable", "harness_invalid"}


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    category = str(row.get("category") or classify_level2_cell(row))
    condition = str(row["condition"])
    normalized = {
        "task_id": str(row["task_id"]),
        "condition": condition,
        "replicate_id": str(row["replicate_id"]),
        "score": _coerce_float(row.get("score"), default=0.0),
        "category": category,
        "benchmark_execution_status": row.get("benchmark_execution_status"),
        "benchmark_outcome_status": row.get("benchmark_outcome_status"),
        "benchmark_classification_reason": row.get("benchmark_classification_reason"),
        "solution_hash_changed_between_attempt_and_repair": _coerce_bool(
            row.get("solution_hash_changed_between_attempt_and_repair")
        ),
        "verify_run_ok": _coerce_bool(row.get("verify_run_ok")),
        "feedback_delivered": _coerce_bool(row.get("feedback_delivered")),
    }
    if condition == "B-agentharness" and not normalized["feedback_delivered"]:
        normalized["feedback_delivered"] = row.get("verify_run_ok") is not None
    return normalized


def load_analysis_dataset(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise Stage2AnalysisError(f"Expected a JSON list at {path}")
    rows = [_normalize_row(dict(item)) for item in payload]
    if not rows:
        raise Stage2AnalysisError(f"Dataset at {path} is empty")
    return rows


def build_dataset_from_progress(progress_path: Path) -> list[dict[str, Any]]:
    payload = _load_json(progress_path)
    if not isinstance(payload, list):
        raise Stage2AnalysisError(f"Expected a JSON list at {progress_path}")
    rows: list[dict[str, Any]] = []
    for record in payload:
        if not isinstance(record, dict):
            raise Stage2AnalysisError("Progress payload contained a non-object record")
        final = record.get("final") or {}
        if not isinstance(final, dict):
            final = {}
        row = {
            "task_id": record.get("task_id"),
            "condition": record.get("condition"),
            "replicate_id": record.get("replicate_id"),
            "score": final.get("score", 0.0),
            "benchmark_execution_status": final.get("benchmark_execution_status", "harness_invalid"),
            "benchmark_outcome_status": final.get("benchmark_outcome_status", "invalid"),
            "benchmark_classification_reason": final.get("benchmark_classification_reason") or record.get("final_error"),
            "solution_hash_changed_between_attempt_and_repair": final.get(
                "solution_hash_changed_between_attempt_and_repair", False
            ),
            "verify_run_ok": final.get("verify_run_ok", False),
            "feedback_delivered": final.get("verify_run_ok", False),
        }
        rows.append(_normalize_row(row))
    return rows


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def summarize_dataset(rows: list[dict[str, Any]]) -> DatasetSummary:
    counts_by_category: dict[str, int] = {}
    counts_by_condition: dict[str, int] = {}
    for row in rows:
        counts_by_category[row["category"]] = counts_by_category.get(row["category"], 0) + 1
        counts_by_condition[row["condition"]] = counts_by_condition.get(row["condition"], 0) + 1
    return DatasetSummary(
        rows_total=len(rows),
        tasks_total=len({row["task_id"] for row in rows}),
        conditions=sorted({row["condition"] for row in rows}),
        counts_by_category=counts_by_category,
        counts_by_condition=counts_by_condition,
    )


def apply_invalid_policy(rows: list[dict[str, Any]], policy: str) -> list[dict[str, Any]]:
    policy = policy.strip().lower()
    out: list[dict[str, Any]] = []
    for row in rows:
        category = str(row["category"])
        if policy == "exclude_infrastructure_invalids":
            if _is_invalid_category(category):
                continue
            out.append(dict(row))
            continue
        if policy == "count_infrastructure_invalids_as_zero":
            patched = dict(row)
            if _is_invalid_category(category):
                patched["score"] = 0.0
            out.append(patched)
            continue
        raise Stage2AnalysisError(f"Unknown invalid policy: {policy}")
    if not out:
        raise Stage2AnalysisError(f"Invalid policy {policy} removed all rows")
    return out


def _task_condition_means(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pandas = _require_pandas()
    df = pandas.DataFrame(rows)
    grouped = (
        df.groupby(["task_id", "condition"], as_index=False)
        .agg(score=("score", "mean"), n=("score", "size"))
        .sort_values(["task_id", "condition"])
    )
    return grouped.to_dict(orient="records")


def _task_differences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    means = _task_condition_means(rows)
    by_task: dict[str, dict[str, float]] = {}
    for row in means:
        by_task.setdefault(str(row["task_id"]), {})[str(row["condition"])] = float(row["score"])
    diffs: list[dict[str, Any]] = []
    for task_id, conds in sorted(by_task.items()):
        if "A-baseline" not in conds or "B-agentharness" not in conds:
            raise Stage2AnalysisError(f"Task {task_id} is missing one condition in the analytic dataset")
        diffs.append(
            {
                "task_id": task_id,
                "mean_a": conds["A-baseline"],
                "mean_b": conds["B-agentharness"],
                "diff": conds["B-agentharness"] - conds["A-baseline"],
            }
        )
    if len(diffs) < 2:
        raise Stage2AnalysisError("Need at least two tasks with both conditions for Stage 2 inference")
    return diffs


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / (len(values) - 1)


def _try_mixedlm_effect(rows: list[dict[str, Any]]) -> tuple[float | None, bool | None, str | None]:
    if smf is None:
        return None, None, "statsmodels unavailable"
    pandas = _require_pandas()
    df = pandas.DataFrame(rows).copy()
    df["condition_flag"] = (df["condition"] == "B-agentharness").astype(int)
    try:
        model = smf.mixedlm("score ~ condition_flag", df, groups=df["task_id"])
        fit = model.fit(reml=True, disp=False)
        return float(fit.params["condition_flag"]), bool(getattr(fit, "converged", True)), None
    except Exception as exc:  # pragma: no cover - best-effort concordance only
        return None, False, repr(exc)


def primary_analysis(rows: list[dict[str, Any]], *, mme: float = MME_DEFAULT) -> PrimaryAnalysisResult:
    diffs = _task_differences(rows)
    values = [float(row["diff"]) for row in diffs]
    n_tasks = len(values)
    effect = _mean(values)
    variance = _sample_variance(values)
    se = math.sqrt(variance / n_tasks) if variance > 0 else 0.0
    df = float(n_tasks - 1)
    if se == 0.0:
        t_value = math.inf if effect > 0 else (-math.inf if effect < 0 else 0.0)
        p_two = 0.0 if effect != 0 else 1.0
        critical = _t_quantile(0.975, df)
        ci_lower = effect
        ci_upper = effect
    else:
        t_value = effect / se
        p_two = 2.0 * _t_sf(abs(t_value), df)
        critical = _t_quantile(0.975, df)
        ci_lower = effect - critical * se
        ci_upper = effect + critical * se
    mixedlm_effect, mixedlm_converged, mixedlm_note = _try_mixedlm_effect(rows)
    return PrimaryAnalysisResult(
        method="paired task-level mean difference with small-cluster t inference",
        n_rows=len(rows),
        n_tasks=n_tasks,
        effect_b_minus_a=effect,
        standard_error=se,
        df=df,
        t_value=t_value,
        p_value_two_sided=p_two,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        mme=mme,
        mme_cleared=ci_lower >= mme,
        ci_entirely_above_zero=ci_lower > 0.0,
        mixedlm_effect_b_minus_a=mixedlm_effect,
        mixedlm_converged=mixedlm_converged,
        mixedlm_note=mixedlm_note,
    )


def cluster_bootstrap(rows: list[dict[str, Any]], *, seed: int, resamples: int, mme: float) -> BootstrapResult:
    diffs = _task_differences(rows)
    rng = random.Random(seed)
    task_diffs = [float(row["diff"]) for row in diffs]
    estimates: list[float] = []
    for _ in range(resamples):
        sampled = [rng.choice(task_diffs) for _ in range(len(task_diffs))]
        estimates.append(_mean(sampled))
    estimates.sort()
    point = _mean(task_diffs)
    ci_lower = _percentile(estimates, 0.025)
    ci_upper = _percentile(estimates, 0.975)
    return BootstrapResult(
        method="cluster bootstrap over task-level paired differences",
        seed=seed,
        resamples=resamples,
        n_tasks=len(task_diffs),
        effect_b_minus_a=point,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        bootstrap_mean=_mean(estimates),
        mme=mme,
        mme_cleared=ci_lower >= mme,
        ci_entirely_above_zero=ci_lower > 0.0,
    )


def wild_cluster_bootstrap(rows: list[dict[str, Any]], *, seed: int, resamples: int, mme: float) -> BootstrapResult:
    diffs = _task_differences(rows)
    rng = random.Random(seed)
    task_diffs = [float(row["diff"]) for row in diffs]
    observed = _mean(task_diffs)
    centered = [value - observed for value in task_diffs]
    estimates: list[float] = []
    for _ in range(resamples):
        sample = [observed + (1 if rng.random() < 0.5 else -1) * delta for delta in centered]
        estimates.append(_mean(sample))
    estimates.sort()
    ci_lower = _percentile(estimates, 0.025)
    ci_upper = _percentile(estimates, 0.975)
    return BootstrapResult(
        method="wild cluster bootstrap over task-level paired differences",
        seed=seed,
        resamples=resamples,
        n_tasks=len(task_diffs),
        effect_b_minus_a=observed,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        bootstrap_mean=_mean(estimates),
        mme=mme,
        mme_cleared=ci_lower >= mme,
        ci_entirely_above_zero=ci_lower > 0.0,
    )


def leave_one_task_out(rows: list[dict[str, Any]], *, mme: float) -> list[LeaveOneTaskOutRow]:
    tasks = sorted({str(row["task_id"]) for row in rows})
    if len(tasks) < 3:
        raise Stage2AnalysisError("Need at least three tasks for leave-one-task-out analysis")
    out: list[LeaveOneTaskOutRow] = []
    for task in tasks:
        subset = [row for row in rows if str(row["task_id"]) != task]
        result = primary_analysis(subset, mme=mme)
        out.append(
            LeaveOneTaskOutRow(
                left_out_task=task,
                effect_b_minus_a=result.effect_b_minus_a,
                ci_lower=result.ci_lower,
                ci_upper=result.ci_upper,
                mme_cleared=result.mme_cleared,
                ci_entirely_above_zero=result.ci_entirely_above_zero,
            )
        )
    return out


def manipulation_checks(rows: list[dict[str, Any]]) -> list[ManipulationCheckResult]:
    out: list[ManipulationCheckResult] = []
    for condition in sorted({str(row["condition"]) for row in rows}):
        subset = [row for row in rows if str(row["condition"]) == condition]
        n = len(subset)
        changed = sum(1 for row in subset if _coerce_bool(row.get("solution_hash_changed_between_attempt_and_repair")))
        if condition == "B-agentharness":
            delivered = sum(1 for row in subset if _coerce_bool(row.get("feedback_delivered")))
            out.append(
                ManipulationCheckResult(
                    condition=condition,
                    n_rows=n,
                    hash_changed_count=changed,
                    hash_changed_rate=changed / n if n else 0.0,
                    feedback_delivered_count=delivered,
                    feedback_delivered_rate=delivered / n if n else 0.0,
                )
            )
        else:
            out.append(
                ManipulationCheckResult(
                    condition=condition,
                    n_rows=n,
                    hash_changed_count=changed,
                    hash_changed_rate=changed / n if n else 0.0,
                )
            )
    return out


def synthetic_dataset(
    *,
    n_tasks: int = 8,
    replicates: int = 6,
    true_effect: float = 0.18,
    task_step: float = 0.03,
    replicate_step: float = 0.005,
    include_invalids: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task_index in range(n_tasks):
        task_id = f"task-{task_index + 1}"
        base = 0.20 + task_index * task_step
        for replicate_index in range(replicates):
            rep = f"r{replicate_index + 1}"
            replicate_offset = (replicate_index - (replicates - 1) / 2.0) * replicate_step
            for condition in ("A-baseline", "B-agentharness"):
                score = base + replicate_offset + (true_effect if condition == "B-agentharness" else 0.0)
                score = max(0.0, min(1.0, round(score, 6)))
                row = {
                    "task_id": task_id,
                    "condition": condition,
                    "replicate_id": rep,
                    "score": score,
                    "benchmark_execution_status": "valid",
                    "benchmark_outcome_status": "success" if score >= 0.999 else "real_failure",
                    "benchmark_classification_reason": None,
                    "solution_hash_changed_between_attempt_and_repair": condition == "B-agentharness",
                    "verify_run_ok": condition == "B-agentharness",
                    "feedback_delivered": condition == "B-agentharness",
                }
                rows.append(_normalize_row(row))
    if include_invalids:
        # Replace one A and one B observation for the last task to exercise sensitivity handling.
        for row in rows:
            if row["task_id"] == f"task-{n_tasks}" and row["replicate_id"] == "r1" and row["condition"] == "A-baseline":
                row.update(
                    {
                        "score": 0.0,
                        "category": "provider_unavailable",
                        "benchmark_execution_status": "harness_invalid",
                        "benchmark_outcome_status": "invalid",
                        "benchmark_classification_reason": "provider_unavailable: synthetic provider outage",
                        "solution_hash_changed_between_attempt_and_repair": False,
                    }
                )
            if row["task_id"] == f"task-{n_tasks}" and row["replicate_id"] == "r2" and row["condition"] == "B-agentharness":
                row.update(
                    {
                        "score": 0.0,
                        "category": "harness_invalid",
                        "benchmark_execution_status": "harness_invalid",
                        "benchmark_outcome_status": "invalid",
                        "benchmark_classification_reason": "synthetic harness invalid",
                        "solution_hash_changed_between_attempt_and_repair": False,
                        "verify_run_ok": False,
                        "feedback_delivered": False,
                    }
                )
    return rows


def run_full_analysis(
    rows: list[dict[str, Any]],
    *,
    mme: float = MME_DEFAULT,
    cluster_seed: int = CLUSTER_BOOTSTRAP_SEED_DEFAULT,
    cluster_resamples: int = CLUSTER_BOOTSTRAP_RESAMPLES_DEFAULT,
    wild_seed: int = WILD_BOOTSTRAP_SEED_DEFAULT,
    wild_resamples: int = WILD_BOOTSTRAP_RESAMPLES_DEFAULT,
) -> dict[str, Any]:
    primary_rows = apply_invalid_policy(rows, "exclude_infrastructure_invalids")
    primary = primary_analysis(primary_rows, mme=mme)
    cluster = cluster_bootstrap(primary_rows, seed=cluster_seed, resamples=cluster_resamples, mme=mme)
    wild = wild_cluster_bootstrap(primary_rows, seed=wild_seed, resamples=wild_resamples, mme=mme)
    loto = leave_one_task_out(primary_rows, mme=mme)
    sensitivity_zero_rows = apply_invalid_policy(rows, "count_infrastructure_invalids_as_zero")
    sensitivity_zero = primary_analysis(sensitivity_zero_rows, mme=mme)
    summary = summarize_dataset(rows)
    manipulation = manipulation_checks(rows)
    decision = {
        "mixed_model_favors_b": primary.effect_b_minus_a > 0.0,
        "cluster_bootstrap_favors_b": cluster.effect_b_minus_a > 0.0,
        "ci_entirely_above_zero": primary.ci_entirely_above_zero,
        "mme_cleared": primary.mme_cleared,
        "not_driven_by_single_task": all(row.ci_entirely_above_zero for row in loto),
        "headline": _headline_from_results(primary, cluster, loto),
    }
    return {
        "dataset_summary": asdict(summary),
        "primary_analysis": asdict(primary),
        "cluster_bootstrap": asdict(cluster),
        "wild_cluster_bootstrap": asdict(wild),
        "leave_one_task_out": [asdict(row) for row in loto],
        "sensitivity_invalids": {
            "primary_policy": "exclude_infrastructure_invalids",
            "primary": asdict(primary),
            "count_infrastructure_invalids_as_zero": asdict(sensitivity_zero),
        },
        "manipulation_checks": [asdict(row) for row in manipulation],
        "decision": decision,
    }


def _headline_from_results(
    primary: PrimaryAnalysisResult,
    cluster: BootstrapResult,
    loto: list[LeaveOneTaskOutRow],
) -> str:
    if (
        primary.effect_b_minus_a > 0.0
        and cluster.effect_b_minus_a > 0.0
        and primary.ci_entirely_above_zero
        and primary.mme_cleared
        and all(row.ci_entirely_above_zero for row in loto)
    ):
        return "improvement_supported"
    if primary.effect_b_minus_a <= 0.0 and cluster.effect_b_minus_a <= 0.0:
        return "no_effect_detected"
    return "mixed_evidence"


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen Stage 2 analysis on a prepared JSON dataset.")
    parser.add_argument("dataset", type=Path, help="Path to stage2-analysis-dataset.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mme", type=float, default=MME_DEFAULT)
    parser.add_argument("--cluster-seed", type=int, default=CLUSTER_BOOTSTRAP_SEED_DEFAULT)
    parser.add_argument("--cluster-resamples", type=int, default=CLUSTER_BOOTSTRAP_RESAMPLES_DEFAULT)
    parser.add_argument("--wild-seed", type=int, default=WILD_BOOTSTRAP_SEED_DEFAULT)
    parser.add_argument("--wild-resamples", type=int, default=WILD_BOOTSTRAP_RESAMPLES_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = _cli()
    rows = load_analysis_dataset(args.dataset)
    outputs = run_full_analysis(
        rows,
        mme=args.mme,
        cluster_seed=args.cluster_seed,
        cluster_resamples=args.cluster_resamples,
        wild_seed=args.wild_seed,
        wild_resamples=args.wild_resamples,
    )
    output_dir = args.output_dir
    write_json(output_dir / "dataset-summary.json", outputs["dataset_summary"])
    write_json(output_dir / "primary-analysis.json", outputs["primary_analysis"])
    write_json(output_dir / "cluster-bootstrap.json", outputs["cluster_bootstrap"])
    write_json(output_dir / "wild-cluster-bootstrap.json", outputs["wild_cluster_bootstrap"])
    write_json(output_dir / "leave-one-task-out.json", outputs["leave_one_task_out"])
    write_json(output_dir / "sensitivity-invalids.json", outputs["sensitivity_invalids"])
    write_json(output_dir / "manipulation-checks.json", outputs["manipulation_checks"])
    write_json(output_dir / "final-report.json", outputs)
    print(json.dumps({"ok": True, "output_dir": str(output_dir), "headline": outputs["decision"]["headline"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
