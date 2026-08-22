from __future__ import annotations

"""Frozen primitives for the mechanism-first V4 calibration/evaluation pilot.

V4 compiles the mutation selector out of Batch-2/3 reference sources before a
workspace becomes agent-visible.  This module performs no provider calls.
"""

import ast
import hashlib
import json
import shutil
import stat
from pathlib import Path
from typing import Mapping, Sequence

PILOT_ID = "mechanism-first-controlled-repair-v4"
CALIBRATION_TASKS = ("dependency-impact-planner", "access-policy-evaluator")
EVALUATION_TASKS = (
    "safe-archive-extraction", "versioned-document-api",
    "signed-artifact-verifier", "pii-redaction-pipeline",
    "lease-coordination-api", "double-entry-ledger-api",
)
TASKS = CALIBRATION_TASKS + EVALUATION_TASKS
CONDITIONS = ("A-baseline", "B-agentharness")
CONDITION_ORDERS = (
    ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
    ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
    ("A-baseline", "B-agentharness"), ("B-agentharness", "A-baseline"),
)
TASK_DEFECTS = {
    "dependency-impact-planner": "dependency_reverse_impact",
    "access-policy-evaluator": "policy_temporal_validity",
    "safe-archive-extraction": "archive_collision_atomic",
    "versioned-document-api": "document_restore_history",
    "signed-artifact-verifier": "signed_manifest_trust_window",
    "pii-redaction-pipeline": "pii_redaction_actions",
    "lease-coordination-api": "lease_renewal",
    "double-entry-ledger-api": "ledger_balances_and_journal",
}
TARGET_CHECKS = dict(TASK_DEFECTS)
OPAQUE_FINDING_IDS = {task: f"finding-v4-{i:03d}" for i, task in enumerate(EVALUATION_TASKS, 1)}
FINDING_CONTENT = {
    "safe-archive-extraction": {
        "requirement": "Archive extraction must reject normalized duplicate and file/directory namespace collisions atomically before materializing output.",
        "observed": "A crafted archive with colliding normalized member paths was accepted instead of being rejected without output residue.",
        "remediation": "Preflight the complete normalized member namespace, including duplicate and file-versus-directory prefix collisions, before extraction.",
    },
    "versioned-document-api": {
        "requirement": "Restoring historical content must create a new immutable revision with a new ETag and history entry.",
        "observed": "Historical content was restored in place without advancing all revision, ETag, and history state.",
        "remediation": "Commit the restored body through the normal compare-and-swap revision path rather than overwriting current state in place.",
    },
    "signed-artifact-verifier": {
        "requirement": "A signing key is trusted only in the half-open interval from valid_from inclusive to valid_until exclusive.",
        "observed": "Verification accepted an artifact at the key's exact valid_until boundary.",
        "remediation": "Reject verification times greater than or equal to key valid_until while preserving signature, manifest, and inventory checks.",
    },
    "pii-redaction-pipeline": {
        "requirement": "Pseudonymization must use the configured secret as an HMAC key so identical values under different keys produce different pseudonyms.",
        "observed": "Changing the configured secret did not change the pseudonym for the same canonical value.",
        "remediation": "Use HMAC-SHA256 over the canonical value with the configured secret instead of an unkeyed digest.",
    },
    "lease-coordination-api": {
        "requirement": "Lease renewal requires both the current owner and the current fencing token.",
        "observed": "A stale fencing token from an earlier generation was accepted for renewal by the same owner.",
        "remediation": "Validate exact equality with the persisted current fencing token before renewing, without weakening owner or expiry checks.",
    },
    "double-entry-ledger-api": {
        "requirement": "Journal output must preserve canonical posting order within each transaction.",
        "observed": "Entries within a transaction were returned in reverse posting order even though balances and amounts remained correct.",
        "remediation": "Preserve stored posting ordinal when constructing journal entries while retaining transaction ordering and balance semantics.",
    },
}
ALL_CHECK_IDS = frozenset({
    "dependency_graph_validation", "dependency_reverse_impact", "dependency_parallel_levels", "dependency_deterministic_output", "dependency_cycle_atomic",
    "policy_wildcard_matching", "policy_subject_group_composition", "policy_deny_default_precedence", "policy_temporal_validity", "policy_rejections_determinism",
    "archive_extract_manifest", "archive_path_containment_atomic", "archive_special_entry_rejection", "archive_collision_atomic", "archive_limits_corruption_atomic",
    "document_create_etag_persistence", "document_if_match_atomic", "document_merge_patch", "document_revision_history", "document_restore_history",
    "signed_manifest_authenticity", "signed_manifest_inventory", "signed_manifest_content_integrity", "signed_manifest_trust_window", "signed_manifest_atomic_report",
    "pii_selector_resolution", "pii_redaction_actions", "pii_structure_preservation", "pii_rule_precedence", "pii_atomic_audit",
    "lease_acquire_fencing", "lease_concurrent_contention", "lease_renewal", "lease_release_reacquire", "lease_state_and_failure_atomicity",
    "ledger_account_identity", "ledger_balanced_posting", "ledger_idempotency_conflict", "ledger_balances_and_journal", "ledger_compensating_reversal",
    "AGENTHARNESS_MUTANT", "MUTANT", "evaluation_result_schema",
})
FORBIDDEN_AGENT_TOKENS = ALL_CHECK_IDS


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tree_manifest(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink(): raise ValueError("tree_root_invalid")
    rows = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix(); info = path.lstat()
        if stat.S_ISLNK(info.st_mode): raise ValueError(f"tree_symlink_forbidden:{rel}")
        if path.is_file():
            data = path.read_bytes(); rows.append({"path": rel, "mode": stat.S_IMODE(info.st_mode), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def tree_fingerprint(root: Path) -> str: return canonical_hash(tree_manifest(root))


class _ResolveSelector(ast.NodeTransformer):
    def __init__(self, selected: str): self.selected = selected
    def visit_Assign(self, node: ast.Assign):
        if any(isinstance(t, ast.Name) and t.id == "MUTANT" for t in node.targets): return None
        return self.generic_visit(node)
    def visit_Compare(self, node: ast.Compare):
        self.generic_visit(node)
        if len(node.ops) == len(node.comparators) == 1:
            left, right = node.left, node.comparators[0]; value = None
            if isinstance(left, ast.Name) and left.id == "MUTANT" and isinstance(right, ast.Constant): value = right.value
            elif isinstance(right, ast.Name) and right.id == "MUTANT" and isinstance(left, ast.Constant): value = left.value
            if isinstance(value, str):
                if isinstance(node.ops[0], ast.Eq): return ast.copy_location(ast.Constant(value == self.selected), node)
                if isinstance(node.ops[0], ast.NotEq): return ast.copy_location(ast.Constant(value != self.selected), node)
        return node


def _compile(path: Path, selected: str) -> None:
    tree = _ResolveSelector(selected).visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    ast.fix_missing_locations(tree); rendered = ast.unparse(tree) + "\n"; compile(rendered, str(path), "exec"); path.write_text(rendered, encoding="utf-8")


def leakage_scan(root: Path) -> list[dict[str, str]]:
    leaks = []
    needles = {x.lower(): x for x in FORBIDDEN_AGENT_TOKENS}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink(): leaks.append({"path": rel, "token": "SYMLINK"}); continue
        haystacks = [rel.lower()]
        if path.is_file():
            try: haystacks.append(path.read_text(encoding="utf-8").lower())
            except UnicodeDecodeError: pass
        for needle, token in needles.items():
            if any(needle in value for value in haystacks): leaks.append({"path": rel, "token": token})
    return leaks


def assert_leak_free(root: Path) -> None:
    leaks = leakage_scan(root)
    if leaks: raise ValueError(f"agent_visible_leakage:{leaks}")


def reference_root(repo_root: Path, task_id: str) -> Path:
    batch = "task-expansion-batch2" if task_id in CALIBRATION_TASKS or task_id in EVALUATION_TASKS[:2] else "task-expansion-batch3"
    return repo_root / "benchmarks/grading-env" / batch / "references"


def _materialize(task_id: str, repo_root: Path, destination: Path, selected: str) -> dict[str, object]:
    if task_id not in TASK_DEFECTS: raise ValueError(f"unknown_v4_task:{task_id}")
    if destination.exists() or destination.is_symlink(): raise FileExistsError(destination)
    source = reference_root(repo_root, task_id) / task_id
    if not source.is_dir() or source.is_symlink(): raise ValueError(f"reference_missing:{task_id}")
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.name == "__pycache__" and path.is_dir(): shutil.rmtree(path)
        elif path.is_file() and path.suffix in {".pyc", ".db", ".sqlite3"}: path.unlink()
        elif path.name == "README.md" and path.is_file():
            text = path.read_text(encoding="utf-8")
            if not text.startswith("# Hidden positive reference"):
                raise ValueError(f"unexpected_reference_readme:{task_id}")
            path.unlink()
    for path in sorted(destination.rglob("*.py")): _compile(path, selected)
    assert_leak_free(destination)
    return {"schema_version": 4, "task_id": task_id, "source_fingerprint": tree_fingerprint(source), "controlled_fingerprint": tree_fingerprint(destination), "agent_visible_leakage": []}


def materialize_controlled_start(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    return _materialize(task_id, repo_root, destination, TASK_DEFECTS[task_id])


def materialize_clean_reference(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    return _materialize(task_id, repo_root, destination, "__clean_v4__")


def clone_pair(source: Path, a: Path, b: Path) -> str:
    expected = tree_manifest(source)
    for target in (a, b):
        shutil.copytree(source, target, copy_function=shutil.copy2)
        if tree_manifest(target) != expected: raise ValueError("clone_identity_mismatch")
        assert_leak_free(target)
    return tree_fingerprint(source)


def opaque_review_feedback(task_id: str, observed: str) -> dict[str, object]:
    if task_id not in EVALUATION_TASKS: raise ValueError("review_task_not_evaluation")
    content = FINDING_CONTENT[task_id]
    return {"schema_version": 4, "feedback_contract_version": 2, "task_id": task_id, "partition": "review-v4", "feedback": {"items": [{"claim_id": OPAQUE_FINDING_IDS[task_id], "status": "unsupported", "requirement": content["requirement"], "observed": content["observed"], "remediation": content["remediation"], "reason": "Repair the reproduced invariant failure without weakening surrounding behavior."}]}}


def validate_opaque_feedback(payload: Mapping[str, object], *, task_id: str) -> str:
    try: items = payload["feedback"]["items"]  # type: ignore[index]
    except (KeyError, TypeError) as exc: raise ValueError("feedback_schema_invalid") from exc
    if payload.get("feedback_contract_version") != 2 or not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping): raise ValueError("review_requires_exactly_one_finding")
    item = items[0]
    if item.get("claim_id") != OPAQUE_FINDING_IDS.get(task_id) or item.get("status") != "unsupported": raise ValueError("review_finding_invalid")
    if any(not isinstance(item.get(k), str) or not str(item[k]).strip() for k in ("requirement", "observed", "remediation", "reason")): raise ValueError("review_finding_schema_invalid")
    encoded = json.dumps(payload, sort_keys=True).lower()
    if any(token.lower() in encoded for token in FORBIDDEN_AGENT_TOKENS): raise ValueError("review_feedback_leaks_private_identifier")
    return str(item["claim_id"])


def validate_marker_accounting(markers: Sequence[Mapping[str, object]], *, evaluation_admitted: bool) -> None:
    expected = {(task, "A-baseline") for task in CALIBRATION_TASKS}
    if evaluation_admitted: expected |= {(task, condition) for task in EVALUATION_TASKS for condition in CONDITIONS}
    observed = set()
    for marker in markers:
        key = (str(marker.get("task_id")), str(marker.get("condition")))
        if marker.get("phase") != "repair" or marker.get("initial_provider_call") is not False or key in observed: raise ValueError("provider_marker_invalid")
        observed.add(key)
    if observed != expected or len(markers) != len(expected): raise ValueError("provider_marker_roster_mismatch")


def calibration_admission(rows: Sequence[Mapping[str, object]]) -> str:
    if len(rows) != 2 or {str(x.get("task_id")) for x in rows} != set(CALIBRATION_TASKS): return "INVALID"
    if any(x.get("condition") != "A-baseline" or x.get("invocation_valid") is not True or x.get("heldout_valid") is not True or x.get("guards_passed") is not True for x in rows): return "INVALID"
    return "CEILING" if sum(bool(x.get("target_passed")) for x in rows) == 2 else "ADMIT"


def quota_admission(start_usage: float, end_usage: float) -> tuple[bool, float]:
    if any(type(x) not in (int, float) for x in (start_usage, end_usage)) or not (0 <= start_usage <= end_usage <= 100): raise ValueError("quota_telemetry_invalid")
    projected = float(end_usage) + 12 * max(0.5, (float(end_usage) - float(start_usage)) / 2)
    return projected <= 76.0, projected


def finalize_results(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if len(rows) != 12: return {"schema_version": 4, "verdict": "INVALID", "reason": "cell_roster_incomplete"}
    by_task: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in rows:
        task, condition = str(row.get("task_id")), str(row.get("condition"))
        if task not in EVALUATION_TASKS or condition not in CONDITIONS or condition in by_task.setdefault(task, {}): return {"schema_version": 4, "verdict": "INVALID", "reason": "cell_identity_invalid"}
        by_task[task][condition] = row
    if any(set(by_task.get(t, {})) != set(CONDITIONS) for t in EVALUATION_TASKS): return {"schema_version": 4, "verdict": "INVALID", "reason": "pairing_invalid"}
    for row in rows:
        if any(row.get(k) is not True for k in ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated")): return {"schema_version": 4, "verdict": "INVALID", "reason": "provider_harness_or_accounting_failure"}
        if type(row.get("target_passed")) is not bool or type(row.get("guards_passed")) is not bool: return {"schema_version": 4, "verdict": "INVALID", "reason": "endpoint_type_invalid"}
        if row["condition"] == "B-agentharness" and any(row.get(k) is not True for k in ("feedback_delivered", "feedback_immutable", "feedback_accounted")): return {"schema_version": 4, "verdict": "INVALID", "reason": "feedback_delivery_invalid"}
    paired=[]; recovery=b_gt_a=a_gt_b=regressions=0
    for task in EVALUATION_TASKS:
        a,b=by_task[task]["A-baseline"],by_task[task]["B-agentharness"]
        sa=int(bool(a.get("target_passed")) and bool(a.get("guards_passed"))); sb=int(bool(b.get("target_passed")) and bool(b.get("guards_passed")))
        recovery += int(bool(b.get("target_passed"))); b_gt_a += int(sb>sa); a_gt_b += int(sa>sb); regressions += int(not bool(b.get("guards_passed")))
        paired.append({"task_id":task,"score_a":sa,"score_b":sb,"difference_b_minus_a":sb-sa})
    delta=sum(x["difference_b_minus_a"] for x in paired)/6.0
    go=b_gt_a>=5 and a_gt_b==0 and delta>=5/6 and recovery>=5 and regressions==0
    return {"schema_version":4,"verdict":"GO" if go else "NO-GO","conditional_on_calibration_admission":True,"paired_binary_endpoints":paired,"b_target_recovery":recovery,"b_gt_a":b_gt_a,"a_gt_b":a_gt_b,"mean_delta_b_minus_a":delta,"b_guard_regressions":regressions}
