from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentharness.verify import default_verify_run_report_path, verify_run

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
RUN_FIXTURE = FIXTURES / "run_invite_success.json"
CLAIMS_FIXTURE = FIXTURES / "claims_invite_success.json"
RUN_SCHEMA_FIXTURE = FIXTURES / "run_invite_schema_success.json"
RUN_SCHEMA_BAD_FIXTURE = FIXTURES / "run_invite_schema_bad.json"
CLAIMS_SCHEMA_FIXTURE = FIXTURES / "claims_invite_schema.json"
RUN_LIE_FIXTURE = FIXTURES / "run_invite_lie.json"
CLAIMS_LIE_FIXTURE = FIXTURES / "claims_invite_lie.json"


class VerifyRunTests(unittest.TestCase):
    def test_verify_run_supports_all_claims_on_happy_path(self) -> None:
        result = verify_run(RUN_FIXTURE, CLAIMS_FIXTURE)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary["supported"], 3)
        self.assertEqual(result.summary["unsupported"], 0)
        self.assertEqual(result.summary["inconclusive"], 0)
        self.assertEqual(result.summary["invalid"], 0)
        self.assertEqual(result.blocking_claim_ids, [])
        self.assertEqual(result.gating_errors, [])
        command_result = next(item for item in result.results if item.claim_id == "claim_tests")
        self.assertIn(command_result.truth_source, {"parsed-evidence", "reexecuted"})

    def test_verify_run_supports_forbidden_paths_schema_and_test_evidence_claims(self) -> None:
        result = verify_run(RUN_SCHEMA_FIXTURE, CLAIMS_SCHEMA_FIXTURE)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary["supported"], 4)
        self.assertTrue(any(item.claim_id == "claim_scope_forbidden" and item.status == "supported" for item in result.results))
        self.assertTrue(any(item.claim_id == "claim_schema" and item.status == "supported" for item in result.results))
        self.assertTrue(any(item.claim_id == "claim_tests_schema" and item.status == "supported" for item in result.results))

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
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_schema_001"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "pytest.stdout").write_text(
                "============================= test session starts ==============================\ncollected 1 item\n\ntests/test_invite.py .                                                   [100%]\n\n============================== 1 passed in 0.04s ===============================\n",
                encoding="utf-8",
            )
            (evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_payload = json.loads(RUN_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
            run_payload["artifacts"]["changed_files"].append("docs/adr-001.md")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_SCHEMA_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, reexecute_mode="never")
            self.assertFalse(result.ok)
            self.assertTrue(any(item.claim_id == "claim_scope_allowed" and item.status == "unsupported" for item in result.results))
            self.assertEqual(result.blocking_claim_ids, ["claim_scope_allowed"])

    def test_verify_run_reports_forbidden_path_as_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(FIXTURES / "workspace_invite")
            run_payload["artifacts"]["changed_files"].append("infra/deploy.yml")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertTrue(any(item.claim_id == "claim_scope" and item.status == "unsupported" for item in result.results))

    def test_verify_run_reports_missing_required_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(FIXTURES / "workspace_invite")
            run_payload["artifacts"]["commands"] = []
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertTrue(any(item.claim_id == "claim_tests" and item.status == "unsupported" for item in result.results))

    def test_verify_run_supports_required_command_patterns_in_relaxed_mode(self) -> None:
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
                            ],
                            "require_evidence_files": False,
                        },
                    }
                ],
            }
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.summary["supported"], 1)
            self.assertEqual(result.results[0].truth_source, "run-artifact")

    def test_verify_run_defaults_to_strict_evidence_for_tests(self) -> None:
        result = verify_run(RUN_FIXTURE, CLAIMS_FIXTURE)
        command_result = next(item for item in result.results if item.claim_id == "claim_tests")
        self.assertEqual(command_result.status, "supported")
        self.assertIn(command_result.truth_source, {"parsed-evidence", "reexecuted"})
        self.assertTrue(command_result.evidence)

    def test_verify_run_marks_missing_command_evidence_as_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace_invite"
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            (workspace / "tests").mkdir(parents=True)
            (workspace / "tests" / "test_invite.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
            (evidence_dir / "pytest.stdout").write_text("ok\n", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, reexecute_mode="never")
            self.assertFalse(result.ok)
            command_result = next(item for item in result.results if item.claim_id == "claim_tests")
            self.assertEqual(command_result.status, "inconclusive")
            self.assertIn(command_result.truth_source, {"none", "parsed-evidence"})

    def test_verify_run_rejects_command_evidence_outside_reserved_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace_invite"
            (workspace / "tests").mkdir(parents=True)
            (workspace / "tests" / "test_invite.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            (workspace / "pytest.stdout").write_text("ok\n", encoding="utf-8")
            (workspace / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_payload["artifacts"]["commands"] = [
                {
                    "cmd": "pytest tests/test_invite.py -q",
                    "exit_code": 0,
                    "stdout_path": "pytest.stdout",
                    "stderr_path": "pytest.stderr",
                }
            ]
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, reexecute_mode="never")
            self.assertFalse(result.ok)
            command_result = next(item for item in result.results if item.claim_id == "claim_tests")
            self.assertEqual(command_result.status, "inconclusive")
            self.assertTrue(any("reserved run evidence directory" in item for item in command_result.evidence))

    def test_verify_run_rejects_command_evidence_under_wrong_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace_invite"
            (workspace / "tests").mkdir(parents=True)
            (workspace / "tests" / "test_invite.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
            wrong_evidence_dir = workspace / ".agentharness" / "evidence" / "different-run"
            wrong_evidence_dir.mkdir(parents=True)
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            (wrong_evidence_dir / "pytest.stdout").write_text("ok\n", encoding="utf-8")
            (wrong_evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_payload["artifacts"]["commands"] = [
                {
                    "cmd": "pytest tests/test_invite.py -q",
                    "exit_code": 0,
                    "stdout_path": ".agentharness/evidence/different-run/pytest.stdout",
                    "stderr_path": ".agentharness/evidence/different-run/pytest.stderr",
                }
            ]
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, reexecute_mode="never")
            self.assertFalse(result.ok)
            command_result = next(item for item in result.results if item.claim_id == "claim_tests")
            self.assertEqual(command_result.status, "inconclusive")
            self.assertTrue(any("reserved run evidence directory" in item for item in command_result.evidence))

    def test_verify_run_rejects_zero_byte_test_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace_invite"
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            (workspace / "tests").mkdir(parents=True)
            (workspace / "tests" / "test_invite.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
            (evidence_dir / "pytest.stdout").write_text("", encoding="utf-8")
            (evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, reexecute_mode="never")
            self.assertFalse(result.ok)
            command_result = next(item for item in result.results if item.claim_id == "claim_tests")
            self.assertEqual(command_result.status, "unsupported")
            self.assertIn("did not prove", command_result.reason)

    def test_verify_run_marks_disallowed_command_as_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "pytest.stdout").write_text("1 passed\n", encoding="utf-8")
            (evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_payload["artifacts"]["commands"] = [
                {
                    "cmd": "bash -lc 'echo forged'",
                    "exit_code": 0,
                    "stdout_path": ".agentharness/evidence/run_invite_001/pytest.stdout",
                    "stderr_path": ".agentharness/evidence/run_invite_001/pytest.stderr",
                }
            ]
            claims_payload = {
                "run_id": "run_invite_001",
                "claims": [
                    {
                        "id": "claim_tests",
                        "type": "tests_executed",
                        "statement": "Ho eseguito i test richiesti",
                        "expected": {
                            "required_commands": [
                                "bash -lc 'echo forged'"
                            ]
                        },
                    }
                ],
            }
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["inconclusive"], 1)
            self.assertEqual(result.results[0].status, "inconclusive")
            self.assertIn("not allowed", result.results[0].reason)

    def test_verify_run_reports_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(FIXTURES / "workspace_invite")
            run_payload["artifacts"]["outputs"] = []
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertTrue(any(item.claim_id == "claim_openapi" and item.status == "unsupported" for item in result.results))

    def test_verify_run_defaults_to_on_disk_artifact_proof(self) -> None:
        result = verify_run(RUN_FIXTURE, CLAIMS_FIXTURE)
        self.assertTrue(result.ok)
        artifact_result = next(item for item in result.results if item.claim_id == "claim_openapi")
        self.assertEqual(artifact_result.status, "supported")
        self.assertTrue(artifact_result.evidence[0].endswith("openapi.yaml"))

    def test_verify_run_reports_declared_artifact_missing_on_disk_when_default_is_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "pytest.stdout").write_text("1 passed\n", encoding="utf-8")
            (evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["claims"][2]["expected"] = {"required_outputs": ["openapi.yaml"]}
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            artifact_result = next(item for item in result.results if item.claim_id == "claim_openapi")
            self.assertEqual(artifact_result.status, "unsupported")
            self.assertIn("missing on disk", artifact_result.reason)

    def test_verify_run_rejects_artifact_path_that_escapes_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            secret_path = Path(tmp_dir) / "secret.txt"
            secret_path.write_text("secret\n", encoding="utf-8")
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "pytest.stdout").write_text("1 passed\n", encoding="utf-8")
            (evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_payload["artifacts"]["outputs"] = [{"type": "file", "path": "../secret.txt"}]
            claims_payload = {
                "run_id": "run_invite_001",
                "claims": [
                    {
                        "id": "claim_escape_artifact",
                        "type": "artifact_present",
                        "statement": "Ho prodotto un file fuori workspace",
                        "expected": {
                            "required_outputs": ["../secret.txt"],
                            "must_exist_on_disk": True
                        }
                    }
                ],
            }
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.results[0].status, "unsupported")
            self.assertIn("outside workspace scope", result.results[0].reason)

    def test_verify_run_reports_schema_mismatch(self) -> None:
        result = verify_run(RUN_SCHEMA_BAD_FIXTURE, CLAIMS_SCHEMA_FIXTURE)
        self.assertFalse(result.ok)
        self.assertTrue(any(item.claim_id == "claim_schema" and item.status == "unsupported" for item in result.results))
        self.assertTrue(any("Schema mismatch" in item.reason for item in result.results if item.claim_id == "claim_schema"))

    def test_verify_run_rejects_schema_target_outside_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "openapi.yaml").write_text((FIXTURES / "workspace_success" / "openapi.yaml").read_text(encoding="utf-8"), encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_payload["artifacts"]["outputs"] = []
            claims_path.write_text(CLAIMS_SCHEMA_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            schema_result = next(item for item in result.results if item.claim_id == "claim_schema")
            self.assertEqual(schema_result.status, "unsupported")
            self.assertIn("not declared in run outputs", schema_result.reason)

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

    def test_verify_run_fails_when_run_id_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["run_id"] = ""
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertIn("missing a non-empty run_id", result.gating_errors[0])

    def test_verify_run_fails_when_claims_run_id_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["run_id"] = ""
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertIn("Claims document is missing a non-empty run_id.", result.gating_errors)

    def test_verify_run_rejects_run_id_with_path_traversal_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace_invite"
            escaped_evidence_dir = workspace / ".agentharness" / "evil"
            escaped_evidence_dir.mkdir(parents=True)
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            (escaped_evidence_dir / "pytest.stdout").write_text("ok\n", encoding="utf-8")
            (escaped_evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            run_payload["run_id"] = "../evil"
            claims_payload["run_id"] = "../evil"
            run_payload["workspace"] = str(workspace)
            run_payload["artifacts"]["commands"] = [
                {
                    "cmd": "pytest tests/test_invite.py -q",
                    "exit_code": 0,
                    "stdout_path": ".agentharness/evil/pytest.stdout",
                    "stderr_path": ".agentharness/evil/pytest.stderr",
                }
            ]
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertTrue(
                any("path-safe evidence namespace" in item for item in result.gating_errors)
            )
            self.assertFalse((workspace / ".agentharness" / "evil" / "reexecuted").exists())
            self.assertTrue(all(item.status == "invalid" for item in result.results))

    def test_verify_run_marks_binary_evidence_as_unsupported_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace_invite"
            evidence_dir = workspace / ".agentharness" / "evidence" / "run_invite_001"
            evidence_dir.mkdir(parents=True)
            (workspace / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
            (workspace / "tests").mkdir(parents=True)
            (workspace / "tests" / "test_invite.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")
            (evidence_dir / "pytest.stdout").write_bytes(b"\xff\xfe\x00\x00")
            (evidence_dir / "pytest.stderr").write_text("", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(workspace)
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, reexecute_mode="never")
            self.assertFalse(result.ok)
            command_result = next(item for item in result.results if item.claim_id == "claim_tests")
            self.assertEqual(command_result.status, "unsupported")
            self.assertIn("could not be read reliably", command_result.reason)

    def test_verify_run_fails_on_duplicate_claim_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            claims_payload = json.loads(CLAIMS_FIXTURE.read_text(encoding="utf-8"))
            claims_payload["claims"].append(dict(claims_payload["claims"][0]))
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(json.dumps(claims_payload, indent=2) + "\n", encoding="utf-8")

            result = verify_run(run_path, claims_path)
            self.assertFalse(result.ok)
            self.assertTrue(any("duplicate claim ids" in error for error in result.gating_errors))

    def test_verify_run_can_write_default_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(FIXTURES / "workspace_invite")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
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
            self.assertEqual(payload["gating_errors"], [])
            self.assertIn("run_sha256", payload)
            self.assertIn("claims_sha256", payload)
            self.assertIn("tool_version", payload)
            self.assertIn("evaluated_at", payload)
            self.assertIn("policy", payload["audit_trail"])

    def test_verify_run_can_write_custom_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            report_path = Path(tmp_dir) / "reports" / "custom.verify-report.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(FIXTURES / "workspace_invite")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            result = verify_run(run_path, claims_path, write_report=True, report_path=report_path)

            self.assertTrue(result.ok)
            self.assertEqual(result.report_written, str(report_path))
            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["report_written"], str(report_path))
            self.assertEqual(payload["summary"]["supported"], 3)

    def test_verify_run_hashes_are_stable_for_same_input_and_change_for_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            run_path.write_text(RUN_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            claims_path.write_text(CLAIMS_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            first = verify_run(run_path, claims_path)
            second = verify_run(run_path, claims_path)
            self.assertEqual(first.run_sha256, second.run_sha256)
            self.assertEqual(first.claims_sha256, second.claims_sha256)

            tampered_payload = json.loads(run_path.read_text(encoding="utf-8"))
            tampered_payload["task"] = "tampered"
            run_path.write_text(json.dumps(tampered_payload, indent=2) + "\n", encoding="utf-8")
            third = verify_run(run_path, claims_path)
            self.assertNotEqual(first.run_sha256, third.run_sha256)

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
        self.assertIn("truth_source", payload["results"][1])

    def test_cli_verify_run_can_write_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_path = Path(tmp_dir) / "run.json"
            claims_path = Path(tmp_dir) / "claims.json"
            report_path = Path(tmp_dir) / "out" / "verify-run-report.json"
            run_payload = json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))
            run_payload["workspace"] = str(FIXTURES / "workspace_invite")
            run_path.write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
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

    def test_cli_verify_run_reexecution_catches_a_lie(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            venv_dir = Path(tmp_dir) / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
            python_bin = venv_dir / "bin" / "python"
            agentharness_bin = venv_dir / "bin" / "agentharness"
            subprocess.run([str(python_bin), "-m", "pip", "install", "-q", "-e", str(REPO_ROOT)], check=True)

            completed = subprocess.run(
                [
                    str(agentharness_bin),
                    "verify-run",
                    "--run",
                    str(RUN_LIE_FIXTURE),
                    "--claims",
                    str(CLAIMS_LIE_FIXTURE),
                    "--json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["ok"])
            claim = next(item for item in payload["results"] if item["claim_id"] == "claim_tests_lie")
            self.assertEqual(claim["status"], "unsupported")
            self.assertEqual(claim["truth_source"], "reexecuted")
            self.assertIn("authoritative", claim["reason"])
            self.assertTrue(any(path.endswith(".stdout") for path in claim["evidence"]))


if __name__ == "__main__":
    unittest.main()
