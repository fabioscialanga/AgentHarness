#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agentharness.benchmarking import write_rendered_json_template


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def write_run(run_path: Path, workspace: Path, run_id: str) -> None:
    changed_files = sorted(
        str(path.relative_to(workspace))
        for path in workspace.rglob("*")
        if path.is_file() and ".agentharness" not in path.parts
    )
    run_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workspace": str(workspace),
                "artifacts": {
                    "changed_files": changed_files,
                    "commands": [{"cmd": "pytest -q", "exit_code": 0}],
                    "outputs": [
                        {"type": "file", "path": rel_path}
                        for rel_path in changed_files[:20]
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGENTHARNESS_GRADING_ENV_DIR"] = str(BENCHMARKS_DIR / "grading-env")
    return subprocess.run(command, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline smoke check for a benchmark solution workspace.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(json.dumps({"ok": False, "error": f"workspace not found: {workspace}"}, indent=2))
        return 2

    template_path = BENCHMARKS_DIR / args.task_id / "HELDOUT_EVALUATION_SUITE.template.json"
    if not template_path.is_file():
        print(json.dumps({"ok": False, "error": f"suite template not found: {template_path}"}, indent=2))
        return 2

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_root = Path(tmp_dir)
        run_id = f"smoke_{args.task_id.replace('-', '_')}"
        run_path = temp_root / "run.json"
        write_run(run_path, workspace, run_id)
        suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")

        hidden_eval = run_command(
            [
                sys.executable,
                "-m",
                "agentharness",
                "benchmark-evaluate-task",
                "--run",
                str(run_path),
                "--task-id",
                args.task_id,
                "--json",
            ]
        )
        if hidden_eval.returncode != 0:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "stage": "benchmark-evaluate-task",
                        "returncode": hidden_eval.returncode,
                        "stdout": hidden_eval.stdout,
                        "stderr": hidden_eval.stderr,
                    },
                    indent=2,
                )
            )
            return hidden_eval.returncode or 1

        evaluate = run_command(
            [
                sys.executable,
                "-m",
                "agentharness",
                "evaluate",
                "--run",
                str(run_path),
                "--suite",
                str(suite_path),
                "--json",
            ]
        )
        if evaluate.returncode != 0:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "stage": "evaluate",
                        "returncode": evaluate.returncode,
                        "stdout": evaluate.stdout,
                        "stderr": evaluate.stderr,
                    },
                    indent=2,
                )
            )
            return evaluate.returncode or 1

        print(
            json.dumps(
                {
                    "ok": True,
                    "task_id": args.task_id,
                    "workspace": str(workspace),
                    "benchmark_evaluate_task": json.loads(hidden_eval.stdout),
                    "evaluate": json.loads(evaluate.stdout),
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
