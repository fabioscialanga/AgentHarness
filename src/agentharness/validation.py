from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SLUG_RE = re.compile(r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")

WORKFLOW_FILE_MAP = {
    "create-feature": "workflows/create-feature.md",
    "fix-bug": "workflows/fix-bug.md",
    "refactor-module": "workflows/refactor-module.md",
    "add-tests": "workflows/add-tests.md",
}

DELIVERABLE_RULES = {
    "agents_md": lambda root: _file_exists(root / "AGENTS.md"),
    "architecture_summary": lambda root: _file_exists(root / "docs/ARCHITECTURE_SUMMARY.md"),
    "delivery_model": lambda root: _file_exists(root / "docs/DELIVERY_MODEL.md"),
    "workflows": lambda root: _dir_has_files(root / "workflows", "*.md"),
    "checklists": lambda root: _dir_has_files(root / "checklists", "*.md"),
    "test_bootstrap": lambda root: all(
        _file_exists(root / rel)
        for rel in (
            "tests/unit/README.md",
            "tests/integration/README.md",
            "tests/regression/README.md",
        )
    ),
    "policy_files": lambda root: _dir_has_files(root / "policies", "*.yaml"),
}


@dataclass
class ValidationResult:
    project_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "notes": self.notes,
        }


class ValidationError(Exception):
    pass


def _file_exists(path: Path) -> bool:
    return path.is_file()


def _dir_has_files(path: Path, pattern: str) -> bool:
    return path.is_dir() and any(path.glob(pattern))


def _expect_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"'{field_name}' must be a mapping/object")
    return value


def _expect_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"'{field_name}' must be a list")
    return value


def _require_str(data: dict[str, Any], field_name: str, result: ValidationResult) -> str | None:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        result.errors.append(f"Missing or invalid string field: {field_name}")
        return None
    return value


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_required_top_level(data: dict[str, Any], result: ValidationResult) -> None:
    for field_name in (
        "project_name",
        "project_slug",
        "project_type",
        "stack",
        "modules",
        "testing",
        "quality",
        "security",
        "agent_policy",
        "deliverables",
        "workflows_enabled",
    ):
        if field_name not in data:
            result.errors.append(f"Missing required top-level field: {field_name}")


def _validate_slug(data: dict[str, Any], result: ValidationResult) -> None:
    slug = _require_str(data, "project_slug", result)
    if slug and not SLUG_RE.fullmatch(slug):
        result.errors.append(
            "project_slug must use lowercase letters, digits, hyphens, or underscores"
        )


def _validate_stack(data: dict[str, Any], result: ValidationResult) -> None:
    stack = data.get("stack")
    try:
        stack = _expect_mapping(stack, "stack")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    for field_name in ("language", "framework", "database", "package_manager", "api_style"):
        value = stack.get(field_name)
        if not isinstance(value, str) or not value.strip():
            result.errors.append(f"stack.{field_name} is required and must be a non-empty string")


def _validate_modules(data: dict[str, Any], result: ValidationResult) -> None:
    modules = data.get("modules")
    try:
        modules = _expect_list(modules, "modules")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    if not modules:
        result.errors.append("modules must contain at least one module name")
        return

    bad = [module for module in modules if not isinstance(module, str) or not module.strip()]
    if bad:
        result.errors.append("modules must contain only non-empty strings")


def _validate_testing(data: dict[str, Any], result: ValidationResult) -> None:
    testing = data.get("testing")
    try:
        testing = _expect_mapping(testing, "testing")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    framework = testing.get("framework")
    if not isinstance(framework, str) or not framework.strip():
        result.errors.append("testing.framework is required and must be a non-empty string")

    minimum = testing.get("minimum")
    if minimum is not None:
        try:
            minimum = _expect_list(minimum, "testing.minimum")
        except ValidationError as exc:
            result.errors.append(str(exc))
            minimum = []
        if any(not isinstance(item, str) or not item.strip() for item in minimum):
            result.errors.append("testing.minimum must contain only non-empty strings")


