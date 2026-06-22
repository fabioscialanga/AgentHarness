from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from .models import Claim, ClaimResult, CommandArtifact, RunRecord


SUPPORTED_CLAIM_TYPES = {
    "files_changed",
    "forbidden_paths",
    "tests_executed",
    "artifact_present",
    "schema_match",
}


def evaluate_claim(run: RunRecord, claim: Claim) -> ClaimResult:
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
        return _check_tests_executed(run, claim)
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
        )
    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason="All changed files stayed within the declared allowed_paths",
        evidence=run.changed_files,
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
        )
    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason="No changed files matched the declared forbidden_paths",
        evidence=forbidden_paths,
    )


def _check_tests_executed(run: RunRecord, claim: Claim) -> ClaimResult:
    required_commands = [str(item) for item in claim.expected.get("required_commands", [])]
    required_command_patterns = [str(item) for item in claim.expected.get("required_command_patterns", [])]
    require_evidence_files = bool(claim.expected.get("require_evidence_files", False))
    executed_commands = {command.cmd: command for command in run.commands}
    command_list = list(run.commands)

    missing = [command for command in required_commands if command not in executed_commands]
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
        )

    failed = [command for command in required_commands if executed_commands[command].exit_code != 0]
    failed_patterns = [
        pattern
        for pattern in required_command_patterns
        if not any(fnmatch(command.cmd, pattern) and command.exit_code == 0 for command in command_list)
    ]
    if failed or failed_patterns:
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Required command exited with a non-zero code",
            evidence=[*failed, *failed_patterns],
        )

    matched_commands: list[CommandArtifact] = [executed_commands[command] for command in required_commands]
    for pattern in required_command_patterns:
        for command in command_list:
            if fnmatch(command.cmd, pattern) and command.exit_code == 0:
                matched_commands.append(command)
                break

    evidence_paths: list[str] = []
    if require_evidence_files:
        if not matched_commands:
            return ClaimResult(
                claim_id=claim.id,
                claim_type=claim.type,
                statement=claim.statement,
                status="unsupported",
                reason="Required command evidence could not be resolved",
            )

        evidence_errors: list[str] = []
        for command in matched_commands:
            command_evidence, command_errors = _collect_command_evidence(
                run.workspace,
                run.run_id,
                command,
            )
            evidence_paths.extend(command_evidence)
            evidence_errors.extend(command_errors)

        if evidence_errors:
            return ClaimResult(
                claim_id=claim.id,
                claim_type=claim.type,
                statement=claim.statement,
                status="unsupported",
                reason="Required command evidence is missing or out of workspace scope",
                evidence=evidence_errors,
            )

    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason=(
            "All required commands were found with exit_code 0"
            if not require_evidence_files
            else "All required commands were found with exit_code 0 and persisted evidence files"
        ),
        evidence=evidence_paths or [*required_commands, *required_command_patterns],
    )


def _check_artifact_present(run: RunRecord, claim: Claim) -> ClaimResult:
    required_outputs = [str(item) for item in claim.expected.get("required_outputs", [])]
    must_exist_on_disk = bool(claim.expected.get("must_exist_on_disk", False))
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
        )

    scoped_paths: list[str] = []
    if must_exist_on_disk:
        missing_on_disk: list[str] = []
        for path in required_outputs:
            resolved_output_path, path_error = _resolve_workspace_path(run.workspace, path)
            if path_error:
                missing_on_disk.append(f"{path}: {path_error}")
                continue
            assert resolved_output_path is not None
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
        )
    assert resolved_output_path is not None

    if not resolved_output_path.is_file():
        return ClaimResult(
            claim_id=claim.id,
            claim_type=claim.type,
            statement=claim.statement,
            status="unsupported",
            reason="Schema target file not found",
            evidence=[str(resolved_output_path)],
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
        )

    return ClaimResult(
        claim_id=claim.id,
        claim_type=claim.type,
        statement=claim.statement,
        status="supported",
        reason="Structured output matched the declared schema",
        evidence=[str(resolved_output_path)],
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
        assert candidate is not None
        resolved_path, path_error = _resolve_workspace_path(workspace, candidate)
        if path_error:
            errors.append(f"{command.cmd}: {candidate} ({path_error})")
            continue
        assert resolved_path is not None
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

    if not evidence_paths:
        return [], errors
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
        assert isinstance(value, list)
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
