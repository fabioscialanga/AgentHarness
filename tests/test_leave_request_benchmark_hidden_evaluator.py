from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from agentharness.benchmark_hidden_evaluators import evaluate_benchmark_task
from agentharness.benchmarking import write_rendered_json_template
from agentharness.evaluation import evaluate_run

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
TASK_ID = "leave-request-api"

GOOD_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    from copy import deepcopy
    from datetime import date, datetime, timezone

    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class LeaveRequestCreate(BaseModel):
        employee_id: str
        leave_type: str
        start_date: date
        end_date: date
        reason: str

    class LeaveReview(BaseModel):
        decision: str
        reviewer: str
        note: str

    VALID_LEAVE_TYPES = {"vacation", "sick", "personal"}
    requests: dict[int, dict] = {}
    next_id = 1

    def now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def clone_request(item: dict) -> dict:
        return deepcopy(item)

    def overlaps(left: dict, right: dict) -> bool:
        return not (left["end_date"] < right["start_date"] or right["end_date"] < left["start_date"])

    @app.post("/requests", status_code=201)
    def create_request(payload: LeaveRequestCreate):
        global next_id
        if payload.leave_type not in VALID_LEAVE_TYPES:
            raise HTTPException(status_code=422, detail="invalid leave_type")
        if payload.start_date > payload.end_date:
            raise HTTPException(status_code=422, detail="start_date after end_date")
        record = {
            "id": next_id,
            "employee_id": payload.employee_id,
            "leave_type": payload.leave_type,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "reason": payload.reason,
            "status": "pending",
            "reviewer": None,
            "review_note": None,
            "reviewed_at": None,
            "created_at": now(),
        }
        requests[next_id] = record
        next_id += 1
        return clone_request(record)

    @app.get("/requests")
    def list_requests(employee_id: str | None = None, status: str | None = None):
        items = list(requests.values())
        if employee_id is not None:
            items = [item for item in items if item["employee_id"] == employee_id]
        if status is not None:
            items = [item for item in items if item["status"] == status]
        items.sort(key=lambda item: item["id"])
        return [clone_request(item) for item in items]

    @app.get("/requests/{request_id}")
    def get_request(request_id: int):
        item = requests.get(request_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return clone_request(item)

    @app.post("/requests/{request_id}/review")
    def review_request(request_id: int, payload: LeaveReview):
        item = requests.get(request_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="invalid decision")
        if item["status"] in {"approved", "rejected"}:
            raise HTTPException(status_code=409, detail="terminal state")
        start = date.fromisoformat(item["start_date"])
        end = date.fromisoformat(item["end_date"])
        duration_days = (end - start).days + 1
        if item["leave_type"] == "personal" and duration_days > 3:
            raise HTTPException(status_code=409, detail="personal leave exceeds limit")
        if payload.decision == "approve":
            current_window = {"start_date": start, "end_date": end}
            for other in requests.values():
                if other["id"] == request_id:
                    continue
                if other["employee_id"] != item["employee_id"]:
                    continue
                if other["status"] != "approved":
                    continue
                other_window = {
                    "start_date": date.fromisoformat(other["start_date"]),
                    "end_date": date.fromisoformat(other["end_date"]),
                }
                if overlaps(current_window, other_window):
                    raise HTTPException(status_code=409, detail="overlapping approved leave")
            item["status"] = "approved"
        else:
            item["status"] = "rejected"
        item["reviewer"] = payload.reviewer
        item["review_note"] = payload.note
        item["reviewed_at"] = now()
        return clone_request(item)
    '''
).strip() + "\n"

BUGGY_APP = (
    GOOD_APP.replace(
        'raise HTTPException(status_code=409, detail="terminal state")',
        'pass  # BUG: allow second review on terminal requests',
    )
    .replace(
        'raise HTTPException(status_code=409, detail="personal leave exceeds limit")',
        'pass  # BUG: allow personal leave beyond 3 days',
    )
    .replace(
        'raise HTTPException(status_code=409, detail="overlapping approved leave")',
        'pass  # BUG: allow overlap with approved leave',
    )
    .replace(
        'item["reviewed_at"] = now()',
        'item["reviewed_at"] = None  # BUG: missing reviewed_at on review',
    )
)


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_source, encoding="utf-8")
    (workspace / "README.md").write_text("# Leave request API\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = \"leave-request-api\"\nversion = \"0.1.0\"\ndependencies = [\"fastapi\", \"pydantic\", \"pytest\", \"sqlalchemy\"]\n",
        encoding="utf-8",
    )


def _write_run(run_path: Path, workspace: Path, run_id: str) -> None:
    run_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workspace": str(workspace),
                "artifacts": {
                    "changed_files": ["app/main.py", "README.md", "pyproject.toml"],
                    "commands": [{"cmd": "pytest -q", "exit_code": 0}],
                    "outputs": [
                        {"type": "file", "path": "README.md"},
                        {"type": "file", "path": "pyproject.toml"},
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class LeaveRequestBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "leave_request_good_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / ".agentharness" / "evaluation" / TASK_ID / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("valid_request_created=pass", summary_text)
            self.assertIn("terminal_state_blocks_second_review=pass", summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "leave_request_cli_good_001"
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")

            hidden_eval = subprocess.run(
                [sys.executable, "-m", "agentharness", "benchmark-evaluate-task", "--run", str(run_path), "--task-id", TASK_ID, "--json"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hidden_eval.returncode, 0, hidden_eval.stderr)
            hidden_payload = json.loads(hidden_eval.stdout)
            self.assertTrue(hidden_payload["critical_ok"])

            completed = subprocess.run(
                [sys.executable, "-m", "agentharness", "evaluate", "--run", str(run_path), "--suite", str(suite_path), "--json"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["failed"], 0)
            self.assertGreaterEqual(payload["summary"]["passed"], 6)

    def test_cli_evaluate_fails_for_buggy_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, BUGGY_APP)
            run_id = "leave_request_cli_buggy_001"
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")

            hidden_eval = subprocess.run(
                [sys.executable, "-m", "agentharness", "benchmark-evaluate-task", "--run", str(run_path), "--task-id", TASK_ID, "--json"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hidden_eval.returncode, 1, hidden_eval.stdout)
            hidden_payload = json.loads(hidden_eval.stdout)
            self.assertFalse(hidden_payload["critical_ok"])
            self.assertIn("overlap_rejected", hidden_payload["failed_checks"])
            self.assertIn("personal_leave_limit_enforced", hidden_payload["failed_checks"])
            self.assertIn("approval_sets_reviewed_at", hidden_payload["failed_checks"])
            self.assertIn("terminal_state_blocks_second_review", hidden_payload["failed_checks"])

            completed = subprocess.run(
                [sys.executable, "-m", "agentharness", "evaluate", "--run", str(run_path), "--suite", str(suite_path), "--json"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["ok"])
            self.assertGreaterEqual(payload["summary"]["failed"], 1)

    def test_hidden_evaluator_outputs_match_declared_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "leave_request_schema_001"
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, run_id)
            suite_path = write_rendered_json_template(
                BENCHMARKS_DIR / TASK_ID / "HELDOUT_EVALUATION_SUITE.template.json",
                run_id=run_id,
                output_path=temp_root / "suite.json",
            )
            evaluate_benchmark_task(run_path, TASK_ID)

            result = evaluate_run(run_path, suite_path)
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.summary["failed"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
