from __future__ import annotations

"""Provider-free primitives for the source-native V6 efficacy campaign."""

import ast
import hashlib
import importlib.util
import json
import math
import shutil
import stat
from pathlib import Path
from typing import Mapping, Sequence

from . import efficacy_v5 as v5

PILOT_ID = "mechanism-first-controlled-repair-v6"
CALIBRATION_TASKS = (
    "envelope-context-decryptor",
    "attenuated-capability-verifier",
    "transactional-release-pointer",
)
EVALUATION_TASKS = (
    "envelope-context-decryptor",
    "attenuated-capability-verifier",
    "transactional-release-pointer",
    "streaming-csv-quoted-records",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)
CONDITIONS = ("A-baseline", "B-agentharness")
CONDITION_ORDERS = tuple(
    CONDITIONS if index % 2 == 0 else tuple(reversed(CONDITIONS))
    for index in range(len(EVALUATION_TASKS))
)
TASK_DEFECTS = {
    "envelope-context-decryptor": "envelope_context_binding",
    "attenuated-capability-verifier": "capability_attenuation",
    "transactional-release-pointer": "release_generation_cas",
    "streaming-csv-quoted-records": "csv_quoted_chunk_state",
    "length-prefixed-frame-parser": "frame_split_prefix_payload",
    "atomic-batch-state-machine": "batch_all_or_none",
}
TASK_CHECKS = {task: v5.TASK_CHECKS[task] for task in EVALUATION_TASKS}
REFERENCE_RELATIVE = {task: v5.REFERENCE_RELATIVE[task] for task in EVALUATION_TASKS}
OPAQUE_FINDING_IDS = {task: f"finding-v6-{index:03d}" for index, task in enumerate(EVALUATION_TASKS, 1)}
FINDING_CONTENT = {task: v5.FINDING_CONTENT[task] for task in EVALUATION_TASKS}
# These values are private scanner inputs. None may survive in a materialized workspace.
FORBIDDEN_AGENT_TOKENS = frozenset({
    "AGENTHARNESS_MUTANT", "MUTANT", "mutant", "sequential_bug",
    "mechanism-first-v5", "mechanism-first-v5.2", "mechanism-first-v6",
    "qualification-results", *{check for checks in TASK_CHECKS.values() for check in checks},
})
_SELECTOR_NAMES = frozenset({"MUTANT", "mutant"})
_CLEAN_SELECTOR = "__v6_no_selector_can_equal_this_value_7f1e9c__"
_UNKNOWN = object()


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


def _literal(node: ast.AST) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    return _UNKNOWN


