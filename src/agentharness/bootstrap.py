from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .generation import generate_framework_outputs
from .validation import validate_project_directory

SLUG_RE = re.compile(r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")

DEFAULT_WORKFLOWS = ["create-feature", "fix-bug", "refactor-module", "add-tests"]
DEFAULT_MODULES = ["api", "domain", "validation", "notifications", "persistence", "audit"]


@dataclass
class BootstrapResult:
    project_dir: Path
    files_written: list[str]
    validation_ok: bool
    generated_checks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "files_written": self.files_written,
            "validation_ok": self.validation_ok,
            "generated_checks": self.generated_checks,
        }


@dataclass(frozen=True)
class BootstrapOptions:
    project_name: str
    project_slug: str
    project_type: str = "open_source_web_api"
    language: str = "python"
    framework: str = "fastapi"
    database: str = "postgres"
    package_manager: str = "uv"
    license_name: str = "MIT"


def _ensure_valid_slug(slug: str) -> None:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("project_slug must use lowercase letters, digits, hyphens, or underscores")


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _project_md(options: BootstrapOptions) -> str:
    return f"""# {options.project_name}

## Project purpose
{options.project_name} is an AgentHarness bootstrap project created from a reusable template.

Its goal is to provide a clean starting point for teams that want to define project intent, guardrails, and operating rules before asking agents to contribute code.

## Problem it addresses
Without a project contract, AI-assisted development often drifts into:
- vague requirements
- missing scope boundaries
- inconsistent review expectations
- weak testing discipline
- unclear security posture

This template gives the project a machine-readable and human-readable operating baseline from day one.

## Primary users
- engineering teams adopting AI-assisted development
- maintainers who need clearer project rules
- reviewers who want explicit delivery and risk boundaries

## Key use cases
1. Describe the product intent in a readable way.
2. Define the stack, modules, and quality gates in `project.yaml`.
3. Constrain agent behavior with `AGENTS.md`, policies, workflows, and checklists.
4. Validate the project contract before deeper automation is introduced.

## Non-goals for v1
- full production deployment automation
- fully autonomous software delivery
- benchmark-specific optimization loops

## Technical constraints
- language: {options.language}
- framework: {options.framework}
- database: {options.database}
- package manager: {options.package_manager}
- secrets via environment variables only
- project contract must remain readable by humans first

## Product / governance constraints
- keep scope explicit
- prefer simple guardrails over hidden conventions
- require human review for high-risk changes
- prioritize testability, auditability, and secure defaults

## Team conventions
- make the smallest useful change
- keep project rules explicit
- if behavior changes, update tests
- avoid hardcoded secrets, credentials, or tokens
- document risk boundaries instead of assuming them

## Definition of done
A change is done when:
- scope stayed bounded
- relevant checks passed
- no secrets were introduced
- documentation and policy assumptions remain coherent
- residual risks are summarized clearly
"""


def _project_yaml(options: BootstrapOptions) -> str:
    payload = {
        "project_name": options.project_name,
        "project_slug": options.project_slug,
        "project_type": options.project_type,
        "opensource": True,
        "license": options.license_name,
        "stack": {
            "language": options.language,
            "framework": options.framework,
            "database": options.database,
            "package_manager": options.package_manager,
            "api_style": "rest",
        },
        "modules": DEFAULT_MODULES,
        "external_services": ["smtp_optional", "webhook_optional"],
        "testing": {
            "framework": "pytest",
            "required": True,
            "minimum": ["unit", "integration_smoke"],
            "bugfix_requires_regression_test": True,
        },
        "quality": {
            "lint": True,
            "format": True,
            "type_check": True,
            "required_checks": [
                "format",
                "lint",
                "type_check",
                "unit_tests",
                "no_hardcoded_secrets",
            ],
        },
        "security": {
            "level": "medium",
            "pii_present": False,
            "secrets_policy": "env_only",
            "dependency_policy": "approved_only",
            "upload_validation_required": True,
            "required_checks": [
                "no_hardcoded_secrets",
                "dependency_scan",
                "input_validation",
                "safe_logging",
                "upload_constraints",
            ],
        },
        "agent_policy": {
            "autonomy": "medium",
            "allowed_tools": ["read_files", "edit_files", "run_tests", "search"],
            "forbidden_actions": [
                "deploy_prod",
                "disable_auth",
                "commit_secrets",
                "remove_audit_logging",
                "disable_input_validation",
            ],
            "review_required_for": [
                "auth_changes",
                "dependency_changes",
                "ci_pipeline_changes",
                "upload_handling_changes",
                "audit_model_changes",
            ],
        },
        "deliverables": {
            "generate": [
                "agents_md",
                "architecture_summary",
                "delivery_model",
                "workflows",
                "checklists",
                "test_bootstrap",
                "policy_files",
            ]
        },
        "workflows_enabled": DEFAULT_WORKFLOWS,
    }
    return yaml.safe_dump(payload, sort_keys=False)


