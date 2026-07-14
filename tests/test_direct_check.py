from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agentharness.direct_check import check_workspace


REPO_ROOT = Path(__file__).resolve().parents[1]


class DirectCheckTests(unittest.TestCase):
    def test_check_passes_and_preserves_original_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            test_file = workspace / "test_sample.py"
            test_file.write_text(
                "from pathlib import Path\n\n"
                "def test_passes():\n"
                "    Path('marker.txt').write_text('snapshot', encoding='utf-8')\n"
                "    assert True\n",
                encoding="utf-8",
            )

            result = check_workspace(
                workspace,
                "python -m pytest -q",
                run_id="check-pass",
                timeout_seconds=30,
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.verification.summary["supported"], 1)
            self.assertTrue(result.report_path.is_file())
            self.assertTrue((result.snapshot_workspace / "marker.txt").is_file())
            self.assertFalse((workspace / "marker.txt").exists())
            self.assertEqual(
                test_file.read_text(encoding="utf-8"),
                (result.snapshot_workspace / "test_sample.py").read_text(encoding="utf-8"),
            )
            payload = result.to_dict()
            self.assertEqual(payload["isolation"]["mode"], "workspace-copy")
            self.assertTrue(payload["isolation"]["command_cwd_is_snapshot"])
            self.assertFalse(payload["isolation"]["original_workspace_write_protected"])
            self.assertFalse(payload["isolation"]["network_isolated"])
            self.assertFalse(payload["isolation"]["host_filesystem_isolated"])

    def test_check_reports_failed_command_as_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "test_failure.py").write_text(
                "def test_fails():\n    assert False\n",
                encoding="utf-8",
            )

            result = check_workspace(
                workspace,
                "python -m pytest -q",
                run_id="check-failure",
                timeout_seconds=30,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.verification.summary["unsupported"], 1)
            claim = result.verification.results[0]
            self.assertEqual(claim.truth_source, "reexecuted")
            self.assertIn("exit_code 1", claim.reason)

    def test_check_can_add_scope_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            output_dir = Path(tmp_dir) / "artifacts"

            result = check_workspace(
                workspace,
                "python -m pytest -q",
                run_id="check-scope",
                output_dir=output_dir,
                allowed_paths=["src/*", "tests/*"],
                forbidden_paths=["secrets/*"],
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.verification.summary["supported"], 3)
            claims = json.loads(result.claims_path.read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in claims["claims"]], [
                "command_succeeds",
                "changes_stay_in_scope",
                "forbidden_paths_untouched",
            ])

    def test_check_rejects_symlink_that_escapes_workspace(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are not supported on this platform")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (workspace / "external-link").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "escape the snapshot boundary"):
                check_workspace(workspace, "python -m pytest -q", run_id="check-symlink")

    def test_cli_check_returns_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "test_cli.py").write_text("def test_cli():\n    assert 2 + 2 == 4\n", encoding="utf-8")
            command = [
                sys.executable,
                "-m",
                "agentharness",
                "check",
                "--workspace",
                str(workspace),
                "--command",
                "python -m pytest -q",
                "--run-id",
                "check-cli",
                "--json",
            ]
            completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["run_id"], "check-cli")
            self.assertEqual(payload["verification"]["summary"]["supported"], 1)
            self.assertTrue(Path(payload["report_path"]).is_file())

    def test_cli_check_returns_structured_invalid_error(self) -> None:
        command = [
            sys.executable,
            "-m",
            "agentharness",
            "check",
            "--workspace",
            "/path/that/does/not/exist",
            "--command",
            "python -m pytest -q",
            "--json",
        ]
        completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("does not exist", payload["error"])


if __name__ == "__main__":
    unittest.main()
