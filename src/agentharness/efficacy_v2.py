from __future__ import annotations

"""Pure, fail-closed primitives for the cloned-start efficacy-v2 pilot.

This module deliberately performs no provider calls and does not know where a
campaign stores outcomes.  It is shared by the collector, finalizer, and tests
so that partition and scoring rules have one implementation.
"""

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA_GATE_ID = "evaluation_result_schema"
TASK_PARTITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "appointment-booking-api": {
        "review": ("appointment_interval_validation", "appointment_reschedule_atomic"),
        "heldout": ("appointment_create_and_filters", "appointment_provider_conflicts", "appointment_cancel_releases_slot"),
    },
    "shipment-event-api": {
        "review": ("shipment_skipped_transition_atomic", "shipment_event_idempotency"),
        "heldout": ("shipment_create_and_filters", "shipment_valid_transition_path", "shipment_time_and_terminal_invariants"),
    },
    "jsonl-event-aggregation": {
        "review": ("jsonl_summary_consistency", "jsonl_deterministic_outputs"),
        "heldout": ("jsonl_grouped_counts", "jsonl_utc_date_normalization", "jsonl_invalid_and_duplicate_handling"),
    },
    "invoice-payment-reconciliation": {
        "review": ("reconciliation_rows_and_order", "reconciliation_summary_and_validation"),
        "heldout": ("reconciliation_cutoff_and_duplicates", "reconciliation_status_and_decimals", "reconciliation_unmatched_reporting"),
    },
}
TASKS = tuple(TASK_PARTITIONS)

REVIEW_CATALOG: dict[str, dict[str, str]] = {
    "appointment_interval_validation": {
        "requirement": "Appointment intervals must be valid explicit-offset timestamps with starts_at strictly before ends_at; rejected create/reschedule requests must not mutate state.",
        "remediation": "Validate timezone presence and interval ordering before any database write. Execute reschedule validation and persistence atomically so malformed requests preserve the prior appointment.",
    },
    "appointment_reschedule_atomic": {
        "requirement": "Rescheduling must reject provider conflicts without changing the original appointment and must accept a later conflict-free interval.",
        "remediation": "Check overlap against the target provider before updating. Commit only after all validation succeeds, and roll back the transaction on conflict so the previous interval remains byte-for-byte unchanged.",
    },
    "shipment_skipped_transition_atomic": {
        "requirement": "Shipment events must follow the exact next lifecycle transition; rejected skipped transitions must not append an event or alter projected state.",
        "remediation": "Derive the single allowed next event from current state before inserting. Reject any skipped transition before persistence and keep event history unchanged on failure.",
    },
    "shipment_event_idempotency": {
        "requirement": "Replaying the same event identity and canonical payload must be idempotent, while reusing that identity with a different payload must fail without mutation.",
        "remediation": "Persist event identity with a canonical payload fingerprint. Return the original result for an exact replay and reject conflicting reuse before appending or changing projection state.",
    },
    "jsonl_summary_consistency": {
        "requirement": "Aggregation output, rejection output, and summary totals must reconcile exactly with every accepted, rejected, and duplicate input row.",
        "remediation": "Compute all outputs from one classified-record ledger. Derive accepted, rejected, duplicate, group, and amount totals from that ledger rather than maintaining independent counters.",
    },
    "jsonl_deterministic_outputs": {
        "requirement": "Equivalent input must produce byte-identical deterministic JSON/JSONL artifacts in the specified canonical order.",
        "remediation": "Sort every emitted collection by the SPEC keys and serialize with fixed UTF-8 JSON separators/newlines. Avoid iteration-order, locale, wall-clock, and temporary-path data in outputs.",
    },
    "reconciliation_rows_and_order": {
        "requirement": "Reconciliation rows must preserve exact decimal allocation semantics and be emitted in the canonical deterministic order.",
        "remediation": "Use Decimal throughout allocation, never binary float. Build normalized rows first, then sort them by the SPEC ordering keys before serialization.",
    },
    "reconciliation_summary_and_validation": {
        "requirement": "Summary amounts and counts must exactly reconcile with output rows, and invalid inputs must fail atomically without replacing existing outputs.",
        "remediation": "Validate both input ledgers completely before writing. Derive summary values from finalized reconciliation rows and publish outputs through same-directory staging plus atomic replace only after success.",
    },
}


