from __future__ import annotations

"""Fail-closed primitives for the mechanism-first controlled-start V3 pilot.

The controlled workspaces are compiled from the frozen Batch-1 references: the
mutation selector is resolved at materialization time and all selector names,
environment hooks, and evaluator check IDs are then rejected from the tree.
This module performs no provider calls.
"""

import ast
import hashlib
import json
import shutil
import stat
from pathlib import Path
from typing import Mapping, Sequence

TASK_DEFECTS: dict[str, str] = {
    "appointment-booking-api": "appointment_reschedule_atomic",
    "shipment-event-api": "shipment_skipped_transition_atomic",
    "jsonl-event-aggregation": "jsonl_summary_consistency",
    "invoice-payment-reconciliation": "reconciliation_summary_and_validation",
}
TASKS = tuple(TASK_DEFECTS)
CONDITIONS = ("A-baseline", "B-agentharness")
CONDITION_ORDERS = (
    ("A-baseline", "B-agentharness"),
    ("B-agentharness", "A-baseline"),
    ("A-baseline", "B-agentharness"),
    ("B-agentharness", "A-baseline"),
)
OPAQUE_FINDING_IDS = {task: f"finding-v3-{index:03d}" for index, task in enumerate(TASKS, 1)}

# None of these implementation/evaluator labels may cross into an agent-visible
# controlled tree.  Task IDs are intentionally not forbidden: they are public.
ALL_CHECK_IDS = frozenset(
    {
        "appointment_create_and_filters", "appointment_interval_validation",
        "appointment_provider_conflicts", "appointment_reschedule_atomic",
        "appointment_cancel_releases_slot", "shipment_create_and_filters",
        "shipment_valid_transition_path", "shipment_skipped_transition_atomic",
        "shipment_event_idempotency", "shipment_time_and_terminal_invariants",
        "jsonl_grouped_counts", "jsonl_utc_date_normalization",
        "jsonl_invalid_and_duplicate_handling", "jsonl_summary_consistency",
        "jsonl_deterministic_outputs", "reconciliation_rows_and_order",
        "reconciliation_cutoff_and_duplicates", "reconciliation_status_and_decimals",
        "reconciliation_unmatched_reporting", "reconciliation_summary_and_validation",
        "evaluation_result_schema",
    }
)
FORBIDDEN_AGENT_TOKENS = frozenset({"MUTANT", "AGENTHARNESS_MUTANT", *ALL_CHECK_IDS})


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def tree_manifest(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("tree_root_invalid")
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"tree_symlink_forbidden:{rel}")
        if path.is_file():
            data = path.read_bytes()
            rows.append({"path": rel, "mode": stat.S_IMODE(info.st_mode), "size": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def tree_fingerprint(root: Path) -> str:
    return canonical_hash(tree_manifest(root))


class _ResolveMutationSelector(ast.NodeTransformer):
    def __init__(self, selected: str) -> None:
        self.selected = selected

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        if any(isinstance(target, ast.Name) and target.id == "MUTANT" for target in node.targets):
            return None
        return self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if len(node.ops) == 1 and len(node.comparators) == 1:
            left, right = node.left, node.comparators[0]
            value: str | None = None
            if isinstance(left, ast.Name) and left.id == "MUTANT" and isinstance(right, ast.Constant) and isinstance(right.value, str):
                value = right.value
            elif isinstance(right, ast.Name) and right.id == "MUTANT" and isinstance(left, ast.Constant) and isinstance(left.value, str):
                value = left.value
            if value is not None:
                if isinstance(node.ops[0], ast.Eq):
                    return ast.copy_location(ast.Constant(value == self.selected), node)
                if isinstance(node.ops[0], ast.NotEq):
                    return ast.copy_location(ast.Constant(value != self.selected), node)
        return node


def _compile_selected_defect(path: Path, defect: str) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tree = _ResolveMutationSelector(defect).visit(tree)
    ast.fix_missing_locations(tree)
    rendered = ast.unparse(tree) + "\n"
    compile(rendered, str(path), "exec")
    path.write_text(rendered, encoding="utf-8")


def leakage_scan(root: Path) -> list[dict[str, str]]:
    leaks: list[dict[str, str]] = []
    lowered = {token.lower(): token for token in FORBIDDEN_AGENT_TOKENS}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            leaks.append({"path": path.relative_to(root).as_posix(), "token": "SYMLINK"})
            continue
        rel = path.relative_to(root).as_posix()
        rel_lower = rel.lower()
        for needle, token in lowered.items():
            if needle in rel_lower:
                leaks.append({"path": rel, "token": token})
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for needle, token in lowered.items():
            if needle in text:
                leaks.append({"path": rel, "token": token})
    return leaks


def assert_leak_free(root: Path) -> None:
    leaks = leakage_scan(root)
    if leaks:
        raise ValueError(f"agent_visible_leakage:{leaks}")


def _materialize_selected(*, task_id: str, references_root: Path, destination: Path, selected: str) -> dict[str, object]:
    if task_id not in TASK_DEFECTS:
        raise ValueError(f"unknown_v3_task:{task_id}")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    source = references_root / task_id
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"reference_missing:{task_id}")
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    # Runtime residue is never part of a controlled start.
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.name == "__pycache__" and path.is_dir():
            shutil.rmtree(path)
        elif path.is_file() and path.suffix in {".pyc", ".db"}:
            path.unlink()
    python_files = sorted(destination.rglob("*.py"))
    if not python_files:
        shutil.rmtree(destination)
        raise ValueError(f"reference_has_no_python:{task_id}")
    for path in python_files:
        _compile_selected_defect(path, selected)
    assert_leak_free(destination)
    return {
        "schema_version": 3, "task_id": task_id,
        "source_fingerprint": tree_fingerprint(source),
        "controlled_fingerprint": tree_fingerprint(destination),
        "agent_visible_leakage": [],
    }


def materialize_controlled_start(*, task_id: str, references_root: Path, destination: Path) -> dict[str, object]:
    """Create one deterministic, leak-free, single-defect controlled start."""
    return _materialize_selected(
        task_id=task_id, references_root=references_root, destination=destination,
        selected=TASK_DEFECTS[task_id],
    )


def materialize_clean_reference(*, task_id: str, references_root: Path, destination: Path) -> dict[str, object]:
    """Compile a selector-free clean reference (qualification/mock use only)."""
    return _materialize_selected(
        task_id=task_id, references_root=references_root, destination=destination,
        selected="__no_selected_defect__",
    )


def clone_pair(source: Path, cell_a: Path, cell_b: Path) -> str:
    manifest = tree_manifest(source)
    for target in (cell_a, cell_b):
        if target.exists():
            raise FileExistsError(target)
        shutil.copytree(source, target, copy_function=shutil.copy2)
        if tree_manifest(target) != manifest:
            raise ValueError("clone_identity_mismatch")
        assert_leak_free(target)
    return tree_fingerprint(source)


def opaque_review_feedback(task_id: str, *, observed: str) -> dict[str, object]:
    if task_id not in TASK_DEFECTS:
        raise ValueError(f"unknown_v3_task:{task_id}")
    finding = OPAQUE_FINDING_IDS[task_id]
    return {
        "schema_version": 3,
        "feedback_contract_version": 2,
        "task_id": task_id,
        "partition": "review-v3",
        "feedback": {"items": [{
            "claim_id": finding,
            "status": "unsupported",
            "requirement": "A required state/output invariant is violated by a local adversarial example.",
            "observed": observed,
            "remediation": "Locate the violated invariant, validate before mutation/publication, and preserve prior state or outputs on rejection.",
            "reason": "Repair the locally reproduced invariant failure without weakening surrounding behavior.",
        }]},
    }


def validate_opaque_feedback(payload: Mapping[str, object], *, task_id: str) -> str:
    """Validate the V2 verify-feedback envelope and its single opaque finding."""
    if task_id not in TASK_DEFECTS:
        raise ValueError(f"unknown_v3_task:{task_id}")
    if payload.get("feedback_contract_version") != 2:
        raise ValueError("feedback_contract_version_invalid")
    try:
        items = payload["feedback"]["items"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise ValueError("feedback_schema_invalid") from exc
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
        raise ValueError("review_requires_exactly_one_finding")
    item = items[0]
    finding_id = item.get("claim_id")
    if finding_id != OPAQUE_FINDING_IDS[task_id]:
        raise ValueError("review_finding_not_opaque_or_unbound")
    if item.get("status") != "unsupported" or any(
        not isinstance(item.get(field), str) or not str(item[field]).strip()
        for field in ("requirement", "observed", "remediation", "reason")
    ):
        raise ValueError("review_finding_schema_invalid")
    # Treat serialized feedback as an agent-visible artifact.  The scan is
    # case-insensitive and includes selector vocabulary as well as check IDs.
    encoded = json.dumps(payload, sort_keys=True).lower()
    leaked = next((token for token in FORBIDDEN_AGENT_TOKENS if token.lower() in encoded), None)
    if leaked is not None:
        raise ValueError("review_feedback_leaks_private_identifier")
    return str(finding_id)


def validate_marker_accounting(markers: Sequence[Mapping[str, object]]) -> None:
    expected = {(task, condition) for task in TASKS for condition in CONDITIONS}
    observed: set[tuple[str, str]] = set()
    for marker in markers:
        if marker.get("phase") != "repair" or marker.get("initial_provider_call") is not False:
            raise ValueError("unexpected_provider_marker_kind")
        key = (str(marker.get("task_id")), str(marker.get("condition")))
        if key in observed:
            raise ValueError("duplicate_repair_marker")
        observed.add(key)
    if observed != expected or len(markers) != 8:
        raise ValueError(f"repair_marker_roster_mismatch:{sorted(expected - observed)}")


def finalize_results(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Apply the preregistered binary endpoint and fail closed on invalidity."""
    if len(rows) != 8:
        return {"schema_version": 3, "verdict": "INVALID", "reason": "cell_roster_incomplete"}
    by_task: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in rows:
        task, condition = str(row.get("task_id")), str(row.get("condition"))
        if task not in TASKS or condition not in CONDITIONS or condition in by_task.setdefault(task, {}):
            return {"schema_version": 3, "verdict": "INVALID", "reason": "cell_identity_invalid"}
        by_task[task][condition] = row
    if any(set(by_task.get(task, {})) != set(CONDITIONS) for task in TASKS):
        return {"schema_version": 3, "verdict": "INVALID", "reason": "pairing_invalid"}
    required_true = ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated")
    for row in rows:
        if any(row.get(key) is not True for key in required_true):
            return {"schema_version": 3, "verdict": "INVALID", "reason": "provider_harness_or_accounting_failure"}
        if row["condition"] == "B-agentharness" and any(
            row.get(key) is not True for key in ("feedback_delivered", "feedback_immutable", "feedback_accounted")
        ):
            return {"schema_version": 3, "verdict": "INVALID", "reason": "feedback_delivery_invalid"}
    paired: list[dict[str, object]] = []
    b_recovery = b_gt_a = a_gt_b = b_guard_regression = 0
    for task in TASKS:
        a, b = by_task[task]["A-baseline"], by_task[task]["B-agentharness"]
        score_a = int(bool(a.get("target_passed")) and bool(a.get("guards_passed")))
        score_b = int(bool(b.get("target_passed")) and bool(b.get("guards_passed")))
        b_recovery += int(bool(b.get("target_passed")))
        b_gt_a += int(score_b > score_a)
        a_gt_b += int(score_a > score_b)
        b_guard_regression += int(bool(a.get("guards_passed")) and not bool(b.get("guards_passed")))
        paired.append({"task_id": task, "score_a": score_a, "score_b": score_b,
                       "difference_b_minus_a": score_b - score_a})
    mean_delta = sum(int(item["difference_b_minus_a"]) for item in paired) / 4.0
    go = b_recovery >= 3 and b_gt_a >= 2 and a_gt_b == 0 and mean_delta >= 0.5 and b_guard_regression == 0
    return {
        "schema_version": 3, "verdict": "GO" if go else "NO-GO",
        "paired_binary_endpoints": paired, "b_target_recovery": b_recovery,
        "b_gt_a": b_gt_a, "a_gt_b": a_gt_b, "mean_delta_b_minus_a": mean_delta,
        "b_guard_regressions": b_guard_regression,
    }
