from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "benchmarks/grading-env/run_exploratory_actionable_repair_v1.py"
MANIFEST = REPO_ROOT / "benchmarks/grading-env/EXPLORATORY_ACTIONABLE_REPAIR_V1_2026-07-27.json"
SPEC = importlib.util.spec_from_file_location("actionable_repair_pilot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def synthetic_row(task: str, condition: str, slot: int, score: float) -> dict[str, object]:
    cell_id = f"p{runner.json.loads(MANIFEST.read_text())['tasks'].index(task) + 1:03d}-s{slot}"
    return {
        "task_id": task,
        "condition": condition,
        "pilot_cell_id": cell_id,
        "score": score,
        "heldout_endpoint_valid": True,
        "repair_response_valid": condition == "B-agentharness",
        "feedback_items_accounted": True,
        "feedback_postverify_supported": 2 if condition == "B-agentharness" else None,
        "feedback_postverify_unresolved": 1 if condition == "B-agentharness" else None,
        "repair_change_retained": condition == "B-agentharness",
        "repair_rollback_performed": False,
        "benchmark_execution_status": "valid",
        "benchmark_classification_reason": None,
    }


def write_complete_run(run_root: Path, deltas: list[float]) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    for index, (task, delta) in enumerate(zip(manifest["tasks"], deltas, strict=True), 1):
        rows.append(synthetic_row(task, "A-baseline", 1, 0.5))
        rows.append(synthetic_row(task, "B-agentharness", 2, 0.5 + delta))
    runner.atomic_write(run_root / "progress.private.json", rows, private=True)
    runner.atomic_write(
        run_root / "campaign-state.private.json",
        {"status": "complete", "manifest_file_sha256": runner.sha256_file(MANIFEST)}, private=True,
    )
    runner.atomic_write(
        run_root / "collection-audit.final.json",
        {
            "analysis_authorized": True,
            "progress_sha256": runner.sha256_file(run_root / "progress.private.json"),
            "manifest_file_sha256": runner.sha256_file(MANIFEST),
        }, private=True,
    )


class ExploratoryActionableRepairPilotTests(unittest.TestCase):
    def test_manifest_is_exact_paired_counterbalanced_exploratory_freeze(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["pilot_id"], "exploratory_actionable_repair_v1")
        self.assertFalse(manifest["confirmatory"])
        self.assertEqual(manifest["frozen_at"], "2026-07-27")
        self.assertEqual(len(manifest["blocks"]), 4)
        self.assertEqual(manifest["expected_cells"], 8)
        self.assertEqual([b["condition_order"][0] for b in manifest["blocks"]], ["A-baseline", "B-agentharness", "A-baseline", "B-agentharness"])
        self.assertTrue(all(sorted(b["condition_order"]) == ["A-baseline", "B-agentharness"] for b in manifest["blocks"]))
        self.assertEqual(runner.manifest_payload_hash(manifest), manifest["manifest_payload_sha256"])

    def test_runtime_is_exactly_pinned(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            {key: manifest[key] for key in ("provider", "model", "hermes_command", "hermes_home", "toolsets", "max_turns")},
            {
                "provider": "openai-codex", "model": "gpt-5.6-sol",
                "hermes_command": "/home/fabio/.local/bin/stage2codex2",
                "hermes_home": "/home/fabio/.hermes/profiles/stage2codex2",
                "toolsets": "terminal,file", "max_turns": 40,
            },
        )

    def test_preflight_accepts_clean_exact_published_head_and_all_suites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pilot = runner.ExploratoryPilot(manifest_path=MANIFEST, run_root=Path(tmp) / "run")
            def fake_git(*args: str) -> str:
                if args[0] == "status":
                    return ""
                if args[:2] == ("rev-parse", "HEAD") or args[:2] == ("rev-parse", "origin/improve/actionable-repair-loop-20260725"):
                    return "published"
                raise AssertionError(args)
            with mock.patch.object(runner, "git", side_effect=fake_git), mock.patch.dict(
                os.environ, {"HERMES_HOME": "/home/fabio/.hermes/profiles/stage2codex2"}
            ):
                result = pilot.preflight()
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["suite_sha256"]), set(json.loads(MANIFEST.read_text())["tasks"]))

    def test_suite_failure_precedes_any_destructive_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            sentinel = run_root / "private-cells/p001-s1/sentinel"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("preserve", encoding="utf-8")
            pilot = runner.ExploratoryPilot(manifest_path=MANIFEST, run_root=run_root)
            with mock.patch.object(runner, "validate_suite_executability", side_effect=runner.IntegrityFailure("bad suite")), mock.patch.dict(
                os.environ, {"HERMES_HOME": "/home/fabio/.hermes/profiles/stage2codex2"}
            ):
                with self.assertRaises(runner.IntegrityFailure):
                    pilot.run()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_collection_console_rejects_outcome_fields(self) -> None:
        with self.assertRaises(ValueError):
            runner.structural_message(status="collecting", score=1.0)
        stream = StringIO()
        with redirect_stdout(stream):
            runner.structural_message(status="collecting", completed_blocks=1, total_blocks=4, completed_cells=2, total_cells=8)
        payload = json.loads(stream.getvalue())
        self.assertNotIn("score", payload)
        self.assertNotIn("outcome", payload)

    def test_stop_classification_is_immediate_for_provider_and_delivery(self) -> None:
        self.assertEqual(
            runner.ExploratoryPilot._stop_invalidity({"benchmark_classification_reason": "provider_unavailable: quota", "treatment_delivered": False}),
            "provider_unavailable",
        )
        self.assertEqual(
            runner.ExploratoryPilot._stop_invalidity({"benchmark_classification_reason": "treatment_not_delivered: response", "treatment_delivered": False}),
            "treatment_not_delivered",
        )
        self.assertIsNone(runner.ExploratoryPilot._stop_invalidity({"benchmark_classification_reason": None, "treatment_delivered": True}))

    def test_quota_gate_is_fail_closed_and_pauses_at_reserve(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            pilot = runner.ExploratoryPilot(manifest_path=MANIFEST, run_root=Path(tmp) / "run")
            available = mock.Mock(available=True, windows=[mock.Mock(used_percent=12.0, reset_at=None)], fetched_at="now")
            with mock.patch.object(runner, "fetch_usage", return_value=available):
                pilot._quota_gate(phase="test-low")
            at_limit = mock.Mock(available=True, windows=[mock.Mock(used_percent=manifest["quota_policy"]["single_window_pause_percent"], reset_at=None)], fetched_at="now")
            with mock.patch.object(runner, "fetch_usage", return_value=at_limit):
                with self.assertRaises(runner.QuotaPause):
                    pilot._quota_gate(phase="test-limit")
            unavailable = mock.Mock(available=False, windows=[])
            with mock.patch.object(runner, "fetch_usage", return_value=unavailable):
                with self.assertRaises(runner.QuotaPause):
                    pilot._quota_gate(phase="test-unavailable")

    def test_private_progress_exposes_only_pair_complete_blocks_and_mode_0600(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            pilot = runner.ExploratoryPilot(manifest_path=MANIFEST, run_root=Path(tmp) / "run")
            block = manifest["blocks"][0]
            first = pilot._cell_dir(block["block_id"], 1) / "cell-result.commit.json"
            runner.atomic_write(first, synthetic_row(block["task_id"], block["condition_order"][0], 1, 0.5), private=True)
            self.assertEqual(pilot._private_progress(), [])
            second = pilot._cell_dir(block["block_id"], 2) / "cell-result.commit.json"
            runner.atomic_write(second, synthetic_row(block["task_id"], block["condition_order"][1], 2, 0.5), private=True)
            progress = pilot._private_progress()
            runner.atomic_write(pilot.progress_path, progress, private=True)
            self.assertEqual(len(progress), 2)
            self.assertEqual(stat.S_IMODE(pilot.progress_path.stat().st_mode), 0o600)

    def test_finalizer_refuses_incomplete_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            runner.atomic_write(run_root / "campaign-state.private.json", {"status": "running"}, private=True)
            runner.atomic_write(run_root / "progress.private.json", [], private=True)
            runner.atomic_write(run_root / "collection-audit.final.json", {"analysis_authorized": False}, private=True)
            with self.assertRaises(runner.IntegrityFailure):
                runner.finalize(manifest_path=MANIFEST, run_root=run_root)

    def test_frozen_directional_verdicts_and_metrics(self) -> None:
        cases = [
            ([0.2, 0.1, 0.1, -0.1], "directional_signal_positive"),
            ([0.0, -0.1, 0.0, 0.0], "no_directional_signal"),
            ([0.2, -0.2, 0.1, -0.1], "mixed_or_inconclusive"),
        ]
        for deltas, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp)
                write_complete_run(run_root, deltas)
                result = runner.finalize(manifest_path=MANIFEST, run_root=run_root)
                self.assertEqual(result["verdict"], expected)
                self.assertEqual(result["n_paired_tasks"], 4)
                self.assertFalse(result["confirmatory"])
                self.assertEqual(result["b_adoption_accounting"]["denominator"], 4)
                self.assertIn("no strong", result["warning"].lower())
                self.assertEqual(stat.S_IMODE((run_root / "EXPLORATORY_ACTIONABLE_REPAIR_V1_RESULT.json").stat().st_mode), 0o600)

    def test_historical_stage2_runner_and_freeze_hashes_unchanged(self) -> None:
        self.assertEqual(
            runner.sha256_file(REPO_ROOT / "benchmarks/grading-env/run_stage2_efficacy_campaign.py"),
            "b454718d19d856dcdfc0d23b9b2a1c22e6a91b4edb8ab8807461fcf2f908a978",
        )
        self.assertEqual(
            runner.sha256_file(REPO_ROOT / "benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-18_ACCOUNT2.json"),
            "7a6b7f399ae084b0524fa138935ca69d63075b6ed84278c94db98ca9af99e5c4",
        )


if __name__ == "__main__":
    unittest.main()
