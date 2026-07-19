from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = (REPO_ROOT / "src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import agentharness
from scipy.stats import t as student_t

from agentharness.stage2_analysis import (
    apply_invalid_policy,
    build_dataset_from_progress,
    load_analysis_dataset,
    run_full_analysis,
    validate_campaign_dataset,
)

if not Path(agentharness.__file__).resolve().is_relative_to(SRC_ROOT):
    raise ImportError("agentharness runtime is not loaded from the frozen repository tree")

NORMATIVE_MANIFEST_RELATIVE = "benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-18_ACCOUNT2.json"
AMENDED_FREEZE_TAG = "stage2-account2-freeze-20260718-v1"
AMENDMENT_AUDIT_NAME = "credential-tranche-amendment.json"

REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "provider",
        "model",
        "hermes_command",
        "hermes_command_sha256",
        "hermes_home",
        "credential_tranche",
        "toolsets",
        "max_turns",
        "codex_sse_idle_seconds",
        "invocation_max_retries",
        "retry_backoff_seconds",
        "tasks",
        "conditions",
        "replicates",
        "expected_cells",
        "expected_blocks",
        "blocks",
        "mme",
        "rerun_policy",
        "quota_policy",
        "analysis_parameters",
        "frozen_file_sha256",
        "manifest_payload_sha256",
    }
)