def _validate_quality(data: dict[str, Any], result: ValidationResult) -> None:
    quality = data.get("quality")
    try:
        quality = _expect_mapping(quality, "quality")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    required_checks = quality.get("required_checks")
    try:
        required_checks = _expect_list(required_checks, "quality.required_checks")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    required_set = set(required_checks)
    expected = set()
    if quality.get("format"):
        expected.add("format")
    if quality.get("lint"):
        expected.add("lint")
    if quality.get("type_check"):
        expected.add("type_check")
    expected.add("unit_tests")
    expected.add("no_hardcoded_secrets")

    missing = sorted(expected - required_set)
    if missing:
        result.errors.append(
            f"quality.required_checks is missing expected checks: {', '.join(missing)}"
        )


def _validate_security(data: dict[str, Any], result: ValidationResult) -> None:
    security = data.get("security")
    try:
        security = _expect_mapping(security, "security")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    required_checks = security.get("required_checks")
    try:
        required_checks = _expect_list(required_checks, "security.required_checks")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    if security.get("secrets_policy") != "env_only":
        result.warnings.append("security.secrets_policy is not 'env_only'")

    required_set = set(required_checks)
    for check in (
        "no_hardcoded_secrets",
        "dependency_scan",
        "input_validation",
        "safe_logging",
    ):
        if check not in required_set:
            result.errors.append(f"security.required_checks must include '{check}'")

    if security.get("upload_validation_required") and "upload_constraints" not in required_set:
        result.errors.append(
            "security.required_checks must include 'upload_constraints' when upload_validation_required is true"
        )


def _validate_agent_policy(data: dict[str, Any], result: ValidationResult) -> None:
    policy = data.get("agent_policy")
    try:
        policy = _expect_mapping(policy, "agent_policy")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    autonomy = policy.get("autonomy")
    if autonomy not in {"low", "medium", "high"}:
        result.errors.append("agent_policy.autonomy must be one of: low, medium, high")

    review_model = policy.get("review_model")
    if review_model is not None and review_model not in {"human-reviewed", "agent-autonomous"}:
        result.errors.append("agent_policy.review_model must be either 'human-reviewed' or 'agent-autonomous'")

    for bool_field in ("allow_db_writes", "allow_schema_changes"):
        value = policy.get(bool_field)
        if value is not None and not isinstance(value, bool):
            result.errors.append(f"agent_policy.{bool_field} must be a boolean when provided")

    max_files_per_task = policy.get("max_files_per_task")
    if max_files_per_task is not None and (not isinstance(max_files_per_task, int) or max_files_per_task <= 0):
        result.errors.append("agent_policy.max_files_per_task must be a positive integer when provided")

    for list_field in ("allowed_tools", "forbidden_actions", "review_required_for"):
        try:
            values = _expect_list(policy.get(list_field), f"agent_policy.{list_field}")
        except ValidationError as exc:
            result.errors.append(str(exc))
            continue
        if not values:
            result.errors.append(f"agent_policy.{list_field} must not be empty")
        elif any(not isinstance(item, str) or not item.strip() for item in values):
            result.errors.append(f"agent_policy.{list_field} must contain only non-empty strings")


def _validate_workflows(root: Path, data: dict[str, Any], result: ValidationResult) -> None:
    workflows = data.get("workflows_enabled")
    try:
        workflows = _expect_list(workflows, "workflows_enabled")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    for workflow_name in workflows:
        if not isinstance(workflow_name, str) or not workflow_name.strip():
            result.errors.append("workflows_enabled must contain only non-empty strings")
            continue
        workflow_path = WORKFLOW_FILE_MAP.get(workflow_name)
        if workflow_path is None:
            result.warnings.append(f"Unknown workflow '{workflow_name}' has no built-in file mapping")
            continue
        if not _file_exists(root / workflow_path):
            result.errors.append(
                f"Enabled workflow '{workflow_name}' is missing file: {workflow_path}"
            )


