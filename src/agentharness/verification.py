from __future__ import annotations

import filecmp
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .generation import generate_framework_outputs
from .validation import ValidationResult, validate_project_directory

GENERATED_FRAMEWORK_FILES = (
    ".framework/required-checks.json",
    ".framework/risk-matrix.yaml",
    ".framework/generation-report.json",
)


@dataclass
class VerificationResult:
    project_dir: Path
    validation: ValidationResult
    compared_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    drifted_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    report_written: str | None = None

    @property
    def ok(self) -> bool:
        return self.validation.ok and not self.missing_files and not self.drifted_files

    @property
    def errors(self) -> list[str]:
        return [
            *self.validation.errors,
            *[f"Missing generated framework file: {path}" for path in self.missing_files],
            *[
                "Generated framework drift detected: "
                f"{path} does not match the output derived from project.yaml"
                for path in self.drifted_files
            ],
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "ok": self.ok,
            "validation": self.validation.to_dict(),
            "compared_files": self.compared_files,
            "missing_files": self.missing_files,
            "drifted_files": self.drifted_files,
            "errors": self.errors,
            "notes": self.notes,
            "report_written": self.report_written,
        }


def _copy_minimum_contract(root: Path, temp_root: Path) -> None:
    shutil.copy2(root / "project.yaml", temp_root / "project.yaml")


def _compare_generated_framework(root: Path) -> tuple[list[str], list[str], list[str]]:
    compared_files = [str(path) for path in GENERATED_FRAMEWORK_FILES]
    missing_files: list[str] = []
    drifted_files: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_minimum_contract(root, temp_root)
        generate_framework_outputs(temp_root)

        for relative_path in GENERATED_FRAMEWORK_FILES:
            actual_path = root / relative_path
            expected_path = temp_root / relative_path
            if not actual_path.is_file():
                missing_files.append(relative_path)
                continue
            if not filecmp.cmp(actual_path, expected_path, shallow=False):
                drifted_files.append(relative_path)

    return compared_files, missing_files, drifted_files


def write_verification_report(result: VerificationResult, output_path: str | Path | None = None) -> Path:
    report_path = Path(output_path) if output_path else result.project_dir / ".framework" / "verification-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report_path


def verify_project_directory(
    project_dir: str | Path,
    *,
    write_report: bool = False,
    report_path: str | Path | None = None,
) -> VerificationResult:
    root = Path(project_dir).resolve()
    validation = validate_project_directory(root)

    compared_files: list[str] = []
    missing_files: list[str] = []
    drifted_files: list[str] = []
    notes = [
        "Verification checks structural validity, semantic contract guardrails, and drift in deterministic .framework artifacts regenerated from project.yaml.",
        "A project only passes verification when contract validation and generated artifact comparison both succeed.",
    ]

    if root.is_dir() and (root / "project.yaml").is_file():
        compared_files, missing_files, drifted_files = _compare_generated_framework(root)
        if not missing_files and not drifted_files:
            notes.append("Generated .framework artifacts match the current project contract.")
    else:
        notes.append("Generated artifact comparison was skipped because the project directory or project.yaml is missing.")

    result = VerificationResult(
        project_dir=root,
        validation=validation,
        compared_files=compared_files,
        missing_files=missing_files,
        drifted_files=drifted_files,
        notes=notes,
    )

    if write_report:
        written_path = write_verification_report(result, report_path)
        result.report_written = str(written_path)

    return result