REQUIRED_FROZEN_FILE_KEYS = frozenset(
    {
        "benchmarks/grading-env/run_stage2_efficacy_campaign.py",
        "benchmarks/grading-env/finalize_stage2_efficacy.py",
        "benchmarks/grading-env/stage2_run_analysis.py",
        "benchmarks/grading-env/stage2-analysis-requirements.txt",
        "src/agentharness/benchmark_cells.py",
        "src/agentharness/evaluation.py",
        "src/agentharness/stage2_analysis.py",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


def atomic_write(path: Path, payload: object, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    if mode is not None:
        os.chmod(path, mode)
    directory_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _validate_manifest_binding(manifest_path: Path) -> tuple[dict[str, Any], str, str]:
    """Validate manifest identity/roster/hash binding. Returns (manifest, payload_sha256, file_sha256)."""
    expected_manifest_path = (REPO_ROOT / NORMATIVE_MANIFEST_RELATIVE).resolve()
    if manifest_path.resolve() != expected_manifest_path:
        raise ValueError(f"Manifest must be the frozen normative file: {NORMATIVE_MANIFEST_RELATIVE}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing_keys = sorted(REQUIRED_MANIFEST_KEYS - manifest.keys())
    if missing_keys:
        raise ValueError(f"Manifest missing required keys: {missing_keys}")

    manifest_copy = dict(manifest)
    expected_manifest_hash = str(manifest_copy.pop("manifest_payload_sha256"))
    actual_manifest_hash = hashlib.sha256(canonical(manifest_copy)).hexdigest()
    if actual_manifest_hash != expected_manifest_hash:
        raise ValueError("Campaign manifest payload hash mismatch")
    manifest_file_hash = sha256(manifest_path)

    blocks = list(manifest["blocks"])
    expected_block_ids = {f"b{index:03d}" for index in range(1, 61)}
    observed_block_ids = {str(row["block_id"]) for row in blocks}
    if observed_block_ids != expected_block_ids:
        raise ValueError("Block ID roster mismatch: expected b001..b060")

    cell_ids: set[str] = set()
    for row in blocks:
        if sorted(row["condition_order"]) != ["A-baseline", "B-agentharness"]:
            raise ValueError(f"Invalid condition order in {row['block_id']}")
        for slot in (1, 2):
            cell_ids.add(f"{row['block_id']}-s{slot}")
    if len(cell_ids) != 120:
        raise ValueError("Cell ID roster is not unique/complete")

    required_frozen_keys = set(REQUIRED_FROZEN_FILE_KEYS)
    for task in manifest["tasks"]:
        required_frozen_keys.add(f"benchmarks/{task}/SPEC.md")
        required_frozen_keys.add(f"benchmarks/{task}/CLAIMS_CONTRACT.template.json")
    frozen_hashes = manifest["frozen_file_sha256"]
    missing_frozen_keys = sorted(required_frozen_keys - frozen_hashes.keys())
    if missing_frozen_keys:
        raise ValueError(f"Manifest frozen_file_sha256 missing required keys: {missing_frozen_keys}")
    for relative, expected in frozen_hashes.items():
        path = REPO_ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Frozen file hash mismatch: {relative}")

    return manifest, expected_manifest_hash, manifest_file_hash


def _validate_progress_identities(progress: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    blocks_by_id = {str(row["block_id"]): row for row in manifest["blocks"]}
    seen_cells: set[str] = set()
    for row in progress:
        block_id = str(row["block_id"])
        block = blocks_by_id.get(block_id)
        if block is None:
            raise ValueError(f"Progress row references unknown block {block_id}")
        final = row.get("final") or {}
        slot = final.get("slot")
        if slot not in (1, 2):
            raise ValueError(f"Progress row for {block_id} has an invalid slot")
        expected_cell_id = f"{block_id}-s{slot}"
        if str(row.get("campaign_cell_id")) != expected_cell_id:
            raise ValueError(f"Campaign cell id mismatch for {block_id}")
        if str(row["task_id"]) != str(block["task_id"]) or str(row["replicate_id"]) != str(block["replicate_id"]):
            raise ValueError(f"Task/replicate mismatch for {block_id}")
        if str(row["condition"]) != str(block["condition_order"][slot - 1]):
            raise ValueError(f"Condition/slot mismatch for {block_id}")
        if expected_cell_id in seen_cells:
            raise ValueError(f"Duplicate cell id {expected_cell_id}")
        seen_cells.add(expected_cell_id)
    expected_cells = {f"{row['block_id']}-s{slot}" for row in manifest["blocks"] for slot in (1, 2)}
    if seen_cells != expected_cells:
        raise ValueError("Progress cell roster incomplete or mismatched")


def paired_task_result(task_differences: list[float], *, favorable: str) -> dict[str, object]:
    n = len(task_differences)
    if n < 2:
        raise ValueError("At least two task differences are required")
    estimate = mean(task_differences)
    sd = stdev(task_differences)
    se = sd / math.sqrt(n)
    if se == 0.0:
        statistic = math.inf if estimate > 0 else (-math.inf if estimate < 0 else 0.0)
        p_value = 0.0 if estimate != 0 else 1.0
        lower = upper = estimate
    else:
        statistic = estimate / se
        p_value = float(2.0 * student_t.sf(abs(statistic), df=n - 1))
        critical = float(student_t.ppf(0.975, df=n - 1))
        lower = estimate - critical * se
        upper = estimate + critical * se
    return {
        "method": "equal_weight_paired_task_mean_student_t",
        "favorable_direction": favorable,
        "n_tasks": n,
        "estimate_b_minus_a": estimate,
        "task_difference_sd": sd,
        "standard_error": se,
        "df": n - 1,
        "t_value": statistic,
        "p_value_two_sided": p_value,
        "ci_lower": lower,
        "ci_upper": upper,
    }


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    m = len(ordered)
    for index, (name, value) in enumerate(ordered):
        candidate = min(1.0, value * (m - index))
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted


def task_differences(
    progress: list[dict[str, Any]],
    value_fn: Any,
) -> list[float]:
    tasks = sorted({str(row["task_id"]) for row in progress})
    out: list[float] = []
    for task in tasks:
        arm_values: dict[str, list[float]] = {"A-baseline": [], "B-agentharness": []}
        for row in progress:
            if str(row["task_id"]) != task:
                continue
            arm_values[str(row["condition"])].append(float(value_fn(row["final"])))
        if len(arm_values["A-baseline"]) != 3 or len(arm_values["B-agentharness"]) != 3:
            raise ValueError(f"Secondary endpoint shape mismatch for {task}")
        out.append(mean(arm_values["B-agentharness"]) - mean(arm_values["A-baseline"]))
    return out


def mechanism_summary(progress: list[dict[str, Any]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for condition in ("A-baseline", "B-agentharness"):
        finals = [row["final"] for row in progress if row["condition"] == condition]
        n = len(finals)
        if n != 60:
            raise ValueError(f"Expected 60 scheduled cells for {condition}, got {n}")
        result[condition] = {
            "scheduled_cells": n,
            "treatment_delivered_count": sum(bool(row.get("treatment_delivered")) for row in finals),
            "feedback_delivered_count": sum(bool(row.get("feedback_delivered")) for row in finals),
            "solution_hash_changed_count": sum(
                bool(row.get("solution_hash_changed_between_attempt_and_repair")) for row in finals
            ),
            "valid_endpoint_count": sum(bool(row.get("heldout_endpoint_valid")) for row in finals),
            "infrastructure_invalid_count": sum(
                str(row.get("benchmark_execution_status")) == "harness_invalid" for row in finals
            ),
            "rollback_performed_count": sum(bool(row.get("repair_rollback_performed")) for row in finals),
            "agent_invocation_count": sum(int(row.get("agent_invocation_count", 0)) for row in finals),
            "agent_duration_seconds_total": sum(float(row.get("agent_duration_seconds", 0.0)) for row in finals),
        }
    return result


def require_valid_coverage(rows: list[dict[str, Any]], tasks: list[str]) -> None:
    valid = apply_invalid_policy(rows, "exclude_infrastructure_invalids")
    observed = {(row["task_id"], row["condition"]) for row in valid}
    missing = [
        (task, condition)
        for task in tasks
        for condition in ("A-baseline", "B-agentharness")
        if (task, condition) not in observed
    ]
    if missing:
        raise ValueError(f"Primary analysis invalid: no valid replicate for task-condition pairs {missing}")


def _validate_credential_amendment(
    *,
    run_root: Path,
    state: dict[str, Any],
    seal: dict[str, Any],
    manifest_payload_sha256: str,
    manifest_file_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    audit_path = run_root / AMENDMENT_AUDIT_NAME
    if not audit_path.is_file():
        raise ValueError("Credential-tranche amendment audit is missing")
    audit_sha = sha256(audit_path)
    if state.get("credential_tranche_amendment_sha256") != audit_sha:
        raise ValueError("State credential-tranche amendment hash mismatch")
    if seal.get("credential_tranche_amendment_sha256") != audit_sha:
        raise ValueError("Dataset seal credential-tranche amendment hash mismatch")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("migration_complete") is not True or audit.get("analysis_authorized") is not False:
        raise ValueError("Credential-tranche migration is not complete and sealed")
    if audit.get("new_manifest_payload_sha256") != manifest_payload_sha256:
        raise ValueError("Credential-tranche audit manifest payload mismatch")
    if audit.get("new_manifest_file_sha256") != manifest_file_sha256:
        raise ValueError("Credential-tranche audit manifest file mismatch")
    if audit.get("new_repository_commit") != repository_commit:
        raise ValueError("Credential-tranche audit repository commit mismatch")
    if audit.get("preserved_pair_complete_blocks") != [f"b{i:03d}" for i in range(1, 19)]:
        raise ValueError("Credential-tranche audit preserved-block frontier mismatch")
    if audit.get("boundary_block_restarted") != "b019":
        raise ValueError("Credential-tranche audit boundary mismatch")
    fingerprints = audit.get("account_fingerprints_sha256")
    if not isinstance(fingerprints, dict) or set(fingerprints) != {
        "codex-account-tranche-1",
        "codex-account-tranche-2",
    }:
        raise ValueError("Credential-tranche fingerprints are incomplete")
    if fingerprints["codex-account-tranche-1"] == fingerprints["codex-account-tranche-2"]:
        raise ValueError("Credential tranches resolve to the same account")
    tagged_commit = git("rev-parse", f"refs/tags/{AMENDED_FREEZE_TAG}^{{commit}}")
    if tagged_commit != repository_commit:
        raise ValueError("Finalization repository commit is not the amended freeze tag")
    return audit


def _rows_with_block_ids(
    rows: list[dict[str, Any]], progress: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    row_map = {
        (str(row["task_id"]), str(row["condition"]), str(row["replicate_id"])): row
        for row in rows
    }
    joined: list[dict[str, Any]] = []
    for progress_row in progress:
        key = (
            str(progress_row["task_id"]),
            str(progress_row["condition"]),
            str(progress_row["replicate_id"]),
        )
        sealed_row = row_map.get(key)
        if sealed_row is None:
            raise ValueError("Credential-tranche sensitivity identity join failed")
        joined.append({**sealed_row, "block_id": str(progress_row["block_id"])})
    if len(joined) != len(rows):
        raise ValueError("Credential-tranche sensitivity identity join is not one-to-one")
    return joined


def _task_weighted_tranche_summary(
    joined_rows: list[dict[str, Any]], block_ids: set[str], *, mme: float
) -> dict[str, Any]:
    valid = apply_invalid_policy(
        [row for row in joined_rows if str(row["block_id"]) in block_ids],
        "exclude_infrastructure_invalids",
    )
    by_task: dict[str, dict[str, list[float]]] = {}
    for row in valid:
        task = str(row["task_id"])
        condition = str(row["condition"])
        by_task.setdefault(
            task, {"A-baseline": [], "B-agentharness": []}
        )[condition].append(float(row["score"]))
    differences = [
        mean(arms["B-agentharness"]) - mean(arms["A-baseline"])
        for _, arms in sorted(by_task.items())
        if arms["A-baseline"] and arms["B-agentharness"]
    ]
    if len(differences) < 2:
        raise ValueError("Credential-tranche sensitivity has fewer than two represented tasks")
    result = paired_task_result(differences, favorable="positive")
    result["method"] = "descriptive_equal_weight_task_mean_within_credential_tranche"
    lower = float(str(result["ci_lower"]))
    upper = float(str(result["ci_upper"]))
    if lower > mme:
        headline = "improvement_supported"
    elif upper < mme:
        headline = "no_meaningful_effect"
    else:
        headline = "inconclusive"
    result["mme"] = mme
    result["descriptive_headline"] = headline
    result["confirmatory_status"] = "sensitivity_only_cannot_override_primary"
    return result


def credential_tranche_sensitivity(
    rows: list[dict[str, Any]],
    progress: list[dict[str, Any]],
    *,
    mme: float,
    primary_headline: str,
    analysis_parameters: dict[str, Any],
) -> dict[str, Any]:
    joined = _rows_with_block_ids(rows, progress)
    without_boundary = [row for row in joined if row["block_id"] != "b019"]
    primary_without_b019 = run_full_analysis(
        without_boundary,
        mme=mme,
        cluster_seed=int(analysis_parameters["cluster_seed"]),
        cluster_resamples=int(analysis_parameters["cluster_resamples"]),
        wild_seed=int(analysis_parameters["wild_seed"]),
        wild_resamples=int(analysis_parameters["wild_resamples"]),
        include_mixedlm=True,
    )
    tranche_1 = _task_weighted_tranche_summary(
        joined, {f"b{i:03d}" for i in range(1, 19)}, mme=mme
    )
    tranche_2 = _task_weighted_tranche_summary(
        joined, {f"b{i:03d}" for i in range(19, 61)}, mme=mme
    )
    boundary_headline = str(primary_without_b019["decision"]["headline"])
    return {
        "primary_estimand_without_boundary_block_b019": primary_without_b019,
        "boundary_exclusion_headline_matches_primary": boundary_headline == primary_headline,
        "credential_tranche_conditioned_equal_weight_task_summaries": {
            "codex-account-tranche-1_b001_b018": tranche_1,
            "codex-account-tranche-2_b019_b060": tranche_2,
        },
        "primary_headline": primary_headline,
        "cannot_rescue_or_override_primary": True,
    }


def finalize(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    manifest_path = manifest_path.resolve()
    run_root = run_root.resolve()
    manifest, expected_manifest_hash, manifest_file_hash = _validate_manifest_binding(manifest_path)

    state = json.loads((run_root / "campaign-state.private.json").read_text(encoding="utf-8"))
    seal = json.loads((run_root / "dataset-seal.json").read_text(encoding="utf-8"))
    dataset_path = run_root / "analysis-dataset.sealed.json"
    progress_path = run_root / "progress.private.json"

    if state.get("status") != "complete":
        raise ValueError("Campaign is not complete")
    if state.get("manifest_sha256") != expected_manifest_hash:
        raise ValueError("State is not bound to the frozen campaign manifest payload")
    if state.get("manifest_file_sha256") != manifest_file_hash:
        raise ValueError("State is not bound to the frozen campaign manifest file")
    if seal.get("manifest_file_sha256") != manifest_file_hash:
        raise ValueError("Seal is not bound to the frozen campaign manifest file")
    repository_commit = state.get("repository_commit")
    if not repository_commit or seal.get("repository_commit") != repository_commit:
        raise ValueError("Seal repository commit does not match campaign state")
    amendment_audit = _validate_credential_amendment(
        run_root=run_root,
        state=state,
        seal=seal,
        manifest_payload_sha256=expected_manifest_hash,
        manifest_file_sha256=manifest_file_hash,
        repository_commit=str(repository_commit),
    )
    if sha256(dataset_path) != seal["dataset_sha256"] or sha256(progress_path) != seal["progress_sha256"]:
        raise ValueError("Dataset seal hash mismatch")

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    tasks = list(manifest["tasks"])
    _validate_progress_identities(progress, manifest)

    rebuilt_rows = build_dataset_from_progress(progress_path)
    sealed_rows = load_analysis_dataset(dataset_path)
    if canonical(rebuilt_rows) != canonical(sealed_rows):
        raise ValueError("Sealed dataset is not semantically identical to the progress-rebuilt dataset")

    rows = sealed_rows
    validate_campaign_dataset(rows, expected_task_ids=tasks, expected_replicates_per_condition=3)
    require_valid_coverage(rows, tasks)

    params = manifest["analysis_parameters"]
    if not isinstance(params, dict):
        raise ValueError("Invalid analysis parameter block")
    primary = run_full_analysis(
        rows,
        mme=float(manifest["mme"]),
        cluster_seed=int(params["cluster_seed"]),
        cluster_resamples=int(params["cluster_resamples"]),
        wild_seed=int(params["wild_seed"]),
        wild_resamples=int(params["wild_resamples"]),
        include_mixedlm=True,
    )
    sensitivity = credential_tranche_sensitivity(
        rows,
        progress,
        mme=float(manifest["mme"]),
        primary_headline=str(primary["decision"]["headline"]),
        analysis_parameters=params,
    )
    success = paired_task_result(
        task_differences(progress, lambda final: float(final.get("score", 0.0)) == 1.0),
        favorable="positive",
    )
    cost = paired_task_result(
        task_differences(progress, lambda final: float(final["agent_duration_seconds"])),
        favorable="negative",
    )
    adjusted = holm_adjust(
        {
            "complete_six_of_six_success": float(success["p_value_two_sided"]),
            "total_agent_wall_clock_seconds": float(cost["p_value_two_sided"]),
        }
    )
    success["holm_adjusted_p_value"] = adjusted["complete_six_of_six_success"]
    cost["holm_adjusted_p_value"] = adjusted["total_agent_wall_clock_seconds"]
    report = {
        "schema_version": 1,
        "campaign_id": manifest["campaign_id"],
        "manifest_payload_sha256": manifest["manifest_payload_sha256"],
        "manifest_file_sha256": manifest_file_hash,
        "repository_commit": repository_commit,
        "dataset_sha256": seal["dataset_sha256"],
        "power_disclosure": manifest["power"],
        "scope": {
            "tasks": 20,
            "replicates_per_condition": 3,
            "cells": 120,
            "provider": manifest["provider"],
            "model": manifest["model"],
            "generalization": "frozen_suite_model_tools_and_budget_only",
        },
        "primary": primary,
        "credential_tranche_amendment": {
            "audit_sha256": state["credential_tranche_amendment_sha256"],
            "amendment": amendment_audit["amendment"],
            "outcome_blind_when_applied": amendment_audit["outcome_blind"],
        },
        "credential_tranche_sensitivity": sensitivity,
        "secondary_confirmatory_holm_family": {
            "familywise_alpha": 0.05,
            "complete_six_of_six_success": success,
            "total_agent_wall_clock_seconds": cost,
            "cannot_rescue_primary": True,
        },
        "mechanism_descriptive": mechanism_summary(progress),
    }
    output = run_root / "STAGE2_EFFICACY_RESULT.json"
    atomic_write(output, report)
    result = {
        "output": str(output),
        "output_sha256": sha256(output),
        "headline": primary["decision"]["headline"],
        "public_claim_classification": primary["decision"]["public_claim_classification"],
    }
    summary_path = run_root / "STAGE2_EFFICACY_RESULT_SUMMARY.json"
    atomic_write(summary_path, result)

    finalization_seal = {
        "campaign_id": manifest["campaign_id"],
        "manifest_payload_sha256": expected_manifest_hash,
        "manifest_file_sha256": manifest_file_hash,
        "repository_commit": repository_commit,
        "credential_tranche_amendment_sha256": state[
            "credential_tranche_amendment_sha256"
        ],
        "rows": len(rows),
        "blocks": seal.get("blocks"),
        "output_sha256": result["output_sha256"],
        "summary_sha256": sha256(summary_path),
        "finalized_at": utc_now(),
        "authorized": True,
    }
    atomic_write(run_root / "STAGE2_EFFICACY_FINALIZATION_SEAL.json", finalization_seal, mode=0o600)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize the frozen Stage 2 efficacy campaign")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(finalize(manifest_path=args.manifest, run_root=args.run_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
