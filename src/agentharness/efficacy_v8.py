from __future__ import annotations

"""Provider-free V8 delta over the qualified V6/V7 campaign machinery."""

import ast
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Mapping, Sequence

from . import efficacy_v5 as v5
from . import efficacy_v6 as v6

PILOT_ID = "mechanism-first-controlled-repair-v8"
CALIBRATION_TASKS = (
    "context-complete-authorization-cache",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)
EVALUATION_TASKS = (
    "envelope-context-decryptor",
    "attenuated-capability-verifier",
    "transactional-release-pointer",
    "context-complete-authorization-cache",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)
CONDITIONS = ("A-baseline", "B-agentharness")
CONDITION_ORDERS = tuple(
    CONDITIONS if index % 2 == 0 else tuple(reversed(CONDITIONS))
    for index in range(len(EVALUATION_TASKS))
)
TASK_DEFECTS = {task: v5.TASK_DEFECTS[task] for task in EVALUATION_TASKS}
TASK_CHECKS = {task: v5.TASK_CHECKS[task] for task in EVALUATION_TASKS}
REFERENCE_RELATIVE = {task: v5.REFERENCE_RELATIVE[task] for task in EVALUATION_TASKS}
MATERIALIZATION_PROFILE = "v8-source-native-v6-ast-with-v5-context-reference"
OPAQUE_FINDING_IDS = {task: f"finding-v8-{index:03d}" for index, task in enumerate(EVALUATION_TASKS, 1)}
FINDING_CONTENT = {task: v5.FINDING_CONTENT[task] for task in EVALUATION_TASKS}
FORBIDDEN_AGENT_TOKENS = frozenset({
    "AGENTHARNESS_MUTANT", "MUTANT", "mutant", "sequential_bug",
    "mechanism-first-v5", "mechanism-first-v5.1", "mechanism-first-v5.2",
    "mechanism-first-v6", "mechanism-first-v7", "mechanism-first-v8",
    "qualification-results", *{check for checks in TASK_CHECKS.values() for check in checks},
})
_CLEAN_SELECTOR = "__v8_no_selector_can_equal_this_value_91d70b__"

canonical_hash = v6.canonical_hash
tree_manifest = v6.tree_manifest
tree_fingerprint = v6.tree_fingerprint
conservative_usage_percent = v6.conservative_usage_percent
quota_admission = v6.quota_admission


def leakage_scan(root: Path) -> list[dict[str, str]]:
    """Scan against the complete V8 roster, including authorization-cache IDs."""
    leaks: list[dict[str, str]] = []
    needles = {token.casefold(): token for token in FORBIDDEN_AGENT_TOKENS}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            leaks.append({"path": relative, "token": "SYMLINK"})
            continue
        haystacks = [relative.casefold()]
        if path.is_file():
            try:
                haystacks.append(path.read_text(encoding="utf-8").casefold())
            except UnicodeDecodeError:
                pass
        for needle, token in needles.items():
            if any(needle in value for value in haystacks):
                leaks.append({"path": relative, "token": token})
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp)) and isinstance(node.test, ast.Constant) and type(node.test.value) is bool:
                leaks.append({"path": path.relative_to(root).as_posix(), "token": f"if {node.test.value}"})
    return leaks


def _copy_reference(repo_root: Path, task_id: str, destination: Path) -> Path:
    if task_id not in REFERENCE_RELATIVE:
        raise ValueError(f"unknown_v8_task:{task_id}")
    source = repo_root / v5.REFERENCE_RELATIVE[task_id]
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


def _finish(task_id: str, source: Path, destination: Path) -> dict[str, object]:
    leaks = leakage_scan(destination)
    if leaks:
        raise ValueError(f"agent_visible_leakage:{leaks}")
    return {
        "schema_version": 8, "materialization_profile": MATERIALIZATION_PROFILE,
        "task_id": task_id, "reference_relative": v5.REFERENCE_RELATIVE[task_id],
        "source_fingerprint": tree_fingerprint(source),
        "controlled_fingerprint": tree_fingerprint(destination), "agent_visible_leakage": [],
    }


