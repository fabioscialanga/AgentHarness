from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class GenerationResult:
    project_dir: Path
    files_written: list[str]
    generated_checks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "files_written": self.files_written,
            "generated_checks": self.generated_checks,
        }


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("project.yaml must parse to an object")
    return payload


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _collect_required_checks(payload: dict[str, Any]) -> list[str]:
    checks: list[str] = []

    quality = payload.get("quality", {})
    if isinstance(quality, dict):
        quality_checks = quality.get("required_checks", [])
        if isinstance(quality_checks, list):
            checks.extend(item for item in quality_checks if isinstance(item, str) and item.strip())

    security = payload.get("security", {})
    if isinstance(security, dict):
        security_checks = security.get("required_checks", [])
        if isinstance(security_checks, list):
            checks.extend(item for item in security_checks if isinstance(item, str) and item.strip())

    testing = payload.get("testing", {})
    if isinstance(testing, dict):
        minimum = testing.get("minimum", [])
        if isinstance(minimum, list):
            for item in minimum:
                if not isinstance(item, str) or not item.strip():
                    continue
                if item == "unit":
                    checks.append("unit_tests")
                else:
                    checks.append(item)

    observability = payload.get("observability", {})
    if isinstance(observability, dict) and observability.get("emit_jsonl_traces"):
        checks.append("structured_traces")

    evaluation = payload.get("evaluation", {})
    if isinstance(evaluation, dict) and evaluation.get("enabled"):
        checks.append("evaluation_suite")

    return _dedupe(checks)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _build_risk_matrix(payload: dict[str, Any]) -> dict[str, Any]:
    security = payload.get("security", {}) if isinstance(payload.get("security"), dict) else {}
    policy = payload.get("agent_policy", {}) if isinstance(payload.get("agent_policy"), dict) else {}
    testing = payload.get("testing", {}) if isinstance(payload.get("testing"), dict) else {}
    observability = payload.get("observability", {}) if isinstance(payload.get("observability"), dict) else {}
    resilience = payload.get("resilience", {}) if isinstance(payload.get("resilience"), dict) else {}
    evaluation = payload.get("evaluation", {}) if isinstance(payload.get("evaluation"), dict) else {}

    autonomy = str(policy.get("autonomy", "medium"))
    security_level = str(security.get("level", "medium"))
    pii_present = _coerce_bool(security.get("pii_present"), False)
    upload_validation_required = _coerce_bool(security.get("upload_validation_required"), False)
    review_required_for = [item for item in policy.get("review_required_for", []) if isinstance(item, str) and item.strip()]
    forbidden_actions = [item for item in policy.get("forbidden_actions", []) if isinstance(item, str) and item.strip()]
    testing_minimum = [item for item in testing.get("minimum", []) if isinstance(item, str) and item.strip()]

    review_model = str(policy.get("review_model") or ("human-reviewed" if review_required_for else "agent-autonomous"))
    allow_db_writes = _coerce_bool(policy.get("allow_db_writes"), False)
    allow_schema_changes = _coerce_bool(policy.get("allow_schema_changes"), False)
    max_files_per_task = policy.get("max_files_per_task")

    score = 0
    score += {"low": 0, "medium": 1, "high": 2}.get(autonomy, 1)
    score += {"low": 0, "medium": 1, "high": 2}.get(security_level, 1)
    score += 1 if pii_present else 0
    score += 1 if upload_validation_required else 0
    score += 1 if allow_db_writes else 0
    score += 1 if allow_schema_changes else 0
    score += 1 if review_model == "agent-autonomous" else 0
    score += 1 if len(review_required_for) >= 4 else 0
    score += 1 if "integration_smoke" in testing_minimum else 0

    if score >= 6:
        overall_risk = "high"
    elif score >= 3:
        overall_risk = "medium"
    else:
        overall_risk = "low"

    low_autonomy = "high" if autonomy == "high" and overall_risk == "low" else "medium"
    medium_autonomy = "low" if overall_risk == "high" else autonomy
    high_autonomy = "low"

    high_triggers = _dedupe(
        [
            *review_required_for,
            *( ["handles_pii"] if pii_present else []),
            *( ["upload_surface"] if upload_validation_required else []),
            *( ["db_writes_enabled"] if allow_db_writes else []),
            *( ["schema_changes_enabled"] if allow_schema_changes else []),
            *( ["autonomous_review_model"] if review_model == "agent-autonomous" else []),
        ]
    )

    medium_checks = _dedupe(
        [
            "unit_tests",
            *( ["integration_smoke"] if "integration_smoke" in testing_minimum else []),
            *( ["input_validation"] if upload_validation_required else []),
            *( ["safe_logging"] if pii_present else []),
        ]
    )

    return {
        "meta": {
            "project_profile": {
                "overall_risk": overall_risk,
                "autonomy": autonomy,
                "review_model": review_model,
                "security_level": security_level,
                "pii_present": pii_present,
                "upload_validation_required": upload_validation_required,
                "allow_db_writes": allow_db_writes,
                "allow_schema_changes": allow_schema_changes,
                "max_files_per_task": max_files_per_task,
                "review_required_for": review_required_for,
                "forbidden_actions": forbidden_actions,
                "structured_logging": str(observability.get("logging_format", "json")),
                "jsonl_traces_enabled": _coerce_bool(observability.get("emit_jsonl_traces"), False),
                "default_retry_attempts": resilience.get("retry_defaults", {}).get("max_attempts") if isinstance(resilience.get("retry_defaults"), dict) else None,
                "fallback_chain": resilience.get("fallback_defaults", {}).get("fallback_chain", []) if isinstance(resilience.get("fallback_defaults"), dict) else [],
                "evaluation_enabled": _coerce_bool(evaluation.get("enabled"), False),
            },
            "derivation_notes": [
                "Risk matrix is derived from project.yaml security, testing, and agent_policy declarations.",
                "Changing autonomy, review model, review boundaries, or dangerous write permissions changes this file deterministically.",
            ],
        },
        "low": {
            "examples": ["docs_update", "local_refactor", "add_tests"],
            "autonomy": low_autonomy,
            "human_review_required": False,
            "focus": ["readability", "small diff", "preserve required checks"],
        },
        "medium": {
            "examples": ["endpoint_change", "validation_change", "notification_change"],
            "autonomy": medium_autonomy,
            "human_review_required": overall_risk != "low" or bool(review_required_for),
            "required_checks": medium_checks,
        },
        "high": {
            "examples": ["auth_change", "upload_change", "audit_model_change", "dependency_change"],
            "autonomy": high_autonomy,
            "human_review_required": True,
            "extra_checks": ["security_review_checklist", "human_approval"],
            "review_triggers": high_triggers,
        },
    }


