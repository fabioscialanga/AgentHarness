from __future__ import annotations

"""Pre-data primitives for the 12-task mechanism-first V5 efficacy study.

This module performs no provider calls. Private defect/check identifiers must not
survive in an agent-visible controlled workspace or feedback artifact.
"""

import ast
import hashlib
import importlib.util
import json
import math
import os
import shutil
import stat
from pathlib import Path
from typing import Mapping, Sequence

PILOT_ID = "mechanism-first-controlled-repair-v5"
CALIBRATION_TASKS = ("dependency-impact-planner", "access-policy-evaluator")
EVALUATION_TASKS = (
    "rotating-key-token-verifier",
    "envelope-context-decryptor",
    "attenuated-capability-verifier",
    "atomic-batch-state-machine",
    "ack-token-work-queue",
    "length-prefixed-frame-parser",
    "streaming-csv-quoted-records",
    "epoch-guarded-leader-heartbeat",
    "context-complete-authorization-cache",
    "transactional-release-pointer",
    "two-tier-read-through-cache",
    "portable-command-receipt-ledger",
)
CONDITIONS = ("A-baseline", "B-agentharness")
CONDITION_ORDERS = tuple(
    CONDITIONS if index % 2 == 0 else tuple(reversed(CONDITIONS))
    for index in range(len(EVALUATION_TASKS))
)
TASK_DEFECTS = {
    "rotating-key-token-verifier": "token_rotation_window",
    "envelope-context-decryptor": "envelope_context_binding",
    "attenuated-capability-verifier": "capability_attenuation",
    "atomic-batch-state-machine": "batch_all_or_none",
    "ack-token-work-queue": "ack_stale_worker_rejected",
    "length-prefixed-frame-parser": "frame_split_prefix_payload",
    "streaming-csv-quoted-records": "csv_quoted_chunk_state",
    "epoch-guarded-leader-heartbeat": "leader_stale_epoch_publish",
    "context-complete-authorization-cache": "auth_cache_resource_identity",
    "transactional-release-pointer": "release_generation_cas",
    "two-tier-read-through-cache": "tier_two_level_invalidation",
    "portable-command-receipt-ledger": "receipt_key_identity",
}
TASK_CHECKS = {
    "rotating-key-token-verifier": ("token_rotation_window", "token_issuer_audience", "token_algorithm_pin", "token_time_claims", "token_canonical_encoding"),
    "envelope-context-decryptor": ("envelope_context_binding", "envelope_key_version", "envelope_nonce_tag", "envelope_schema", "envelope_output_atomicity"),
    "attenuated-capability-verifier": ("capability_attenuation", "capability_chain_signatures", "capability_depth", "capability_request_match", "capability_time_intersection"),
    "atomic-batch-state-machine": ("batch_all_or_none", "batch_duplicate_entity", "batch_error_index", "batch_idempotent_replay", "batch_response_order"),
    "ack-token-work-queue": ("ack_attempt_accounting", "ack_nack_requeues", "ack_single_claim", "ack_stale_worker_rejected", "ack_visibility_timeout"),
    "length-prefixed-frame-parser": ("frame_split_prefix_payload", "frame_max_before_alloc", "frame_truncated_eof", "frame_zero_and_multiple", "frame_endianness"),
    "streaming-csv-quoted-records": ("csv_field_limit", "csv_header_exact", "csv_quoted_chunk_state", "csv_row_width", "csv_strict_eof"),
    "epoch-guarded-leader-heartbeat": ("leader_epoch_monotonic", "leader_expiry_boundary", "leader_one_winner", "leader_publication_order", "leader_stale_epoch_publish"),
    "context-complete-authorization-cache": ("auth_cache_resource_identity", "auth_cache_tenant", "auth_cache_subject", "auth_cache_action", "auth_cache_policy_revision"),
    "transactional-release-pointer": ("release_generation_cas", "release_artifact_approval", "release_publication_completeness", "release_failure_atomicity", "release_idempotent_replay"),
    "two-tier-read-through-cache": ("tier_l1_short_circuit", "tier_l2_promotion", "tier_origin_fill", "tier_two_level_invalidation", "tier_failure_non_admission"),
    "portable-command-receipt-ledger": ("receipt_key_identity", "receipt_tenant_identity", "receipt_command_identity", "receipt_revision_identity", "receipt_process_portability"),
}
REFERENCE_RELATIVE = {
    **{task: f"benchmarks/grading-env/mechanism-first-v5/references/{task}" for task in EVALUATION_TASKS[:8]},
    "context-complete-authorization-cache": "benchmarks/grading-env/mechanism-first-v5.1/references/context-complete-authorization-cache",
    **{task: f"benchmarks/grading-env/mechanism-first-v5.2/references/{task}" for task in EVALUATION_TASKS[9:]},
}
OPAQUE_FINDING_IDS = {task: f"finding-v5-{index:03d}" for index, task in enumerate(EVALUATION_TASKS, 1)}
FINDING_CONTENT = {
    "rotating-key-token-verifier": ("Token verification must enforce the selected key's half-open active interval.", "A boundary probe accepted a token outside active_from inclusive to retire_at exclusive.", "Enforce the exact selected-key interval without weakening signature, token-time, issuer, audience, or encoding checks."),
    "envelope-context-decryptor": ("Authenticated decryption must bind the complete request context into canonical associated data.", "Changing one required context dimension did not invalidate authentication.", "Bind tenant, purpose, object identifier, schema version, and key identifier canonically while preserving authentication and atomic output."),
    "attenuated-capability-verifier": ("Every delegated capability must be no broader than its ancestor across every authorization dimension.", "A delegated capability widened an ancestor authorization dimension.", "Enforce attenuation across tenant, actions, resource prefix, time interval, and depth without weakening chain verification."),
    "atomic-batch-state-machine": ("A rejected batch must leave entity and command state unchanged.", "A failing command left a partial durable batch mutation.", "Validate from one pre-batch snapshot and commit the complete accepted batch atomically, or change nothing."),
    "ack-token-work-queue": ("Acknowledgement requires the current claimed state, worker, and exact current ownership token.", "An expired or superseded ownership generation was accepted.", "Reject every stale token after timeout and reclaim, including reclaim by the same worker, without weakening queue ordering."),
    "length-prefixed-frame-parser": ("Streaming parser state must survive arbitrary splits of both the four-byte prefix and payload.", "A valid frame split across chunk boundaries was parsed incorrectly.", "Retain prefix and payload state across chunks without whole-input concatenation or weaker EOF and size checks."),
    "streaming-csv-quoted-records": ("Quoted-field state must survive byte-chunk boundaries, embedded separators, line breaks, and doubled quotes.", "A quoted record split across chunks was decoded incorrectly.", "Preserve streaming quote state and decoded fields without weakening EOF, header, row-width, or size validation."),
    "epoch-guarded-leader-heartbeat": ("Publish requires the current leader identity, exact current epoch, and an unexpired lease.", "A stale leadership generation was allowed to publish.", "Validate leader and epoch against durable current state before staging; rejection must consume no sequence."),
    "context-complete-authorization-cache": ("Authorization cache identity must include the exact case-sensitive resource identifier.", "A decision for one resource satisfied a request for another resource.", "Use the complete key: tenant, subject, resource identifier, action, and policy revision."),
    "transactional-release-pointer": ("Publication requires expected generation to equal the current channel generation inside the transaction.", "A publication with a stale or future expected generation proceeded.", "Perform the exact generation comparison transactionally and roll back without staged durable effects on mismatch."),
    "two-tier-read-through-cache": ("Invalidation must remove the exact case-sensitive key from both cache tiers.", "An invalidated key remained reusable in one tier.", "Delete the exact key once from L1 and once from L2 in the specified order without normalization or aliasing."),
    "portable-command-receipt-ledger": ("Durable receipt identity must include the exact case-sensitive idempotency key.", "Distinct idempotency keys replayed the same stored receipt.", "Persist and look up the complete tenant, command, API revision, and idempotency-key tuple."),
}
FORBIDDEN_AGENT_TOKENS = frozenset({
    "AGENTHARNESS_MUTANT", "MUTANT", "mechanism-first-v5", "qualification-results",
    *TASK_DEFECTS.values(),
})


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tree_manifest(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("tree_root_invalid")
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"tree_symlink_forbidden:{relative}")
        if path.is_file():
            data = path.read_bytes()
            rows.append({"path": relative, "mode": stat.S_IMODE(info.st_mode), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def tree_fingerprint(root: Path) -> str:
    return canonical_hash(tree_manifest(root))


class _CompileSelector(ast.NodeTransformer):
    def __init__(self, selected: str):
        self.selected = selected

    def visit_Assign(self, node: ast.Assign):
        if any(isinstance(target, ast.Name) and target.id in {"MUTANT", "mutant"} for target in node.targets):
            return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        transformed = self.generic_visit(node)
        if (
            isinstance(transformed, ast.Call)
            and isinstance(transformed.func, ast.Attribute)
            and transformed.func.attr == "get"
            and isinstance(transformed.func.value, ast.Attribute)
            and transformed.func.value.attr == "environ"
            and transformed.args
            and isinstance(transformed.args[0], ast.Constant)
            and transformed.args[0].value == "AGENTHARNESS_MUTANT"
        ):
            return ast.copy_location(ast.Constant(self.selected), transformed)
        return transformed

    def visit_Compare(self, node: ast.Compare):
        transformed = self.generic_visit(node)
        if isinstance(transformed, ast.Compare) and len(transformed.ops) == len(transformed.comparators) == 1:
            left, right = transformed.left, transformed.comparators[0]
            value = None
            if isinstance(left, ast.Name) and left.id in {"MUTANT", "mutant"} and isinstance(right, ast.Constant):
                value = right.value
            elif isinstance(right, ast.Name) and right.id in {"MUTANT", "mutant"} and isinstance(left, ast.Constant):
                value = left.value
            elif isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
                if isinstance(transformed.ops[0], ast.Eq):
                    return ast.copy_location(ast.Constant(left.value == right.value), transformed)
                if isinstance(transformed.ops[0], ast.NotEq):
                    return ast.copy_location(ast.Constant(left.value != right.value), transformed)
            if isinstance(value, str):
                if isinstance(transformed.ops[0], ast.Eq):
                    return ast.copy_location(ast.Constant(value == self.selected), transformed)
                if isinstance(transformed.ops[0], ast.NotEq):
                    return ast.copy_location(ast.Constant(value != self.selected), transformed)
        return transformed

    def visit_If(self, node: ast.If):
        transformed = self.generic_visit(node)
        if isinstance(transformed, ast.If) and isinstance(transformed.test, ast.Constant) and isinstance(transformed.test.value, bool):
            return transformed.body if transformed.test.value else transformed.orelse
        return transformed


def _compile_selectors(root: Path, selected: str) -> None:
    for path in sorted(root.rglob("*.py")):
        tree = _CompileSelector(selected).visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        ast.fix_missing_locations(tree)
        rendered = ast.unparse(tree) + "\n"
        compile(rendered, str(path), "exec")
        path.write_text(rendered, encoding="utf-8")


def leakage_scan(root: Path) -> list[dict[str, str]]:
    leaks: list[dict[str, str]] = []
    needles = {token.lower(): token for token in FORBIDDEN_AGENT_TOKENS}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            leaks.append({"path": relative, "token": "SYMLINK"})
            continue
        haystacks = [relative.lower()]
        if path.is_file():
            try:
                haystacks.append(path.read_text(encoding="utf-8").lower())
            except UnicodeDecodeError:
                pass
        for needle, token in needles.items():
            if any(needle in value for value in haystacks):
                leaks.append({"path": relative, "token": token})
    return leaks


def _copy_reference(repo_root: Path, task_id: str, destination: Path) -> Path:
    source = repo_root / REFERENCE_RELATIVE[task_id]
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"reference_missing:{task_id}")
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.is_symlink():
            raise ValueError(f"tree_symlink_forbidden:{path.relative_to(destination)}")
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache", "build"}:
            shutil.rmtree(path)
        elif path.is_file() and (path.suffix in {".pyc", ".db", ".sqlite", ".sqlite3"} or path.name == "README.md"):
            path.unlink()
    return source


def materialize_clean_reference(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    source = _copy_reference(repo_root, task_id, destination)
    _compile_selectors(destination, "__clean_v5__")
    leaks = leakage_scan(destination)
    if leaks:
        raise ValueError(f"agent_visible_leakage:{leaks}")
    return {"schema_version": 5, "task_id": task_id, "source_fingerprint": tree_fingerprint(source), "controlled_fingerprint": tree_fingerprint(destination), "agent_visible_leakage": []}


def materialize_controlled_start(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    if task_id not in TASK_DEFECTS:
        raise ValueError(f"unknown_v5_task:{task_id}")
    source = _copy_reference(repo_root, task_id, destination)
    if task_id in EVALUATION_TASKS[:9]:
        _compile_selectors(destination, TASK_DEFECTS[task_id])
    else:
        grading = repo_root / "benchmarks/grading-env"
        materializer_path = grading / "materialize_v5_crypto_mutants.py"
        spec = importlib.util.spec_from_file_location("v5_private_materializer", materializer_path)
        if spec is None or spec.loader is None:
            raise ValueError("materializer_import_invalid")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        temporary = destination.with_name(destination.name + ".patched")
        module.materialize_mutant(destination, task_id, TASK_DEFECTS[task_id], temporary)
        shutil.rmtree(destination)
        temporary.rename(destination)
    leaks = leakage_scan(destination)
    if leaks:
        raise ValueError(f"agent_visible_leakage:{leaks}")
    return {"schema_version": 5, "task_id": task_id, "source_fingerprint": tree_fingerprint(source), "controlled_fingerprint": tree_fingerprint(destination), "agent_visible_leakage": []}


def clone_pair(source: Path, a: Path, b: Path) -> str:
    expected = tree_manifest(source)
    for target in (a, b):
        if target.exists():
            raise FileExistsError(target)
        shutil.copytree(source, target, copy_function=shutil.copy2)
        if tree_manifest(target) != expected:
            raise ValueError("clone_identity_mismatch")
        if leakage_scan(target):
            raise ValueError("clone_leakage")
    return tree_fingerprint(source)


def opaque_review_feedback(task_id: str) -> dict[str, object]:
    if task_id not in EVALUATION_TASKS:
        raise ValueError("review_task_not_evaluation")
    requirement, observed, remediation = FINDING_CONTENT[task_id]
    payload = {
        "schema_version": 5,
        "feedback_contract_version": 2,
        "task_id": task_id,
        "partition": "review-v5",
        "feedback": {"items": [{
            "claim_id": OPAQUE_FINDING_IDS[task_id],
            "status": "unsupported",
            "requirement": requirement,
            "observed": observed,
            "remediation": remediation,
            "reason": "Repair the reproduced invariant failure without weakening surrounding behavior.",
        }]},
    }
    validate_opaque_feedback(payload, task_id=task_id)
    return payload


def validate_opaque_feedback(payload: Mapping[str, object], *, task_id: str) -> str:
    try:
        items = payload["feedback"]["items"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise ValueError("feedback_schema_invalid") from exc
    if payload.get("feedback_contract_version") != 2 or not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
        raise ValueError("review_requires_exactly_one_finding")
    item = items[0]
    required_text = {"claim_id", "status", "requirement", "observed", "remediation", "reason"}
    if not required_text <= set(item) or any(not isinstance(item[key], str) or not item[key].strip() for key in required_text):
        raise ValueError("review_finding_text_invalid")
    if item.get("claim_id") != OPAQUE_FINDING_IDS.get(task_id) or item.get("status") != "unsupported":
        raise ValueError("review_finding_invalid")
    encoded = json.dumps(payload, sort_keys=True).lower()
    forbidden = [token for token in FORBIDDEN_AGENT_TOKENS if token.lower() in encoded]
    if forbidden:
        raise ValueError(f"review_feedback_leaks_private_identifier:{sorted(forbidden)}")
    return str(item["claim_id"])


def calibration_admission(rows: Sequence[Mapping[str, object]]) -> str:
    if len(rows) != 2 or {str(row.get("task_id")) for row in rows} != set(CALIBRATION_TASKS):
        return "INVALID"
    if any(row.get("condition") != "A-baseline" or any(row.get(key) is not True for key in ("invocation_valid", "heldout_valid", "guards_passed")) for row in rows):
        return "INVALID"
    return "CEILING" if sum(row.get("target_passed") is True for row in rows) == 2 else "ADMIT"


def validate_marker_accounting(markers: Sequence[Mapping[str, object]], *, evaluation_admitted: bool) -> None:
    expected = {(task, "A-baseline") for task in CALIBRATION_TASKS}
    if evaluation_admitted:
        expected |= {(task, condition) for task in EVALUATION_TASKS for condition in CONDITIONS}
    observed: set[tuple[str, str]] = set()
    for marker in markers:
        key = (str(marker.get("task_id")), str(marker.get("condition")))
        if marker.get("phase") != "repair" or marker.get("initial_provider_call") is not False or key in observed:
            raise ValueError("provider_marker_invalid")
        observed.add(key)
    if observed != expected or len(markers) != len(expected):
        raise ValueError("provider_marker_roster_mismatch")


def conservative_usage_percent(windows: Sequence[object]) -> float:
    """Require the frozen Codex Session+Weekly shape and return the tighter window."""
    required = {"Session", "Weekly"}
    if len(windows) != 2:
        raise ValueError("quota_window_count")
    observed: dict[str, float] = {}
    for window in windows:
        label = getattr(window, "label", None)
        value = getattr(window, "used_percent", None)
        if label not in required or label in observed or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("quota_window_shape")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0 <= numeric <= 100:
            raise ValueError("quota_window_range")
        observed[str(label)] = numeric
    if set(observed) != required:
        raise ValueError("quota_window_labels")
    return max(observed.values())


def quota_admission(start_usage: float, end_usage: float) -> tuple[bool, float]:
    if any(type(value) not in (int, float) for value in (start_usage, end_usage)) or not (0 <= start_usage <= end_usage <= 100):
        raise ValueError("quota_telemetry_invalid")
    projected = float(end_usage) + 24 * max(0.5, (float(end_usage) - float(start_usage)) / 2)
    return projected <= 76.0, projected


def finalize_results(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if len(rows) != 24:
        return {"schema_version": 5, "verdict": "INVALID", "reason": "cell_roster_incomplete"}
    by_task: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in rows:
        task, condition = str(row.get("task_id")), str(row.get("condition"))
        if task not in EVALUATION_TASKS or condition not in CONDITIONS or condition in by_task.setdefault(task, {}):
            return {"schema_version": 5, "verdict": "INVALID", "reason": "cell_identity_invalid"}
        by_task[task][condition] = row
    if any(set(by_task.get(task, {})) != set(CONDITIONS) for task in EVALUATION_TASKS):
        return {"schema_version": 5, "verdict": "INVALID", "reason": "pairing_invalid"}
    for row in rows:
        if any(row.get(key) is not True for key in ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated")):
            return {"schema_version": 5, "verdict": "INVALID", "reason": "provider_harness_or_accounting_failure"}
        if type(row.get("target_passed")) is not bool or type(row.get("guards_passed")) is not bool:
            return {"schema_version": 5, "verdict": "INVALID", "reason": "endpoint_type_invalid"}
        if row["condition"] == "B-agentharness" and any(row.get(key) is not True for key in ("feedback_delivered", "feedback_immutable", "feedback_accounted")):
            return {"schema_version": 5, "verdict": "INVALID", "reason": "feedback_delivery_invalid"}
        if row["condition"] == "A-baseline" and row.get("feedback_delivered") is not False:
            return {"schema_version": 5, "verdict": "INVALID", "reason": "baseline_contamination"}
    paired = []
    recovery = b_gt_a = a_gt_b = regressions = 0
    for task in EVALUATION_TASKS:
        a, b = by_task[task]["A-baseline"], by_task[task]["B-agentharness"]
        score_a = int(bool(a["target_passed"]) and bool(a["guards_passed"]))
        score_b = int(bool(b["target_passed"]) and bool(b["guards_passed"]))
        recovery += int(bool(b["target_passed"]))
        b_gt_a += int(score_b > score_a)
        a_gt_b += int(score_a > score_b)
        regressions += int(not bool(b["guards_passed"]))
        paired.append({"task_id": task, "score_a": score_a, "score_b": score_b, "difference_b_minus_a": score_b - score_a})
    delta = sum(row["difference_b_minus_a"] for row in paired) / 12.0
    go = b_gt_a >= 10 and a_gt_b == 0 and delta >= 10 / 12 and recovery >= 10 and regressions == 0
    return {
        "schema_version": 5,
        "verdict": "GO" if go else "NO-GO",
        "study_class": "exploratory",
        "paired_binary_endpoints": paired,
        "b_target_recovery": recovery,
        "b_gt_a": b_gt_a,
        "a_gt_b": a_gt_b,
        "mean_delta_b_minus_a": delta,
        "b_guard_regressions": regressions,
    }
