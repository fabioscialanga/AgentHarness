from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentharness.benchmark_cells import (
    AgentAttempt,
    AgentInvocationResult,
    HermesCliInvoker,
    _build_agentharness_repair_prompt,
    _build_baseline_repair_prompt,
    _build_initial_prompt,
    _is_retryable_invocation_failure,
    assert_nonshared_solution_hashes,
    compute_solution_hash,
    execute_cell,
    prepare_fresh_cell,
)


class _FakeInvoker:
    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path) -> AgentInvocationResult:
        outputs_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        task_id = str(manifest["task_id"])
        condition = str(manifest["condition"])
        replicate_id = str(manifest["replicate_id"])
        package_dir = workspace / task_id.replace("-", "_")
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        (package_dir / "main.py").write_text(
            f"VALUE = {condition!r}\nREPLICATE = {replicate_id!r}\n",
            encoding="utf-8",
        )
        tests_dir = workspace / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_smoke.py").write_text(
            "def test_smoke():\n    assert True\n",
            encoding="utf-8",
        )
        (workspace / "README.md").write_text(f"# {task_id} {condition}\n", encoding="utf-8")
        (workspace / "pyproject.toml").write_text(
            "[project]\nname='demo'\nversion='0.1.0'\ndependencies=[]\n",
            encoding="utf-8",
        )
        attempts_dir = outputs_dir / "agent-invocations"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        attempts: list[AgentAttempt] = []
        for index, prompt_kind in enumerate(("initial", "repair"), start=1):
            stdout_path = attempts_dir / f"attempt-{index}.stdout"
            stderr_path = attempts_dir / f"attempt-{index}.stderr"
            stdout_path.write_text(f"session_id: fake_{condition}_{replicate_id}_{index}\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            attempts.append(
                AgentAttempt(
                    attempt_name=f"attempt-{index}",
                    prompt_kind=prompt_kind,
                    command=["fake-agent", prompt_kind],
                    exit_code=0,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    working_directory=workspace,
                    session_id=f"fake_{condition}_{replicate_id}_{index}",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    duration_seconds=1.0,
                )
            )
        return AgentInvocationResult(attempts=attempts)


