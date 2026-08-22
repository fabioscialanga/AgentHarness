from __future__ import annotations

"""Physically separate private V4 review evaluator.

The returned artifact contains one opaque actionable finding and no private
case/check identity. Runtime residue is confined to a disposable clone.
"""

import shutil
import tempfile
import multiprocessing as mp
from pathlib import Path

from .benchmark_hidden_evaluators_batch2 import evaluate_batch2_task
from .benchmark_hidden_evaluators_batch3 import evaluate_batch3_task
from .efficacy_v4 import EVALUATION_TASKS, TARGET_CHECKS, opaque_review_feedback, validate_opaque_feedback

REVIEW_ROSTERS = {
    "safe-archive-extraction": {"archive_extract_manifest", "archive_path_containment_atomic", "archive_special_entry_rejection", "archive_collision_atomic", "archive_limits_corruption_atomic"},
    "versioned-document-api": {"document_create_etag_persistence", "document_if_match_atomic", "document_merge_patch", "document_revision_history", "document_restore_history"},
    "signed-artifact-verifier": {"signed_manifest_authenticity", "signed_manifest_inventory", "signed_manifest_content_integrity", "signed_manifest_trust_window", "signed_manifest_atomic_report"},
    "pii-redaction-pipeline": {"pii_selector_resolution", "pii_redaction_actions", "pii_structure_preservation", "pii_rule_precedence", "pii_atomic_audit"},
    "lease-coordination-api": {"lease_acquire_fencing", "lease_concurrent_contention", "lease_renewal", "lease_release_reacquire", "lease_state_and_failure_atomicity"},
    "double-entry-ledger-api": {"ledger_account_identity", "ledger_balanced_posting", "ledger_idempotency_conflict", "ledger_balances_and_journal", "ledger_compensating_reversal"},
}


def _evaluate_review(workspace: Path, task_id: str) -> dict[str, object]:
    if task_id not in EVALUATION_TASKS: raise ValueError(f"review_not_available:{task_id}")
    with tempfile.TemporaryDirectory(prefix="agentharness-v4-review-") as temporary:
        clone = Path(temporary) / "workspace"; shutil.copytree(workspace, clone)
        result = evaluate_batch2_task(clone, task_id) if task_id in EVALUATION_TASKS[:2] else evaluate_batch3_task(clone, task_id)
    target = TARGET_CHECKS[task_id]
    observation_ids = [item.id for item in result.observations]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError(f"controlled_start_duplicate_check_id:{task_id}")
    statuses = {item.id: item.status for item in result.observations}
    if result.execution_status != "valid" or set(statuses) != REVIEW_ROSTERS[task_id] or statuses.get(target) != "fail" or any(status != "pass" for key, status in statuses.items() if key != target):
        raise ValueError(f"controlled_start_target_not_reproduced:{task_id}")
    # Observation details remain private; only a generic, actionable invariant
    # statement crosses the review boundary.
    payload = opaque_review_feedback(task_id, "The local target probe reproduced an invariant violation.")
    validate_opaque_feedback(payload, task_id=task_id)
    return payload


def _worker(connection, workspace: str, task_id: str) -> None:
    try: connection.send(("ok", _evaluate_review(Path(workspace), task_id)))
    except BaseException as exc: connection.send(("error", f"{type(exc).__name__}:{exc}"))
    finally: connection.close()


def evaluate_review(workspace: Path, task_id: str) -> dict[str, object]:
    context=mp.get_context("fork"); parent,child=context.Pipe(duplex=False); process=context.Process(target=_worker,args=(child,str(workspace),task_id)); process.start(); child.close()
    status,payload="error","review_pipe_closed"
    try:
        if not parent.poll(180):
            process.kill(); process.join(5); raise ValueError("review_timeout")
        try: status,payload=parent.recv()
        except EOFError: pass
    finally:
        parent.close()
    process.join(5)
    if process.is_alive(): process.kill(); process.join(5)
    if process.exitcode!=0 or status!="ok" or not isinstance(payload,dict): raise ValueError(f"review_invalid:{payload}")
    return payload
