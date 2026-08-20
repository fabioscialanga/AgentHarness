from __future__ import annotations

import subprocess
import sys

from agentharness import __version__


def test_module_cli_reports_package_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "agentharness", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"agentharness {__version__}"
    assert completed.stderr == ""