def materialize_clean_reference(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    source = _copy_reference(repo_root, task_id, destination)
    v6._compile_selectors(destination, _CLEAN_SELECTOR)
    return _finish(task_id, source, destination)


def materialize_controlled_start(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    source = _copy_reference(repo_root, task_id, destination)
    target = TASK_DEFECTS[task_id]
    if task_id == "transactional-release-pointer":
        materializer_path = repo_root / "benchmarks/grading-env/materialize_v5_crypto_mutants.py"
        spec = importlib.util.spec_from_file_location("v8_private_materializer", materializer_path)
        if spec is None or spec.loader is None:
            raise ValueError("materializer_import_invalid")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        temporary = destination.with_name(destination.name + ".patched")
        module.materialize_mutant(destination, task_id, target, temporary)
        shutil.rmtree(destination)
        temporary.rename(destination)
    v6._compile_selectors(destination, target)
    return _finish(task_id, source, destination)


def clone_pair(source: Path, a: Path, b: Path) -> str:
    expected = tree_manifest(source)
    for target in (a, b):
        if target.exists() or target.is_symlink():
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
    payload = {"schema_version": 8, "feedback_contract_version": 2, "task_id": task_id,
               "partition": "review-v8", "feedback": {"items": [{
                   "claim_id": OPAQUE_FINDING_IDS[task_id], "status": "unsupported",
                   "requirement": requirement, "observed": observed, "remediation": remediation,
                   "reason": "Repair the reproduced invariant failure without weakening surrounding behavior.",
               }]}}
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
    required = {"claim_id", "status", "requirement", "observed", "remediation", "reason"}
    if not required <= set(item) or any(not isinstance(item[key], str) or not item[key].strip() for key in required):
        raise ValueError("review_finding_text_invalid")
    if item.get("claim_id") != OPAQUE_FINDING_IDS.get(task_id) or item.get("status") != "unsupported":
        raise ValueError("review_finding_invalid")
    encoded = json.dumps(payload, sort_keys=True).casefold()
    private = {check.casefold() for checks in TASK_CHECKS.values() for check in checks}
    if any(token in encoded for token in private):
        raise ValueError("review_feedback_leaks_private_identifier")
    return str(item["claim_id"])


def evaluate_heldout(workspace: Path, task_id: str, *, repo_root: Path | None = None):
    result = dict(v6.evaluate_heldout(workspace, task_id, repo_root=repo_root))
    result["schema_version"] = 8
    return result


def evaluate_review(_workspace: Path, task_id: str):
    return opaque_review_feedback(task_id)


def calibration_admission(rows: Sequence[Mapping[str, object]]) -> str:
    if len(rows) != 3 or {str(row.get("task_id")) for row in rows} != set(CALIBRATION_TASKS):
        return "INVALID"
    validity = ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated", "guards_passed")
    if any(row.get("condition") != "A-baseline" or any(row.get(key) is not True for key in validity)
           or type(row.get("target_passed")) is not bool for row in rows):
        return "INVALID"
    recovered = sum(row.get("target_passed") is True for row in rows)
    return "ADMIT" if recovered <= 1 else "CEILING"


def validate_marker_accounting(markers: Sequence[Mapping[str, object]], *, evaluation_admitted: bool) -> None:
    expected = {(f"v8-cal-{index:03d}:A-baseline:repair-1", task, "A-baseline")
                for index, task in enumerate(CALIBRATION_TASKS, 1)}
    if evaluation_admitted:
        expected |= {(f"v8-eval-{index:03d}:{condition}:repair-1", task, condition)
                     for index, task in enumerate(EVALUATION_TASKS, 1) for condition in CONDITIONS}
    observed: set[tuple[str, str, str]] = set()
    for marker in markers:
        key = (str(marker.get("invocation_id")), str(marker.get("task_id")), str(marker.get("condition")))
        if marker.get("phase") != "repair" or marker.get("initial_provider_call") is not False or key in observed:
            raise ValueError("provider_marker_invalid")
        observed.add(key)
    if observed != expected or len(markers) != len(expected):
        raise ValueError("provider_marker_roster_mismatch")


def finalize_results(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    # V8 preserves the frozen V6 reducer and 5-of-6 rule. Adapt only the one
    # roster slot replaced after V7's outcome-aware CSV observation.
    adapted: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        if item.get("task_id") == "context-complete-authorization-cache":
            item["task_id"] = "streaming-csv-quoted-records"
        adapted.append(item)
    result = dict(v6.finalize_results(adapted))
    pairs = result.get("paired_binary_endpoints")
    if isinstance(pairs, list):
        for pair in pairs:
            if isinstance(pair, dict) and pair.get("task_id") == "streaming-csv-quoted-records":
                pair["task_id"] = "context-complete-authorization-cache"
    result["schema_version"] = 8
    return result
