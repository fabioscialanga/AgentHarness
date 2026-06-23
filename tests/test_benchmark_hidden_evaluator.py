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
TASK_ID = "support-ticket-api"

GOOD_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    from copy import deepcopy
    from datetime import datetime, timezone

    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class TicketCreate(BaseModel):
        title: str
        description: str
        requester_email: str
        category: str
        priority: str

    class TicketUpdate(BaseModel):
        status: str | None = None
        assignee: str | None = None

    class CommentCreate(BaseModel):
        author: str
        body: str

    VALID_CATEGORIES = {"hardware", "software", "access", "network", "other"}
    VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
    VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}

    tickets: dict[int, dict] = {}
    next_id = 1

    def now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def normalize_ticket(ticket: dict) -> dict:
        payload = deepcopy(ticket)
        payload["comments"] = [deepcopy(item) for item in ticket["comments"]]
        return payload

    @app.post("/tickets", status_code=201)
    def create_ticket(ticket: TicketCreate):
        global next_id
        if not ticket.title.strip() or not ticket.description.strip():
            raise HTTPException(status_code=422, detail="title and description are required")
        if "@" not in ticket.requester_email or "." not in ticket.requester_email.split("@")[-1]:
            raise HTTPException(status_code=422, detail="invalid requester_email")
        if ticket.category not in VALID_CATEGORIES:
            raise HTTPException(status_code=422, detail="invalid category")
        if ticket.priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=422, detail="invalid priority")
        record = {
            "id": next_id,
            "title": ticket.title,
            "description": ticket.description,
            "requester_email": ticket.requester_email,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": "open",
            "assignee": None,
            "comments": [],
            "created_at": now(),
            "updated_at": now(),
        }
        tickets[next_id] = record
        next_id += 1
        return normalize_ticket(record)

    @app.get("/tickets")
    def list_tickets(status: str | None = None, priority: str | None = None, category: str | None = None):
        items = list(tickets.values())
        if status is not None:
            items = [item for item in items if item["status"] == status]
        if priority is not None:
            items = [item for item in items if item["priority"] == priority]
        if category is not None:
            items = [item for item in items if item["category"] == category]
        items.sort(key=lambda item: item["id"], reverse=True)
        return [normalize_ticket(item) for item in items]

    @app.get("/tickets/{ticket_id}")
    def get_ticket(ticket_id: int):
        ticket = tickets.get(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="not found")
        return normalize_ticket(ticket)

    @app.patch("/tickets/{ticket_id}")
    def update_ticket(ticket_id: int, payload: TicketUpdate):
        ticket = tickets.get(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.status is not None:
            if payload.status not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid status")
            if ticket["status"] == "closed" and payload.status == "open":
                raise HTTPException(status_code=409, detail="closed tickets cannot reopen")
            ticket["status"] = payload.status
            if payload.status in {"resolved", "closed"}:
                ticket["updated_at"] = now()
        if payload.assignee is not None:
            ticket["assignee"] = payload.assignee
        return normalize_ticket(ticket)

    @app.post("/tickets/{ticket_id}/comments", status_code=201)
    def add_comment(ticket_id: int, payload: CommentCreate):
        ticket = tickets.get(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="not found")
        if not payload.body.strip():
            raise HTTPException(status_code=422, detail="empty comment")
        ticket["comments"].append({"author": payload.author, "body": payload.body})
        ticket["updated_at"] = now()
        return {"ok": True}
    '''
).strip() + "\n"

BUGGY_APP = GOOD_APP.replace(
    'raise HTTPException(status_code=422, detail="invalid requester_email")',
    'pass  # BUG: invalid requester_email accepted',
).replace(
    'raise HTTPException(status_code=409, detail="closed tickets cannot reopen")',
    'pass  # BUG: closed tickets can reopen',
)


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_source, encoding="utf-8")
    (workspace / "README.md").write_text("# Support ticket API\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = \"support-ticket-api\"\nversion = \"0.1.0\"\n",
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


class BenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "support_ticket_good_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_path = workspace / ".agentharness" / "evaluation" / TASK_ID / "summary.txt"
            result_path = workspace / ".agentharness" / "evaluation" / TASK_ID / "result.json"
            self.assertTrue(summary_path.is_file())
            self.assertTrue(result_path.is_file())
            summary_text = summary_path.read_text(encoding="utf-8")
            self.assertIn("create_valid_ticket=pass", summary_text)
            self.assertIn("invalid_email_rejected=pass", summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "support_ticket_cli_good_001"
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")

            hidden_eval = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentharness",
                    "benchmark-evaluate-task",
                    "--run",
                    str(run_path),
                    "--task-id",
                    TASK_ID,
                    "--json",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hidden_eval.returncode, 0, hidden_eval.stderr)
            hidden_payload = json.loads(hidden_eval.stdout)
            self.assertTrue(hidden_payload["critical_ok"])

            completed = subprocess.run(
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
                ],
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
            run_id = "support_ticket_cli_buggy_001"
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")

            hidden_eval = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentharness",
                    "benchmark-evaluate-task",
                    "--run",
                    str(run_path),
                    "--task-id",
                    TASK_ID,
                    "--json",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hidden_eval.returncode, 1, hidden_eval.stdout)
            hidden_payload = json.loads(hidden_eval.stdout)
            self.assertFalse(hidden_payload["critical_ok"])
            self.assertIn("closed_ticket_reopen_blocked", hidden_payload["failed_checks"])
            self.assertIn("invalid_email_rejected", hidden_payload["failed_checks"])

            completed = subprocess.run(
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
                ],
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
            run_id = "support_ticket_schema_001"
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
