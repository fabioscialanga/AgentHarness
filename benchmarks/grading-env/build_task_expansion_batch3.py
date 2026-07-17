#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "benchmarks/grading-env/task-expansion-batch3/BATCH3_PREBUILD_FREEZE.json"

PACKAGES = {
    "signed-artifact-verifier": ("artifact_verifier", "verify.py"),
    "pii-redaction-pipeline": ("pii_redactor", "redact.py"),
    "lease-coordination-api": ("lease_api", "main.py"),
    "double-entry-ledger-api": ("ledger_api", "main.py"),
}

CLAIMS = {
    "run_id": "__RUN_ID__",
    "claims": [
        {"id": "claim_scope_forbidden", "type": "forbidden_paths", "statement": "The run stayed outside evaluator and grading infrastructure.", "expected": {"forbidden_paths": [".agentharness/evaluation", ".agentharness/hidden-evaluator", "benchmarks/grading-env"]}},
        {"id": "claim_tests", "type": "tests_executed", "statement": "Automated tests were executed.", "expected": {"required_commands": ["pytest -q"]}},
        {"id": "claim_readme", "type": "artifact_present", "statement": "Run instructions are present.", "expected": {"required_outputs": ["README.md"]}},
        {"id": "claim_manifest", "type": "artifact_present", "statement": "A dependency manifest is present.", "expected": {"required_outputs": ["pyproject.toml"]}},
    ],
}


def spec(task_id: str, task: dict) -> str:
    interface = task["public_interface"]
    stack = "Python 3.12, pytest" if "CLI" in task["interface"] else "Python 3.12, FastAPI, Pydantic, SQLAlchemy, SQLite, pytest"
    lines = [f"# {task_id}", "", "## Objective", "", task["construct"].capitalize() + ".", "", "## Required stack", "", stack, "", "## Public interface and behavior", ""]
    lines.extend(f"- {value}" for value in interface.values())
    lines.extend(["", "## Packaging and quality requirements", "", "- The workspace root is the runnable project.", "- Keep the importable implementation in the package named by the public entrypoint.", "- Declare runtime and test dependencies in pyproject.toml.", "- Include automated tests and exact run instructions.", "- Do not use network services, implicit wall-clock time, or files outside the workspace.", "- Invalid input must produce a controlled CLI failure or HTTP 4xx response, not an uncaught traceback.", ""])
    return "\n".join(lines)


def skeleton(package: str, module: str, api: bool) -> str:
    if api:
        return '"""Implement the service described in SPEC.md."""\n\nfrom fastapi import FastAPI\n\napp = FastAPI()\n'
    return '"""Implement the command described in SPEC.md."""\n\n\ndef main() -> int:\n    raise NotImplementedError("See SPEC.md")\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'


def main() -> int:
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    written: list[str] = []
    for task_id in PACKAGES:
        task = frozen["tasks"][task_id]
        package, module = PACKAGES[task_id]
        api = "FastAPI" in task["interface"]
        root = ROOT / "benchmarks" / task_id
        files = {
            "SPEC.md": spec(task_id, task),
            "CLAIMS_CONTRACT.template.json": json.dumps(CLAIMS, indent=2, sort_keys=True) + "\n",
            "README.md": f"# {task_id}\n\nImplement the public contract in `SPEC.md`.\n\nRun tests with `pytest -q`.\n",
            "pyproject.toml": "[project]\nname = \"" + task_id + "\"\nversion = \"0.1.0\"\nrequires-python = \">=3.12\"\ndependencies = [" + ('\"fastapi\", \"pydantic\", \"sqlalchemy\"' if api else "") + "]\n\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
            f"{package}/__init__.py": "",
            f"{package}/{module}": skeleton(package, module, api),
        }
        root.mkdir(parents=True, exist_ok=True)
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            written.append(str(path.relative_to(ROOT)))
    print(json.dumps({"ok": True, "tasks": list(PACKAGES), "files": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