def _readme(options: BootstrapOptions) -> str:
    return f"""# {options.project_name}

This project was bootstrapped by AgentHarness.

## What this repository contains
- `PROJECT.md` — human-readable project intent
- `project.yaml` — machine-readable project definition
- `AGENTS.md` — agent operating rules
- `docs/` — architecture and delivery model summaries
- `workflows/` — reusable engineering task templates
- `checklists/` — quality, testing, and security checklists
- `policies/` — machine-facing governance rules
- `.framework/` — generated framework metadata

## Why it exists
The repository starts with explicit project intent and execution guardrails so agent-assisted work can be more predictable, reviewable, and secure.

## Next steps
1. Customize `PROJECT.md` for the actual product.
2. Adjust `project.yaml` to match the real stack and risk posture.
3. Refine workflows, policies, and checklists.
4. Run:
   - `PYTHONPATH=src python3 -m agentharness generate <project-dir>`
   - `PYTHONPATH=src python3 -m agentharness validate <project-dir>`
"""


def _agents_md(options: BootstrapOptions) -> str:
    return f"""# AGENTS.md

## Project identity
Project: {options.project_name}
Type: {options.project_type}
Primary goal: turn project intent into reliable, bounded agent execution.

## Core rules
- Prefer explicit behavior over hidden abstractions.
- Keep business rules out of transport handlers.
- Do not modify authentication, upload handling, audit logging, or dependencies without human review.
- Never hardcode secrets, credentials, or tokens.
- Every bug fix should leave a regression test when technically feasible.
- If a task is ambiguous, reduce scope instead of widening it.

## Quality gates
Before considering a task done:
- run configured format, lint, and type checks
- run relevant unit tests
- run integration smoke tests when interfaces or persistence behavior changes
- verify no secrets were introduced
- summarize changed files, tests run, and residual risks

## Security rules
- validate all user-controlled inputs
- constrain upload types and size when uploads exist
- avoid logging raw sensitive data unless explicitly required and reviewed
- treat external integrations as failure-prone
- prefer safe defaults over convenience shortcuts

## Risk boundaries
Human review required for:
- auth or permission changes
- audit model changes
- upload handling changes
- dependency additions or removals
- CI pipeline changes

## Working style
- make the smallest viable change
- prefer readability over cleverness
- if you touch behavior, touch tests
- keep project rules and assumptions visible in the repository
"""


def _architecture_summary(options: BootstrapOptions) -> str:
    return f"""# Architecture Summary

## Overview
{options.project_name} starts from a contract-first repository structure.

The project separates:
- project intent
- machine-readable configuration
- agent operating constraints
- quality and security rules
- reusable workflows

## Main components

### 1. Project definition
- `PROJECT.md`
- `project.yaml`

### 2. Agent operating layer
- `AGENTS.md`
- `policies/`
- `workflows/`
- `checklists/`

### 3. Framework metadata
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

## Design goals
- explicit scope boundaries
- reusable delivery rules
- machine-readable governance
- easier validation before execution
- safer handoff to humans and agents
"""


def _delivery_model() -> str:
    return """# Delivery Model

## Autonomy model
The project uses a medium-autonomy model.

Agents may:
- inspect files
- propose scoped changes
- implement isolated features
- add or update tests
- run local checks

Agents may not independently:
- change authentication behavior
- weaken validation rules
- alter upload safety constraints
- remove audit coverage
- modify CI or release behavior without review

## Task classes

### Low risk
Examples:
- documentation updates
- local refactors without behavior change
- adding tests
- improving error messages

### Medium risk
Examples:
- new endpoint inside an existing bounded flow
- validation rule change
- notification behavior update
- persistence query change

### High risk
Examples:
- auth changes
- upload handling changes
- audit model changes
- dependency changes
- CI pipeline changes

## Review policy
- Low risk: human review recommended
- Medium risk: human review required
- High risk: human review required with focused checklist
"""