def _validate_deliverables(root: Path, data: dict[str, Any], result: ValidationResult) -> None:
    deliverables = data.get("deliverables")
    try:
        deliverables = _expect_mapping(deliverables, "deliverables")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    generate = deliverables.get("generate")
    try:
        generate = _expect_list(generate, "deliverables.generate")
    except ValidationError as exc:
        result.errors.append(str(exc))
        return

    for item in generate:
        if not isinstance(item, str) or not item.strip():
            result.errors.append("deliverables.generate must contain only non-empty strings")
            continue
        rule = DELIVERABLE_RULES.get(item)
        if rule is None:
            result.warnings.append(f"Unknown deliverable '{item}' has no built-in validation rule")
            continue
        if not rule(root):
            result.errors.append(f"Deliverable '{item}' is declared but matching files are missing")


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _validate_agents_contract(root: Path, data: dict[str, Any], result: ValidationResult) -> None:
    agents_path = root / "AGENTS.md"
    if not agents_path.is_file():
        return

    content = agents_path.read_text(encoding="utf-8")
    normalized = content.lower()
    section_requirements = {
        "project identity": "AGENTS.md must include a 'Project identity' section",
        "core rules": "AGENTS.md must include a 'Core rules' section",
        "quality gates": "AGENTS.md must include a 'Quality gates' section",
        "security rules": "AGENTS.md must include a 'Security rules' section",
        "risk boundaries": "AGENTS.md must include a 'Risk boundaries' section",
        "working style": "AGENTS.md must include a 'Working style' section",
    }
    for marker, error in section_requirements.items():
        if marker not in normalized:
            result.errors.append(error)

    bullet_count = sum(1 for line in content.splitlines() if line.strip().startswith(("-", "*")))
    if bullet_count < 12:
        result.errors.append(
            "AGENTS.md is too thin to act as an operational contract; add more explicit rules, gates, and boundaries"
        )

    project_name = str(data.get("project_name", "")).strip().lower()
    project_slug = str(data.get("project_slug", "")).strip().lower()
    if project_name and project_name not in normalized and project_slug and project_slug not in normalized:
        result.errors.append("AGENTS.md must reference the project identity from project.yaml")

    testing = data.get("testing", {})
    if isinstance(testing, dict) and testing.get("bugfix_requires_regression_test") and "regression test" not in normalized:
        result.errors.append(
            "AGENTS.md must mention regression-test expectations when testing.bugfix_requires_regression_test is true"
        )

    quality = data.get("quality", {})
    if isinstance(quality, dict):
        required_quality_phrases = {
            "format": quality.get("format"),
            "lint": quality.get("lint"),
            "type": quality.get("type_check"),
        }
        for phrase, enabled in required_quality_phrases.items():
            if enabled and phrase not in normalized:
                result.errors.append(
                    f"AGENTS.md quality gates must mention '{phrase}' because it is required in project.yaml"
                )

    security = data.get("security", {})
    if isinstance(security, dict):
        if security.get("upload_validation_required") and "upload" not in normalized:
            result.errors.append(
                "AGENTS.md must mention upload constraints because security.upload_validation_required is true"
            )
        if security.get("pii_present") and not _contains_any(normalized, ("pii", "personal data", "contact data", "sensitive data")):
            result.errors.append(
                "AGENTS.md must mention handling of sensitive or personal data because security.pii_present is true"
            )

    policy = data.get("agent_policy", {})
    if isinstance(policy, dict):
        autonomy = policy.get("autonomy")
        if autonomy == "low" and not _contains_any(normalized, ("human review required", "require human review", "human-reviewed")):
            result.errors.append(
                "AGENTS.md must make human review explicit when agent_policy.autonomy is low"
            )

        expected_reviews = {
            "auth_changes": ("auth", "permission"),
            "dependency_changes": ("dependency",),
            "ci_pipeline_changes": ("ci", "pipeline"),
            "upload_handling_changes": ("upload",),
            "audit_model_changes": ("audit",),
        }
        review_required_for = policy.get("review_required_for", [])
        if isinstance(review_required_for, list):
            for item in review_required_for:
                if not isinstance(item, str):
                    continue
                keywords = expected_reviews.get(item)
                if keywords and not _contains_any(normalized, keywords):
                    result.errors.append(
                        f"AGENTS.md risk boundaries must reflect review_required_for item '{item}' from project.yaml"
                    )

        expected_forbidden = {
            "disable_auth": ("auth", "permission"),
            "remove_audit_logging": ("audit",),
            "disable_input_validation": ("input validation", "validate all user-controlled inputs"),
        }
        forbidden_actions = policy.get("forbidden_actions", [])
        if isinstance(forbidden_actions, list):
            for item in forbidden_actions:
                if not isinstance(item, str):
                    continue
                keywords = expected_forbidden.get(item)
                if keywords and not _contains_any(normalized, keywords):
                    result.errors.append(
                        f"AGENTS.md core or security rules must reflect forbidden action '{item}' from project.yaml"
                    )


