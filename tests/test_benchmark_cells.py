from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentharness.benchmark_cells import (
    AgentAttempt,
    AgentInvocationResult,
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
                    session_id=f"fake_{condition}_{replicate_id}_{index}",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    duration_seconds=1.0,
                )
            )
        return AgentInvocationResult(attempts=attempts)


class BenchmarkCellsTests(unittest.TestCase):
    def test_prepare_fresh_cell_copies_canonical_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cell_dir = Path(tmp_dir) / "support-ticket-api" / "A-baseline" / "r1"
            manifest = prepare_fresh_cell(
                task_id="support-ticket-api",
                condition="A-baseline",
                replicate_id="r1",
                cell_dir=cell_dir,
            )
            self.assertEqual(manifest["task_id"], "support-ticket-api")
            self.assertTrue((cell_dir / "inputs" / "SPEC.md").is_file())
            self.assertTrue((cell_dir / "inputs" / "CLAIMS_CONTRACT.template.json").is_file())
            self.assertTrue((cell_dir / "cell_manifest.json").is_file())
            self.assertTrue((cell_dir / "workspace").is_dir())

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


if __name__ == "__main__":
    unittest.main()
