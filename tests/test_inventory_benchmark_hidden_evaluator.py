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
TASK_ID = "inventory-adjustment-api"

GOOD_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    from copy import deepcopy
    from datetime import datetime, timezone

    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class ItemCreate(BaseModel):
        sku: str
        name: str
        on_hand: int

    class AdjustmentCreate(BaseModel):
        reason: str
        delta: int | None = None
        counted_quantity: int | None = None

    class ReservationCreate(BaseModel):
        order_id: str
        quantity: int

    class ReleaseCreate(BaseModel):
        quantity: int

    items: dict[str, dict] = {}

    def now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def clone_item(item: dict) -> dict:
        payload = deepcopy(item)
        payload["history"] = sorted(
            [deepcopy(entry) for entry in item["history"]],
            key=lambda entry: entry["created_at"],
            reverse=True,
        )
        return payload

    @app.post("/items", status_code=201)
    def create_item(payload: ItemCreate):
        if payload.sku in items:
            raise HTTPException(status_code=409, detail="duplicate sku")
        if payload.on_hand < 0:
            raise HTTPException(status_code=422, detail="invalid quantities")
        items[payload.sku] = {
            "sku": payload.sku,
            "name": payload.name,
            "on_hand": payload.on_hand,
            "reserved": 0,
            "history": [],
        }
        return clone_item(items[payload.sku])

    @app.get("/items")
    def list_items(sku: str | None = None, low_stock: bool | None = None):
        values = list(items.values())
        if sku is not None:
            values = [item for item in values if item["sku"] == sku]
        if low_stock:
            values = [item for item in values if item["on_hand"] - item["reserved"] <= 5]
        return [clone_item(item) for item in values]

    @app.get("/items/{sku}")
    def get_item(sku: str):
        item = items.get(sku)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return clone_item(item)

    @app.post("/items/{sku}/adjustments", status_code=201)
    def create_adjustment(sku: str, payload: AdjustmentCreate):
        item = items.get(sku)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.reason not in {"receive", "damage", "recount"}:
            raise HTTPException(status_code=422, detail="invalid reason")
        if payload.reason == "recount":
            if payload.counted_quantity is None or payload.counted_quantity < 0:
                raise HTTPException(status_code=422, detail="invalid counted quantity")
            item["on_hand"] = payload.counted_quantity
        else:
            if payload.delta is None:
                raise HTTPException(status_code=422, detail="missing delta")
            candidate = item["on_hand"] + payload.delta
            if candidate < 0:
                raise HTTPException(status_code=409, detail="on_hand cannot go negative")
            item["on_hand"] = candidate
        if item["reserved"] > item["on_hand"]:
            raise HTTPException(status_code=409, detail="reserved exceeds on_hand")
        item["history"].append(
            {
                "type": "adjustment",
                "reason": payload.reason,
                "delta": payload.delta,
                "counted_quantity": payload.counted_quantity,
                "created_at": now(),
            }
        )
        return clone_item(item)

    @app.post("/items/{sku}/reservations", status_code=201)
    def reserve_stock(sku: str, payload: ReservationCreate):
        item = items.get(sku)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        available = item["on_hand"] - item["reserved"]
        if payload.quantity <= 0 or payload.quantity > available:
            raise HTTPException(status_code=409, detail="insufficient available stock")
        item["reserved"] += payload.quantity
        item["history"].append(
            {
                "type": "reservation",
                "order_id": payload.order_id,
                "quantity": payload.quantity,
                "created_at": now(),
            }
        )
        return {"ok": True}

    @app.post("/items/{sku}/reservations/{order_id}/release", status_code=201)
    def release_stock(sku: str, order_id: str, payload: ReleaseCreate):
        item = items.get(sku)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        reserved_for_order = sum(
            entry["quantity"]
            for entry in item["history"]
            if entry["type"] == "reservation" and entry.get("order_id") == order_id
        ) - sum(
            entry["quantity"]
            for entry in item["history"]
            if entry["type"] == "release" and entry.get("order_id") == order_id
        )
        if payload.quantity <= 0 or payload.quantity > reserved_for_order:
            raise HTTPException(status_code=409, detail="release exceeds reserved quantity")
        item["reserved"] -= payload.quantity
        item["history"].append(
            {
                "type": "release",
                "order_id": order_id,
                "quantity": payload.quantity,
                "created_at": now(),
            }
        )
        return {"ok": True}
    '''
).strip() + "\n"

BUGGY_APP = (
    GOOD_APP.replace(
        'raise HTTPException(status_code=409, detail="on_hand cannot go negative")',
        'candidate = max(candidate, -999)  # BUG: allow negative on_hand',
    )
    .replace(
        'raise HTTPException(status_code=409, detail="reserved exceeds on_hand")',
        'pass  # BUG: tolerate reserved above on_hand after adjustment',
    )
    .replace(
        'raise HTTPException(status_code=409, detail="insufficient available stock")',
        'pass  # BUG: allow over-reservation',
    )
    .replace(
        'raise HTTPException(status_code=409, detail="release exceeds reserved quantity")',
        'pass  # BUG: allow over-release',
    )
    .replace(
        'item["on_hand"] = payload.counted_quantity',
        'item["on_hand"] = item["on_hand"] + payload.counted_quantity  # BUG: recount as delta',
    )
)


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_source, encoding="utf-8")
    (workspace / "README.md").write_text("# Inventory adjustment API\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = \"inventory-adjustment-api\"\nversion = \"0.1.0\"\ndependencies = [\"fastapi\", \"pydantic\", \"pytest\", \"sqlalchemy\"]\n",
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


class InventoryBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "inventory_good_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / ".agentharness" / "evaluation" / TASK_ID / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("reserve_within_available=pass", summary_text)
            self.assertIn("release_cannot_exceed_reserved=pass", summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "inventory_cli_good_001"
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
            run_id = "inventory_cli_buggy_001"
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
            self.assertIn("over_reserve_rejected", hidden_payload["failed_checks"])
            self.assertIn("damage_cannot_go_negative", hidden_payload["failed_checks"])
            self.assertIn("recount_sets_exact_quantity", hidden_payload["failed_checks"])
            self.assertIn("release_cannot_exceed_reserved", hidden_payload["failed_checks"])

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
            run_id = "inventory_schema_001"
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
