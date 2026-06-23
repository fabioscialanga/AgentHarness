from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from agentharness.benchmarking import render_json_template, write_rendered_json_template
from agentharness.evaluation import evaluate_run

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
TASK_IDS = [
    "support-ticket-api",
    "inventory-adjustment-api",
    "webhook-ingestion-service",
    "report-export-job",
    "leave-request-api",
    "incident-escalation-api",
    "refund-approval-api",
    "csv-member-import",
]


def _synthesize_schema_value(schema: Mapping[str, object]) -> object:
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required", [])
        if not isinstance(required, list):
            required = []
        payload: dict[str, object] = {}
        for key in required:
            child = properties.get(key, {"type": "string"})
            if not isinstance(child, dict):
                child = {"type": "string"}
            payload[str(key)] = _synthesize_schema_value(child)
        return payload
    if schema_type == "array":
        items = schema.get("items", {"type": "string"})
        if not isinstance(items, dict):
            items = {"type": "string"}
        return [_synthesize_schema_value(items)]
    if schema_type == "boolean":
        return True
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    return "ok"


def _write_hidden_evaluator_outputs(workspace: Path, task_id: str, suite_payload: dict[str, object]) -> None:
    summary_lines: list[str] = []
    cases = suite_payload.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_type = str(case.get("type", ""))
        relative_path = str(case.get("path", ""))
        expected = case.get("expected", {})
        if not isinstance(expected, dict):
            expected = {}
        output_path = workspace / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if case_type == "text_contains":
            contains = expected.get("contains", [])
            if isinstance(contains, list):
                summary_lines.extend(str(item) for item in contains)
        elif case_type == "json_schema":
            schema = expected.get("schema", {})
            if not isinstance(schema, dict):
                schema = {"type": "object"}
            output_path.write_text(json.dumps(_synthesize_schema_value(schema), indent=2) + "\n", encoding="utf-8")
    summary_path = workspace / ".agentharness" / "evaluation" / task_id / "summary.txt"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


class BenchmarkEvaluationSuiteTests(unittest.TestCase):
    def test_render_json_template_replaces_run_id_placeholder(self) -> None:
        template_path = BENCHMARKS_DIR / "support-ticket-api" / "HELDOUT_EVALUATION_SUITE.template.json"
        rendered = render_json_template(template_path, run_id="bench_run_001")
        self.assertEqual(rendered["run_id"], "bench_run_001")
        self.assertEqual(rendered["suite_id"], "support-ticket-api_heldout_eval")

    def test_all_benchmark_task_suites_pass_with_hidden_outputs_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            for task_id in TASK_IDS:
                run_id = f"{task_id.replace('-', '_')}_run_001"
                task_dir = temp_root / task_id
                workspace = task_dir / "workspace"
                workspace.mkdir(parents=True)
                suite_template_path = BENCHMARKS_DIR / task_id / "HELDOUT_EVALUATION_SUITE.template.json"
                suite_path = task_dir / "suite.json"
                run_path = task_dir / "run.json"
                rendered_suite = render_json_template(suite_template_path, run_id=run_id)
                suite_path.write_text(json.dumps(rendered_suite, indent=2) + "\n", encoding="utf-8")
                _write_hidden_evaluator_outputs(workspace, task_id, rendered_suite)
                run_path.write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "workspace": str(workspace),
                            "artifacts": {
                                "changed_files": [],
                                "commands": [],
                                "outputs": [
                                    {"type": "file", "path": f".agentharness/evaluation/{task_id}/summary.txt"},
                                    {"type": "file", "path": f".agentharness/evaluation/{task_id}/result.json"},
                                ],
                            },
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result = evaluate_run(run_path, suite_path)
                self.assertTrue(result.ok, f"evaluation failed for {task_id}: {result.to_dict()}")
                self.assertEqual(result.summary["failed"], 0)
                self.assertGreaterEqual(result.summary["passed"], 1)

    def test_cli_render_then_evaluate_support_ticket_suite_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            task_id = "support-ticket-api"
            run_id = "support_ticket_cli_001"
            workspace = temp_root / "workspace"
            workspace.mkdir()
            template_path = BENCHMARKS_DIR / task_id / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = temp_root / "suite.json"
            run_path = temp_root / "run.json"

            render_command = [
                sys.executable,
                "-m",
                "agentharness",
                "render-evaluation-suite",
                "--template",
                str(template_path),
                "--run-id",
                run_id,
                "--output",
                str(suite_path),
                "--json",
            ]
            rendered = subprocess.run(render_command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            render_payload = json.loads(rendered.stdout)
            self.assertEqual(render_payload["run_id"], run_id)
            suite_payload = json.loads(suite_path.read_text(encoding="utf-8"))

            _write_hidden_evaluator_outputs(workspace, task_id, suite_payload)
            run_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "workspace": str(workspace),
                        "artifacts": {"changed_files": [], "commands": [], "outputs": []},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            evaluate_command = [
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
            completed = subprocess.run(evaluate_command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertGreaterEqual(payload["summary"]["passed"], 1)

    def test_cli_evaluate_fails_when_hidden_summary_is_missing_required_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            task_id = "support-ticket-api"
            run_id = "support_ticket_cli_fail_001"
            workspace = temp_root / "workspace"
            workspace.mkdir()
            template_path = BENCHMARKS_DIR / task_id / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")
            suite_payload = json.loads(Path(suite_path).read_text(encoding="utf-8"))
            _write_hidden_evaluator_outputs(workspace, task_id, suite_payload)
            summary_path = workspace / ".agentharness" / "evaluation" / task_id / "summary.txt"
            summary_path.write_text("create_valid_ticket=pass\n", encoding="utf-8")
            run_path = temp_root / "run.json"
            run_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "workspace": str(workspace),
                        "artifacts": {"changed_files": [], "commands": [], "outputs": []},
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
            self.assertEqual(completed.returncode, 1, completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["ok"])
            self.assertGreaterEqual(payload["summary"]["failed"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()