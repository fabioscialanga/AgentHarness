from __future__ import annotations

import hashlib
import json
import re
import shlex
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .models import Claim, ClaimResult, CommandArtifact, RunRecord
from .reexecution import ExecutionPolicy, ReexecutionResult, reexecute_command


SUPPORTED_CLAIM_TYPES = {
    "files_changed",
    "forbidden_paths",
    "tests_executed",
    "artifact_present",
    "schema_match",
}


def evaluate_claim(
    run: RunRecord,
    claim: Claim,
    *,
    execution_policy: ExecutionPolicy,
) -> ClaimResult:
    structural_error = _validate_claim_shape(claim)
    if structural_error:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="invalid",
            reason=structural_error,
        )

    if claim.type == "files_changed":
        return _check_files_changed(run, claim)
    if claim.type == "forbidden_paths":
        return _check_forbidden_paths(run, claim)
    if claim.type == "tests_executed":
        return _check_tests_executed(run, claim, execution_policy=execution_policy)
    if claim.type == "artifact_present":
        return _check_artifact_present(run, claim)
    if claim.type == "schema_match":
        return _check_schema_match(run, claim)

    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="invalid",
        reason=f"Unsupported claim type: {claim.type}",
    )


def _validate_claim_shape(claim: Claim) -> str | None:
    if not claim.id:
        return "Claim is missing required field 'id'"
    if not claim.statement.strip():
        return f"Claim {claim.id} is missing a non-empty statement"
    if claim.type not in SUPPORTED_CLAIM_TYPES:
        return f"Unsupported claim type: {claim.type}"

    if claim.type == "files_changed":
        allowed_paths = claim.expected.get("allowed_paths", [])
        if not allowed_paths:
            return f"Claim {claim.id} must define allowed_paths"
        return None

    if claim.type == "forbidden_paths":
        forbidden_paths = claim.expected.get("forbidden_paths", [])
        if not forbidden_paths:
            return f"Claim {claim.id} must define forbidden_paths"
        return None

    if claim.type == "tests_executed":
        required_commands = claim.expected.get("required_commands", [])
        required_command_patterns = claim.expected.get("required_command_patterns", [])
        if not required_commands and not required_command_patterns:
            return f"Claim {claim.id} must define required_commands or required_command_patterns"
        return None

    if claim.type == "artifact_present":
        required_outputs = claim.expected.get("required_outputs", [])
        if not required_outputs:
            return f"Claim {claim.id} must define required_outputs"
        return None

    if claim.type == "schema_match":
        output_path = claim.expected.get("output_path")
        schema = claim.expected.get("schema")
        if not output_path:
            return f"Claim {claim.id} must define output_path"
        if not schema:
            return f"Claim {claim.id} must define schema"
        return None

    return None


def _check_files_changed(run: RunRecord, claim: Claim) -> ClaimResult:
    allowed_paths = [str(item) for item in claim.expected.get("allowed_paths", [])]
    outside_scope = [
        path for path in run.changed_files
        if not any(fnmatch(path, pattern) for pattern in allowed_paths)
    ]

    if outside_scope:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason=(
                "Modified files fell outside allowed_paths: "
                + ", ".join(allowed_paths)
            ),
            evidence=outside_scope,
            truth_source="run-artifact",
        )
    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason="All changed files stayed within the declared allowed_paths",
        evidence=run.changed_files,
        truth_source="run-artifact",
    )


def _check_forbidden_paths(run: RunRecord, claim: Claim) -> ClaimResult:
    forbidden_paths = [str(item) for item in claim.expected.get("forbidden_paths", [])]
    forbidden_hits = [
        path for path in run.changed_files
        if any(fnmatch(path, pattern) for pattern in forbidden_paths)
    ]

    if forbidden_hits:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason=(
                "Modified files matched forbidden_paths: "
                + ", ".join(forbidden_paths)
            ),
            evidence=forbidden_hits,
            truth_source="run-artifact",
        )
    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason="No changed files matched the declared forbidden_paths",
        evidence=forbidden_paths,
        truth_source="run-artifact",
    )


def _normalized_pytest_command(command: str) -> tuple[str, ...] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    executable = Path(tokens[0]).name.lower()
    if executable in {"uv", "uv.exe"} and len(tokens) > 1 and tokens[1] == "run":
        tokens = tokens[2:]
        if not tokens:
            return None
        executable = Path(tokens[0]).name.lower()
    if executable in {"pytest", "pytest.exe"}:
        return ("pytest", *tokens[1:])
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable):
        if len(tokens) >= 3 and tokens[1:3] == ["-m", "pytest"]:
            return ("pytest", *tokens[3:])
    return None


