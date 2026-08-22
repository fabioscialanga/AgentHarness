from __future__ import annotations

"""Private V4 heldout boundary with process isolation and aggregate-only output."""

import multiprocessing
import queue as queue_module
import shutil
import tempfile
from pathlib import Path

from .benchmark_hidden_evaluators_batch2 import evaluate_batch2_task
from .benchmark_hidden_evaluators_batch3 import evaluate_batch3_task
from .efficacy_v4 import TARGET_CHECKS, TASKS

CHECK_ROSTERS = {
    "dependency-impact-planner": {"dependency_graph_validation", "dependency_reverse_impact", "dependency_parallel_levels", "dependency_deterministic_output", "dependency_cycle_atomic"},
    "access-policy-evaluator": {"policy_wildcard_matching", "policy_subject_group_composition", "policy_deny_default_precedence", "policy_temporal_validity", "policy_rejections_determinism"},
    "safe-archive-extraction": {"archive_extract_manifest", "archive_path_containment_atomic", "archive_special_entry_rejection", "archive_collision_atomic", "archive_limits_corruption_atomic"},
    "versioned-document-api": {"document_create_etag_persistence", "document_if_match_atomic", "document_merge_patch", "document_revision_history", "document_restore_history"},
    "signed-artifact-verifier": {"signed_manifest_authenticity", "signed_manifest_inventory", "signed_manifest_content_integrity", "signed_manifest_trust_window", "signed_manifest_atomic_report"},
    "pii-redaction-pipeline": {"pii_selector_resolution", "pii_redaction_actions", "pii_structure_preservation", "pii_rule_precedence", "pii_atomic_audit"},
    "lease-coordination-api": {"lease_acquire_fencing", "lease_concurrent_contention", "lease_renewal", "lease_release_reacquire", "lease_state_and_failure_atomicity"},
    "double-entry-ledger-api": {"ledger_account_identity", "ledger_balanced_posting", "ledger_idempotency_conflict", "ledger_balances_and_journal", "ledger_compensating_reversal"},
}


def _evaluate(workspace: Path, task_id: str) -> dict[str, bool]:
    result = evaluate_batch2_task(workspace, task_id) if task_id in TASKS[:4] else evaluate_batch3_task(workspace, task_id)
    observation_ids = [item.id for item in result.observations]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("heldout_result_duplicate_check_id")
    observations = {item.id: item.status == "pass" for item in result.observations}
    target = TARGET_CHECKS[task_id]
    if result.execution_status != "valid" or set(observations) != CHECK_ROSTERS[task_id] or target not in observations:
        raise ValueError("heldout_result_invalid")
    return {"target": observations[target], "guards": all(value for key, value in observations.items() if key != target)}


def _worker(workspace: str, task_id: str, queue: object) -> None:
    try: queue.put(("ok", _evaluate(Path(workspace), task_id)))  # type: ignore[attr-defined]
    except BaseException as exc: queue.put(("error", type(exc).__name__))  # type: ignore[attr-defined]


def _isolated(workspace: Path, task_id: str, timeout_seconds: int) -> dict[str, bool]:
    context = multiprocessing.get_context("fork"); queue = context.Queue(maxsize=1)
    process = context.Process(target=_worker, args=(str(workspace), task_id, queue), daemon=True)
    process.start(); process.join(timeout_seconds)
    if process.is_alive(): process.terminate(); process.join(10); raise ValueError(f"heldout_evaluator_timeout:{task_id}")
    if process.exitcode != 0: raise ValueError(f"heldout_evaluator_process_invalid:{task_id}")
    try: status, payload = queue.get(timeout=5)
    except queue_module.Empty as exc: raise ValueError("heldout_evaluator_missing_payload") from exc
    finally: queue.close(); queue.join_thread()
    if status != "ok" or not isinstance(payload, dict) or set(payload) != {"target", "guards"} or any(type(x) is not bool for x in payload.values()):
        raise ValueError(f"heldout_evaluator_invalid:{task_id}:{payload}")
    return payload


def evaluate_heldout(workspace: Path, task_id: str, *, timeout_seconds: int = 180) -> dict[str, object]:
    if task_id not in TASKS: raise ValueError(f"unknown_v4_task:{task_id}")
    with tempfile.TemporaryDirectory(prefix="agentharness-v4-heldout-") as temporary:
        clone = Path(temporary) / "workspace"; shutil.copytree(workspace, clone)
        status = _isolated(clone, task_id, timeout_seconds)
    return {"target_evaluated": True, "guards_evaluated": True, "target_passed": status["target"], "guards_passed": status["guards"], "binary_endpoint": int(status["target"] and status["guards"])}