def partition_ids(task_id: str, kind: str) -> tuple[str, ...]:
    if task_id not in TASK_PARTITIONS:
        raise ValueError(f"unknown_v2_task:{task_id}")
    if kind not in {"review", "heldout"}:
        raise ValueError(f"unknown_partition:{kind}")
    return TASK_PARTITIONS[task_id][kind]


def validate_suite_partition(task_id: str, suite: Mapping[str, object]) -> None:
    cases = suite.get("cases")
    if not isinstance(cases, list):
        raise ValueError("suite_cases_invalid")
    ids: list[str] = []
    for case in cases:
        if not isinstance(case, Mapping) or not isinstance(case.get("id"), str):
            raise ValueError("suite_case_id_invalid")
        ids.append(str(case["id"]))
    if len(ids) != len(set(ids)):
        raise ValueError("suite_case_id_duplicate")
    expected = set(partition_ids(task_id, "review")) | set(partition_ids(task_id, "heldout")) | {SCHEMA_GATE_ID}
    if set(ids) != expected:
        missing, extra = sorted(expected - set(ids)), sorted(set(ids) - expected)
        raise ValueError(f"suite_partition_mismatch:missing={missing}:extra={extra}")
    if set(partition_ids(task_id, "review")) & set(partition_ids(task_id, "heldout")):
        raise ValueError("suite_partition_overlap")