def _build_generation_report(payload: dict[str, Any], generated_checks: list[str]) -> dict[str, Any]:
    project_name = payload.get("project_name", "unknown")
    generated_artifacts = [
        "README.md",
        "PROJECT.md",
        "project.yaml",
        "AGENTS.md",
        "docs/ARCHITECTURE_SUMMARY.md",
        "docs/DELIVERY_MODEL.md",
        "workflows/*",
        "checklists/*",
        "policies/*",
        ".framework/*",
    ]
    return {
        "project_name": project_name,
        "generated_artifacts": generated_artifacts,
        "notes": [
            "Framework outputs were generated from project.yaml by AgentHarness.",
            "Required checks were derived from quality, security, testing, observability, and evaluation declarations.",
            "Risk matrix content was derived from security posture, observability, resilience defaults, and agent policy declarations.",
            f"Generated {len(generated_checks)} required checks.",
        ],
    }


def generate_framework_outputs(project_dir: str | Path) -> GenerationResult:
    root = Path(project_dir).resolve()
    project_yaml_path = root / "project.yaml"
    if not root.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {root}")
    if not project_yaml_path.is_file():
        raise FileNotFoundError(f"Missing required file: {project_yaml_path}")

    payload = _load_yaml(project_yaml_path)
    generated_checks = _collect_required_checks(payload)
    risk_matrix = _build_risk_matrix(payload)

    framework_dir = root / ".framework"
    framework_dir.mkdir(parents=True, exist_ok=True)

    required_checks_path = framework_dir / "required-checks.json"
    required_checks_path.write_text(
        json.dumps({"required_checks": generated_checks}, indent=2) + "\n",
        encoding="utf-8",
    )

    risk_matrix_path = framework_dir / "risk-matrix.yaml"
    risk_matrix_path.write_text(
        yaml.safe_dump(risk_matrix, sort_keys=False),
        encoding="utf-8",
    )

    generation_report_path = framework_dir / "generation-report.json"
    generation_report_path.write_text(
        json.dumps(_build_generation_report(payload, generated_checks), indent=2) + "\n",
        encoding="utf-8",
    )

    return GenerationResult(
        project_dir=root,
        files_written=[
            str(required_checks_path.relative_to(root)),
            str(risk_matrix_path.relative_to(root)),
            str(generation_report_path.relative_to(root)),
        ],
        generated_checks=generated_checks,
    )
