from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentharness.evaluation import evaluate_run
from agentharness.resilience import run_resilience_plan
from agentharness.verify import verify_run

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
RUN_FIXTURE = FIXTURES / "run_invite_success.json"
CLAIMS_FIXTURE = FIXTURES / "claims_invite_success.json"


class RuntimeFeaturesTests(unittest.TestCase):
    def test_verify_run_can_emit_structured_trace_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "verify-run.jsonl"
            result = verify_run(RUN_FIXTURE, CLAIMS_FIXTURE, trace_path=trace_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.trace_path, str(trace_path.resolve()))
            lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(lines), 3)
            event_types = [json.loads(line)["event_type"] for line in lines]
            self.assertIn("verify_run_started", event_types)
            self.assertIn("verify_run_claim_finished", event_types)
            self.assertIn("verify_run_finished", event_types)

    def test_evaluate_run_passes_text_and_schema_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "answer.txt").write_text("status: ok\nsummary: invite created\n", encoding="utf-8")
            (workspace / "result.json").write_text(
                json.dumps({"status": "ok", "count": 1}, indent=2) + "\n",
                encoding="utf-8",
            )
            run_path = Path(tmp_dir) / "run.json"
            run_path.write_text(
                json.dumps(
                    {
                        "run_id": "eval_run_001",
                        "workspace": str(workspace),
                        "artifacts": {"changed_files": [], "commands": [], "outputs": []},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            suite_path = Path(tmp_dir) / "suite.json"
            suite_path.write_text(
                json.dumps(
                    {
                        "suite_id": "eval_suite_001",
                        "run_id": "eval_run_001",
                        "cases": [
                            {
                                "id": "case_text",
                                "type": "text_contains",
                                "path": "answer.txt",
                                "expected": {
                                    "contains": ["status: ok", "invite created"],
                                    "forbidden": ["Traceback"],
                                },
                            },
                            {
                                "id": "case_schema",
                                "type": "json_schema",
                                "path": "result.json",
                                "expected": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["status", "count"],
                                        "properties": {
                                            "status": {"type": "string"},
                                            "count": {"type": "integer"},
                                        },
                                        "additionalProperties": False,
                                    }
                                },
                            },
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            trace_path = Path(tmp_dir) / "evaluate.jsonl"
            result = evaluate_run(run_path, suite_path, trace_path=trace_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.summary["passed"], 2)
            self.assertTrue(trace_path.is_file())
            event_types = [json.loads(line)["event_type"] for line in trace_path.read_text(encoding="utf-8").splitlines()]
            self.assertIn("evaluation_started", event_types)
            self.assertIn("evaluation_case_finished", event_types)
            self.assertIn("evaluation_finished", event_types)

    def test_evaluate_run_reports_failure_for_missing_required_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "answer.txt").write_text("status: degraded\n", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            suite_path = Path(tmp_dir) / "suite.json"
            run_path.write_text(
                json.dumps(
                    {
                        "run_id": "eval_run_002",
                        "workspace": str(workspace),
                        "artifacts": {"changed_files": [], "commands": [], "outputs": []},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            suite_path.write_text(
                json.dumps(
                    {
                        "suite_id": "eval_suite_002",
                        "run_id": "eval_run_002",
                        "cases": [
                            {
                                "id": "case_text",
                                "type": "text_contains",
                                "path": "answer.txt",
                                "expected": {"contains": ["status: ok"]},
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            result = evaluate_run(run_path, suite_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["failed"], 1)
            self.assertIn("missing required text", result.results[0].reason)

    def test_run_plan_retries_then_uses_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            primary = workspace / "primary.py"
            fallback = workspace / "fallback.py"
            primary.write_text(
                "from pathlib import Path\n"
                "counter = Path('primary.count')\n"
                "count = int(counter.read_text() if counter.exists() else '0') + 1\n"
                "counter.write_text(str(count))\n"
                "print(f'primary attempt {count}')\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            fallback.write_text(
                "print('fallback success')\n",
                encoding="utf-8",
            )
            plan_path = Path(tmp_dir) / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "plan_id": "plan_001",
                        "workspace": str(workspace),
                        "steps": [
                            {
                                "id": "provider_call",
                                "description": "try primary provider then fallback",
                                "success_exit_codes": [0],
                                "targets": [
                                    {
                                        "name": "primary",
                                        "command": f"{sys.executable} primary.py",
                                        "retry": {
                                            "max_attempts": 2,
                                            "backoff_seconds": 0.01,
                                            "retry_on_exit_codes": [1],
                                        },
                                    },
                                    {
                                        "name": "fallback",
                                        "command": f"{sys.executable} fallback.py",
                                        "retry": {"max_attempts": 1},
                                    },
                                ],
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            trace_path = Path(tmp_dir) / "plan.jsonl"
            result = run_resilience_plan(plan_path, trace_path=trace_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.steps[0].winner, "fallback")
            self.assertEqual([attempt.target_name for attempt in result.steps[0].attempts], ["primary", "primary", "fallback"])
            self.assertTrue(trace_path.is_file())
            event_types = [json.loads(line)["event_type"] for line in trace_path.read_text(encoding="utf-8").splitlines()]
            self.assertIn("resilience_plan_started", event_types)
            self.assertIn("resilience_attempt_finished", event_types)
            self.assertIn("resilience_plan_finished", event_types)
            self.assertEqual((workspace / "primary.count").read_text(encoding="utf-8"), "2")

    def test_cli_evaluate_command_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "answer.txt").write_text("status: ok\n", encoding="utf-8")
            run_path = Path(tmp_dir) / "run.json"
            suite_path = Path(tmp_dir) / "suite.json"
            run_path.write_text(
                json.dumps(
                    {
                        "run_id": "eval_run_cli",
                        "workspace": str(workspace),
                        "artifacts": {"changed_files": [], "commands": [], "outputs": []},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            suite_path.write_text(
                json.dumps(
                    {
                        "suite_id": "eval_suite_cli",
                        "run_id": "eval_run_cli",
                        "cases": [
                            {
                                "id": "case_text",
                                "type": "text_contains",
                                "path": "answer.txt",
                                "expected": {"contains": ["status: ok"]},
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "-m",
                "agentharness",
                "evaluate",
                "--run",
                str(run_path),
                "--suite",
                str(suite_path),
                "--json",
            ]
            completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["passed"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
