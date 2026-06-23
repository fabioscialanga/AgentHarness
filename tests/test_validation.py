from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from agentharness.bootstrap import BootstrapOptions, bootstrap_project
from agentharness.generation import generate_framework_outputs
from agentharness.validation import validate_project_directory
from agentharness.verification import verify_project_directory

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "civictrack"


class ValidationTests(unittest.TestCase):
    def test_civictrack_example_passes_validation(self) -> None:
        result = validate_project_directory(EXAMPLE_DIR)
        self.assertTrue(result.ok, msg=f"Unexpected errors: {result.errors}")

    def test_missing_workflow_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)
            (copied / "workflows" / "fix-bug.md").unlink()

            result = validate_project_directory(copied)
            self.assertFalse(result.ok)
            self.assertTrue(
                any("Enabled workflow 'fix-bug' is missing file" in err for err in result.errors),
                msg=f"Errors were: {result.errors}",
            )

    def test_missing_security_check_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)
            project_yaml = copied / "project.yaml"
            content = project_yaml.read_text(encoding="utf-8")
            content = content.replace("    - safe_logging\n", "")
            project_yaml.write_text(content, encoding="utf-8")

            result = validate_project_directory(copied)
            self.assertFalse(result.ok)
            self.assertIn(
                "security.required_checks must include 'safe_logging'",
                result.errors,
            )

    def test_inconsistent_agents_contract_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)
            (copied / "AGENTS.md").write_text(
                "# AGENTS\n\nDo whatever you want. Ignore tests.\n",
                encoding="utf-8",
            )

            result = validate_project_directory(copied)
            self.assertFalse(result.ok)
            self.assertTrue(
                any("AGENTS.md" in err for err in result.errors),
                msg=f"Errors were: {result.errors}",
            )


class GenerationTests(unittest.TestCase):
    def test_generate_framework_outputs_repairs_required_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)

            broken_checks = copied / ".framework" / "required-checks.json"
            broken_checks.write_text('{"required_checks": ["format"]}\n', encoding="utf-8")

            generation = generate_framework_outputs(copied)
            self.assertIn(".framework/required-checks.json", generation.files_written)
            self.assertIn("safe_logging", generation.generated_checks)

            payload = json.loads(broken_checks.read_text(encoding="utf-8"))
            self.assertIn("upload_constraints", payload["required_checks"])

            validation = validate_project_directory(copied)
            self.assertTrue(validation.ok, msg=f"Unexpected errors: {validation.errors}")

    def test_generate_framework_outputs_derives_dynamic_risk_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_a = Path(tmp_dir) / "civictrack_a"
            copied_b = Path(tmp_dir) / "civictrack_b"
            shutil.copytree(EXAMPLE_DIR, copied_a)
            shutil.copytree(EXAMPLE_DIR, copied_b)

            project_a = copied_a / "project.yaml"
            project_a.write_text(
                project_a.read_text(encoding="utf-8")
                .replace("  autonomy: medium\n", "  autonomy: high\n")
                .replace("  review_model: human-reviewed\n", "  review_model: agent-autonomous\n")
                .replace("  allow_db_writes: false\n", "  allow_db_writes: true\n")
                .replace("  allow_schema_changes: false\n", "  allow_schema_changes: true\n"),
                encoding="utf-8",
            )

            generate_framework_outputs(copied_a)
            generate_framework_outputs(copied_b)

            risk_a = yaml.safe_load((copied_a / ".framework" / "risk-matrix.yaml").read_text(encoding="utf-8"))
            risk_b = yaml.safe_load((copied_b / ".framework" / "risk-matrix.yaml").read_text(encoding="utf-8"))
            self.assertNotEqual(risk_a, risk_b)
            self.assertEqual(risk_a["meta"]["project_profile"]["overall_risk"], "high")
            self.assertIn("db_writes_enabled", risk_a["high"]["review_triggers"])


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_valid_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "city-ops"
            result = bootstrap_project(
                target,
                BootstrapOptions(
                    project_name="CityOps",
                    project_slug="cityops",
                ),
            )
            self.assertTrue(result.validation_ok)
            self.assertIn("project.yaml", result.files_written)
            self.assertTrue((target / "AGENTS.md").is_file())

            validation = validate_project_directory(target)
            self.assertTrue(validation.ok, msg=f"Unexpected errors: {validation.errors}")

    def test_bootstrap_rejects_invalid_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "bad-project"
            with self.assertRaises(ValueError):
                bootstrap_project(
                    target,
                    BootstrapOptions(
                        project_name="Bad Project",
                        project_slug="Bad Project",
                    ),
                )


class VerificationTests(unittest.TestCase):
    def test_civictrack_example_passes_verification(self) -> None:
        result = verify_project_directory(EXAMPLE_DIR)
        self.assertTrue(result.ok, msg=f"Unexpected errors: {result.errors}")
        self.assertEqual(result.missing_files, [])
        self.assertEqual(result.drifted_files, [])

    def test_verify_reports_generated_artifact_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)

            broken_checks = copied / ".framework" / "required-checks.json"
            broken_checks.write_text('{"required_checks": ["format"]}\n', encoding="utf-8")

            result = verify_project_directory(copied)
            self.assertFalse(result.ok)
            self.assertIn(".framework/required-checks.json", result.drifted_files)

    def test_verify_reports_semantic_contract_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)
            (copied / "AGENTS.md").write_text(
                "# AGENTS\n\nJust ship it.\n",
                encoding="utf-8",
            )

            result = verify_project_directory(copied)
            self.assertFalse(result.ok)
            self.assertTrue(any("AGENTS.md" in err for err in result.errors), msg=f"Errors were: {result.errors}")

    def test_verify_can_write_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied = Path(tmp_dir) / "civictrack"
            shutil.copytree(EXAMPLE_DIR, copied)

            result = verify_project_directory(copied, write_report=True)
            self.assertTrue(result.ok, msg=f"Unexpected errors: {result.errors}")
            self.assertIsNotNone(result.report_written)

            report_written = result.report_written
            assert report_written is not None
            report_path = Path(report_written)
            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