def _result_rows(report: Mapping[str, object]) -> list[dict[str, object]]:
    raw = report.get("results", report.get("observations"))
    if not isinstance(raw, list):
        raise ValueError("evaluation_rows_invalid")
    rows: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("evaluation_row_invalid")
        case_id = item.get("case_id", item.get("id"))
        status = item.get("status")
        if not isinstance(case_id, str) or not isinstance(status, str):
            raise ValueError("evaluation_row_schema_invalid")
        normalized = dict(item)
        normalized["case_id"] = case_id
        normalized["status"] = {"pass": "passed", "fail": "failed"}.get(status, status)
        if normalized["status"] not in {"passed", "failed"}:
            raise ValueError(f"evaluation_status_invalid:{case_id}:{normalized['status']}")
        rows.append(normalized)
    ids = [str(row["case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation_case_duplicate")
    return rows


def filter_evaluation_report(report: Mapping[str, object], *, task_id: str, partition: str) -> dict[str, object]:
    """Return only an authorized partition; reject unknown IDs before filtering."""
    rows = _result_rows(report)
    known = set(partition_ids(task_id, "review")) | set(partition_ids(task_id, "heldout")) | {SCHEMA_GATE_ID}
    observed = {str(row["case_id"]) for row in rows}
    if not observed.issubset(known):
        raise ValueError(f"evaluation_unknown_ids:{sorted(observed - known)}")
    if observed != known:
        raise ValueError(f"evaluation_report_incomplete:missing={sorted(known - observed)}")
    allowed = set(partition_ids(task_id, partition))
    if partition == "heldout":
        allowed.add(SCHEMA_GATE_ID)
    selected = [row for row in rows if row["case_id"] in allowed]
    return {
        "schema_version": 2,
        "task_id": task_id,
        "partition": partition,
        "results": selected,
        "summary": {
            "passed": sum(row["status"] == "passed" for row in selected),
            "failed": sum(row["status"] == "failed" for row in selected),
        },
    }


def review_feedback_from_report(report: Mapping[str, object], *, task_id: str) -> dict[str, object]:
    filtered = filter_evaluation_report(report, task_id=task_id, partition="review")
    failures = [row for row in filtered["results"] if row["status"] == "failed"]  # type: ignore[index]
    return {
        "schema_version": 2,
        "feedback_contract_version": 2,
        "task_id": task_id,
        "partition": "review",
        "zero_findings_valid": True,
        "feedback": {
            "items": [
                {
                    "claim_id": row["case_id"],
                    "status": "unsupported",
                    "requirement": REVIEW_CATALOG[str(row["case_id"])]["requirement"],
                    "observed": row.get("reason", row.get("detail", "review check failed")),
                    "remediation": REVIEW_CATALOG[str(row["case_id"])]["remediation"],
                    "reason": REVIEW_CATALOG[str(row["case_id"])]["remediation"],
                }
                for row in failures
            ]
        },
    }


def score_heldout_report(report: Mapping[str, object], *, task_id: str) -> float:
    if report.get("gating_errors") not in (None, []):
        raise ValueError("evaluation_report_gating_errors")
    filtered = filter_evaluation_report(report, task_id=task_id, partition="heldout")
    rows = {str(row["case_id"]): row for row in filtered["results"]}  # type: ignore[index]
    expected = set(partition_ids(task_id, "heldout")) | {SCHEMA_GATE_ID}
    if set(rows) != expected:
        raise ValueError("heldout_report_incomplete")
    if rows[SCHEMA_GATE_ID]["status"] != "passed":
        raise ValueError("heldout_schema_gate_failed")
    statuses = [rows[case_id]["status"] for case_id in partition_ids(task_id, "heldout")]
    if any(status not in {"passed", "failed"} for status in statuses):
        raise ValueError("heldout_status_invalid")
    return sum(status == "passed" for status in statuses) / 3.0


def tree_manifest(root: Path) -> list[dict[str, object]]:
    """Manifest every regular file and empty directory, rejecting symlinks."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"tree_root_invalid:{root}")
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"tree_symlink_forbidden:{rel}")
        if stat.S_ISDIR(info.st_mode):
            if not any(path.iterdir()):
                entries.append({"path": rel, "type": "directory", "mode": stat.S_IMODE(info.st_mode)})
        elif stat.S_ISREG(info.st_mode):
            content = path.read_bytes()
            entries.append({
                "path": rel, "type": "file", "mode": stat.S_IMODE(info.st_mode),
                "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            })
        else:
            raise ValueError(f"tree_special_file_forbidden:{rel}")
    return entries


def tree_fingerprint(root: Path) -> str:
    encoded = json.dumps(tree_manifest(root), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clone_tree_identical(source: Path, destination: Path) -> dict[str, object]:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    source_manifest = tree_manifest(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    clone_manifest = tree_manifest(destination)
    if clone_manifest != source_manifest:
        shutil.rmtree(destination, ignore_errors=True)
        raise RuntimeError("clone_tree_identity_mismatch")
    return {"manifest": source_manifest, "fingerprint": tree_fingerprint(source)}


def verify_clone_pair(source: Path, clone_a: Path, clone_b: Path) -> str:
    manifests = [tree_manifest(path) for path in (source, clone_a, clone_b)]
    if not (manifests[0] == manifests[1] == manifests[2]):
        raise ValueError("clone_pair_not_byte_identical")
    return tree_fingerprint(source)


def repair_count(attempts: Iterable[Mapping[str, object]]) -> int:
    return sum(item.get("prompt_kind") == "repair" for item in attempts)


def funnel(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Structural/treatment funnel only; it intentionally ignores scores."""
    return {
        "cells": len(rows),
        "initial_generations": len({str(row.get("initial_origin")) for row in rows if row.get("initial_origin")}),
        "repair_invocations": sum(int(row.get("repair_passes_used", 0)) for row in rows),
        "treatments_delivered": sum(row.get("treatment_delivered") is True for row in rows),
        "valid_repair_responses": sum(row.get("repair_response_valid") is True for row in rows),
        "retained_repairs": sum(row.get("repair_change_retained") is True for row in rows),
    }
