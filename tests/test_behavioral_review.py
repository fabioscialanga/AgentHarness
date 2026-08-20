from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentharness.behavioral_review import _fingerprint_tree, review_workspace


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_plan(root: Path, checks: list[dict[str, str]], *, test_root: str = "review-tests") -> Path:
    plan_path = root / "review-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "plan_id": "calculator-behavior-v1",
                "test_root": test_root,
                "checks": checks,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return plan_path


def _checks() -> list[dict[str, str]]:
    return [
        {
            "id": "adds_positive_numbers",
            "behavior": "Positive integers are added correctly",
            "nodeid": "test_behavior.py::test_adds_positive_numbers",
            "remediation": "Implement arithmetic addition for positive integers.",
        },
        {
            "id": "adds_negative_numbers",
            "behavior": "Negative integers are added correctly",
            "nodeid": "test_behavior.py::test_adds_negative_numbers",
            "remediation": "Preserve the sign of both operands instead of using absolute values.",
        },
    ]


def _run_single_check(root: Path, test_source: str, nodeid: str = "test_behavior.py::test_behavior"):
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "application.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_root = root / "review-tests"
    test_root.mkdir()
    (test_root / "test_behavior.py").write_text(test_source, encoding="utf-8")
    plan_path = _write_plan(root, [{
        "id": "behavior",
        "behavior": "The trusted behavior is established",
        "nodeid": nodeid,
        "remediation": "Make the exact trusted test execute and pass.",
    }])
    return review_workspace(workspace, plan_path, run_id=f"review-{root.name}")


