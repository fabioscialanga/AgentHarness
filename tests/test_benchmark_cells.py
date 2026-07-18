from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from agentharness.benchmark_cells import (
    AgentAttempt,
    AgentInvocationResult,
    ClassifiedCellFailure,
    GRADING_ENV_DIR,
    HermesCliInvoker,
    _build_agentharness_repair_prompt,
    _build_baseline_repair_prompt,
    _build_initial_prompt,
    _classify_empty_workspace_failure,
    _inspect_verify_feedback_report,
    _is_retryable_invocation_failure,
    assert_nonshared_solution_hashes,
    compute_solution_hash,
    execute_cell,
    heldout_endpoint_error,
    heldout_suite_template_path,
    prepare_fresh_cell,
    replay_uncommitted_successful_invocations,
    score_from_evaluation,
    write_run_json,
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
        return AgentInvocationResult(
            attempts=attempts,
            attempt_solution_hashes={
                "attempt_1_initial": f"initial_{condition}_{replicate_id}",
                "attempt_2_repair": f"repair_{condition}_{replicate_id}",
            },
            treatment_delivery={
                "repair_invocation_succeeded": True,
                "treatment_prompt_immutable": True,
                "feedback_delivered": condition == "B-agentharness",
                "feedback_immutable": condition == "B-agentharness",
            },
        )


class _EmptyWorkspaceInvoker:
    def __init__(self, stdout_text: str, stderr_text: str = "") -> None:
        self._stdout_text = stdout_text
        self._stderr_text = stderr_text

    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path) -> AgentInvocationResult:
        outputs_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        attempts_dir = outputs_dir / "agent-invocations"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = attempts_dir / "attempt-1.stdout"
        stderr_path = attempts_dir / "attempt-1.stderr"
        stdout_path.write_text(self._stdout_text, encoding="utf-8")
        stderr_path.write_text(self._stderr_text, encoding="utf-8")
        return AgentInvocationResult(
            attempts=[
                AgentAttempt(
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    command=["fake-agent", "initial"],
                    exit_code=1,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    working_directory=workspace,
                    session_id="fake_session",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    duration_seconds=1.0,
                )
            ]
        )


class _NoEvidenceInvoker:
    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path) -> AgentInvocationResult:
        outputs_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        attempts_dir = outputs_dir / "agent-invocations"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = attempts_dir / "attempt-1.stdout"
        stderr_path = attempts_dir / "attempt-1.stderr"
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return AgentInvocationResult(
            attempts=[
                AgentAttempt(
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    command=["fake-agent", "initial"],
                    exit_code=1,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    working_directory=workspace,
                    session_id=None,
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    duration_seconds=1.0,
                )
            ]
        )


class _PreRepairFailureInvoker:
    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path) -> AgentInvocationResult:
        outputs_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        attempts_dir = outputs_dir / "agent-invocations"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = attempts_dir / "attempt-1.stdout"
        stderr_path = attempts_dir / "attempt-1.stderr"
        stdout_path.write_text("session_id: fake_session\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        raise ClassifiedCellFailure(
            "harness_invalid",
            f"Offline shared deps install failed for {workspace}: boom",
            invocation_result=AgentInvocationResult(
                attempts=[
                    AgentAttempt(
                        attempt_name="attempt-1",
                        prompt_kind="initial",
                        command=["fake-agent", "initial"],
                        exit_code=0,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        working_directory=workspace,
                        session_id="fake_session",
                        started_at="2026-01-01T00:00:00Z",
                        finished_at="2026-01-01T00:00:01Z",
                        duration_seconds=1.0,
                    )
                ]
            ),
        )