class _CompileSelector(ast.NodeTransformer):
    """Partial evaluator for the private selector language used by V5 references."""

    def __init__(self, selected: str):
        self.selected = selected

    def visit_Assign(self, node: ast.Assign):
        if any(isinstance(target, ast.Name) and target.id in _SELECTOR_NAMES for target in node.targets):
            return None
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.target.id in _SELECTOR_NAMES:
            return None
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id in _SELECTOR_NAMES:
            return ast.copy_location(ast.Constant(self.selected), node)
        if node.id == "sequential_bug":
            return ast.copy_location(ast.Name(id="apply_individually", ctx=node.ctx), node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name == "sequential_bug":
            node.name = "apply_individually"
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        transformed = self.generic_visit(node)
        if not isinstance(transformed, ast.Call) or not isinstance(transformed.func, ast.Attribute) or transformed.func.attr != "get":
            return transformed
        owner = transformed.func.value
        if (isinstance(owner, ast.Attribute) and owner.attr == "environ" and
                transformed.args and isinstance(transformed.args[0], ast.Constant) and
                transformed.args[0].value == "AGENTHARNESS_MUTANT"):
            return ast.copy_location(ast.Constant(self.selected), transformed)
        return transformed

    def visit_Compare(self, node: ast.Compare):
        transformed = self.generic_visit(node)
        if not isinstance(transformed, ast.Compare):
            return transformed
        values = [_literal(transformed.left), *(_literal(item) for item in transformed.comparators)]
        if any(value is _UNKNOWN for value in values) or not all(isinstance(op, (ast.Eq, ast.NotEq)) for op in transformed.ops):
            return transformed
        result = all((left == right) if isinstance(op, ast.Eq) else (left != right)
                     for left, op, right in zip(values[:-1], transformed.ops, values[1:], strict=True))
        return ast.copy_location(ast.Constant(result), transformed)

    def visit_UnaryOp(self, node: ast.UnaryOp):
        transformed = self.generic_visit(node)
        if isinstance(transformed, ast.UnaryOp) and isinstance(transformed.op, ast.Not):
            value = _literal(transformed.operand)
            if value is not _UNKNOWN:
                return ast.copy_location(ast.Constant(not bool(value)), transformed)
        return transformed

    def visit_BoolOp(self, node: ast.BoolOp):
        transformed = self.generic_visit(node)
        if not isinstance(transformed, ast.BoolOp):
            return transformed
        kept: list[ast.expr] = []
        for value in transformed.values:
            literal = _literal(value)
            if isinstance(transformed.op, ast.And):
                if literal is not _UNKNOWN and not bool(literal):
                    return ast.copy_location(value, transformed)
                if literal is not _UNKNOWN and bool(literal):
                    continue
            else:
                if literal is not _UNKNOWN and bool(literal):
                    return ast.copy_location(value, transformed)
                if literal is not _UNKNOWN and not bool(literal):
                    continue
            kept.append(value)
        if not kept:
            identity = True if isinstance(transformed.op, ast.And) else False
            return ast.copy_location(ast.Constant(identity), transformed)
        if len(kept) == 1:
            return ast.copy_location(kept[0], transformed)
        transformed.values = kept
        return transformed

    def visit_If(self, node: ast.If):
        transformed = self.generic_visit(node)
        if isinstance(transformed, ast.If) and isinstance(transformed.test, ast.Constant):
            return transformed.body if bool(transformed.test.value) else transformed.orelse
        return transformed

    def visit_IfExp(self, node: ast.IfExp):
        transformed = self.generic_visit(node)
        if isinstance(transformed, ast.IfExp) and isinstance(transformed.test, ast.Constant):
            return transformed.body if bool(transformed.test.value) else transformed.orelse
        return transformed


def _compile_selectors(root: Path, selected: str) -> None:
    for path in sorted(root.rglob("*.py")):
        tree: ast.AST = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Repeated passes fold expressions exposed by an earlier branch reduction.
        for _ in range(4):
            tree = _CompileSelector(selected).visit(tree)
            ast.fix_missing_locations(tree)
        rendered = ast.unparse(tree) + "\n"
        compile(rendered, str(path), "exec")
        path.write_text(rendered, encoding="utf-8")


def leakage_scan(root: Path) -> list[dict[str, str]]:
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
    # Selector compilation must also leave no literal boolean branch scars.
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp)) and isinstance(node.test, ast.Constant) and type(node.test.value) is bool:
                leaks.append({"path": path.relative_to(root).as_posix(), "token": f"if {node.test.value}"})
    return leaks


def _copy_reference(repo_root: Path, task_id: str, destination: Path) -> Path:
    if task_id not in REFERENCE_RELATIVE:
        raise ValueError(f"unknown_v6_task:{task_id}")
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


def _finish_materialization(task_id: str, source: Path, destination: Path) -> dict[str, object]:
    leaks = leakage_scan(destination)
    if leaks:
        raise ValueError(f"agent_visible_leakage:{leaks}")
    return {"schema_version": 6, "task_id": task_id, "source_fingerprint": tree_fingerprint(source),
            "controlled_fingerprint": tree_fingerprint(destination), "agent_visible_leakage": []}