def _commands_equivalent(required: str, executed: str) -> bool:
    if required == executed:
        return True
    required_pytest = _normalized_pytest_command(required)
    executed_pytest = _normalized_pytest_command(executed)
    return required_pytest is not None and required_pytest == executed_pytest


def _check_tests_executed(
    run: RunRecord,
    claim: Claim,
    *,
    execution_policy: ExecutionPolicy,
) -> ClaimResult:
    required_commands = [str(item) for item in claim.expected.get("required_commands", [])]
    required_command_patterns = [str(item) for item in claim.expected.get("required_command_patterns", [])]
    require_evidence_files = bool(claim.expected.get("require_evidence_files", True))
    command_list = list(run.commands)
    required_matches: list[CommandArtifact] = []
    missing: list[str] = []
    for required in required_commands:
        match = next((command for command in command_list if _commands_equivalent(required, command.cmd)), None)
        if match is None:
            missing.append(required)
        else:
            required_matches.append(match)
    missing_patterns = [
        pattern for pattern in required_command_patterns if not any(fnmatch(command.cmd, pattern) for command in command_list)
    ]
    if missing or missing_patterns:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Required command not found in run artifacts",
            evidence=[*missing, *missing_patterns],
            truth_source="run-artifact",
        )

    matched_commands: list[CommandArtifact] = list(required_matches)
    for pattern in required_command_patterns:
        for command in command_list:
            if fnmatch(command.cmd, pattern):
                matched_commands.append(command)
                break

    if not matched_commands:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="inconclusive",
            reason="Required command evidence could not be resolved",
            truth_source="none",
        )

    if not require_evidence_files:
        failed = [command.cmd for command in matched_commands if command.exit_code != 0]
        if failed:
            return ClaimResult(
                claim_id=claim.id,
                claim_type=claim.type,
                statement=claim.statement,
                status="unsupported",
                reason="Required command exited with a non-zero declared code",
                evidence=failed,
                truth_source="run-artifact",
            )
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="supported",
            reason="All required commands were found with a declared exit_code of 0 under relaxed proof mode",
            evidence=[item.cmd for item in matched_commands],
            truth_source="run-artifact",
        )

    command_results = [
        _verify_test_command_proof(run, command, execution_policy=execution_policy)
        for command in matched_commands
    ]
    return _merge_test_command_results(claim, command_results)


def _merge_test_command_results(claim: Claim, command_results: list[ClaimResult]) -> ClaimResult:
    if not command_results:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="inconclusive",
            reason="No test command results were produced",
            truth_source="none",
        )

    evidence: list[str] = []
    audit_commands: list[dict[str, Any]] = []
    truth_sources: list[str] = []
    statuses: list[str] = []
    reasons: list[str] = []
    for result in command_results:
        evidence.extend(result.evidence)
        audit_commands.append(result.audit)
        truth_sources.append(result.truth_source)
        statuses.append(result.status)
        reasons.append(result.reason)

    if any(status == "unsupported" for status in statuses):
        final_status = "unsupported"
    elif any(status == "inconclusive" for status in statuses):
        final_status = "inconclusive"
    else:
        final_status = "supported"

    final_truth_source = truth_sources[0] if len(set(truth_sources)) == 1 else "mixed"
    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status=final_status,
        reason="; ".join(reasons),
        evidence=evidence,
        truth_source=final_truth_source,
        audit={"commands": audit_commands},
    )


def _verify_test_command_proof(
    run: RunRecord,
    command: CommandArtifact,
    *,
    execution_policy: ExecutionPolicy,
) -> ClaimResult:
    if execution_policy.mode != "never":
        reexecution = reexecute_command(
            run.workspace,
            run.run_id,
            command.cmd,
            working_dir=command.working_dir,
            policy=execution_policy,
            environment=command.environment,
        )
        if reexecution.completed:
            return _claim_result_from_reexecution(command, reexecution)
        if not reexecution.allowed:
            return ClaimResult(
                claim_id=command.cmd,
                claim_type="tests_executed",
                statement=command.cmd,
                status="inconclusive",
                reason=reexecution.reason or "Command is not allowed by reexecution policy",
                evidence=reexecution.evidence_paths(),
                truth_source="none",
                audit={
                    "command": command.cmd,
                    "declared_exit_code": command.exit_code,
                    "reexecution": reexecution.to_dict(),
                },
            )
        parsed_result = _claim_result_from_parsed_evidence(run, command, reexecution=reexecution)
        if parsed_result is not None:
            return parsed_result
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="inconclusive",
            reason=reexecution.reason or "Reexecution did not establish a verdict and no usable evidence was available",
            evidence=reexecution.evidence_paths(),
            truth_source="none",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "reexecution": reexecution.to_dict(),
            },
        )

    parsed_result = _claim_result_from_parsed_evidence(run, command, reexecution=None)
    if parsed_result is not None:
        return parsed_result
    return ClaimResult(
        claim_id=command.cmd,
        claim_type="tests_executed",
        statement=command.cmd,
        status="inconclusive",
        reason="No usable parsed evidence was available for this command",
        truth_source="none",
        audit={
            "command": command.cmd,
            "declared_exit_code": command.exit_code,
        },
    )


