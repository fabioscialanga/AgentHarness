from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .observability import EventLogger, default_trace_path, utc_now_iso
from .verify import load_run


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    type: str
    path: str
    description: str = ""
    expected: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationCase":
        expected = payload.get("expected", {})
        if not isinstance(expected, dict):
            expected = {}
        return cls(
            id=str(payload.get("id", "")).strip(),
            type=str(payload.get("type", "")).strip(),
            path=str(payload.get("path", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            expected=dict(expected),
        )


@dataclass(frozen=True)
class EvaluationSuite:
    suite_id: str
    run_id: str
    cases: tuple[EvaluationCase, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationSuite":
        cases_payload = payload.get("cases", [])
        if not isinstance(cases_payload, list):
            cases_payload = []
        return cls(
            suite_id=str(payload.get("suite_id", "")).strip(),
            run_id=str(payload.get("run_id", "")).strip(),
            cases=tuple(EvaluationCase.from_dict(item) for item in cases_payload if isinstance(item, dict)),
        )


@dataclass
class EvaluationCaseResult:
    case_id: str
    case_type: str
    status: str
    reason: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_type": self.case_type,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class EvaluationResult:
    suite_id: str
    run_id: str
    run_path: Path
    suite_path: Path
    results: list[EvaluationCaseResult]
    evaluated_at: str
    tool_version: str
    run_sha256: str
    suite_sha256: str
    trace_path: str | None = None
    report_written: str | None = None
    gating_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.gating_errors and all(item.status == "passed" for item in self.results)

    @property
    def summary(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "invalid": 0}
        for item in self.results:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "run_id": self.run_id,
            "run_path": str(self.run_path),
            "suite_path": str(self.suite_path),
            "ok": self.ok,
            "summary": self.summary,
            "results": [item.to_dict() for item in self.results],
            "evaluated_at": self.evaluated_at,
            "tool_version": self.tool_version,
            "run_sha256": self.run_sha256,
            "suite_sha256": self.suite_sha256,
            "trace_path": self.trace_path,
            "report_written": self.report_written,
            "gating_errors": self.gating_errors,
        }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_evaluation_suite(path: str | Path) -> EvaluationSuite:
    suite_path = Path(path).resolve()
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Evaluation suite must parse to a JSON object")
    return EvaluationSuite.from_dict(payload)


def _resolve_workspace_path(workspace: Path, relative_path: str) -> tuple[Path | None, str | None]:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None, "Evaluation case path must stay relative to the run workspace"
    resolved = (workspace / candidate).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError:
        return None, "Evaluation case path escapes the run workspace"
    return resolved, None


def _validate_suite(run_id: str, suite: EvaluationSuite) -> list[str]:
    errors: list[str] = []
    if not suite.suite_id:
        errors.append("Evaluation suite is missing suite_id")
    if not suite.run_id:
        errors.append("Evaluation suite is missing run_id")
    if suite.run_id and suite.run_id != run_id:
        errors.append("Evaluation suite run_id does not match run artifact run_id")
    if not suite.cases:
        errors.append("Evaluation suite must contain at least one case")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case in suite.cases:
        if not case.id:
            errors.append("Evaluation suite contains a case without id")
            continue
        if case.id in seen:
            duplicates.add(case.id)
        seen.add(case.id)
    if duplicates:
        errors.append("Evaluation suite contains duplicate case ids: " + ", ".join(sorted(duplicates)))
    return errors


def validate_evaluation_suite_payload(
    payload: dict[str, Any],
    *,
    run_id: str,
    expected_case_count: int | None = None,
) -> list[str]:
    """Validate a rendered suite before it is materialized or evaluated."""
    suite = EvaluationSuite.from_dict(payload)
    errors = _validate_suite(run_id, suite)
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        errors.append("Evaluation suite cases must be a list")
        return errors
    if expected_case_count is not None and len(raw_cases) != expected_case_count:
        errors.append(
            f"Evaluation suite must contain exactly {expected_case_count} cases; found {len(raw_cases)}"
        )
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            errors.append(f"Evaluation suite case at index {index} must be an object")
            continue
        shape_error = _validate_case_shape(EvaluationCase.from_dict(raw_case))
        if shape_error:
            errors.append(shape_error)
    return errors


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_case_shape(case: EvaluationCase) -> str | None:
    if case.type not in {"text_contains", "json_schema"}:
        return f"Unsupported evaluation case type: {case.type}"
    if not case.path:
        return f"Evaluation case {case.id} must define a path"
    if case.type == "text_contains":
        contains = case.expected.get("contains", [])
        if not isinstance(contains, list) or not contains:
            return f"Evaluation case {case.id} must define expected.contains"
    if case.type == "json_schema" and not case.expected.get("schema"):
        return f"Evaluation case {case.id} must define expected.schema"
    return None


def _match_json_schema(payload: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(payload, dict):
            return [f"{path} expected object"]
        required = schema.get("required", [])
        if isinstance(required, list):
            for field_name in required:
                if field_name not in payload:
                    errors.append(f"{path} missing required field '{field_name}'")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field_name, child_schema in properties.items():
                if field_name in payload and isinstance(child_schema, dict):
                    errors.extend(_match_json_schema(payload[field_name], child_schema, f"{path}.{field_name}"))
        additional_allowed = schema.get("additionalProperties", True)
        if additional_allowed is False and isinstance(properties, dict):
            extra_fields = sorted(set(payload.keys()) - set(properties.keys()))
            for field_name in extra_fields:
                errors.append(f"{path} has unexpected field '{field_name}'")
        return errors
    if expected_type == "array":
        if not isinstance(payload, list):
            return [f"{path} expected array"]
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(payload):
                errors.extend(_match_json_schema(item, item_schema, f"{path}[{index}]"))
        return errors
    primitive_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    if expected_type in primitive_map:
        expected_python = primitive_map[expected_type]
        if not isinstance(payload, expected_python) or (expected_type == "integer" and isinstance(payload, bool)):
            return [f"{path} expected {expected_type}"]
        return []
    if expected_type is None:
        return []
    return [f"{path} uses unsupported schema type '{expected_type}'"]


def _evaluate_text_contains(case: EvaluationCase, workspace: Path) -> EvaluationCaseResult:
    resolved, error = _resolve_workspace_path(workspace, case.path)
    if error:
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="failed", reason=error)
    if resolved is None or not resolved.is_file():
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="failed", reason="Evaluation target file is missing")
    content = _read_text_file(resolved)
    contains = [str(item) for item in case.expected.get("contains", [])]
    missing = [item for item in contains if item not in content]
    forbidden = [str(item) for item in case.expected.get("forbidden", []) if str(item) in content]
    regex_patterns = [str(item) for item in case.expected.get("regex", [])]
    regex_failures = [pattern for pattern in regex_patterns if re.search(pattern, content, re.MULTILINE) is None]
    if missing or forbidden or regex_failures:
        evidence = [*missing, *forbidden, *regex_failures]
        reason_parts = []
        if missing:
            reason_parts.append("missing required text")
        if forbidden:
            reason_parts.append("forbidden text present")
        if regex_failures:
            reason_parts.append("regex expectations not met")
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="failed", reason="; ".join(reason_parts), evidence=evidence)
    return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="passed", reason="Text output satisfied all expectations", evidence=[str(resolved)])


