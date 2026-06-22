from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentharness.verify import (
    default_verify_run_report_path,
    verify_run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
RUN_FIXTURE = FIXTURES / "run_invite_success.json"
CLAIMS_FIXTURE = FIXTURES / "claims_invite_success.json"
RUN_SCHEMA_FIXTURE = FIXTURES / "run_invite_schema_success.json"
RUN_SCHEMA_BAD_FIXTURE = FIXTURES / "run_invite_schema_bad.json"
CLAIMS_SCHEMA_FIXTURE = FIXTURES / "claims_invite_schema.json"


class VerifyRunTests(unittest.TestCase):
    def test_verify_run_supports_all_claims_on_happy_path(self) -> None:
        result = verify_run(RUN_FIXTURE, CLAIMS_FIXTURE)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary["supported"], 3)
        self.assertEqual(result.summary["unsupported"], 0)
        self.assertEqual(result.summary["invalid"], 0)
        self.assertEqual(result.blocking_claim_ids, [])

    def test_verify_run_supports_forbidden_paths_and_schema_match_claims(self) -> None:
        result = verify_run(RUN_SCHEMA_FIXTURE, CLAIMS_SCHEMA_FIXTURE)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary["supported"], 3)
        self.assertTrue(any(item.claim_id == "claim_scope_forbidden" and item.status == "supported" for item in result.results))
        self.assertTrue(any(item.claim_id == "claim_schema" and item.status == "supported" for item in result.results))

    def test_verify_run_reports_allowed_scope_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            workspace = Path(tmp_dir) / "workspace_success"
            workspace.mkdir()
            (workspace / "openapi.yaml").write_text(
                (FIXTURES / "workspace_success" / "openapi.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            run_payload = json.loads(RUN_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
            run_payload["artifacts"]["changed_files"].append("docs/adr-001.md")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_SCHEMA_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertTrue(any(item.claim_id == "claim_scope_allowed" and item.status == "unsupported" for item in result.results))
            self.assertEqual(result.blocking_claim_ids, ["claim_scope_allowed"])

    def test_verify_run_reports_forbidden_path_as_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["artifacts"]["changed_files"].append("infra/deploy.yml")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["unsupported"], 1)
            self.assertTrue(any(item.claim_id == "claim_scope" and item.status == "unsupported" for item in result.results))

    def test_verify_run_reports_missing_required_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["artifacts"]["commands"] = []
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["unsupported"], 1)
            self.assertTrue(any(item.claim_id == "claim_tests" and item.status == "unsupported" for item in result.results))

    def test_verify_run_supports_required_command_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["artifacts"]["commands"] = [
                {
                    "cmd": "pytest tests/test_invite.py -q",
                    "exit_code": 0,
                }
            ]
            claims_payload = {
                "run_id": "run_invite_001",
                "claims": [
                    {
                        "id": "claim_tests_pattern",
                        "type": "tests_executed",
                        "statement": "Ho eseguito i test richiesti con una variante del comando",
                        "expected": {
                            "required_command_patterns": [
                                "pytest tests/test_invite.py*"
                            ]
                        },
                    }
                ],
            }
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.summary["supported"], 1)
            self.assertEqual(result.results[0].evidence, ["pytest tests/test_invite.py*"])

    def test_verify_run_reports_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["artifacts"]["outputs"] = []
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["unsupported"], 1)
            self.assertTrue(any(item.claim_id == "claim_openapi" and item.status == "unsupported" for item in result.results))

    def test_verify_run_can_require_artifact_to_exist_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["claims"][2]["expected"]["must_exist_on_disk"] = True
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertTrue(result.ok)
            artifact_result = next(item for item in result.results if item.claim_id == "claim_openapi")
            self.assertEqual(artifact_result.status, "supported")
            self.assertTrue(artifact_result.evidence[0].endswith("openapi.yaml"))

    def test_verify_run_reports_declared_artifact_missing_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["claims"][2]["expected"]["must_exist_on_disk"] = True
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            artifact_result = next(item for item in result.results if item.claim_id == "claim_openapi")
            self.assertEqual(artifact_result.status, "unsupported")
            self.assertIn("missing on disk", artifact_result.reason)

    def test_verify_run_reports_schema_mismatch(self) -> None:
        result = verify_run(RUN_SCHEMA_BAD_FIXTURE, CLAIMS_SCHEMA_FIXTURE)
        self.assertFalse(result.ok)
        self.assertTrue(any(item.claim_id == "claim_schema" and item.status == "unsupported" for item in result.results))
        self.assertTrue(any("Schema mismatch" in item.reason for item in result.results if item.claim_id == "claim_schema"))

    def test_verify_run_rejects_vague_or_incomplete_claim_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["claims"].append(
                {
                    "id": "claim_vague",
                    "type": "tests_executed",
                    "statement": "nessuna regressione",
                    "expected": {},
                }
            )
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["invalid"], 1)
            self.assertTrue(any(item.claim_id == "claim_vague" and item.status == "invalid" for item in result.results))

    def test_verify_run_fails_when_claims_are_bound_to_a_different_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["run_id"] = "different-run"
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(len(result.gating_errors), 1)
            self.assertIn("different run", result.gating_errors[0])

    def test_verify_run_can_write_default_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            expected_report_path = default_verify_run_report_path(run_path)
            result = verify_run(run_path, claims_path, write_report=True)

            self.assertTrue(result.ok)
            self.assertEqual(result.report_written, str(expected_report_path))
            self.assertTrue(expected_report_path.is_file())
            payload = json.loads(expected_report_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["supported"], 3)
            self.assertEqual(payload["blocking_claim_ids"], [])

    def test_verify_run_can_write_custom_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            report_path = Path(tmp_dir) / "reports" / "custom.verify-report.json"
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, write_report=True, report_path=report_path)

            self.assertTrue(result.ok)
            self.assertEqual(result.report_written, str(report_path))
            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["report_written"], str(report_path))
            self.assertEqual(payload["summary"]["supported"], 3)

    def test_cli_verify_run_outputs_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agentharness",
                "verify-run",
                "--run",
                str(RUN_FIXTURE),
                "--claims",
                str(CLAIMS_FIXTURE),
                "--json",
            ],
            cwd=REPO_ROOT,
            env={**os.environ, **{"PYTHONPATH": str(REPO_ROOT / 'src')}},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["supported"], 3)
        self.assertEqual(payload["results"][0]["claim_type"], "files_changed")

    def test_cli_verify_run_can_write_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            report_path = Path(tmp_dir) / "out" / "verify-run-report.json"
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentharness",
                    "verify-run",
                    "--run",
                    str(run_path),
                    "--claims",
                    str(claims_path),
                    "--write-report",
                    "--report-path",
                    str(report_path),
                ],
                cwd=REPO_ROOT,
                env={**os.environ, **{"PYTHONPATH": str(REPO_ROOT / 'src')}},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Report written:", completed.stdout)
            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["report_written"], str(report_path))
            self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
