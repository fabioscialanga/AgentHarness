from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentharness.repair_safety import (
    assess_repair_safety,
    restore_workspace,
    snapshot_workspace,
    static_repair_guardrails,
    write_cumulative_diff,
)


class RepairSafetyTests(unittest.TestCase):
    def _green_sqlalchemy_workspace(self, root: Path) -> Path:
        workspace = root / "workspace"
        package = workspace / "src" / "demo"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "models.py").write_text("from sqlalchemy import create_engine\n", encoding="utf-8")
        (workspace / "pyproject.toml").write_text(
            "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['sqlalchemy>=2']\n",
            encoding="utf-8",
        )
        return workspace

    def test_inventory_regression_flags_manifest_change_after_green_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = self._green_sqlalchemy_workspace(root)
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot)
            (workspace / "pyproject.toml").write_text(
                "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['sqlalchemy>=2','pytest>=9']\n",
                encoding="utf-8",
            )
            report = static_repair_guardrails(snapshot, workspace, pre_pytest_exit=0)
            self.assertFalse(report["ok"])
            self.assertIn("green_baseline_manifest_changed", {item["code"] for item in report["violations"]})

    def test_leave_regression_flags_abandoned_declared_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = self._green_sqlalchemy_workspace(root)
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot)
            (workspace / "src" / "demo" / "models.py").write_text("import sqlite3\n", encoding="utf-8")
            report = static_repair_guardrails(snapshot, workspace, pre_pytest_exit=0)
            self.assertFalse(report["ok"])
            self.assertIn("green_baseline_dependency_abandoned", {item["code"] for item in report["violations"]})

    def test_refund_regression_flags_local_dependency_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = self._green_sqlalchemy_workspace(root)
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot)
            shadow = workspace / "sqlalchemy"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("from sqlalchemy import create_engine\n", encoding="utf-8")
            report = static_repair_guardrails(snapshot, workspace, pre_pytest_exit=0)
            self.assertFalse(report["ok"])
            self.assertIn("local_dependency_shadow", {item["code"] for item in report["violations"]})

    def test_snapshot_diff_and_restore_preserve_pre_repair_solution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = self._green_sqlalchemy_workspace(root)
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot)
            models = workspace / "src" / "demo" / "models.py"
            original = models.read_text(encoding="utf-8")
            models.write_text("import sqlite3\n", encoding="utf-8")
            diff = write_cumulative_diff(snapshot, workspace, root / "repair.diff")
            self.assertIn("src/demo/models.py", diff["changed_files"])
            self.assertIn("sqlite3", (root / "repair.diff").read_text(encoding="utf-8"))
            restore_workspace(workspace, snapshot)
            self.assertEqual(models.read_text(encoding="utf-8"), original)

    def test_new_symlink_is_visible_in_diff_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = self._green_sqlalchemy_workspace(root)
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot)
            target = root / "outside.py"
            target.write_text("raise RuntimeError('outside')\n", encoding="utf-8")
            (workspace / "src" / "demo" / "outside.py").symlink_to(target)
            diff = write_cumulative_diff(snapshot, workspace, root / "repair.diff")
            self.assertIn("src/demo/outside.py", diff["changed_files"])
            self.assertIn("SYMLINK->", (root / "repair.diff").read_text(encoding="utf-8"))
            guardrails = static_repair_guardrails(snapshot, workspace, pre_pytest_exit=0)
            self.assertIn("new_workspace_symlink", {item["code"] for item in guardrails["violations"]})

    def test_restore_deletes_poisoned_runtime_virtualenvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = self._green_sqlalchemy_workspace(root)
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot)
            for name in (".stageb-test-venv", ".venv"):
                poisoned = workspace / name / "bin"
                poisoned.mkdir(parents=True)
                (poisoned / "python").write_text("poisoned\n", encoding="utf-8")
            restore_workspace(workspace, snapshot)
            self.assertFalse((workspace / ".stageb-test-venv").exists())
            self.assertFalse((workspace / ".venv").exists())

    def test_assessment_detects_worse_pytest_outcomes_when_both_runs_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pre_stdout = root / "pre.stdout"
            post_stdout = root / "post.stdout"
            pre_stdout.write_text("1 failed, 5 passed in 0.1s\n", encoding="utf-8")
            post_stdout.write_text("3 failed, 2 passed in 0.1s\n", encoding="utf-8")
            report = assess_repair_safety(
                pre_pytest={"exit_code": 1, "stdout_path": str(pre_stdout)},
                post_pytest={"exit_code": 1, "stdout_path": str(post_stdout)},
                pre_manifest_install={"ok": True},
                post_manifest_install={"ok": True},
                static_guardrails={"violations": []},
                cumulative_diff={"changed_files": ["src/demo.py"]},
            )
            self.assertTrue(report["rollback_required"])
            self.assertIn("canonical_pytest_outcomes_worsened", report["reasons"])

    def test_assessment_blocks_protected_test_environment_modification(self) -> None:
        report = assess_repair_safety(
            pre_pytest={"exit_code": 0},
            post_pytest={"exit_code": 0},
            pre_manifest_install={"ok": True},
            post_manifest_install={"ok": True},
            static_guardrails={"violations": []},
            cumulative_diff={"changed_files": []},
            protected_runtime_changed=True,
        )
        self.assertTrue(report["rollback_required"])
        self.assertIn("protected_test_environment_modified", report["reasons"])

    def test_assessment_marks_post_manifest_infrastructure_error_invalid(self) -> None:
        report = assess_repair_safety(
            pre_pytest={"exit_code": 0},
            post_pytest={"exit_code": 0},
            pre_manifest_install={"ok": True, "infrastructure_error": False},
            post_manifest_install={"ok": False, "infrastructure_error": True},
            static_guardrails={"violations": []},
            cumulative_diff={"changed_files": []},
        )
        self.assertTrue(report["rollback_required"])
        self.assertTrue(report["harness_invalid_required"])
        self.assertIn("manifest_install_gate_infrastructure_error", report["reasons"])

    def test_assessment_rolls_back_only_on_regression(self) -> None:
        unsafe = assess_repair_safety(
            pre_pytest={"exit_code": 0},
            post_pytest={"exit_code": 1},
            pre_manifest_install={"ok": True},
            post_manifest_install={"ok": False},
            static_guardrails={"violations": []},
            cumulative_diff={"changed_files": ["pyproject.toml"]},
        )
        self.assertTrue(unsafe["rollback_required"])
        self.assertIn("canonical_pytest_regressed:0->1", unsafe["reasons"])
        self.assertIn("canonical_manifest_install_regressed", unsafe["reasons"])

        already_broken = assess_repair_safety(
            pre_pytest={"exit_code": 1},
            post_pytest={"exit_code": 1},
            pre_manifest_install={"ok": False},
            post_manifest_install={"ok": False},
            static_guardrails={"violations": []},
            cumulative_diff={"changed_files": []},
        )
        self.assertFalse(already_broken["rollback_required"])


if __name__ == "__main__":
    unittest.main()