class BehavioralReviewTests(unittest.TestCase):
    def test_review_finds_independent_failure_and_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "calculator.py").write_text(
                "def add(left, right):\n    return abs(left) + abs(right)\n",
                encoding="utf-8",
            )
            # The agent-authored test is green but too weak to expose the negative-number defect.
            (workspace / "test_agent.py").write_text(
                "from calculator import add\n\ndef test_positive_only():\n    assert add(2, 3) == 5\n",
                encoding="utf-8",
            )
            (workspace / "claims.json").write_text(
                json.dumps({"claims": [{"id": "agent_says_done", "status": "supported"}]}),
                encoding="utf-8",
            )
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from pathlib import Path\n"
                "from calculator import add\n\n"
                "def test_adds_positive_numbers():\n"
                "    Path('review-marker.txt').write_text('snapshot only', encoding='utf-8')\n"
                "    assert add(2, 3) == 5\n\n"
                "def test_adds_negative_numbers():\n"
                "    assert add(-2, -3) == -5\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(root, _checks())

            result = review_workspace(workspace, plan_path, run_id="review-independent-failure", timeout_seconds=30)

            self.assertFalse(result.ok)
            self.assertEqual(result.summary, {"passed": 1, "failed": 1, "diagnostic": 0, "actionable": 1})
            self.assertEqual([item.check_id for item in result.findings], [
                "adds_positive_numbers",
                "adds_negative_numbers",
            ])
            failure = result.findings[1]
            self.assertEqual(failure.status, "failed")
            self.assertTrue(failure.actionable)
            self.assertEqual(failure.truth_source, "reexecuted")
            self.assertEqual(failure.reason, "The exact trusted test failed")
            self.assertIn("Preserve the sign", failure.remediation)
            self.assertEqual(len(failure.evidence), 2)
            self.assertTrue(all(Path(path).is_file() for path in failure.evidence))
            positive_snapshot = result.snapshot_workspace / "adds_positive_numbers" / "workspace"
            self.assertTrue((positive_snapshot / "review-marker.txt").is_file())
            self.assertFalse((workspace / "review-marker.txt").exists())
            self.assertTrue(result.review_report_path.is_file())
            self.assertTrue(result.verify_report_path.is_file())
            self.assertTrue(result.source_plan_path.is_file())
            self.assertEqual(result.plan_sha256, hashlib.sha256(plan_path.read_bytes()).hexdigest())
            self.assertNotIn("agent_says_done", result.derived_checks_path.read_text(encoding="utf-8"))
            report = json.loads(result.review_report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["actionable"], 1)
            self.assertEqual(report["actionable_findings"][0]["check_id"], "adds_negative_numbers")
            self.assertTrue(report["isolation"]["review_tests_external_to_original_workspace"])

    def test_review_passes_after_behavior_is_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "calculator.py").write_text(
                "def add(left, right):\n    return left + right\n",
                encoding="utf-8",
            )
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from calculator import add\n\n"
                "def test_adds_positive_numbers():\n    assert add(2, 3) == 5\n\n"
                "def test_adds_negative_numbers():\n    assert add(-2, -3) == -5\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(root, _checks())

            result = review_workspace(workspace, plan_path, run_id="review-fixed", timeout_seconds=30)

            self.assertTrue(result.ok)
            self.assertEqual(result.summary, {"passed": 2, "failed": 0, "diagnostic": 0, "actionable": 0})
            self.assertTrue(all(item.status == "passed" for item in result.findings))

    def test_bundle_fingerprint_changes_when_review_test_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "calculator.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
            test_root = root / "review-tests"
            test_root.mkdir()
            review_test = test_root / "test_behavior.py"
            review_test.write_text(
                "from calculator import add\n"
                "def test_adds_positive_numbers(): assert add(2, 3) == 5\n"
                "def test_adds_negative_numbers(): assert add(-2, -3) == -5\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(root, _checks())
            first = review_workspace(workspace, plan_path, run_id="review-hash-one")
            review_test.write_text(review_test.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            second = review_workspace(workspace, plan_path, run_id="review-hash-two")

            self.assertNotEqual(first.test_bundle_sha256, second.test_bundle_sha256)

    def test_review_rejects_plan_or_tests_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            tests = workspace / "review-tests"
            tests.mkdir()
            (tests / "test_behavior.py").write_text(
                "def test_adds_positive_numbers(): pass\n"
                "def test_adds_negative_numbers(): pass\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(workspace, _checks())

            with self.assertRaisesRegex(ValueError, "plan must be external"):
                review_workspace(workspace, plan_path, run_id="review-inside")

    def test_review_rejects_unsafe_nodeid_and_symlink_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text("def test_ok(): pass\n", encoding="utf-8")
            unsafe = [{
                "id": "unsafe",
                "behavior": "Safe behavior",
                "nodeid": "../test_behavior.py::test_ok;touch-owned",
                "remediation": "Fix it.",
            }]
            plan_path = _write_plan(root, unsafe)
            with self.assertRaisesRegex(ValueError, "unsupported characters"):
                review_workspace(workspace, plan_path, run_id="review-unsafe")

            if hasattr(os, "symlink"):
                plan_path.unlink()
                outside = root / "outside.py"
                outside.write_text("def test_ok(): pass\n", encoding="utf-8")
                (test_root / "linked.py").symlink_to(outside)
                safe = [{
                    "id": "safe",
                    "behavior": "Safe behavior",
                    "nodeid": "test_behavior.py::test_ok",
                    "remediation": "Fix it.",
                }]
                plan_path = _write_plan(root, safe)
                with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
                    review_workspace(workspace, plan_path, run_id="review-symlink")

    def test_workspace_pytest_hooks_cannot_skip_or_reconfigure_trusted_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "calculator.py").write_text("def broken(): return True\n", encoding="utf-8")
            (workspace / "conftest.py").write_text(
                "def pytest_collection_modifyitems(items):\n"
                "    for item in items: item.add_marker('skip')\n",
                encoding="utf-8",
            )
            (workspace / "pytest.ini").write_text("[pytest]\naddopts = --collect-only\n", encoding="utf-8")
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from calculator import broken\n"
                "def test_real_behavior(): assert broken() is False\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(root, [{
                "id": "real_behavior",
                "behavior": "The implementation returns the required value",
                "nodeid": "test_behavior.py::test_real_behavior",
                "remediation": "Return False.",
            }])

            result = review_workspace(workspace, plan_path, run_id="review-hook-bypass")

            self.assertFalse(result.ok)
            self.assertEqual(result.summary["failed"], 1)
            self.assertEqual(result.findings[0].reason, "The exact trusted test failed")
            structured = result.findings[0].audit["behavioral_result"]
            self.assertEqual(structured["status"], "failed")
            self.assertEqual(structured["collected"], [
                ".agentharness/review-tests/review-hook-bypass/test_behavior.py::test_real_behavior"
            ])

    def test_abrupt_zero_exit_without_test_result_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "application.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "import application\n"
                "def test_behavior(): assert True\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(root, [{
                "id": "behavior",
                "behavior": "Application can be imported and satisfies the behavior",
                "nodeid": "test_behavior.py::test_behavior",
                "remediation": "Do not terminate the verification process during import.",
            }])

            result = review_workspace(workspace, plan_path, run_id="review-abrupt-exit")

            self.assertFalse(result.ok)
            self.assertEqual(result.summary["diagnostic"], 1)
            self.assertEqual(result.findings[0].truth_source, "none")
            self.assertIn("structured result", result.findings[0].reason)

    def test_skipped_trusted_test_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_single_check(
                Path(tmp_dir),
                "import pytest\n@pytest.mark.skip(reason='not evidence')\ndef test_behavior(): assert True\n",
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.summary["diagnostic"], 1)
            self.assertIn("skipped or xfailed", result.findings[0].reason)

    def test_xfailed_trusted_test_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_single_check(
                Path(tmp_dir),
                "import pytest\n@pytest.mark.xfail(reason='not evidence')\ndef test_behavior(): assert False\n",
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.summary["diagnostic"], 1)
            self.assertIn("skipped or xfailed", result.findings[0].reason)

    def test_missing_trusted_test_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_single_check(
                Path(tmp_dir),
                "def test_other_behavior(): assert True\n",
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.summary["diagnostic"], 1)
            self.assertIn("not collected exactly once", result.findings[0].reason)

    def test_review_rejects_test_root_that_contains_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (root / "test_behavior.py").write_text("def test_ok(): pass\n", encoding="utf-8")
            plan_path = _write_plan(root, [{
                "id": "ok",
                "behavior": "Safe behavior",
                "nodeid": "test_behavior.py::test_ok",
                "remediation": "Fix it.",
            }], test_root=".")

            with self.assertRaisesRegex(ValueError, "must not contain the workspace"):
                review_workspace(workspace, plan_path, run_id="review-ancestor")

    def test_cross_check_contamination_is_removed_before_next_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "application.py").write_text("VALUE = 0\n", encoding="utf-8")
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from pathlib import Path\n"
                "def test_first():\n"
                "    target = Path('../../second/workspace/application.py')\n"
                "    target.parent.mkdir(parents=True, exist_ok=True)\n"
                "    target.write_text('VALUE = 1\\n', encoding='utf-8')\n"
                "def test_second():\n"
                "    from application import VALUE\n"
                "    assert VALUE == 1\n",
                encoding="utf-8",
            )
            plan = _write_plan(root, [
                {"id": "first", "behavior": "first", "nodeid": "test_behavior.py::test_first", "remediation": "none"},
                {"id": "second", "behavior": "second", "nodeid": "test_behavior.py::test_second", "remediation": "set VALUE to 1"},
            ])

            result = review_workspace(workspace, plan, run_id="review-cross-check")

            self.assertEqual(result.summary["passed"], 1)
            self.assertEqual(result.summary["failed"], 1)
            self.assertEqual(result.findings[1].check_id, "second")

    def test_workspace_fingerprint_includes_symlink_target_and_mode(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = root / "first"
            second = root / "second"
            for tree in (first, second):
                tree.mkdir()
                (tree / "one.py").write_text("VALUE = 'A'\n", encoding="utf-8")
                (tree / "two.py").write_text("VALUE = 'B'\n", encoding="utf-8")
            (first / "current.py").symlink_to("one.py")
            (second / "current.py").symlink_to("two.py")
            self.assertNotEqual(_fingerprint_tree(first), _fingerprint_tree(second))
            (second / "current.py").unlink()
            (second / "current.py").symlink_to("one.py")
            self.assertEqual(_fingerprint_tree(first), _fingerprint_tree(second))
            (second / "one.py").chmod(0o755)
            self.assertNotEqual(_fingerprint_tree(first), _fingerprint_tree(second))

    def test_review_accepts_existing_empty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / "artifacts"
            output.mkdir()
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "application.py").write_text("VALUE = 1\n", encoding="utf-8")
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text("def test_behavior(): assert True\n", encoding="utf-8")
            plan = _write_plan(root, [{
                "id": "behavior", "behavior": "works",
                "nodeid": "test_behavior.py::test_behavior", "remediation": "fix",
            }])
            reviewed = review_workspace(workspace, plan, run_id="review-empty-output", output_dir=output)
            self.assertTrue(reviewed.ok)
            self.assertTrue((output / "behavioral-review-report.json").is_file())

    def test_mutated_staged_trusted_bundle_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "application.py").write_text(
                "from pathlib import Path\n"
                "for candidate in Path('.agentharness/review-tests').rglob('test_behavior.py'):\n"
                "    candidate.write_text('def test_behavior(): assert True\\n')\n"
                "VALUE = 1\n",
                encoding="utf-8",
            )
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "conftest.py").write_text("from application import VALUE\n", encoding="utf-8")
            (test_root / "test_behavior.py").write_text(
                "def test_behavior(): assert False\n", encoding="utf-8"
            )
            plan = _write_plan(root, [{
                "id": "behavior", "behavior": "must fail",
                "nodeid": "test_behavior.py::test_behavior", "remediation": "fix",
            }])
            with self.assertRaisesRegex(ValueError, "trusted review test bundle changed"):
                review_workspace(workspace, plan, run_id="tampered-bundle")

    def test_symlinked_child_report_fails_closed_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            outside = root / "outside.json"
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "application.py").write_text("VALUE = 1\n", encoding="utf-8")
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from pathlib import Path\n"
                "from application import VALUE\n"
                "def test_behavior():\n"
                f"    target = Path({str(outside)!r})\n"
                "    report = Path('../../../per-check-verification/behavior/verify-report.json')\n"
                "    report.symlink_to(target)\n"
                "    assert VALUE == 1\n",
                encoding="utf-8",
            )
            plan = _write_plan(root, [{
                "id": "behavior", "behavior": "works",
                "nodeid": "test_behavior.py::test_behavior", "remediation": "fix",
            }])
            with self.assertRaises(FileExistsError):
                review_workspace(workspace, plan, run_id="symlinked-report")
            self.assertFalse(outside.exists())

    def test_review_ignores_transient_cache_entries_not_copied_to_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "application.py").write_text("VALUE = 1\n", encoding="utf-8")
            cache = workspace / "__pycache__"
            cache.mkdir()
            (cache / "application.cpython-312.pyc").write_bytes(b"transient-cache")
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from application import VALUE\ndef test_behavior(): assert VALUE == 1\n",
                encoding="utf-8",
            )
            plan = _write_plan(root, [{
                "id": "behavior", "behavior": "works",
                "nodeid": "test_behavior.py::test_behavior", "remediation": "fix",
            }])
            result = review_workspace(workspace, plan, run_id="review-with-cache")
            self.assertTrue(result.ok)

    def test_reviewed_source_import_failure_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_single_check(
                Path(tmp_dir),
                "from application import missing_api\ndef test_behavior(): assert missing_api()\n",
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.summary["failed"], 1)
            self.assertEqual(result.summary["actionable"], 1)
            self.assertIn("Reviewed source caused", result.findings[0].reason)

    def test_review_rejects_dot_path_check_ids(self) -> None:
        for unsafe_id in (".", ".."):
            with self.subTest(unsafe_id=unsafe_id), tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                workspace = root / "workspace"
                workspace.mkdir()
                test_root = root / "review-tests"
                test_root.mkdir()
                (test_root / "test_behavior.py").write_text("def test_ok(): pass\n", encoding="utf-8")
                plan = _write_plan(root, [{
                    "id": unsafe_id, "behavior": "safe",
                    "nodeid": "test_behavior.py::test_ok", "remediation": "fix",
                }])
                with self.assertRaisesRegex(ValueError, "not path-safe"):
                    review_workspace(workspace, plan, run_id=f"review-dot-{len(unsafe_id)}")

    def test_cli_review_returns_findings_and_stable_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "calculator.py").write_text(
                "def add(left, right): return abs(left) + abs(right)\n",
                encoding="utf-8",
            )
            test_root = root / "review-tests"
            test_root.mkdir()
            (test_root / "test_behavior.py").write_text(
                "from calculator import add\n"
                "def test_adds_positive_numbers(): assert add(2, 3) == 5\n"
                "def test_adds_negative_numbers(): assert add(-2, -3) == -5\n",
                encoding="utf-8",
            )
            plan_path = _write_plan(root, _checks())
            command = [
                sys.executable,
                "-m",
                "agentharness",
                "review",
                "--workspace",
                str(workspace),
                "--plan",
                str(plan_path),
                "--run-id",
                "review-cli",
                "--json",
            ]
            completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)

            self.assertEqual(completed.returncode, 1, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["summary"]["actionable"], 1)
            self.assertEqual(payload["actionable_findings"][0]["check_id"], "adds_negative_numbers")
            self.assertTrue(Path(payload["review_report_path"]).is_file())

            invalid = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentharness",
                    "review",
                    "--workspace",
                    str(workspace),
                    "--plan",
                    str(root / "missing-plan.json"),
                    "--json",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invalid.returncode, 2)
            invalid_payload = json.loads(invalid.stdout)
            self.assertFalse(invalid_payload["ok"])
            self.assertIn("does not exist", invalid_payload["error"])


if __name__ == "__main__":
    unittest.main()
