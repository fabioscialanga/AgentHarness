from __future__ import annotations

"""Process-isolated V5 workspace evaluator. It performs no provider calls."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .efficacy_v5 import EVALUATION_TASKS, TASK_CHECKS, TASK_DEFECTS

QUALIFIERS = {
    "rotating-key-token-verifier": "qualify_v5_rotating_token.py",
    "envelope-context-decryptor": "qualify_v5_envelope_crypto.py",
    "attenuated-capability-verifier": "qualify_v5_capability.py",
    "atomic-batch-state-machine": "qualify_v5_atomic_batch.py",
    "ack-token-work-queue": "qualify_v5_ack_queue.py",
    "length-prefixed-frame-parser": "qualify_v5_frame_parser.py",
    "streaming-csv-quoted-records": "qualify_v5_csv_stream.py",
    "epoch-guarded-leader-heartbeat": "qualify_v5_epoch_leader.py",
    "context-complete-authorization-cache": "qualify_v5_1_auth_cache.py",
    "transactional-release-pointer": "qualify_v5_2_release_pointer.py",
    "two-tier-read-through-cache": "qualify_v5_2_tiered_cache.py",
    "portable-command-receipt-ledger": "qualify_v5_2_portable_receipts.py",
}


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evaluate_heldout(workspace: Path, task_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    if task_id not in EVALUATION_TASKS:
        raise ValueError("heldout_unknown_v5_task")
    workspace = workspace.resolve()
    if not workspace.is_dir() or workspace.is_symlink():
        raise ValueError("heldout_workspace_invalid")
    root = repo_root.resolve() if repo_root is not None else Path(__file__).resolve().parents[2]
    qualifier = root / "benchmarks/grading-env" / QUALIFIERS[task_id]
    if not qualifier.is_file():
        raise ValueError("heldout_qualifier_missing")
    environment = dict(os.environ)
    environment.pop("AGENTHARNESS_MUTANT", None)
    environment["PYTHONHASHSEED"] = "47"
    completed = subprocess.run(
        [sys.executable, str(qualifier), "--workspace", str(workspace)],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        raise ValueError(f"heldout_evaluator_transport_exit:{completed.returncode}")
    try:
        payload = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("heldout_evaluator_json_invalid") from exc
    if payload.get("task_id") != task_id or payload.get("target_model_calls") != 0:
        raise ValueError("heldout_evaluator_identity_invalid")
    efficacy = payload.get("efficacy_cells")
    if not (efficacy is False or (type(efficacy) is int and efficacy == 0)):
        raise ValueError("heldout_evaluator_claims_efficacy_activity")
    if (completed.returncode == 0) is not (payload.get("ok") is True):
        raise ValueError("heldout_evaluator_exit_payload_mismatch")
    matrix = payload.get("matrix")
    if not isinstance(matrix, list) or len(matrix) != 1 or not isinstance(matrix[0], dict):
        raise ValueError("heldout_evaluator_matrix_invalid")
    row = matrix[0]
    expected_checks = set(TASK_CHECKS[task_id])
    checks = row.get("checks")
    if checks is None:
        passed, failed_roster = row.get("passed"), row.get("failed")
        if not isinstance(passed, list) or not isinstance(failed_roster, list) or set(passed) | set(failed_roster) != expected_checks or set(passed) & set(failed_roster):
            raise ValueError("heldout_evaluator_check_roster_invalid")
        checks = {name: name in passed for name in TASK_CHECKS[task_id]}
    if not isinstance(checks, dict) or set(checks) != expected_checks:
        raise ValueError("heldout_evaluator_check_roster_invalid")
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError("heldout_evaluator_nonboolean_check")
    target = TASK_DEFECTS[task_id]
    if target not in checks:
        raise ValueError("heldout_target_missing")
    failed = row.get("failed")
    if not isinstance(failed, list) or set(failed) != {name for name, passed in checks.items() if not passed}:
        raise ValueError("heldout_failed_roster_invalid")
    common_failed = row.get("common_failed", [])
    if not isinstance(common_failed, list):
        raise ValueError("heldout_common_roster_invalid")
    sibling_checks = {name: passed for name, passed in checks.items() if name != target}
    return {
        "schema_version": 5,
        "task_id": task_id,
        "target_check": target,
        "target_evaluated": True,
        "guards_evaluated": True,
        "target_passed": checks[target],
        "guards_passed": all(sibling_checks.values()) and not common_failed,
        "sibling_checks": sibling_checks,
        "common_failed": common_failed,
        "evaluator_payload_sha256": _canonical_hash(payload),
        "qualifier_sha256": hashlib.sha256(qualifier.read_bytes()).hexdigest(),
    }
