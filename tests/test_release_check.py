from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_release.py"


class ReleaseCheckTests(unittest.TestCase):
    def _run(self, tag: str, version: str = "0.1.0", heading: str = "0.1.0 - 2026-07-15") -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pyproject = root / "pyproject.toml"
            changelog = root / "CHANGELOG.md"
            pyproject.write_text(
                f'[project]\nname = "agentharness"\nversion = "{version}"\n',
                encoding="utf-8",
            )
            changelog.write_text(f"# Changelog\n\n## {heading}\n", encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--tag",
                    tag,
                    "--pyproject",
                    str(pyproject),
                    "--changelog",
                    str(changelog),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_accepts_matching_stable_tag_and_dated_changelog(self) -> None:
        result = self._run("v0.1.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release validation passed", result.stdout)

    def test_rejects_tag_that_does_not_match_package_version(self) -> None:
        result = self._run("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match pyproject version", result.stderr)

    def test_rejects_undated_changelog_entry(self) -> None:
        result = self._run("v0.1.0", heading="0.1.0 - Initial alpha")
        self.assertEqual(result.returncode, 1)
        self.assertIn("dated", result.stderr)

    def test_rejects_prerelease_tag_for_stable_release_workflow(self) -> None:
        result = self._run("v0.1.0rc1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("stable semantic-version", result.stderr)


if __name__ == "__main__":
    unittest.main()