def _claim_result_from_reexecution(command: CommandArtifact, reexecution: ReexecutionResult) -> ClaimResult:
    evidence_paths = reexecution.evidence_paths()
    exit_conflict = command.exit_code is not None and command.exit_code != reexecution.exit_code
    status = "supported" if reexecution.exit_code == 0 else "unsupported"
    reason = (
        "AgentHarness reexecuted the command and observed exit_code 0"
        if status == "supported"
        else f"AgentHarness reexecuted the command and observed exit_code {reexecution.exit_code}"
    )
    if exit_conflict:
        reason += (
            f"; environment_mismatch with declared exit_code {command.exit_code}, "
            "but reexecution evidence is authoritative"
        )
    truth_source = "reexecuted"
    return ClaimResult(
        claim_id=command.cmd,
        claim_type="tests_executed",
        statement=command.cmd,
        status=status,
        reason=reason,
        evidence=evidence_paths,
        truth_source=truth_source,
        audit={
            "command": command.cmd,
            "declared_exit_code": command.exit_code,
            "reexecution": reexecution.to_dict(),
            "evidence": reexecution.evidence_records(),
        },
    )


def _claim_result_from_parsed_evidence(
    run: RunRecord,
    command: CommandArtifact,
    *,
    reexecution: ReexecutionResult | None,
) -> ClaimResult | None:
    evidence_paths, evidence_errors = _collect_command_evidence(run.workspace, run.run_id, command)
    if evidence_errors and not evidence_paths:
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="inconclusive",
            reason="Evidence files were not available in a usable form for parsed verification",
            evidence=evidence_errors,
            truth_source="none",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "evidence_errors": evidence_errors,
            },
        )

    evidence_records: list[dict[str, Any]] = []
    content_error = False
    for path in evidence_paths:
        record, record_error = _read_evidence_record(Path(path))
        if record_error:
            content_error = True
            evidence_records.append({"path": path, "error": record_error})
            continue
        if record is None:
            content_error = True
            evidence_records.append({"path": path, "error": "unknown evidence read failure"})
            continue
        evidence_records.append(record)

    if content_error:
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="unsupported",
            reason="Evidence files existed but could not be read reliably",
            evidence=evidence_paths,
            truth_source="parsed-evidence",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "evidence": evidence_records,
            },
        )

    if not any(int(record.get("size_bytes", 0)) > 0 for record in evidence_records):
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="unsupported",
            reason="Evidence files existed but were empty, so they did not prove the claimed test outcome",
            evidence=evidence_paths,
            truth_source="parsed-evidence",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "evidence": evidence_records,
            },
        )

    parsed_verdict, parser_name, parser_reason = _parse_test_command_evidence(command, evidence_records)
    if parsed_verdict is None:
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="inconclusive",
            reason=parser_reason,
            evidence=evidence_paths,
            truth_source="parsed-evidence",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "parser": parser_name,
                "evidence": evidence_records,
            },
        )

    if command.exit_code is None:
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="inconclusive",
            reason="Evidence suggested an outcome, but the run artifact did not declare an exit_code to compare against",
            evidence=evidence_paths,
            truth_source="parsed-evidence",
            audit={
                "command": command.cmd,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "parser": parser_name,
                "parsed_verdict": parsed_verdict,
                "evidence": evidence_records,
            },
        )

    declared_verdict = "passed" if command.exit_code == 0 else "failed"
    if parsed_verdict != declared_verdict:
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="unsupported",
            reason=(
                f"Parsed evidence said the command {parsed_verdict}, but the run artifact declared exit_code {command.exit_code}"
            ),
            evidence=evidence_paths,
            truth_source="parsed-evidence",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "declared_verdict": declared_verdict,
                "parsed_verdict": parsed_verdict,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "parser": parser_name,
                "evidence": evidence_records,
            },
        )

    if parsed_verdict != "passed":
        return ClaimResult(
            claim_id=command.cmd,
            claim_type="tests_executed",
            statement=command.cmd,
            status="unsupported",
            reason="Parsed evidence showed that the required test command did not pass",
            evidence=evidence_paths,
            truth_source="parsed-evidence",
            audit={
                "command": command.cmd,
                "declared_exit_code": command.exit_code,
                "parsed_verdict": parsed_verdict,
                "reexecution": reexecution.to_dict() if reexecution else None,
                "parser": parser_name,
                "evidence": evidence_records,
            },
        )

    return ClaimResult(
        claim_id=command.cmd,
        claim_type="tests_executed",
        statement=command.cmd,
        status="supported",
        reason="Parsed evidence and declared exit_code both indicated a passing test command",
        evidence=evidence_paths,
        truth_source="parsed-evidence",
        audit={
            "command": command.cmd,
            "declared_exit_code": command.exit_code,
            "parsed_verdict": parsed_verdict,
            "reexecution": reexecution.to_dict() if reexecution else None,
            "parser": parser_name,
            "evidence": evidence_records,
        },
    )