def _validate_framework_outputs(root: Path, data: dict[str, Any], result: ValidationResult) -> None:
    required_checks_path = root / ".framework/required-checks.json"
    if required_checks_path.is_file():
        try:
            payload = _load_json(required_checks_path)
        except Exception as exc:  # pragma: no cover - defensive
            result.errors.append(f"Could not parse .framework/required-checks.json: {exc}")
            payload = None
        if isinstance(payload, dict):
            generated_checks = payload.get("required_checks")
            if isinstance(generated_checks, list):
                generated_set = set(item for item in generated_checks if isinstance(item, str))
                quality_checks = set(data.get("quality", {}).get("required_checks", []))
                security_checks = set(data.get("security", {}).get("required_checks", []))
                testing_checks = set()
                minimum = data.get("testing", {}).get("minimum", [])
                if isinstance(minimum, list) and "integration_smoke" in minimum:
                    testing_checks.add("integration_smoke")
                expected = quality_checks | security_checks | testing_checks
                missing = sorted(expected - generated_set)
                if missing:
                    result.errors.append(
                        ".framework/required-checks.json is missing checks declared in project.yaml: "
                        + ", ".join(missing)
                    )
            else:
                result.errors.append(".framework/required-checks.json must contain a list field 'required_checks'")

    risk_matrix_path = root / ".framework/risk-matrix.yaml"
    if risk_matrix_path.is_file():
        try:
            risk_matrix = _load_yaml(risk_matrix_path)
        except Exception as exc:  # pragma: no cover - defensive
            result.errors.append(f"Could not parse .framework/risk-matrix.yaml: {exc}")
            risk_matrix = None
        if isinstance(risk_matrix, dict):
            for level in ("low", "medium", "high"):
                if level not in risk_matrix:
                    result.errors.append(f".framework/risk-matrix.yaml is missing level '{level}'")
            project_profile = risk_matrix.get("meta", {}).get("project_profile", {}) if isinstance(risk_matrix.get("meta"), dict) else {}
            if not isinstance(project_profile, dict) or project_profile.get("overall_risk") not in {"low", "medium", "high"}:
                result.errors.append(
                    ".framework/risk-matrix.yaml must include meta.project_profile.overall_risk derived from project.yaml"
                )
        else:
            result.errors.append(".framework/risk-matrix.yaml must be a mapping")


def validate_project_directory(project_dir: str | Path) -> ValidationResult:
    root = Path(project_dir).resolve()
    result = ValidationResult(project_dir=root)

    if not root.exists() or not root.is_dir():
        result.errors.append(f"Project directory does not exist: {root}")
        return result

    project_yaml_path = root / "project.yaml"
    if not project_yaml_path.is_file():
        result.errors.append(f"Missing required file: {project_yaml_path}")
        return result

    for required_file in ("PROJECT.md", "README.md", "AGENTS.md"):
        if not _file_exists(root / required_file):
            result.errors.append(f"Missing required file: {required_file}")

    try:
        payload = _load_yaml(project_yaml_path)
    except Exception as exc:
        result.errors.append(f"Could not parse project.yaml: {exc}")
        return result

    if not isinstance(payload, dict):
        result.errors.append("project.yaml must parse to a mapping/object")
        return result

    _validate_required_top_level(payload, result)
    _validate_slug(payload, result)
    _validate_stack(payload, result)
    _validate_modules(payload, result)
    _validate_testing(payload, result)
    _validate_quality(payload, result)
    _validate_security(payload, result)
    _validate_agent_policy(payload, result)
    _validate_workflows(root, payload, result)
    _validate_deliverables(root, payload, result)
    _validate_agents_contract(root, payload, result)
    _validate_framework_outputs(root, payload, result)

    if result.ok:
        result.notes.append("Project definition passed all built-in AgentHarness validation checks")
    else:
        result.notes.append("Project definition failed one or more built-in AgentHarness validation checks")

    return result
