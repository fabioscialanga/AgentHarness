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
TASK_ID = "refund-approval-api"

GOOD_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    from copy import deepcopy

    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class RefundCreate(BaseModel):
        order_id: str
        amount: float
        currency: str
        reason: str
        requested_by: str

    class ReviewPayload(BaseModel):
        decision: str
        approver: str
        note: str

    refunds: dict[int, dict] = {}
    next_id = 1

    def clone_refund(item: dict) -> dict:
        return deepcopy(item)

    @app.post("/refunds", status_code=201)
    def create_refund(payload: RefundCreate):
        global next_id
        if payload.amount <= 0:
            raise HTTPException(status_code=422, detail="invalid amount")
        if payload.amount <= 50:
            status = "approved"
        else:
            status = "pending_manager"
        record = {
            "id": next_id,
            "order_id": payload.order_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "reason": payload.reason,
            "requested_by": payload.requested_by,
            "status": status,
            "manager_approver": None,
            "manager_note": None,
            "finance_approver": None,
            "finance_note": None,
        }
        refunds[next_id] = record
        next_id += 1
        return clone_refund(record)

    @app.get("/refunds")
    def list_refunds(status: str | None = None, requested_by: str | None = None):
        items = list(refunds.values())
        if status is not None:
            items = [item for item in items if item["status"] == status]
        if requested_by is not None:
            items = [item for item in items if item["requested_by"] == requested_by]
        items.sort(key=lambda item: item["id"])
        return [clone_refund(item) for item in items]

    @app.get("/refunds/{refund_id}")
    def get_refund(refund_id: int):
        item = refunds.get(refund_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return clone_refund(item)

    @app.post("/refunds/{refund_id}/manager-review")
    def manager_review(refund_id: int, payload: ReviewPayload):
        item = refunds.get(refund_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="invalid decision")
        if item["status"] in {"approved", "rejected"}:
            raise HTTPException(status_code=409, detail="terminal state")
        if item["amount"] <= 50:
            raise HTTPException(status_code=409, detail="small refunds do not need manager review")
        if payload.decision == "reject":
            item["status"] = "rejected"
        elif item["amount"] > 500:
            item["status"] = "pending_finance"
        else:
            item["status"] = "approved"
        item["manager_approver"] = payload.approver
        item["manager_note"] = payload.note
        return clone_refund(item)

    @app.post("/refunds/{refund_id}/finance-review")
    def finance_review(refund_id: int, payload: ReviewPayload):
        item = refunds.get(refund_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.decision not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail="invalid decision")
        if item["status"] in {"approved", "rejected"}:
            raise HTTPException(status_code=409, detail="terminal state")
        if item["status"] != "pending_finance":
            raise HTTPException(status_code=409, detail="finance review not allowed yet")
        item["status"] = "approved" if payload.decision == "approve" else "rejected"
        item["finance_approver"] = payload.approver
        item["finance_note"] = payload.note
        return clone_refund(item)
    '''
).strip() + "\n"

BUGGY_APP = (
    GOOD_APP.replace(
        'status = "approved"',
        'status = "pending_manager"  # BUG: small refunds are not auto-approved',
        1,
    )
    .replace(
        'item["status"] = "approved"',
        'item["status"] = "pending_finance"  # BUG: medium refunds wrongly require finance',
        1,
    )
    .replace(
        'raise HTTPException(status_code=409, detail="finance review not allowed yet")',
        'pass  # BUG: finance can review before manager approval',
    )
    .replace(
        'raise HTTPException(status_code=422, detail="invalid amount")',
        'pass  # BUG: invalid amount accepted',
    )
    .replace(
        'raise HTTPException(status_code=409, detail="terminal state")',
        'pass  # BUG: terminal manager review can run again',
        1,
    )
)


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_source, encoding="utf-8")
    (workspace / "README.md").write_text("# Refund approval API\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = \"refund-approval-api\"\nversion = \"0.1.0\"\ndependencies = [\"fastapi\", \"pydantic\", \"pytest\", \"sqlalchemy\"]\n",
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


class RefundBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "refund_good_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / ".agentharness" / "evaluation" / TASK_ID / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("small_refund_auto_approved=pass", summary_text)
            self.assertIn("large_refund_needs_finance=pass", summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "refund_cli_good_001"
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
            run_id = "refund_cli_buggy_001"
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
            self.assertIn("small_refund_auto_approved", hidden_payload["failed_checks"])
            self.assertIn("medium_refund_needs_manager", hidden_payload["failed_checks"])
            self.assertIn("large_refund_needs_finance", hidden_payload["failed_checks"])
            self.assertIn("invalid_amount_rejected", hidden_payload["failed_checks"])
            self.assertIn("terminal_state_blocks_reapproval", hidden_payload["failed_checks"])

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
            self.assertGreaterEqual(payload["summary"]["failed"], 4)

    def test_library_evaluator_integrates_with_evaluate_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "refund_evalrun_good_001"
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / "HELDOUT_EVALUATION_SUITE.template.json"
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / "suite.json")

            hidden_result = evaluate_benchmark_task(run_path, TASK_ID)
            self.assertTrue(hidden_result.critical_ok)

            evaluation = evaluate_run(run_path=run_path, suite_path=suite_path)
            self.assertTrue(evaluation.ok, evaluation.to_dict())
            self.assertEqual(evaluation.summary["failed"], 0)
            self.assertGreaterEqual(evaluation.summary["passed"], 6)


if __name__ == "__main__":
    unittest.main()