def _check_artifact_present(run: RunRecord, claim: Claim) -> ClaimResult:
    required_outputs = [str(item) for item in claim.expected.get("required_outputs", [])]
    must_exist_on_disk = bool(claim.expected.get("must_exist_on_disk", True))
    produced_paths = {output.path for output in run.outputs}
    missing = [path for path in required_outputs if path not in produced_paths]
    if missing:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Required output not found in run artifacts",
            evidence=missing,
            truth_source="run-artifact",
        )

    scoped_paths: list[str] = []
    if must_exist_on_disk:
        missing_on_disk: list[str] = []
        for path in required_outputs:
            resolved_output_path, path_error = _resolve_workspace_path(run.workspace, path)
            if path_error:
                missing_on_disk.append(f"{path}: {path_error}")
                continue
            if resolved_output_path is None:
                missing_on_disk.append(f"{path}: could not resolve path inside workspace")
                continue
            if not resolved_output_path.is_file():
                missing_on_disk.append(str(resolved_output_path))
                continue
            scoped_paths.append(str(resolved_output_path))
        if missing_on_disk:
            return ClaimResult(
                claim_id=claim.id,
                claim_type=claim.type,
                statement=claim.statement,
                status="unsupported",
                reason="Required output was declared in run artifacts but is missing on disk or outside workspace scope",
                evidence=missing_on_disk,
                truth_source="filesystem",
            )

    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason=(
            "All required outputs were found in run artifacts"
            if not must_exist_on_disk
            else "All required outputs were found in run artifacts and exist on disk"
        ),
        evidence=scoped_paths or required_outputs,
        truth_source="filesystem" if must_exist_on_disk else "run-artifact",
    )


def _check_schema_match(run: RunRecord, claim: Claim) -> ClaimResult:
    output_path = str(claim.expected.get("output_path"))
    schema = claim.expected.get("schema", {})
    produced_paths = {output.path for output in run.outputs}
    if output_path not in produced_paths:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Schema target file was not declared in run outputs",
            evidence=[output_path],
            truth_source="run-artifact",
        )

    resolved_output_path, path_error = _resolve_workspace_path(run.workspace, output_path)
    if path_error:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason=f"Schema target path is outside workspace scope: {path_error}",
            evidence=[output_path],
            truth_source="filesystem",
        )
    if resolved_output_path is None:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Schema target path could not be resolved inside the workspace",
            evidence=[output_path],
            truth_source="filesystem",
        )

    if not resolved_output_path.is_file():
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Schema target file not found",
            evidence=[str(resolved_output_path)],
            truth_source="filesystem",
        )

    try:
        payload = _load_structured_document(resolved_output_path)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason=f"Could not parse schema target file: {exc}",
            evidence=[str(resolved_output_path)],
            truth_source="filesystem",
        )

    mismatch = _match_schema(payload, schema, path="$")
    if mismatch is not None:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason=f"Schema mismatch: {mismatch}",
            evidence=[str(resolved_output_path)],
            truth_source="filesystem",
        )

    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason="Structured output matched the declared schema",
        evidence=[str(resolved_output_path)],
        truth_source="filesystem",
    )


