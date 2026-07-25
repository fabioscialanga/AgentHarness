from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .evaluation import evaluate_run
from .stage2_analysis import (
    build_dataset_from_progress,
    load_analysis_dataset,
    run_full_analysis,
    validate_campaign_dataset,
)

RECOVERY_SCOPE = "exploratory_amended_16_tasks"
RECOVERY_QUALIFICATION = "non_confirmatory_recovered_exploratory"
EXCLUDED_LEGACY_TASKS = frozenset(
    {
        "access-policy-evaluator",
        "dependency-impact-planner",
        "safe-archive-extraction",
        "versioned-document-api",
    }
)
EXPECTED_ORIGINAL_TASKS = 20
EXPECTED_RECOVERY_TASKS = 16
EXPECTED_ORIGINAL_BLOCKS = 60
EXPECTED_ORIGINAL_CELLS = 120
EXPECTED_RECOVERY_CELLS = 96
EXPECTED_CASES = 6
FINAL_RESULT_NAMES = (
    "STAGE2_EFFICACY_RESULT.json",
    "STAGE2_EFFICACY_RESULT_SUMMARY.json",
    "STAGE2_EFFICACY_FINALIZATION_SEAL.json",
)
ATTEMPT_RE = re.compile(r"^attempt-(\d+)-harness_invalid_rerun$")
RUN_ATTEMPT_RE = re.compile(r"_a(\d+)$")


