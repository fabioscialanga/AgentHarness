from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RUNNER_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "grading-env" / "run_stage_b_diagnostics.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("agentharness_stage_b_runner_test", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Stage B runner from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StageBRunnerTests(unittest.TestCase):
    def test_requires_explicit_provider_and_model_pin(self) -> None:
        runner = _load_runner_module()
        with mock.patch.dict(runner.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "explicit provider/model pin"):
                runner._required_model_pin()

    def test_aborts_after_provider_streak_and_persists_diagnostic_summary(self) -> None:
        runner = _load_runner_module()
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_root = Path(tmp_dir) / "stage-b"
            env = {
                "STAGEB_RUNS_ROOT": str(runs_root),
                "STAGEB_TASKS": "task-a,task-b",
                "STAGEB_CONDITIONS": "B-agentharness",
                "STAGEB_REPLICATES": "r1,r2",
                "STAGEB_PROVIDER": "openai-codex",
                "STAGEB_MODEL": "gpt-5.6-sol",
                "STAGEB_MAX_TURNS": "40",
                "STAGEB_ABORT_PROVIDER_STREAK": "3",
            }
            calls: list[tuple[str, str, str]] = []

            def fake_prepare(*, task_id: str, condition: str, replicate_id: str, cell_dir: Path) -> None:
                cell_dir.mkdir(parents=True, exist_ok=True)

            def fake_execute(cell_dir: Path, invoker) -> dict[str, object]:
                task_id, condition, replicate_id = cell_dir.parts[-3:]
                calls.append((task_id, condition, replicate_id))
                self.assertEqual(invoker._provider, "openai-codex")
                self.assertEqual(invoker._model, "gpt-5.6-sol")
                self.assertEqual(invoker._max_turns, "40")
                return {
                    "cell": str(cell_dir),
                    "task_id": task_id,
                    "condition": condition,
                    "replicate_id": replicate_id,
                    "benchmark_execution_status": "provider_unavailable",
                    "benchmark_outcome_status": "invalid",
                    "benchmark_classification_reason": "provider_unavailable: synthetic outage",
                    "score": 0.0,
                    "solution_hash": "empty",
                }

            with (
                mock.patch.dict(runner.os.environ, env, clear=True),
                mock.patch.object(runner, "prepare_fresh_cell", side_effect=fake_prepare),
                mock.patch.object(runner, "execute_cell", side_effect=fake_execute),
                mock.patch.object(runner, "assert_nonshared_solution_hashes") as hash_guard,
            ):
                self.assertEqual(runner.main(), 0)

            self.assertEqual(len(calls), 3)
            hash_guard.assert_not_called()
            summary = json.loads(
                (runs_root / "stage-b-diagnostics-summary.json").read_text(encoding="utf-8")
            )
            self.assertTrue(summary["aborted_early"])
            self.assertFalse(summary["passes_gate"])
            self.assertEqual(summary["completed_cells"], 3)
            self.assertEqual(summary["remaining_cells"], 1)
            self.assertEqual(summary["trailing_provider_unavailable_streak"], 3)
            self.assertFalse(summary["gate_checks"]["completed_as_planned"])

            provenance = json.loads(
                (runs_root / "stage-b-run-provenance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(provenance["provider"], "openai-codex")
            self.assertEqual(provenance["model"], "gpt-5.6-sol")
            self.assertEqual(len(provenance["planned_cells"]), 4)


if __name__ == "__main__":
    unittest.main()
