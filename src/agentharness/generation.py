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


RISK_MATRIX_TEMPLATE = {
    "low": {
        "examples": ["docs_update", "local_refactor", "add_tests"],
        "autonomy": "medium",
        "human_review_required": False,
    },
    "medium": {
        "examples": ["endpoint_change", "validation_change", "notification_change"],
        "autonomy": "medium",
        "human_review_required": True,
    },
    "high": {
        "examples": ["auth_change", "upload_change", "audit_model_change", "dependency_change"],
        "autonomy": "low",
        "human_review_required": True,
        "extra_checks": ["security_review_checklist"],
    },
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

    return _dedupe(checks)


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
            "Required checks were derived from quality, security, and testing declarations.",
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

    framework_dir = root / ".framework"
    framework_dir.mkdir(parents=True, exist_ok=True)

    required_checks_path = framework_dir / "required-checks.json"
    required_checks_path.write_text(
        json.dumps({"required_checks": generated_checks}, indent=2) + "\n",
        encoding="utf-8",
    )

    risk_matrix_path = framework_dir / "risk-matrix.yaml"
    risk_matrix_path.write_text(
        yaml.safe_dump(RISK_MATRIX_TEMPLATE, sort_keys=False),
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