class RecoveryError(RuntimeError):
    """Fail-closed recovery validation error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise RecoveryError(f"required file missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"invalid required JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RecoveryError(f"expected JSON object: {path.name}")
    return payload


def _load_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"invalid required JSON: {path.name}") from exc
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise RecoveryError(f"expected JSON object list: {path.name}")
    return payload


def _atomic_json(path: Path, payload: object, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _require_separate_output(run_root: Path, output_root: Path) -> None:
    if _is_within(output_root, run_root) or _is_within(run_root, output_root):
        raise RecoveryError("output root and original run root must be disjoint")


def _manifest_payload_hash(manifest: dict[str, Any]) -> str | None:
    declared = manifest.get("manifest_payload_sha256")
    if declared is None:
        return None
    copy = dict(manifest)
    copy.pop("manifest_payload_sha256", None)
    actual = hashlib.sha256(canonical(copy)).hexdigest()
    if actual != declared:
        raise RecoveryError("manifest payload hash mismatch")
    return actual


def _validate_original(
    *, run_root: Path, manifest_path: Path, amendment_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    manifest = _load_object(manifest_path)
    amendment = _load_object(amendment_path)
    state = _load_object(run_root / "campaign-state.private.json")
    seal = _load_object(run_root / "dataset-seal.json")
    progress_path = run_root / "progress.private.json"
    dataset_path = run_root / "analysis-dataset.sealed.json"

    if state.get("status") != "complete":
        raise RecoveryError("original campaign state is not complete")
    if len(manifest.get("tasks", [])) != EXPECTED_ORIGINAL_TASKS:
        raise RecoveryError("original manifest task roster is not 20 tasks")
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != EXPECTED_ORIGINAL_BLOCKS:
        raise RecoveryError("original manifest block roster is not 60 blocks")
    if set(manifest["tasks"]) & EXCLUDED_LEGACY_TASKS != EXCLUDED_LEGACY_TASKS:
        raise RecoveryError("manifest does not contain the four declared legacy exclusions")
    if amendment.get("scope") != RECOVERY_SCOPE or amendment.get("outcome_blind") is not True:
        raise RecoveryError("recovery amendment is missing the frozen outcome-blind scope")
    if set(amendment.get("excluded_tasks", [])) != EXCLUDED_LEGACY_TASKS:
        raise RecoveryError("recovery amendment legacy exclusion roster mismatch")

    manifest_file_hash = sha256_file(manifest_path)
    manifest_payload_hash = _manifest_payload_hash(manifest)
    if state.get("manifest_file_sha256") not in (None, manifest_file_hash):
        raise RecoveryError("state manifest file binding mismatch")
    if seal.get("manifest_file_sha256") != manifest_file_hash:
        raise RecoveryError("original seal manifest file binding mismatch")
    if manifest_payload_hash is not None and state.get("manifest_sha256") != manifest_payload_hash:
        raise RecoveryError("state manifest payload binding mismatch")
    if not state.get("repository_commit") or state.get("repository_commit") != seal.get("repository_commit"):
        raise RecoveryError("state/seal repository binding mismatch")
    if sha256_file(progress_path) != seal.get("progress_sha256"):
        raise RecoveryError("original progress seal mismatch")
    if sha256_file(dataset_path) != seal.get("dataset_sha256"):
        raise RecoveryError("original dataset seal mismatch")
    if int(seal.get("rows", -1)) != EXPECTED_ORIGINAL_CELLS or int(seal.get("blocks", -1)) != EXPECTED_ORIGINAL_BLOCKS:
        raise RecoveryError("original seal shape mismatch")
    for name in FINAL_RESULT_NAMES:
        if (run_root / name).exists():
            raise RecoveryError("a pre-existing final analysis result forbids blind recovery")

    journals = sorted((run_root / "block-journals").glob("*.commit.json"))
    if len(journals) != EXPECTED_ORIGINAL_BLOCKS:
        raise RecoveryError("original block journal count mismatch")
    expected_blocks = {str(block["block_id"]) for block in blocks}
    if {path.name.removesuffix(".commit.json") for path in journals} != expected_blocks:
        raise RecoveryError("original block journal roster mismatch")

    progress = _load_list(progress_path)
    if len(progress) != EXPECTED_ORIGINAL_CELLS:
        raise RecoveryError("original progress row count mismatch")
    blocks_by_id = {str(block["block_id"]): block for block in blocks}
    seen: set[str] = set()
    for row in progress:
        final = row.get("final")
        if not isinstance(final, dict):
            raise RecoveryError("progress row lacks final object")
        block = blocks_by_id.get(str(row.get("block_id")))
        slot = final.get("slot")
        if block is None or slot not in (1, 2):
            raise RecoveryError("progress identity does not bind to manifest")
        cell_id = f"{block['block_id']}-s{slot}"
        if row.get("campaign_cell_id") != cell_id or cell_id in seen:
            raise RecoveryError("progress cell identity mismatch or duplicate")
        if row.get("task_id") != block.get("task_id") or row.get("replicate_id") != block.get("replicate_id"):
            raise RecoveryError("progress task/replicate binding mismatch")
        if row.get("condition") != block["condition_order"][slot - 1]:
            raise RecoveryError("progress condition/slot binding mismatch")
        seen.add(cell_id)
    if len(seen) != EXPECTED_ORIGINAL_CELLS:
        raise RecoveryError("progress cell roster incomplete")
    return manifest, progress, state, seal


def _attempt_number(cell_dir: Path) -> int:
    manifest = _load_object(cell_dir / "cell_manifest.json")
    match = RUN_ATTEMPT_RE.search(str(manifest.get("run_id", "")))
    if not match:
        raise RecoveryError("attempt run_id lacks required _aN suffix")
    return int(match.group(1))


def select_first_attempt(run_root: Path, cell_id: str) -> tuple[Path, int]:
    candidates: list[tuple[int, Path]] = []
    quarantine = run_root / "quarantine" / cell_id
    if quarantine.is_dir():
        for path in quarantine.iterdir():
            if "account-tranche-boundary" in path.name:
                continue
            match = ATTEMPT_RE.fullmatch(path.name)
            if match and path.is_dir():
                number = int(match.group(1))
                if _attempt_number(path) != number:
                    raise RecoveryError("quarantine directory/run_id attempt mismatch")
                candidates.append((number, path))
    final_dir = run_root / "private-cells" / cell_id
    if not final_dir.is_dir():
        raise RecoveryError("final private cell directory missing")
    candidates.append((_attempt_number(final_dir), final_dir))
    numbers = [number for number, _ in candidates]
    if len(numbers) != len(set(numbers)):
        raise RecoveryError("duplicate physical attempt number")
    return min(candidates, key=lambda item: item[0])[1], min(numbers)


def _validate_standard_suite(suite: dict[str, Any], *, expected_run_id: str) -> list[str]:
    if suite.get("run_id") != expected_run_id or not suite.get("suite_id"):
        raise RecoveryError("suite/run envelope binding mismatch")
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASES:
        raise RecoveryError("suite is not a six-case standard evaluator")
    ids: list[str] = []
    for case in cases:
        if not isinstance(case, dict) or not {"id", "type", "path", "expected"} <= case.keys():
            raise RecoveryError("suite case lacks standard evaluator oracle fields")
        ids.append(str(case["id"]))
    if len(set(ids)) != EXPECTED_CASES:
        raise RecoveryError("suite case IDs are not unique")
    return ids


def validate_replay_payload(payload: dict[str, Any], *, expected_ids: list[str]) -> float:
    """Validate endpoint semantics. Deliberately does not use payload['ok']."""
    if payload.get("gating_errors") not in ([], None):
        raise RecoveryError("replay endpoint has gating errors")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != EXPECTED_CASES:
        raise RecoveryError("replay endpoint result count mismatch")
    observed: list[str] = []
    passed = 0
    for result in results:
        if not isinstance(result, dict):
            raise RecoveryError("replay endpoint result is not an object")
        case_id = str(result.get("case_id", ""))
        status = result.get("status")
        if status not in {"passed", "failed"}:
            raise RecoveryError("replay endpoint contains a non-terminal status")
        observed.append(case_id)
        passed += int(status == "passed")
    if len(set(observed)) != EXPECTED_CASES or set(observed) != set(expected_ids):
        raise RecoveryError("replay endpoint case ID roster mismatch")
    return passed / EXPECTED_CASES


def _attempt_cost(attempt_dir: Path) -> tuple[int, float]:
    meta_paths = sorted((attempt_dir / "outputs" / "agent-invocations").glob("*.meta.json"))
    if not meta_paths:
        raise RecoveryError("selected attempt has no invocation provenance")
    duration = 0.0
    for path in meta_paths:
        payload = _load_object(path)
        value = payload.get("duration_seconds")
        if not isinstance(value, (int, float)) or value < 0:
            raise RecoveryError("selected attempt has invalid invocation duration")
        duration += float(value)
    return len(meta_paths), duration


def _recovered_final(
    original: dict[str, Any], *, attempt_dir: Path, attempt_no: int, score: float
) -> dict[str, Any]:
    final = deepcopy(original)
    provenance_path = attempt_dir / "provenance.json"
    if not provenance_path.is_file():
        raise RecoveryError("selected attempt provenance is missing")
    provenance = _load_object(provenance_path)
    delivery = provenance.get("treatment_delivery")
    if not isinstance(delivery, dict) or delivery.get("repair_invocation_succeeded") is not True:
        raise RecoveryError("selected attempt lacks treatment delivery provenance")
    condition = str(final.get("condition"))
    if (
        provenance.get("task_id") != final.get("task_id")
        or provenance.get("condition") != condition
        or provenance.get("replicate_id") != final.get("replicate_id")
    ):
        raise RecoveryError("selected attempt provenance identity mismatch")
    prompt_pre = str(delivery.get("treatment_prompt_sha256_pre") or "")
    prompt_post = str(delivery.get("treatment_prompt_sha256_post") or "")
    if (
        len(prompt_pre) != 64
        or prompt_pre != prompt_post
        or delivery.get("treatment_prompt_immutable") is not True
    ):
        raise RecoveryError("selected attempt treatment prompt binding is invalid")
    if condition == "B-agentharness" and delivery.get("feedback_delivered") is not True:
        raise RecoveryError("selected AgentHarness attempt lacks feedback provenance")
    if condition == "A-baseline" and delivery.get("feedback_delivered") is True:
        raise RecoveryError("selected baseline attempt received AgentHarness feedback")
    if condition == "B-agentharness":
        feedback_pre = str(delivery.get("feedback_sha256_pre") or "")
        feedback_post = str(delivery.get("feedback_sha256_post") or "")
        if (
            len(feedback_pre) != 64
            or feedback_pre != feedback_post
            or delivery.get("feedback_immutable") is not True
        ):
            raise RecoveryError("selected attempt feedback binding is invalid")
    invocation_count, duration = _attempt_cost(attempt_dir)
    final.update(
        {
            "score": score,
            "benchmark_execution_status": "valid",
            "benchmark_outcome_status": "success" if score == 1.0 else "real_failure",
            "benchmark_classification_reason": None,
            "heldout_endpoint_denominator": EXPECTED_CASES,
            "heldout_endpoint_valid": True,
            "heldout_endpoint_error": None,
            "execution_attempt_no": attempt_no,
            "agent_invocation_count": invocation_count,
            "agent_duration_seconds": duration,
            "treatment_delivery": deepcopy(delivery),
            "treatment_delivered": True,
            "feedback_delivered": condition == "B-agentharness",
            "recovered_without_agent_reinvocation": True,
            "recovery_scope": RECOVERY_SCOPE,
            "solution_hash": provenance.get("solution_hash"),
            "attempt_solution_hashes": deepcopy(provenance.get("attempt_solution_hashes", {})),
            "solution_hash_changed_between_attempt_and_repair": bool(
                provenance.get("solution_hash_changed_between_attempt_and_repair")
            ),
        }
    )
    for key in (
        "treatment_prompt_sha256_pre",
        "treatment_prompt_sha256_post",
        "treatment_prompt_immutable",
        "feedback_sha256_pre",
        "feedback_sha256_post",
        "feedback_immutable",
    ):
        if key in delivery:
            final[key] = delivery[key]
    return final


def build_recovery(
    *,
    run_root: Path,
    output_root: Path,
    manifest_path: Path,
    amendment_path: Path,
    evaluator: Callable[..., Any] = evaluate_run,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    output_root = output_root.resolve()
    _require_separate_output(run_root, output_root)
    manifest, progress, state, original_seal = _validate_original(
        run_root=run_root, manifest_path=manifest_path.resolve(), amendment_path=amendment_path.resolve()
    )
    if output_root.exists() and any(output_root.iterdir()):
        raise RecoveryError("output root must be absent or empty")
    staging = output_root / ".recovery-building"
    staging.mkdir(parents=True, exist_ok=False)
    os.chmod(output_root, 0o700)
    os.chmod(staging, 0o700)

    recovered_progress: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    try:
        for row in progress:
            task_id = str(row["task_id"])
            if task_id in EXCLUDED_LEGACY_TASKS:
                continue
            cell_id = str(row["campaign_cell_id"])
            attempt_dir, attempt_no = select_first_attempt(run_root, cell_id)
            run_path = attempt_dir / "run.json"
            suite_path = attempt_dir / "outputs" / "suite.json"
            run_envelope = _load_object(run_path)
            suite = _load_object(suite_path)
            run_id = str(run_envelope.get("run_id", ""))
            if _attempt_number(attempt_dir) != attempt_no or not run_id.endswith(f"_a{attempt_no}"):
                raise RecoveryError("selected run envelope attempt binding mismatch")
            recorded_workspace = Path(str(run_envelope.get("workspace", ""))).resolve()
            if not _is_within(recorded_workspace, run_root):
                raise RecoveryError("selected run workspace is not bound to the original run root")
            current_workspace = (attempt_dir / "workspace").resolve()
            if not current_workspace.is_dir():
                raise RecoveryError("selected attempt workspace is missing")
            expected_ids = _validate_standard_suite(suite, expected_run_id=run_id)
            # Archived run envelopes retain their pre-move private-cells workspace.
            # Derive a replay envelope under output_root; never patch source evidence.
            derived_run_path = staging / "replay-inputs" / cell_id / "run.json"
            derived_run = deepcopy(run_envelope)
            derived_run["workspace"] = str(current_workspace)
            _atomic_json(derived_run_path, derived_run)
            trace_path = staging / "traces" / f"{cell_id}.evaluation-trace.jsonl"
            result = evaluator(
                derived_run_path,
                suite_path,
                write_report=False,
                trace_path=trace_path,
            )
            payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            score = validate_replay_payload(payload, expected_ids=expected_ids)
            patched = deepcopy(row)
            patched["final"] = _recovered_final(
                dict(row["final"]), attempt_dir=attempt_dir, attempt_no=attempt_no, score=score
            )
            recovered_progress.append(patched)
            lineage.append(
                {
                    "campaign_cell_id": cell_id,
                    "task_id": task_id,
                    "condition": row["condition"],
                    "replicate_id": row["replicate_id"],
                    "selected_attempt_no": attempt_no,
                    "selected_attempt_relative_path": attempt_dir.relative_to(run_root).as_posix(),
                    "run_id": run_id,
                    "selection_rule": "minimum_physical_attempt_number_outcome_blind",
                    "source_run_sha256": sha256_file(run_path),
                    "derived_run_sha256": sha256_file(derived_run_path),
                    "trace_relative_path": f"traces/{cell_id}.evaluation-trace.jsonl",
                }
            )

        recovered_tasks = sorted({str(row["task_id"]) for row in recovered_progress})
        expected_tasks = sorted(set(manifest["tasks"]) - EXCLUDED_LEGACY_TASKS)
        if len(recovered_progress) != EXPECTED_RECOVERY_CELLS or recovered_tasks != expected_tasks:
            raise RecoveryError("amended recovery roster is not exactly 16 tasks / 96 cells")

        progress_path = staging / "recovery-progress.private.json"
        _atomic_json(progress_path, recovered_progress)
        rows = build_dataset_from_progress(progress_path)
        validate_campaign_dataset(rows, expected_task_ids=expected_tasks, expected_replicates_per_condition=3)
        dataset_path = staging / "recovery-analysis-dataset.sealed.json"
        _atomic_json(dataset_path, rows)
        lineage_path = staging / "attempt-lineage.private.json"
        _atomic_json(
            lineage_path,
            {
                "schema_version": 1,
                "scope": RECOVERY_SCOPE,
                "outcome_blind_selection": True,
                "excluded_tasks": sorted(EXCLUDED_LEGACY_TASKS),
                "cells": lineage,
            },
        )
        audit_path = staging / "blind-recovery-audit.json"
        audit = {
            "schema_version": 1,
            "scope": RECOVERY_SCOPE,
            "qualification": RECOVERY_QUALIFICATION,
            "outcome_blind": True,
            "analysis_authorized": False,
            "original_run_read_only": True,
            "selection_uses_outcomes": False,
            "selection_rule": "first chronological physical attempt; exact harness_invalid_rerun archives precede final private cell; account-tranche-boundary ignored",
            "endpoint_validity_rule": "no gating errors; exactly six unique expected IDs; statuses passed/failed only; payload ok ignored",
            "excluded_tasks": sorted(EXCLUDED_LEGACY_TASKS),
            "structural_counts": {"tasks": 16, "cells": 96, "original_journals": 60, "original_progress_rows": 120},
            "bindings": {
                "amendment_sha256": sha256_file(amendment_path.resolve()),
                "manifest_file_sha256": sha256_file(manifest_path.resolve()),
                "original_progress_sha256": original_seal["progress_sha256"],
                "original_dataset_sha256": original_seal["dataset_sha256"],
                "repository_commit": state["repository_commit"],
            },
            "built_at": utc_now(),
        }
        _atomic_json(audit_path, audit)
        seal_path = staging / "recovery-seal.json"
        seal = {
            "schema_version": 1,
            "scope": RECOVERY_SCOPE,
            "qualification": RECOVERY_QUALIFICATION,
            "analysis_authorized": False,
            "tasks": EXPECTED_RECOVERY_TASKS,
            "cells": EXPECTED_RECOVERY_CELLS,
            "excluded_tasks": sorted(EXCLUDED_LEGACY_TASKS),
            "recovery_progress_sha256": sha256_file(progress_path),
            "recovery_dataset_sha256": sha256_file(dataset_path),
            "attempt_lineage_sha256": sha256_file(lineage_path),
            "blind_recovery_audit_sha256": sha256_file(audit_path),
            "trace_sha256": {
                path.name: sha256_file(path)
                for path in sorted((staging / "traces").glob("*.jsonl"))
            },
            "derived_replay_input_sha256": {
                path.parent.name: sha256_file(path)
                for path in sorted((staging / "replay-inputs").glob("*/run.json"))
            },
            "amendment_sha256": sha256_file(amendment_path.resolve()),
            "manifest_file_sha256": sha256_file(manifest_path.resolve()),
            "original_progress_sha256": original_seal["progress_sha256"],
            "original_dataset_sha256": original_seal["dataset_sha256"],
            "repository_commit": state["repository_commit"],
            "sealed_at": utc_now(),
        }
        _atomic_json(seal_path, seal)
        for path in list(staging.iterdir()):
            os.replace(path, output_root / path.name)
        staging.rmdir()
        return {"status": "PASS", "structural_counts": {"tasks": 16, "cells": 96, "traces": 96}}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def finalize_recovery(
    *,
    recovery_root: Path,
    output_root: Path,
    manifest_path: Path,
    authorization_path: Path,
) -> dict[str, Any]:
    recovery_root = recovery_root.resolve()
    output_root = output_root.resolve()
    _require_separate_output(recovery_root, output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise RecoveryError("analysis output root must be absent or empty")
    seal_path = recovery_root / "recovery-seal.json"
    dataset_path = recovery_root / "recovery-analysis-dataset.sealed.json"
    progress_path = recovery_root / "recovery-progress.private.json"
    seal = _load_object(seal_path)
    if authorization_path.name != "RECOVERY_ANALYSIS_AUTHORIZATION.json":
        raise RecoveryError("authorization file must use the frozen authorization filename")
    auth = _load_object(authorization_path.resolve())
    manifest = _load_object(manifest_path.resolve())

    if seal.get("analysis_authorized") is not False or seal.get("scope") != RECOVERY_SCOPE:
        raise RecoveryError("recovery seal is not an unauthorised amended recovery seal")
    if auth.get("analysis_authorized") is not True or auth.get("scope") != RECOVERY_SCOPE:
        raise RecoveryError("explicit amended recovery analysis authorization missing")
    if auth.get("recovery_dataset_sha256") != sha256_file(dataset_path):
        raise RecoveryError("authorization dataset hash mismatch")
    if auth.get("recovery_seal_sha256") != sha256_file(seal_path):
        raise RecoveryError("authorization seal hash mismatch")
    if seal.get("recovery_dataset_sha256") != sha256_file(dataset_path):
        raise RecoveryError("recovery dataset seal mismatch")
    if seal.get("recovery_progress_sha256") != sha256_file(progress_path):
        raise RecoveryError("recovery progress seal mismatch")
    if seal.get("manifest_file_sha256") != sha256_file(manifest_path.resolve()):
        raise RecoveryError("recovery seal manifest binding mismatch")
    bound_files = {
        "attempt_lineage_sha256": recovery_root / "attempt-lineage.private.json",
        "blind_recovery_audit_sha256": recovery_root / "blind-recovery-audit.json",
    }
    for field, path in bound_files.items():
        if seal.get(field) != sha256_file(path):
            raise RecoveryError(f"recovery artifact seal mismatch: {field}")
    trace_hashes = seal.get("trace_sha256")
    replay_hashes = seal.get("derived_replay_input_sha256")
    if not isinstance(trace_hashes, dict) or len(trace_hashes) != EXPECTED_RECOVERY_CELLS:
        raise RecoveryError("recovery trace seal roster mismatch")
    if not isinstance(replay_hashes, dict) or len(replay_hashes) != EXPECTED_RECOVERY_CELLS:
        raise RecoveryError("derived replay input seal roster mismatch")
    for name, expected in trace_hashes.items():
        if not isinstance(name, str) or expected != sha256_file(recovery_root / "traces" / name):
            raise RecoveryError("recovery trace seal mismatch")
    for cell_id, expected in replay_hashes.items():
        path = recovery_root / "replay-inputs" / str(cell_id) / "run.json"
        if expected != sha256_file(path):
            raise RecoveryError("derived replay input seal mismatch")

    rows = load_analysis_dataset(dataset_path)
    rebuilt = build_dataset_from_progress(progress_path)
    if canonical(rows) != canonical(rebuilt):
        raise RecoveryError("recovery dataset is not semantically bound to recovery progress")
    expected_tasks = sorted(set(manifest.get("tasks", [])) - EXCLUDED_LEGACY_TASKS)
    if len(expected_tasks) != EXPECTED_RECOVERY_TASKS:
        raise RecoveryError("authorized manifest does not yield 16 amended tasks")
    validate_campaign_dataset(rows, expected_task_ids=expected_tasks, expected_replicates_per_condition=3)
    params = manifest.get("analysis_parameters")
    if not isinstance(params, dict):
        raise RecoveryError("manifest analysis parameters missing")
    analysis = run_full_analysis(
        rows,
        mme=float(manifest["mme"]),
        cluster_seed=int(params["cluster_seed"]),
        cluster_resamples=int(params["cluster_resamples"]),
        wild_seed=int(params["wild_seed"]),
        wild_resamples=int(params["wild_resamples"]),
        include_mixedlm=True,
    )
    analysis["decision"]["public_claim_classification"] = RECOVERY_QUALIFICATION
    analysis["decision"]["confirmatory_public_claim_allowed"] = False
    report = {
        "schema_version": 1,
        "scope": RECOVERY_SCOPE,
        "qualification": RECOVERY_QUALIFICATION,
        "confirmatory": False,
        "public_claim_confirmatory": False,
        "recovery_dataset_sha256": sha256_file(dataset_path),
        "recovery_seal_sha256": sha256_file(seal_path),
        "authorization_sha256": sha256_file(authorization_path.resolve()),
        "manifest_file_sha256": sha256_file(manifest_path.resolve()),
        "analysis": analysis,
        "finalized_at": utc_now(),
    }
    output_root.mkdir(parents=True, exist_ok=False)
    os.chmod(output_root, 0o700)
    report_path = output_root / "STAGE2_RECOVERY_EXPLORATORY_RESULT.json"
    _atomic_json(report_path, report)
    final_seal = {
        "schema_version": 1,
        "scope": RECOVERY_SCOPE,
        "qualification": RECOVERY_QUALIFICATION,
        "authorized": True,
        "confirmatory_public_claim_allowed": False,
        "result_sha256": sha256_file(report_path),
        "authorization_sha256": sha256_file(authorization_path.resolve()),
        "finalized_at": utc_now(),
    }
    _atomic_json(output_root / "STAGE2_RECOVERY_EXPLORATORY_FINALIZATION_SEAL.json", final_seal)
    return {"status": "PASS", "structural_counts": {"tasks": 16, "cells": 96, "reports": 2}}