def _evaluate_json_schema(case: EvaluationCase, workspace: Path) -> EvaluationCaseResult:
    resolved, error = _resolve_workspace_path(workspace, case.path)
    if error:
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="failed", reason=error)
    if resolved is None or not resolved.is_file():
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="failed", reason="Evaluation target JSON file is missing")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    schema = case.expected.get("schema", {})
    if not isinstance(schema, dict):
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="invalid", reason="expected.schema must be an object")
    mismatches = _match_json_schema(payload, schema)
    if mismatches:
        return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="failed", reason="JSON schema expectations were not met", evidence=mismatches)
    return EvaluationCaseResult(case_id=case.id, case_type=case.type, status="passed", reason="JSON output matched the declared schema", evidence=[str(resolved)])


def default_evaluation_report_path(run_path: str | Path, suite_path: str | Path) -> Path:
    resolved_run = Path(run_path).resolve()
    resolved_suite = Path(suite_path).resolve()
    return resolved_run.parent / f"{resolved_run.stem}.{resolved_suite.stem}.evaluation-report.json"


def write_evaluation_report(
    result: EvaluationResult,
    output_path: str | Path | None = None,
) -> Path:
    report_path = Path(output_path) if output_path else default_evaluation_report_path(result.run_path, result.suite_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.report_written = str(report_path)
    report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report_path


def evaluate_run(
    run_path: str | Path,
    suite_path: str | Path,
    *,
    write_report: bool = False,
    report_path: str | Path | None = None,
    trace_path: str | Path | None = None,
) -> EvaluationResult:
    resolved_run_path = Path(run_path).resolve()
    resolved_suite_path = Path(suite_path).resolve()
    run = load_run(resolved_run_path)
    suite = load_evaluation_suite(resolved_suite_path)
    gating_errors = _validate_suite(run.run_id, suite)
    logger: EventLogger | None = None
    if trace_path:
        logger = EventLogger.create(output_path=trace_path, run_id=run.run_id)
    elif run.workspace.exists():
        logger = EventLogger.create(output_path=default_trace_path(run.workspace, "evaluation"), run_id=run.run_id)
    if logger:
        logger.emit("evaluation_started", suite_id=suite.suite_id, run_path=str(resolved_run_path), suite_path=str(resolved_suite_path))
    results: list[EvaluationCaseResult] = []
    if gating_errors:
        results = [
            EvaluationCaseResult(
                case_id=case.id,
                case_type=case.type,
                status="invalid",
                reason="Evaluation aborted because the suite envelope failed gating checks",
                evidence=gating_errors,
            )
            for case in suite.cases
        ]
    else:
        for case in suite.cases:
            case_error = _validate_case_shape(case)
            if case_error:
                result = EvaluationCaseResult(case_id=case.id, case_type=case.type, status="invalid", reason=case_error)
            elif case.type == "text_contains":
                result = _evaluate_text_contains(case, run.workspace)
            else:
                result = _evaluate_json_schema(case, run.workspace)
            results.append(result)
            if logger:
                logger.emit(
                    "evaluation_case_finished",
                    suite_id=suite.suite_id,
                    case_id=case.id,
                    case_type=case.type,
                    status=result.status,
                    reason=result.reason,
                    evidence=result.evidence,
                )
    evaluation_result = EvaluationResult(
        suite_id=suite.suite_id,
        run_id=run.run_id,
        run_path=resolved_run_path,
        suite_path=resolved_suite_path,
        results=results,
        evaluated_at=utc_now_iso(),
        tool_version=__version__,
        run_sha256=_sha256_file(resolved_run_path),
        suite_sha256=_sha256_file(resolved_suite_path),
        trace_path=str(logger.output_path) if logger else None,
        gating_errors=gating_errors,
    )
    if logger:
        logger.emit("evaluation_finished", suite_id=suite.suite_id, ok=evaluation_result.ok, summary=evaluation_result.summary)
    if write_report:
        write_evaluation_report(evaluation_result, output_path=report_path)
    return evaluation_result