def _collect_command_evidence(
    workspace: Path,
    run_id: str,
    command: CommandArtifact,
) -> tuple[list[str], list[str]]:
    evidence_candidates = [path for path in (command.stdout_path, command.stderr_path) if path]
    if not evidence_candidates:
        return [], [f"{command.cmd}: no stdout_path/stderr_path provided"]

    evidence_root = (workspace.resolve() / ".agentharness" / "evidence" / run_id).resolve()
    evidence_namespace_root = (workspace.resolve() / ".agentharness" / "evidence").resolve()
    try:
        evidence_root.relative_to(evidence_namespace_root)
    except ValueError:
        return [], [
            f"{command.cmd}: reserved run evidence directory escapes the evidence namespace {evidence_namespace_root}"
        ]

    evidence_paths: list[str] = []
    errors: list[str] = []
    for candidate in evidence_candidates:
        resolved_path, path_error = _resolve_workspace_path(workspace, candidate)
        if path_error:
            errors.append(f"{command.cmd}: {candidate} ({path_error})")
            continue
        if resolved_path is None:
            errors.append(f"{command.cmd}: {candidate} (could not be resolved)")
            continue
        if not resolved_path.is_file():
            errors.append(f"{command.cmd}: {resolved_path} (missing file)")
            continue
        try:
            resolved_path.relative_to(evidence_root)
        except ValueError:
            errors.append(
                f"{command.cmd}: {resolved_path} (not under reserved run evidence directory {evidence_root})"
            )
            continue
        evidence_paths.append(str(resolved_path))

    return evidence_paths, errors


def _resolve_workspace_path(workspace: Path, artifact_path: str) -> tuple[Path | None, str | None]:
    candidate = Path(artifact_path)
    if candidate.is_absolute():
        return None, "absolute paths are not allowed"

    resolved_workspace = workspace.resolve()
    resolved_candidate = (resolved_workspace / candidate).resolve()
    try:
        resolved_candidate.relative_to(resolved_workspace)
    except ValueError:
        return None, "path escapes the declared workspace"
    return resolved_candidate, None


def _read_evidence_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, str(exc)

    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "content": content,
    }, None


def _parse_test_command_evidence(
    command: CommandArtifact,
    evidence_records: list[dict[str, Any]],
) -> tuple[str | None, str, str]:
    combined = "\n".join(str(record.get("content", "")) for record in evidence_records)
    if not combined.strip():
        return None, "empty-evidence", "Evidence files were present but empty"

    if "pytest" in command.cmd:
        lower = combined.lower()
        if re.search(r"=+ .*?\b(\d+) failed\b", lower) or " failed" in lower or " errors" in lower or "traceback" in lower:
            return "failed", "pytest-summary", "Parsed pytest-style evidence indicated a failing command"
        if re.search(r"=+ .*?\b(\d+) passed\b", lower) or re.search(r"\bpassed in\b", lower):
            return "passed", "pytest-summary", "Parsed pytest-style evidence indicated a passing command"
        return None, "pytest-summary", "Parsed pytest-style evidence could not determine a stable verdict"

    return None, "unsupported-parser", "No parsed-evidence parser is available for this command"


def _load_structured_document(path: Path) -> Any:
    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(content)
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    raise ValueError(f"Unsupported schema_match file type: {suffix or '<no suffix>'}")


def _match_schema(value: Any, schema: dict[str, Any], *, path: str) -> str | None:
    expected_type = schema.get("type")
    if expected_type:
        type_error = _check_type(value, expected_type, path)
        if type_error:
            return type_error

    if expected_type == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for key in required:
            if not isinstance(value, dict) or key not in value:
                return f"{path} is missing required key '{key}'"

        if isinstance(value, dict):
            for key, nested_schema in properties.items():
                if key in value:
                    mismatch = _match_schema(value[key], nested_schema, path=f"{path}.{key}")
                    if mismatch:
                        return mismatch

    if expected_type == "array" and "items" in schema:
        if not isinstance(value, list):
            return f"{path} expected type array but found {type(value).__name__}"
        item_schema = schema["items"]
        for index, item in enumerate(value):
            mismatch = _match_schema(item, item_schema, path=f"{path}[{index}]")
            if mismatch:
                return mismatch

    if "const" in schema and value != schema["const"]:
        return f"{path} expected const value {schema['const']!r} but found {value!r}"

    return None


def _check_type(value: Any, expected_type: str, path: str) -> str | None:
    type_checks: dict[str, tuple[type[Any], ...]] = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "boolean": (bool,),
        "integer": (int,),
        "number": (int, float),
    }
    expected_python_types = type_checks.get(expected_type)
    if expected_python_types is None:
        return f"{path} uses unsupported schema type '{expected_type}'"

    if expected_type == "integer" and isinstance(value, bool):
        return f"{path} expected type integer but found bool"
    if expected_type == "number" and isinstance(value, bool):
        return f"{path} expected type number but found bool"
    if not isinstance(value, expected_python_types):
        return f"{path} expected type {expected_type} but found {type(value).__name__}"
    return None