def materialize_clean_reference(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    source = _copy_reference(repo_root, task_id, destination)
    _compile_selectors(destination, _CLEAN_SELECTOR)
    return _finish_materialization(task_id, source, destination)


def materialize_controlled_start(*, task_id: str, repo_root: Path, destination: Path) -> dict[str, object]:
    source = _copy_reference(repo_root, task_id, destination)
    target = TASK_DEFECTS[task_id]
    if task_id == "transactional-release-pointer":
        materializer_path = repo_root / "benchmarks/grading-env/materialize_v5_crypto_mutants.py"
        spec = importlib.util.spec_from_file_location("v6_private_materializer", materializer_path)
        if spec is None or spec.loader is None:
            raise ValueError("materializer_import_invalid")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        temporary = destination.with_name(destination.name + ".patched")
        module.materialize_mutant(destination, task_id, target, temporary)
        shutil.rmtree(destination)
        temporary.rename(destination)
    _compile_selectors(destination, target)
    return _finish_materialization(task_id, source, destination)


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
    payload = {"schema_version": 6, "feedback_contract_version": 2, "task_id": task_id,
               "partition": "review-v6", "feedback": {"items": [{
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
    from .benchmark_heldout_evaluator_v5 import evaluate_heldout as evaluator
    result = dict(evaluator(workspace, task_id, repo_root=repo_root))
    result["evaluator_schema_version"] = result.pop("schema_version")
    result["schema_version"] = 6
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
    expected = {
        (f"v6-cal-{index:03d}:A-baseline:repair-1", task, "A-baseline")
        for index, task in enumerate(CALIBRATION_TASKS, 1)
    }
    if evaluation_admitted:
        expected |= {
            (f"v6-eval-{index:03d}:{condition}:repair-1", task, condition)
            for index, task in enumerate(EVALUATION_TASKS, 1)
            for condition in CONDITIONS
        }
    observed: set[tuple[str, str, str]] = set()
    for marker in markers:
        key = (
            str(marker.get("invocation_id")),
            str(marker.get("task_id")),
            str(marker.get("condition")),
        )
        if marker.get("phase") != "repair" or marker.get("initial_provider_call") is not False or key in observed:
            raise ValueError("provider_marker_invalid")
        observed.add(key)
    if observed != expected or len(markers) != len(expected):
        raise ValueError("provider_marker_roster_mismatch")


def conservative_usage_percent(windows: Sequence[object]) -> float:
    required = {"Session", "Weekly"}
    if len(windows) != 2:
        raise ValueError("quota_window_count")
    observed: dict[str, float] = {}
    for window in windows:
        label, value = getattr(window, "label", None), getattr(window, "used_percent", None)
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
    projected = float(end_usage) + 12 * max(0.5, (float(end_usage) - float(start_usage)) / 3)
    return projected <= 76.0, projected


def finalize_results(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if len(rows) != 12:
        return {"schema_version": 6, "verdict": "INVALID", "reason": "cell_roster_incomplete"}
    by_task: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in rows:
        task, condition = str(row.get("task_id")), str(row.get("condition"))
        if task not in EVALUATION_TASKS or condition not in CONDITIONS or condition in by_task.setdefault(task, {}):
            return {"schema_version": 6, "verdict": "INVALID", "reason": "cell_identity_invalid"}
        by_task[task][condition] = row
    if any(set(by_task.get(task, {})) != set(CONDITIONS) for task in EVALUATION_TASKS):
        return {"schema_version": 6, "verdict": "INVALID", "reason": "pairing_invalid"}
    for row in rows:
        if any(row.get(key) is not True for key in ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated")):
            return {"schema_version": 6, "verdict": "INVALID", "reason": "provider_harness_or_accounting_failure"}
        if type(row.get("target_passed")) is not bool or type(row.get("guards_passed")) is not bool:
            return {"schema_version": 6, "verdict": "INVALID", "reason": "endpoint_type_invalid"}
        if row["condition"] == "B-agentharness" and any(row.get(key) is not True for key in ("feedback_delivered", "feedback_immutable", "feedback_accounted")):
            return {"schema_version": 6, "verdict": "INVALID", "reason": "feedback_delivery_invalid"}
        if row["condition"] == "A-baseline" and row.get("feedback_delivered") is not False:
            return {"schema_version": 6, "verdict": "INVALID", "reason": "baseline_contamination"}
    paired = []
    recovery = b_gt_a = a_gt_b = regressions = 0
    for task in EVALUATION_TASKS:
        a, b = by_task[task]["A-baseline"], by_task[task]["B-agentharness"]
        score_a = int(bool(a["target_passed"]) and bool(a["guards_passed"]))
        score_b = int(bool(b["target_passed"]) and bool(b["guards_passed"]))
        recovery += int(bool(b["target_passed"])); b_gt_a += int(score_b > score_a)
        a_gt_b += int(score_a > score_b); regressions += int(not bool(b["guards_passed"]))
        paired.append({"task_id": task, "score_a": score_a, "score_b": score_b,
                       "difference_b_minus_a": score_b - score_a})
    go = b_gt_a >= 5 and a_gt_b == 0 and recovery >= 5 and regressions == 0
    return {"schema_version": 6, "verdict": "GO" if go else "NO-GO", "study_class": "exploratory",
            "paired_binary_endpoints": paired, "b_target_recovery": recovery, "b_gt_a": b_gt_a,
            "a_gt_b": a_gt_b, "mean_delta_b_minus_a": sum(x["difference_b_minus_a"] for x in paired) / 6.0,
            "b_guard_regressions": regressions,
            "secondary_report": {"a_target_recovery": sum(bool(by_task[t]["A-baseline"]["target_passed"]) for t in EVALUATION_TASKS)}}
