from __future__ import annotations

"""Provider-free, hash-bound V9 prebuild validator."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATUS = HERE / "V9_PREBUILD_STATUS.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"V9 prebuild NO-GO: {message}")


def run(command: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=600)
    if result.returncode:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"V9 prebuild NO-GO: command failed: {' '.join(command)}")


def main() -> int:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    require(status.get("schema_version") == 9, "status schema")
    require(status.get("status") == "qualified_provider_free_prebuild", "status")
    require(status.get("provider_calls") == status.get("model_calls") == 0, "call count")
    for relative, expected in status.get("artifact_sha256", {}).items():
        path = ROOT / relative
        require(path.is_file() and sha(path) == expected, f"hash mismatch:{relative}")
    report = json.loads((HERE / "V9_PROVIDER_FREE_PREBUILD_REPORT.json").read_text(encoding="utf-8"))
    review = json.loads((HERE / "V9_INDEPENDENT_PRE_DATA_REVIEW.json").read_text(encoding="utf-8"))
    require(report.get("ok") is True and report.get("provider_calls") == report.get("model_calls") == 0, "report")
    require(report.get("source_native_profiles") == 6 and report.get("agent_visible_leaks") == 0, "qualification")
    require(review.get("decision") == "GO" and not review.get("blockers"), "independent review")
    run([sys.executable, "-m", "pytest", "-q", "tests/test_benchmark_cells.py", "tests/test_mechanism_first_v9.py"])
    print("V9 provider-free prebuild: GO (6 source-native profiles; 68 tests; synthetic 15-call path; calls 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