def _workflow(name: str) -> str:
    title = name.replace("-", " ").title()
    return f"""# {title}

## Goal
Describe the change clearly and keep scope bounded.

## Steps
1. Read the relevant project intent and policy files.
2. Inspect the current implementation or target area.
3. Make the smallest useful change.
4. Add or update tests when behavior changes.
5. Run the relevant checks.
6. Summarize what changed and residual risks.
"""


def _checklist(title: str, bullets: list[str]) -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {item}" for item in bullets)
    return "\n".join(lines) + "\n"


def _policy_autonomy() -> str:
    return """default_autonomy: medium

risk_levels:
  low:
    review_required: false
  medium:
    review_required: true
  high:
    review_required: true
    extra_focus:
      - security
      - auditability
      - backwards_compatibility
"""


def _policy_security() -> str:
    return """level: medium
secrets_policy: env_only
dependency_policy: approved_only
input_validation_required: true
upload_validation_required: true
safe_logging_required: true
"""


def _policy_test() -> str:
    return """framework: pytest
required: true
minimum:
  - unit
  - integration_smoke
bugfix_requires_regression_test: true
"""


def bootstrap_project(project_dir: str | Path, options: BootstrapOptions) -> BootstrapResult:
    _ensure_valid_slug(options.project_slug)

    root = Path(project_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Target directory already exists and is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    files_written: list[str] = []
    files_written.append(_write(root / "PROJECT.md", _project_md(options)))
    files_written.append(_write(root / "project.yaml", _project_yaml(options)))
    files_written.append(_write(root / "README.md", _readme(options)))
    files_written.append(_write(root / "AGENTS.md", _agents_md(options)))
    files_written.append(_write(root / "docs/ARCHITECTURE_SUMMARY.md", _architecture_summary(options)))
    files_written.append(_write(root / "docs/DELIVERY_MODEL.md", _delivery_model()))

    for workflow_name in DEFAULT_WORKFLOWS:
        files_written.append(_write(root / f"workflows/{workflow_name}.md", _workflow(workflow_name)))

    files_written.append(
        _write(
            root / "checklists/definition-of-done.md",
            _checklist(
                "Definition of Done",
                [
                    "scope stayed bounded",
                    "relevant tests were added or updated",
                    "required checks passed",
                    "no secrets were introduced",
                    "edge cases and error handling were considered",
                    "review requirement was respected",
                    "execution summary is available",
                ],
            ),
        )
    )
    files_written.append(
        _write(
            root / "checklists/testing-standards.md",
            _checklist(
                "Testing Standards",
                [
                    "prefer targeted tests over broad fragile ones",
                    "add regression coverage for bug fixes",
                    "avoid changing behavior without updating tests",
                    "keep tests readable and deterministic",
                ],
            ),
        )
    )
    files_written.append(
        _write(
            root / "checklists/security-review-checklist.md",
            _checklist(
                "Security Review Checklist",
                [
                    "validate user-controlled inputs",
                    "check secrets handling",
                    "check logging for sensitive data leakage",
                    "review dependency and upload changes carefully",
                ],
            ),
        )
    )
    files_written.append(
        _write(
            root / "checklists/ai-code-review-checklist.md",
            _checklist(
                "AI Code Review Checklist",
                [
                    "verify the change matches stated scope",
                    "look for hidden assumptions or hallucinated behavior",
                    "verify tests and validation are relevant",
                    "document residual risks clearly",
                ],
            ),
        )
    )

    files_written.append(_write(root / "policies/autonomy-policy.yaml", _policy_autonomy()))
    files_written.append(_write(root / "policies/security-policy.yaml", _policy_security()))
    files_written.append(_write(root / "policies/test-policy.yaml", _policy_test()))

    for rel in ("tests/unit/README.md", "tests/integration/README.md", "tests/regression/README.md"):
        files_written.append(_write(root / rel, f"# {Path(rel).parts[-2].title()} Tests\n\nAdd tests for this layer here.\n"))

    generation = generate_framework_outputs(root)
    validation = validate_project_directory(root)

    return BootstrapResult(
        project_dir=root,
        files_written=[str(Path(path).relative_to(root)) for path in files_written] + generation.files_written,
        validation_ok=validation.ok,
        generated_checks=generation.generated_checks,
    )