class BenchmarkCellsTests(unittest.TestCase):
    def test_heldout_suite_resolver_supports_legacy_and_hidden_batch3_envelopes(self) -> None:
        legacy = heldout_suite_template_path("refund-approval-api")
        hidden = heldout_suite_template_path("pii-redaction-pipeline")
        self.assertEqual(legacy.name, "HELDOUT_EVALUATION_SUITE.template.json")
        self.assertEqual(hidden.name, "pii-redaction-pipeline.json")
        self.assertIn("stage2-heldout-suites", hidden.parts)
        self.assertTrue(legacy.is_file())
        self.assertTrue(hidden.is_file())

    def test_hidden_batch3_suite_envelopes_match_frozen_evaluator_check_ids(self) -> None:
        from agentharness.benchmark_hidden_evaluators_batch3_lease import CHECKS as lease_checks
        from agentharness.benchmark_hidden_evaluators_batch3_ledger import CHECKS as ledger_checks
        from agentharness.benchmark_hidden_evaluators_batch3_pii import _CHECKS as pii_checks
        from agentharness.benchmark_hidden_evaluators_batch3_signed import CHECKS as signed_checks

        expected = {
            "pii-redaction-pipeline": pii_checks,
            "signed-artifact-verifier": signed_checks,
            "lease-coordination-api": lease_checks,
            "double-entry-ledger-api": ledger_checks,
        }
        for task_id, check_ids in expected.items():
            payload = json.loads(heldout_suite_template_path(task_id).read_text(encoding="utf-8"))
            observed = tuple(case["id"] for case in payload["cases"])
            self.assertEqual(observed, tuple(check_ids) + ("evaluation_result_schema",))

    def _build_replay_guard_fixture(
        self,
        root: Path,
        *,
        condition: str = "A-baseline",
        attempt_count: int = 2,
        failing_attempt: int | None = None,
        missing_session_attempt: int | None = None,
        prompt_text: str = "Repair without feedback.\n",
        hash_mismatch: bool = False,
    ) -> Path:
        cell_dir = root / "cell"
        workspace = cell_dir / "workspace"
        outputs = cell_dir / "outputs"
        snapshot = outputs / "pre-repair-workspace"
        attempts_dir = outputs / "agent-invocations"
        workspace.mkdir(parents=True)
        snapshot.mkdir(parents=True)
        attempts_dir.mkdir(parents=True)
        (workspace / "solution.py").write_text("VALUE = 2\n" if hash_mismatch else "VALUE = 1\n", encoding="utf-8")
        (snapshot / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
        (cell_dir / "cell_manifest.json").write_text(
            json.dumps({"condition": condition, "workspace": str(workspace)}) + "\n",
            encoding="utf-8",
        )
        (outputs / "pre-repair-treatment-prompt.txt").write_text(prompt_text, encoding="utf-8")
        for index in range(1, attempt_count + 1):
            attempt_name = "attempt-1-initial" if index == 1 else "attempt-2-repair"
            stdout_path = attempts_dir / f"{attempt_name}.stdout"
            stderr_path = attempts_dir / f"{attempt_name}.stderr"
            stdout_path.write_text("agent completed\n", encoding="utf-8")
            stderr_path.write_text(
                "" if missing_session_attempt == index else f"session_id: replay_{index}\n",
                encoding="utf-8",
            )
            payload = {
                "attempt_name": attempt_name,
                "prompt_kind": "initial" if index == 1 else "repair",
                "command": ["hermes", "chat"],
                "exit_code": 1 if failing_attempt == index else 0,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "working_directory": str(workspace),
                "session_id": None,
                "started_at": "2026-07-18T00:00:00Z",
                "finished_at": "2026-07-18T00:00:01Z",
                "duration_seconds": 1.0,
            }
            (attempts_dir / f"{attempt_name}.meta.json").write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        return cell_dir

    def test_replay_guards_fail_closed_before_scoring(self) -> None:
        cases = {
            "wrong_condition": {"condition": "B-agentharness"},
            "wrong_attempt_count": {"attempt_count": 1},
            "nonzero_exit": {"failing_attempt": 2},
            "missing_session": {"missing_session_attempt": 2},
            "empty_prompt": {"prompt_text": ""},
            "hash_mismatch": {"hash_mismatch": True},
        }
        for label, kwargs in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp_dir:
                cell_dir = self._build_replay_guard_fixture(Path(tmp_dir), **kwargs)
                with self.assertRaises(ValueError):
                    replay_uncommitted_successful_invocations(cell_dir)
                self.assertFalse((cell_dir / "run.json").exists())
                self.assertFalse((cell_dir / "cell-result.json").exists())

    def test_heldout_endpoint_requires_exactly_six_terminal_cases(self) -> None:
        valid = {
            "ok": True,
            "results": [
                {"status": "passed"},
                {"status": "passed"},
                {"status": "passed"},
                {"status": "failed"},
                {"status": "failed"},
                {"status": "failed"},
            ],
        }
        self.assertIsNone(heldout_endpoint_error(valid))
        self.assertEqual(score_from_evaluation(valid), 0.5)

        wrong_count = {"ok": True, "results": [{"status": "passed"}] * 5}
        self.assertEqual(heldout_endpoint_error(wrong_count), "heldout_case_count_mismatch:5!=6")
        self.assertEqual(score_from_evaluation(wrong_count), 0.0)

        invalid_status = {"ok": True, "results": [{"status": "passed"}] * 5 + [{"status": "invalid"}]}
        self.assertEqual(heldout_endpoint_error(invalid_status), "heldout_case_status_invalid")
        self.assertEqual(score_from_evaluation(invalid_status), 0.0)

    def test_heldout_endpoint_requires_successful_evaluator(self) -> None:
        payload = {"ok": False, "results": [{"status": "passed"}] * 6}
        self.assertEqual(heldout_endpoint_error(payload), "heldout_evaluation_not_ok")
        self.assertEqual(score_from_evaluation(payload), 0.0)

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

    def test_prompts_use_cell_local_absolute_paths_and_do_not_expose_task_dir(self) -> None:
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
            baseline_cell_dir = Path(tmp_dir) / "cell-a-distinct"
            baseline_initial_prompt = _build_initial_prompt(
                task_id="support-ticket-api",
                condition="A-baseline",
                workspace=baseline_cell_dir / "workspace",
                spec_path=baseline_cell_dir / "inputs" / "SPEC.md",
                claims_template_path=baseline_cell_dir / "inputs" / "CLAIMS_CONTRACT.template.json",
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
            self.assertNotIn(str(workspace.resolve()), initial_prompt)
            self.assertIn("../inputs/SPEC.md", initial_prompt)
            self.assertIn("../inputs/CLAIMS_CONTRACT.template.json", initial_prompt)
            self.assertEqual(initial_prompt, baseline_initial_prompt)
            self.assertNotIn("Condition A", initial_prompt)
            self.assertNotIn("Condition B", initial_prompt)
            self.assertNotIn(str(workspace.resolve()), baseline_repair_prompt)
            self.assertIn("../inputs/SPEC.md", baseline_repair_prompt)
            self.assertIn("../outputs/pre-repair-pytest.stdout", baseline_repair_prompt)
            self.assertIn("../outputs/pre-repair-pytest.stderr", baseline_repair_prompt)
            self.assertNotIn(str(workspace.resolve()), agentharness_repair_prompt)
            self.assertIn("../inputs/SPEC.md", agentharness_repair_prompt)
            self.assertIn("../outputs/pre-repair-pytest.stdout", agentharness_repair_prompt)
            self.assertIn("../outputs/pre-repair-pytest.stderr", agentharness_repair_prompt)
            self.assertIn("../outputs/pre-repair-verify-run-report.json", agentharness_repair_prompt)
            b_only = set(agentharness_repair_prompt.splitlines()) - set(baseline_repair_prompt.splitlines())
            self.assertEqual(
                b_only,
                {"Consult the structured AgentHarness verify-run feedback: ../outputs/pre-repair-verify-run-report.json"},
            )
            for prompt in (initial_prompt, baseline_repair_prompt, agentharness_repair_prompt):
                self.assertNotIn(task_dir, prompt)
                self.assertNotIn(str((Path(__file__).resolve().parents[1] / "benchmarks").resolve()), prompt)

    def test_write_run_json_preserves_canonical_pytest_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            python_path = workspace / ".stageb-test-venv" / "bin" / "python"
            report_path = root / "run.json"
            stdout_path = root / "pytest.stdout"
            stderr_path = root / "pytest.stderr"
            write_run_json(
                run_path=report_path,
                manifest={"run_id": "run-1", "task_id": "task-1"},
                workspace=workspace,
                pytest_command=[str(python_path), "-m", "pytest", "-q"],
                pytest_exit=0,
                pytest_stdout_path=stdout_path,
                pytest_stderr_path=stderr_path,
            )
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            command = payload["artifacts"]["commands"][0]
            self.assertIn(str(python_path), command["cmd"])
            self.assertEqual(
                command["environment"],
                {
                    "PYTHONPATH": str(workspace.resolve()),
                    "AGENTHARNESS_GRADING_ENV_DIR": str(GRADING_ENV_DIR.resolve()),
                },
            )

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
                        "ok": True,
                        "summary": {"passed": 6, "failed": 0, "invalid": 0},
                        "results": [{"status": "passed"} for _ in range(6)],
                    },
                ),
            ):
                result = execute_cell(cell_dir, _FakeInvoker())

            provenance = json.loads((cell_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["attempt_count"], 2)
            self.assertEqual(result["attempt_count"], 2)
            self.assertTrue(provenance["solution_hash"])
            self.assertEqual(provenance["solution_hash"], result["solution_hash"])
            self.assertEqual(
                provenance["attempt_solution_hashes"],
                {
                    "attempt_1_initial": "initial_A-baseline_r1",
                    "attempt_2_repair": "repair_A-baseline_r1",
                },
            )
            self.assertTrue(provenance["solution_hash_changed_between_attempt_and_repair"])
            self.assertTrue(result["solution_hash_changed_between_attempt_and_repair"])
            self.assertTrue(result["heldout_endpoint_valid"])
            self.assertEqual(result["heldout_endpoint_denominator"], 6)
            self.assertIsNone(result["heldout_endpoint_error"])
            metadata = json.loads((cell_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata["solution_hash_changed_between_attempt_and_repair"])
            self.assertTrue(metadata["heldout_endpoint_valid"])
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
                mock.patch("agentharness.benchmark_cells.run_heldout_evaluation", return_value={"ok": True, "summary": {"passed": 6, "failed": 0, "invalid": 0}, "results": [{"status": "passed"} for _ in range(6)]}),
            ):
                execute_cell(cell_dir, _FakeInvoker())
            self.assertFalse((workspace / ".agentharness" / "traces" / "evaluation" / "old.jsonl").exists())
            self.assertFalse((workspace / ".agentharness" / "traces" / "verify-run" / "old.jsonl").exists())
            self.assertFalse((workspace / ".agentharness" / "evidence" / str(manifest["run_id"]) / "reexecuted" / "command.stdout").exists())

    def test_execute_cell_classifies_empty_workspace_codex_sse_stall_as_provider_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "leave-request-api" / "B-agentharness" / "r2"
            prepare_fresh_cell(
                task_id="leave-request-api",
                condition="B-agentharness",
                replicate_id="r2",
                cell_dir=cell_dir,
            )
            result = execute_cell(
                cell_dir,
                _EmptyWorkspaceInvoker(
                    "session_id: fake_session\n",
                    "API call failed after 3 retries: Codex stream produced no SSE events for 12s after first byte (threshold: 12s)\n",
                ),
            )
            benchmark_payload = json.loads((cell_dir / "outputs" / "benchmark-evaluate-task.json").read_text(encoding="utf-8"))
            metadata = json.loads((cell_dir / "metadata.json").read_text(encoding="utf-8"))
            evaluation_summary = cast(dict[str, object], result["evaluation_summary"])
            self.assertEqual(result["benchmark_execution_status"], "harness_invalid")
            self.assertEqual(result["benchmark_outcome_status"], "invalid")
            self.assertTrue(str(result["benchmark_classification_reason"]).startswith("provider_unavailable:"))
            self.assertEqual(benchmark_payload["execution_status"], "harness_invalid")
            self.assertEqual(benchmark_payload["outcome_status"], "invalid")
            self.assertTrue(str(benchmark_payload["classification_reason"]).startswith("provider_unavailable:"))
            self.assertEqual(metadata["benchmark_execution_status"], "harness_invalid")
            self.assertEqual(metadata["benchmark_outcome_status"], "invalid")
            self.assertTrue(str(metadata["benchmark_classification_reason"]).startswith("provider_unavailable:"))
            self.assertEqual(evaluation_summary["invalid"], 1)
            self.assertTrue((cell_dir / "outputs" / "suite.json").is_file())
            self.assertTrue((cell_dir / "provenance.json").is_file())

    def test_execute_cell_classifies_empty_workspace_rate_limit_as_provider_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "leave-request-api" / "B-agentharness" / "r2"
            prepare_fresh_cell(
                task_id="leave-request-api",
                condition="B-agentharness",
                replicate_id="r2",
                cell_dir=cell_dir,
            )
            result = execute_cell(
                cell_dir,
                _EmptyWorkspaceInvoker("API call failed after 3 retries: HTTP 429: The usage limit has been reached\n"),
            )
            benchmark_payload = json.loads((cell_dir / "outputs" / "benchmark-evaluate-task.json").read_text(encoding="utf-8"))
            metadata = json.loads((cell_dir / "metadata.json").read_text(encoding="utf-8"))
            evaluation_summary = cast(dict[str, object], result["evaluation_summary"])
            self.assertEqual(result["benchmark_execution_status"], "harness_invalid")
            self.assertEqual(result["benchmark_outcome_status"], "invalid")
            self.assertTrue(str(result["benchmark_classification_reason"]).startswith("provider_unavailable:"))
            self.assertEqual(benchmark_payload["execution_status"], "harness_invalid")
            self.assertEqual(benchmark_payload["outcome_status"], "invalid")
            self.assertTrue(str(benchmark_payload["classification_reason"]).startswith("provider_unavailable:"))
            self.assertEqual(metadata["benchmark_execution_status"], "harness_invalid")
            self.assertEqual(metadata["benchmark_outcome_status"], "invalid")
            self.assertTrue(str(metadata["benchmark_classification_reason"]).startswith("provider_unavailable:"))
            self.assertEqual(evaluation_summary["invalid"], 1)
            self.assertTrue((cell_dir / "outputs" / "suite.json").is_file())
            self.assertTrue((cell_dir / "provenance.json").is_file())

    def test_execute_cell_classifies_empty_workspace_without_retryable_markers_as_harness_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "leave-request-api" / "B-agentharness" / "r2"
            prepare_fresh_cell(
                task_id="leave-request-api",
                condition="B-agentharness",
                replicate_id="r2",
                cell_dir=cell_dir,
            )
            result = execute_cell(
                cell_dir,
                _EmptyWorkspaceInvoker("session_id: fake_session\n", "unexpected non-provider failure\n"),
            )
            benchmark_payload = json.loads((cell_dir / "outputs" / "benchmark-evaluate-task.json").read_text(encoding="utf-8"))
            self.assertEqual(result["benchmark_execution_status"], "harness_invalid")
            self.assertEqual(result["benchmark_outcome_status"], "invalid")
            self.assertEqual(benchmark_payload["execution_status"], "harness_invalid")
            self.assertEqual(benchmark_payload["outcome_status"], "invalid")

    def test_execute_cell_classifies_missing_invocation_evidence_as_harness_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "leave-request-api" / "B-agentharness" / "r1"
            prepare_fresh_cell(
                task_id="leave-request-api",
                condition="B-agentharness",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            result = execute_cell(cell_dir, _NoEvidenceInvoker())
            payload = json.loads((cell_dir / "outputs" / "benchmark-evaluate-task.json").read_text(encoding="utf-8"))
            self.assertEqual(result["benchmark_execution_status"], "harness_invalid")
            self.assertIn("Missing invocation evidence", payload["classification_reason"])
            self.assertEqual(result["benchmark_outcome_status"], "invalid")

    def test_execute_cell_classifies_pre_repair_failure_from_invoker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "leave-request-api" / "B-agentharness" / "r1"
            prepare_fresh_cell(
                task_id="leave-request-api",
                condition="B-agentharness",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            result = execute_cell(cell_dir, _PreRepairFailureInvoker())
            payload = json.loads((cell_dir / "outputs" / "benchmark-evaluate-task.json").read_text(encoding="utf-8"))
            self.assertEqual(result["benchmark_execution_status"], "harness_invalid")
            self.assertIn("Offline shared deps install failed", payload["classification_reason"])
            self.assertEqual(result["attempt_count"], 1)

    def test_invoke_marks_timeout_as_provider_retryable_failure(self) -> None:
        invoker = HermesCliInvoker(hermes_command="hermes", retry_backoff_seconds=0.01)
        with tempfile.TemporaryDirectory() as tmp_dir:
            outputs_dir = Path(tmp_dir)
            timeout_exc = subprocess.TimeoutExpired(cmd=["hermes"], timeout=1)
            completed_success = subprocess.CompletedProcess(
                args=["hermes"],
                returncode=0,
                stdout="session_id: ok_123\n",
                stderr="",
            )
            with (
                mock.patch("agentharness.benchmark_cells.subprocess.run", side_effect=[timeout_exc, completed_success]) as run_mock,
                mock.patch("agentharness.benchmark_cells.time.sleep") as sleep_mock,
            ):
                attempt = invoker._invoke(
                    prompt="hello",
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    outputs_dir=outputs_dir,
                    workspace=outputs_dir,
                )
                self.assertIn("timed out after", (outputs_dir / "attempt-1.try1.stderr").read_text(encoding="utf-8").lower())
        self.assertEqual(attempt.exit_code, 0)
        self.assertEqual(attempt.session_id, "ok_123")
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.01)

    def test_invoke_pins_provider_model_and_max_turns_in_command(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=0,
            stdout="session_id: pinned_123\n",
            stderr="",
        )
        invoker = HermesCliInvoker(
            hermes_command="hermes",
            max_retries=1,
            provider="openai-codex",
            model="gpt-5.6-sol",
            max_turns=40,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            outputs_dir = Path(tmp_dir)
            with mock.patch("agentharness.benchmark_cells.subprocess.run", return_value=completed) as run_mock:
                attempt = invoker._invoke(
                    prompt="hello",
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    outputs_dir=outputs_dir,
                    workspace=outputs_dir,
                )
        command = run_mock.call_args.args[0]
        self.assertIn("--provider", command)
        self.assertEqual(command[command.index("--provider") + 1], "openai-codex")
        self.assertEqual(command[command.index("-m") + 1], "gpt-5.6-sol")
        self.assertEqual(command[command.index("--max-turns") + 1], "40")
        self.assertEqual(attempt.command, command)

    def test_invoke_isolates_nested_hermes_cwd_from_gateway_environment(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=0,
            stdout="session_id: isolated_123\n",
            stderr="",
        )
        invoker = HermesCliInvoker(hermes_command="hermes", max_retries=1)
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            outputs_dir = Path(tmp_dir) / "outputs"
            workspace.mkdir()
            outputs_dir.mkdir()
            with (
                mock.patch.dict(
                    os.environ,
                    {"_HERMES_GATEWAY": "1", "TERMINAL_CWD": "/home/shared-gateway"},
                    clear=False,
                ),
                mock.patch("agentharness.benchmark_cells.subprocess.run", return_value=completed) as run_mock,
            ):
                invoker._invoke(
                    prompt="hello",
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    outputs_dir=outputs_dir,
                    workspace=workspace,
                )

        invocation_env = run_mock.call_args.kwargs["env"]
        self.assertNotIn("_HERMES_GATEWAY", invocation_env)
        self.assertEqual(invocation_env["TERMINAL_CWD"], str(workspace))
        self.assertEqual(run_mock.call_args.kwargs["cwd"], str(workspace))

    def test_invoke_extracts_session_id_from_stderr(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=0,
            stdout="work completed\n",
            stderr="session_id: stderr_session_123\n",
        )
        invoker = HermesCliInvoker(hermes_command="hermes", max_retries=1)
        with tempfile.TemporaryDirectory() as tmp_dir:
            outputs_dir = Path(tmp_dir)
            with mock.patch("agentharness.benchmark_cells.subprocess.run", return_value=completed):
                attempt = invoker._invoke(
                    prompt="hello",
                    attempt_name="attempt-1",
                    prompt_kind="initial",
                    outputs_dir=outputs_dir,
                    workspace=outputs_dir,
                )
        self.assertEqual(attempt.session_id, "stderr_session_123")
        self.assertEqual(attempt.exit_code, 0)

    def test_empty_workspace_with_successful_invocation_is_not_provider_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stdout_path = root / "attempt.stdout"
            stderr_path = root / "attempt.stderr"
            stdout_path.write_text("Implemented a temporarily unavailable application response\n", encoding="utf-8")
            stderr_path.write_text("session_id: successful_123\n", encoding="utf-8")
            attempt = AgentAttempt(
                attempt_name="attempt-1",
                prompt_kind="initial",
                command=["hermes"],
                exit_code=0,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                working_directory=root,
                session_id="successful_123",
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:00:01Z",
                duration_seconds=1.0,
            )
            status, reason = _classify_empty_workspace_failure(AgentInvocationResult(attempts=[attempt]))

        self.assertEqual(status, "harness_invalid")
        self.assertNotIn("provider_unavailable", reason)

    def test_empty_workspace_mixed_attempts_are_not_provider_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            attempts: list[AgentAttempt] = []
            for name, exit_code, stdout, session_id in (
                ("failed", 1, "HTTP 429: usage limit has been reached\n", None),
                ("successful", 0, "completed\n", "successful_456"),
            ):
                stdout_path = root / f"{name}.stdout"
                stderr_path = root / f"{name}.stderr"
                stdout_path.write_text(stdout, encoding="utf-8")
                stderr_path.write_text(
                    f"session_id: {session_id}\n" if session_id else "",
                    encoding="utf-8",
                )
                attempts.append(
                    AgentAttempt(
                        attempt_name=name,
                        prompt_kind="initial",
                        command=["hermes"],
                        exit_code=exit_code,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        working_directory=root,
                        session_id=session_id,
                        started_at="2026-01-01T00:00:00Z",
                        finished_at="2026-01-01T00:00:01Z",
                        duration_seconds=1.0,
                    )
                )
            status, reason = _classify_empty_workspace_failure(AgentInvocationResult(attempts=attempts))

        self.assertEqual(status, "harness_invalid")
        self.assertNotIn("provider_unavailable", reason)

    def test_retryable_invocation_failure_ignores_provider_words_in_successful_output(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=0,
            stdout="Implemented a temporarily unavailable application response\n",
            stderr="session_id: successful_123\n",
        )
        self.assertFalse(_is_retryable_invocation_failure(completed))

    def test_retryable_invocation_failure_detects_sse_stall_marker_in_stderr(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=1,
            stdout="",
            stderr="API call failed after 3 retries: Codex stream produced no SSE events for 12s after first byte (threshold: 12s)\n",
        )
        self.assertTrue(_is_retryable_invocation_failure(completed))

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

    def test_run_cell_rolls_back_manifest_regression_and_preserves_raw_repair_evidence(self) -> None:
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
                "task_id": "inventory-adjustment-api",
                "condition": "A-baseline",
                "run_id": "stageb_inventory_adjustment_api_a_r1",
                "spec_path": str(spec_path),
                "claims_template_path": str(claims_template_path),
            }
            initial_pyproject = "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['sqlalchemy>=2']\n"

            def fake_invoke(*, prompt: str, attempt_name: str, prompt_kind: str, outputs_dir: Path, workspace: Path) -> AgentAttempt:
                del prompt
                if prompt_kind == "initial":
                    package = workspace / "src" / "demo"
                    package.mkdir(parents=True, exist_ok=True)
                    (package / "__init__.py").write_text("", encoding="utf-8")
                    (package / "models.py").write_text("from sqlalchemy import create_engine\n", encoding="utf-8")
                    (workspace / "pyproject.toml").write_text(initial_pyproject, encoding="utf-8")
                else:
                    (workspace / "pyproject.toml").write_text(
                        "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['sqlalchemy>=2','pytest>=9']\n",
                        encoding="utf-8",
                    )
                stdout_path = outputs_dir / f"{attempt_name}.stdout"
                stderr_path = outputs_dir / f"{attempt_name}.stderr"
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                stdout_path.write_text("session_id: fake\n", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return AgentAttempt(
                    attempt_name=attempt_name,
                    prompt_kind=prompt_kind,
                    command=["fake"],
                    exit_code=0,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    working_directory=workspace,
                    session_id="fake",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    duration_seconds=1.0,
                )

            def fake_pytest(workspace: Path, report_path: Path) -> dict[str, object]:
                stdout_path = report_path.with_suffix(".stdout")
                stderr_path = report_path.with_suffix(".stderr")
                stdout_path.write_text("1 passed\n", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return {
                    "command": [str(workspace / ".stageb-test-venv" / "bin" / "python"), "-m", "pytest", "-q"],
                    "exit_code": 0,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                }

            with (
                mock.patch.object(invoker, "_invoke", side_effect=fake_invoke),
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", side_effect=fake_pytest),
                mock.patch(
                    "agentharness.benchmark_cells.manifest_install_state",
                    side_effect=[
                        {"ok": True, "detail": "pre install ok", "infrastructure_error": False},
                        {"ok": False, "detail": "pytest>=9 conflicts with frozen constraints", "infrastructure_error": False},
                    ],
                ),
            ):
                result = invoker.run_cell(manifest, outputs_dir, workspace)

            self.assertIsNotNone(result.repair_safety)
            safety = cast(dict[str, object], result.repair_safety)
            self.assertTrue(safety["rollback_performed"])
            reasons = cast(list[str], safety["reasons"])
            self.assertIn("canonical_manifest_install_regressed", reasons)
            self.assertEqual((workspace / "pyproject.toml").read_text(encoding="utf-8"), initial_pyproject)
            hashes = cast(dict[str, str | None], result.attempt_solution_hashes)
            self.assertNotEqual(hashes["attempt_2_repair_raw"], hashes["attempt_2_repair"])
            self.assertEqual(hashes["attempt_1_initial"], hashes["attempt_2_repair"])
            self.assertTrue((outputs_dir / "repair-cumulative.diff").is_file())
            self.assertIn("pytest>=9", (outputs_dir / "repair-cumulative.diff").read_text(encoding="utf-8"))
            self.assertTrue((outputs_dir / "repair-safety-gate.json").is_file())

            with (
                mock.patch.object(invoker, "_invoke", side_effect=fake_invoke),
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", side_effect=fake_pytest),
                mock.patch(
                    "agentharness.benchmark_cells.manifest_install_state",
                    side_effect=[
                        {"ok": True, "detail": "pre install ok", "infrastructure_error": False},
                        {"ok": True, "detail": "post install ok", "infrastructure_error": False},
                    ],
                ),
                mock.patch(
                    "agentharness.benchmark_cells.static_repair_guardrails",
                    side_effect=RuntimeError("synthetic safety gate crash"),
                ),
            ):
                with self.assertRaises(ClassifiedCellFailure) as captured:
                    invoker.run_cell(manifest, outputs_dir, workspace)
            self.assertEqual(captured.exception.execution_status, "harness_invalid")
            self.assertEqual((workspace / "pyproject.toml").read_text(encoding="utf-8"), initial_pyproject)
            crash_report = json.loads((outputs_dir / "repair-safety-gate.json").read_text(encoding="utf-8"))
            self.assertTrue(crash_report["rollback_performed"])
            self.assertIn("repair_safety_gate_error", crash_report["reasons"])

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
                prompt_snapshot = (outputs_dir / "pre-repair-treatment-prompt.txt").read_text(encoding="utf-8")
                self.assertIn("../pytest.stdout", prompt_snapshot)

    def test_run_cell_does_not_score_failed_repair_invocation(self) -> None:
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
                "run_id": "stage2_support_ticket_api_a_r1",
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
            initial = subprocess.CompletedProcess(
                args=["hermes"], returncode=0, stdout="session_id: initial_ok\n", stderr=""
            )
            failed_repair = subprocess.CompletedProcess(
                args=["hermes"], returncode=1, stdout="", stderr="HTTP 429 usage limit has been reached"
            )
            with (
                mock.patch(
                    "agentharness.benchmark_cells.subprocess.run",
                    side_effect=[initial, failed_repair],
                ),
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
            ):
                with self.assertRaises(ClassifiedCellFailure) as captured:
                    invoker.run_cell(manifest, outputs_dir, workspace)
            self.assertEqual(captured.exception.execution_status, "harness_invalid")
            self.assertIn("provider_unavailable", captured.exception.classification_reason)
            invocation_result = captured.exception.invocation_result
            self.assertIsNotNone(invocation_result)
            assert invocation_result is not None
            delivery = invocation_result.treatment_delivery
            self.assertIsInstance(delivery, dict)
            assert isinstance(delivery, dict)
            self.assertFalse(delivery["repair_invocation_succeeded"])

    def test_execute_cell_marks_missing_verify_feedback_as_treatment_not_delivered(self) -> None:
        invoker = HermesCliInvoker(hermes_command="hermes", max_retries=1)
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "support-ticket-api" / "B-agentharness" / "r1"
            prepare_fresh_cell(
                task_id="support-ticket-api",
                condition="B-agentharness",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
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
            completed = subprocess.CompletedProcess(args=["hermes"], returncode=0, stdout="session_id: ok_123\n", stderr="")
            with (
                mock.patch("agentharness.benchmark_cells.subprocess.run", return_value=completed) as run_mock,
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
                mock.patch(
                    "agentharness.benchmark_cells.run_verify_run",
                    return_value={
                        "ok": False,
                        "report_exists": False,
                        "report_nonempty": False,
                        "report_valid": False,
                        "report_error": "report_missing",
                    },
                ),
            ):
                result = execute_cell(cell_dir, invoker)
                self.assertEqual(result["benchmark_execution_status"], "harness_invalid")
                self.assertEqual(result["benchmark_classification_reason"], "treatment_not_delivered")
                self.assertEqual(result["attempt_count"], 1)
                self.assertFalse((cell_dir / "outputs" / "pre-repair-treatment-prompt.txt").exists())
                self.assertEqual(run_mock.call_count, 1)

    def test_run_cell_agentharness_repair_receives_written_feedback(self) -> None:
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
                "condition": "B-agentharness",
                "run_id": "stageb_support_ticket_api_b_r1",
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
            verify_report_path = outputs_dir / "pre-repair-verify-run-report.json"

            def _fake_verify_run(*, run_path: Path, claims_path: Path, report_path: Path) -> dict[str, object]:
                self.assertEqual(report_path, verify_report_path)
                report_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "feedback": {
                                "summary": {"supported": 1, "unsupported": 0, "inconclusive": 0, "invalid": 0},
                                "blocking_claim_ids": [],
                                "items": [{"claim_id": "claim_tests", "status": "supported", "reason": "ok"}],
                            },
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return {
                    "ok": True,
                    "report_exists": True,
                    "report_nonempty": True,
                    "report_valid": True,
                    "report_error": None,
                    "report_path": str(report_path),
                }

            completed = subprocess.CompletedProcess(args=["hermes"], returncode=0, stdout="session_id: ok_123\n", stderr="")
            with (
                mock.patch("agentharness.benchmark_cells.subprocess.run", return_value=completed) as run_mock,
                mock.patch("agentharness.benchmark_cells.run_workspace_pytest", return_value=pytest_payload),
                mock.patch("agentharness.benchmark_cells.run_verify_run", side_effect=_fake_verify_run),
            ):
                result = invoker.run_cell(manifest, outputs_dir, workspace)
                self.assertEqual(len(result.attempts), 2)
                prompt_snapshot = (outputs_dir / "pre-repair-treatment-prompt.txt").read_text(encoding="utf-8")
                self.assertIn("../outputs/pre-repair-verify-run-report.json", prompt_snapshot)
                self.assertTrue(verify_report_path.is_file())
                self.assertEqual(run_mock.call_count, 2)

    def test_inspect_verify_feedback_report_rejects_empty_malformed_or_missing_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            empty_path = root / "empty.json"
            empty_path.write_text("", encoding="utf-8")
            malformed_path = root / "malformed.json"
            malformed_path.write_text("{not-json\n", encoding="utf-8")
            missing_feedback_path = root / "missing-feedback.json"
            missing_feedback_path.write_text(json.dumps({"ok": True, "summary": {"supported": 1}}) + "\n", encoding="utf-8")

            empty = _inspect_verify_feedback_report(empty_path)
            malformed = _inspect_verify_feedback_report(malformed_path)
            missing_feedback = _inspect_verify_feedback_report(missing_feedback_path)

        self.assertFalse(empty["report_valid"])
        self.assertEqual(empty["report_error"], "report_empty")
        self.assertFalse(malformed["report_valid"])
        self.assertTrue(str(malformed["report_error"]).startswith("report_invalid_json:"))
        self.assertFalse(missing_feedback["report_valid"])
        self.assertEqual(missing_feedback["report_error"], "report_missing_feedback")


if __name__ == "__main__":
    unittest.main()