class BenchmarkCellsTests(unittest.TestCase):
    def test_prepare_fresh_cell_copies_only_allowed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "support-ticket-api" / "A-baseline" / "r1"
            manifest = prepare_fresh_cell(
                task_id="support-ticket-api",
                condition="A-baseline",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            self.assertEqual(manifest["task_id"], "support-ticket-api")
            inputs_dir = cell_dir / "inputs"
            self.assertEqual(
                {path.name for path in inputs_dir.iterdir() if path.is_file()},
                {"SPEC.md", "CLAIMS_CONTRACT.template.json"},
            )
            self.assertFalse((inputs_dir / "QUALITY_GATE.md").exists())
            self.assertTrue((cell_dir / "cell_manifest.json").is_file())
            self.assertTrue((cell_dir / "workspace").is_dir())

    def test_prompts_use_relative_cell_paths_and_do_not_expose_task_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "support-ticket-api" / "B-agentharness" / "r1"
            prepare_fresh_cell(
                task_id="support-ticket-api",
                condition="B-agentharness",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            workspace = cell_dir / "workspace"
            spec_path = cell_dir / "inputs" / "SPEC.md"
            claims_template_path = cell_dir / "inputs" / "CLAIMS_CONTRACT.template.json"
            pytest_stdout_path = cell_dir / "outputs" / "pre-repair-pytest.stdout"
            pytest_stderr_path = cell_dir / "outputs" / "pre-repair-pytest.stderr"
            verify_feedback_path = cell_dir / "outputs" / "pre-repair-verify-run-report.json"
            initial_prompt = _build_initial_prompt(
                task_id="support-ticket-api",
                condition="B-agentharness",
                workspace=workspace,
                spec_path=spec_path,
                claims_template_path=claims_template_path,
            )
            baseline_repair_prompt = _build_baseline_repair_prompt(
                task_id="support-ticket-api",
                workspace=workspace,
                spec_path=spec_path,
                pytest_stdout_path=pytest_stdout_path,
                pytest_stderr_path=pytest_stderr_path,
            )
            agentharness_repair_prompt = _build_agentharness_repair_prompt(
                task_id="support-ticket-api",
                workspace=workspace,
                spec_path=spec_path,
                pytest_stdout_path=pytest_stdout_path,
                pytest_stderr_path=pytest_stderr_path,
                verify_feedback_path=verify_feedback_path,
            )

            task_dir = str((Path(__file__).resolve().parents[1] / "benchmarks" / "support-ticket-api").resolve())
            self.assertIn("../inputs/SPEC.md", initial_prompt)
            self.assertIn("../inputs/CLAIMS_CONTRACT.template.json", initial_prompt)
            self.assertIn("../inputs/SPEC.md", baseline_repair_prompt)
            self.assertIn("../inputs/SPEC.md", agentharness_repair_prompt)
            self.assertIn("../outputs/pre-repair-pytest.stdout", baseline_repair_prompt)
            self.assertIn("../outputs/pre-repair-pytest.stderr", baseline_repair_prompt)
            self.assertIn("../outputs/pre-repair-verify-run-report.json", agentharness_repair_prompt)
            for prompt in (initial_prompt, baseline_repair_prompt, agentharness_repair_prompt):
                self.assertNotIn(task_dir, prompt)
                self.assertNotIn(str(workspace), prompt)
                self.assertNotIn(str(spec_path), prompt)
                self.assertNotIn(str(claims_template_path), prompt)
                self.assertNotIn(str(pytest_stdout_path), prompt)
                self.assertNotIn(str(pytest_stderr_path), prompt)
            self.assertNotIn(str(verify_feedback_path), agentharness_repair_prompt)

    def test_execute_cell_records_provenance_and_solution_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "support-ticket-api" / "A-baseline" / "r1"
            prepare_fresh_cell(
                task_id="support-ticket-api",
                condition="A-baseline",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            stdout_path = cell_dir / "outputs" / "pytest.stdout"
            stderr_path = cell_dir / "outputs" / "pytest.stderr"
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_path.write_text("1 passed\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            pytest_payload = {
                "command": ["python", "-m", "pytest", "-q"],
                "exit_code": 0,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "duration_seconds": 1.0,
            }
            with (
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
                mock.patch("agentharness.benchmark_cells.run_verify_run", return_value={"ok": True}),
                mock.patch(
                    "agentharness.benchmark_cells.run_hidden_benchmark",
                    return_value={"execution_status": "valid", "outcome_status": "success"},
                ),
                mock.patch(
                    "agentharness.benchmark_cells.run_heldout_evaluation",
                    return_value={
                        "summary": {"passed": 1, "failed": 0, "invalid": 0},
                        "results": [{"status": "passed"}],
                    },
                ),
            ):
                result = execute_cell(cell_dir, _FakeInvoker())

            provenance = json.loads((cell_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["attempt_count"], 2)
            self.assertEqual(result["attempt_count"], 2)
            self.assertTrue(provenance["solution_hash"])
            self.assertEqual(provenance["solution_hash"], result["solution_hash"])
            self.assertTrue((cell_dir / "run.json").is_file())
            self.assertTrue((cell_dir / "claims.json").is_file())

    def test_assert_nonshared_solution_hashes_fails_on_identical_hashes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Identical solution_hash"):
            assert_nonshared_solution_hashes(
                [
                    {"task_id": "support-ticket-api", "solution_hash": "abc"},
                    {"task_id": "support-ticket-api", "solution_hash": "abc"},
                    {"task_id": "support-ticket-api", "solution_hash": "abc"},
                    {"task_id": "support-ticket-api", "solution_hash": "abc"},
                ]
            )

    def test_compute_solution_hash_changes_when_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("a\n", encoding="utf-8")
            first = compute_solution_hash(workspace)
            (workspace / "README.md").write_text("b\n", encoding="utf-8")
            second = compute_solution_hash(workspace)
            self.assertNotEqual(first, second)

    def test_execute_cell_clears_stale_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "support-ticket-api" / "A-baseline" / "r1"
            manifest = prepare_fresh_cell(
                task_id="support-ticket-api",
                condition="A-baseline",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            workspace = Path(str(manifest["workspace"]))
            stale_paths = [
                cell_dir / "outputs" / "benchmark-evaluate-task.json",
                cell_dir / "metadata.json",
                workspace / ".agentharness" / "evaluation" / "support-ticket-api" / "result.json",
                workspace / ".agentharness" / "traces" / "evaluation" / "old.jsonl",
                workspace / ".agentharness" / "traces" / "verify-run" / "old.jsonl",
                workspace / ".agentharness" / "evidence" / str(manifest["run_id"]) / "reexecuted" / "command.stdout",
            ]
            for path in stale_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("stale\n", encoding="utf-8")
            stdout_path = cell_dir / "tmp-pytest.stdout"
            stderr_path = cell_dir / "tmp-pytest.stderr"
            stdout_path.write_text("1 passed\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            pytest_payload = {
                "command": ["python", "-m", "pytest", "-q"],
                "exit_code": 0,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "duration_seconds": 1.0,
            }
            with (
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
                mock.patch("agentharness.benchmark_cells.run_verify_run", return_value={"ok": True}),
                mock.patch("agentharness.benchmark_cells.run_hidden_benchmark", return_value={"execution_status": "valid", "outcome_status": "success"}),
                mock.patch("agentharness.benchmark_cells.run_heldout_evaluation", return_value={"summary": {"passed": 1, "failed": 0, "invalid": 0}, "results": [{"status": "passed"}]}),
            ):
                execute_cell(cell_dir, _FakeInvoker())
            self.assertFalse((workspace / ".agentharness" / "traces" / "evaluation" / "old.jsonl").exists())
            self.assertFalse((workspace / ".agentharness" / "traces" / "verify-run" / "old.jsonl").exists())
            self.assertFalse((workspace / ".agentharness" / "evidence" / str(manifest["run_id"]) / "reexecuted" / "command.stdout").exists())

    def test_retryable_invocation_failure_detects_rate_limit_markers(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=1,
            stdout="API call failed after 3 retries: HTTP 429: The usage limit has been reached\n",
            stderr="",
        )
        self.assertTrue(_is_retryable_invocation_failure(completed))

    def test_invoke_retries_with_backoff_on_retryable_failure(self) -> None:
        completed_retry = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=1,
            stdout="API call failed after 3 retries: HTTP 429: The usage limit has been reached\n",
            stderr="",
        )
        completed_success = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=0,
            stdout="session_id: ok_123\n",
            stderr="",
        )
        invoker = HermesCliInvoker(hermes_command="hermes", retry_backoff_seconds=0.01)
        with tempfile.TemporaryDirectory() as tmp_dir:
            outputs_dir = Path(tmp_dir)
            with (
                mock.patch("agentharness.benchmark_cells.subprocess.run", side_effect=[completed_retry, completed_success]) as run_mock,
                mock.patch("agentharness.benchmark_cells.time.sleep") as sleep_mock,
            ):
                attempt = invoker._invoke(
                    prompt="hello",
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    outputs_dir=outputs_dir,
                    workspace=outputs_dir,
                )
        self.assertEqual(attempt.exit_code, 0)
        self.assertEqual(attempt.session_id, "ok_123")
        self.assertEqual(attempt.working_directory, outputs_dir)
        self.assertEqual(run_mock.call_args_list[0].kwargs["cwd"], str(outputs_dir))
        self.assertEqual(run_mock.call_args_list[1].kwargs["cwd"], str(outputs_dir))
        sleep_mock.assert_called_once_with(0.01)

    def test_run_cell_invokes_agent_in_workspace(self) -> None:
        invoker = HermesCliInvoker(hermes_command="hermes", max_retries=1)
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            spec_path = root / "SPEC.md"
            claims_template_path = root / "CLAIMS_CONTRACT.template.json"
            spec_path.write_text("spec\n", encoding="utf-8")
            claims_template_path.write_text("{}\n", encoding="utf-8")
            outputs_dir = root / "outputs"
            manifest: dict[str, object] = {
                "task_id": "support-ticket-api",
                "condition": "A-baseline",
                "run_id": "stageb_support_ticket_api_a_r1",
                "spec_path": str(spec_path),
                "claims_template_path": str(claims_template_path),
            }
            stdout_path = root / "pytest.stdout"
            stderr_path = root / "pytest.stderr"
            stdout_path.write_text("1 passed\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            pytest_payload = {
                "command": ["python", "-m", "pytest", "-q"],
                "exit_code": 0,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "duration_seconds": 1.0,
            }
            completed = subprocess.CompletedProcess(args=["hermes"], returncode=0, stdout="session_id: ok_123\n", stderr="")
            with (
                mock.patch("agentharness.benchmark_cells.subprocess.run", return_value=completed) as run_mock,
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
            ):
                result = invoker.run_cell(manifest, outputs_dir, workspace)
        self.assertEqual(len(result.attempts), 2)
        self.assertTrue(all(attempt.working_directory == workspace for attempt in result.attempts))
        hermes_calls = [call for call in run_mock.call_args_list if call.args and call.args[0] and call.args[0][0] == "hermes"]
        self.assertEqual(len(hermes_calls), 2)
        self.assertTrue(all(call.kwargs["cwd"] == str(workspace) for call in hermes_calls))


if __name__ == "__main__":
    unittest.main()
