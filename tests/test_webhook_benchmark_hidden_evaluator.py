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
TASK_ID = "webhook-ingestion-service"

GOOD_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    import hashlib
    import hmac
    import json
    import os
    from copy import deepcopy

    from fastapi import FastAPI, HTTPException, Request

    app = FastAPI()

    SECRET = os.environ.get("WEBHOOK_SECRET", "agentharness-test-secret")
    events: dict[str, dict] = {}

    def normalize_status(event_type: str) -> str:
        mapping = {
            "partner.created": "created",
            "partner.updated": "updated",
            "partner.cancelled": "cancelled",
        }
        if event_type not in mapping:
            raise HTTPException(status_code=422, detail="unsupported type")
        return mapping[event_type]

    def verify_signature(raw_body: bytes, signature: str | None) -> None:
        if not signature:
            raise HTTPException(status_code=401, detail="missing signature")
        expected = hmac.new(SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="invalid signature")

    def clone_event(item: dict) -> dict:
        return deepcopy(item)

    @app.post("/webhooks", status_code=201)
    async def receive_webhook(request: Request):
        raw_body = await request.body()
        verify_signature(raw_body, request.headers.get("x-signature"))
        payload = json.loads(raw_body.decode("utf-8"))
        required = {"event_id", "source", "occurred_at", "type", "payload"}
        missing = sorted(required - payload.keys())
        if missing:
            raise HTTPException(status_code=422, detail=f"missing fields: {', '.join(missing)}")
        event_id = payload["event_id"]
        if event_id in events:
            return clone_event(events[event_id])
        record = {
            "event_id": event_id,
            "source": payload["source"],
            "occurred_at": payload["occurred_at"],
            "type": payload["type"],
            "normalized_status": normalize_status(payload["type"]),
            "payload": deepcopy(payload["payload"]),
        }
        events[event_id] = record
        return clone_event(record)

    @app.get("/events/{event_id}")
    def get_event(event_id: str):
        item = events.get(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return clone_event(item)

    @app.get("/events")
    def list_events(normalized_status: str | None = None, source: str | None = None):
        items = list(events.values())
        if normalized_status is not None:
            items = [item for item in items if item["normalized_status"] == normalized_status]
        if source is not None:
            items = [item for item in items if item["source"] == source]
        items.sort(key=lambda item: item["event_id"])
        return [clone_event(item) for item in items]
    '''
).strip() + "\n"

BUGGY_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    import hashlib
    import hmac
    import json
    import os
    from copy import deepcopy

    from fastapi import FastAPI, HTTPException, Request

    app = FastAPI()

    SECRET = os.environ.get("WEBHOOK_SECRET", "agentharness-test-secret")
    events: dict[str, dict] = {}
    event_log: list[dict] = []

    def normalize_status(event_type: str) -> str:
        mapping = {
            "partner.created": "created",
            "partner.updated": "updated",
            "partner.cancelled": "updated",  # BUG: wrong normalization
        }
        if event_type not in mapping:
            raise HTTPException(status_code=422, detail="unsupported type")
        return mapping[event_type]

    def verify_signature(raw_body: bytes, signature: str | None) -> None:
        if not signature:
            raise HTTPException(status_code=401, detail="missing signature")
        expected = hmac.new(SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None  # BUG: accept invalid signatures

    def clone_event(item: dict) -> dict:
        return deepcopy(item)

    @app.post("/webhooks", status_code=201)
    async def receive_webhook(request: Request):
        raw_body = await request.body()
        verify_signature(raw_body, request.headers.get("x-signature"))
        payload = json.loads(raw_body.decode("utf-8"))
        required = {"event_id", "source", "occurred_at", "type", "payload"}
        missing = sorted(required - payload.keys())
        if missing:
            payload.setdefault("type", "partner.created")  # BUG: tolerate missing type
        event_id = payload["event_id"]
        record = {
            "event_id": event_id,
            "source": payload["source"],
            "occurred_at": payload["occurred_at"],
            "type": payload["type"],
            "normalized_status": normalize_status(payload["type"]),
            "payload": deepcopy(payload["payload"]),
        }
        events[event_id] = record
        event_log.append(record)
        return clone_event(record)

    @app.get("/events/{event_id}")
    def get_event(event_id: str):
        item = events.get(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return clone_event(item)

    @app.get("/events")
    def list_events(normalized_status: str | None = None, source: str | None = None):
        items = list(event_log)
        if normalized_status is not None:
            items = [item for item in items if item["normalized_status"] == normalized_status]
        if source is not None:
            items = [item for item in items if item["source"] == source]
        items.sort(key=lambda item: item["event_id"])
        return [clone_event(item) for item in items]
    '''
).strip() + "\n"

RELATIVE_IMPORT_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    from copy import deepcopy

    from fastapi import FastAPI, HTTPException, Request

    from .security import normalize_status, verify_signature

    app = FastAPI()
    events: dict[str, dict] = {}

    def clone_event(item: dict) -> dict:
        return deepcopy(item)

    @app.post("/webhooks", status_code=201)
    async def receive_webhook(request: Request):
        raw_body = await request.body()
        verify_signature(raw_body, request.headers.get("x-signature"))
        payload = await request.json()
        required = {"event_id", "source", "occurred_at", "type", "payload"}
        missing = sorted(required - payload.keys())
        if missing:
            raise HTTPException(status_code=422, detail=f"missing fields: {', '.join(missing)}")
        event_id = payload["event_id"]
        if event_id in events:
            return clone_event(events[event_id])
        record = {
            "event_id": event_id,
            "source": payload["source"],
            "occurred_at": payload["occurred_at"],
            "type": payload["type"],
            "normalized_status": normalize_status(payload["type"]),
            "payload": deepcopy(payload["payload"]),
        }
        events[event_id] = record
        return clone_event(record)

    @app.get("/events/{event_id}")
    def get_event(event_id: str):
        item = events.get(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return clone_event(item)

    @app.get("/events")
    def list_events(normalized_status: str | None = None, source: str | None = None):
        items = list(events.values())
        if normalized_status is not None:
            items = [item for item in items if item["normalized_status"] == normalized_status]
        if source is not None:
            items = [item for item in items if item["source"] == source]
        items.sort(key=lambda item: item["event_id"])
        return [clone_event(item) for item in items]
    '''
).strip() + "\n"

RELATIVE_IMPORT_HELPER = textwrap.dedent(
    '''
    from __future__ import annotations

    import hashlib
    import hmac
    import os

    from fastapi import HTTPException

    SECRET = os.environ.get("WEBHOOK_SECRET", "agentharness-test-secret")

    def normalize_status(event_type: str) -> str:
        mapping = {
            "partner.created": "created",
            "partner.updated": "updated",
            "partner.cancelled": "cancelled",
        }
        if event_type not in mapping:
            raise HTTPException(status_code=422, detail="unsupported type")
        return mapping[event_type]

    def verify_signature(raw_body: bytes, signature: str | None) -> None:
        if not signature:
            raise HTTPException(status_code=401, detail="missing signature")
        expected = hmac.new(SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="invalid signature")
    '''
).strip() + "\n"

PACKAGE_REEXPORT_INIT = 'from .main import app\n__all__ = ["app"]\n'


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_source, encoding="utf-8")
    (workspace / "README.md").write_text("# Webhook ingestion service\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = \"webhook-ingestion-service\"\nversion = \"0.1.0\"\ndependencies = [\"fastapi\", \"pydantic\", \"pytest\", \"sqlalchemy\"]\n",
        encoding="utf-8",
    )


def _write_workspace_with_manifest(workspace: Path, app_source: str, dependencies: list[str]) -> None:
    app_dir = workspace / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_source, encoding="utf-8")
    (workspace / "README.md").write_text("# Webhook ingestion service\n", encoding="utf-8")
    dependency_block = ", ".join(json.dumps(item) for item in dependencies)
    (workspace / "pyproject.toml").write_text(
        f"[project]\nname = \"webhook-ingestion-service\"\nversion = \"0.1.0\"\ndependencies = [{dependency_block}]\n",
        encoding="utf-8",
    )


def _write_workspace_with_relative_imports(workspace: Path) -> None:
    _write_workspace(workspace, RELATIVE_IMPORT_APP)
    app_dir = workspace / "app"
    (app_dir / "security.py").write_text(RELATIVE_IMPORT_HELPER, encoding="utf-8")


def _write_src_package_workspace(workspace: Path, app_source: str, dependencies: list[str]) -> None:
    package_dir = workspace / "src" / "webhook_service"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text(PACKAGE_REEXPORT_INIT, encoding="utf-8")
    (package_dir / "main.py").write_text(app_source, encoding="utf-8")
    dependency_block = ", ".join(json.dumps(item) for item in dependencies)
    (workspace / "README.md").write_text("# Webhook ingestion service\n", encoding="utf-8")
    (workspace / "pyproject.toml").write_text(
        f"[project]\nname = \"webhook-ingestion-service\"\nversion = \"0.1.0\"\ndependencies = [{dependency_block}]\n",
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


class WebhookBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "webhook_good_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / ".agentharness" / "evaluation" / TASK_ID / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("valid_signed_event_stored=pass", summary_text)
            self.assertIn("duplicate_delivery_idempotent=pass", summary_text)

    def test_library_evaluator_supports_package_relative_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace_with_relative_imports(workspace)
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "webhook_relative_imports_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])

    def test_library_evaluator_supports_src_package_reexporting_app_from___init__(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_src_package_workspace(
                workspace,
                GOOD_APP,
                ["fastapi", "pydantic", "pytest>=8.0,<9.0", "sqlalchemy", "httpx", "uvicorn"],
            )
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "webhook_src_package_reexport_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok, result.to_dict())
            self.assertEqual(result.failed_checks, [])

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "webhook_cli_good_001"
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
            run_id = "webhook_cli_buggy_001"
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
            self.assertEqual(hidden_payload["classification_reason"], "behavior_wrong:functional_checks_failed")
            self.assertIn("invalid_signature_rejected", hidden_payload["failed_checks"])
            self.assertIn("duplicate_delivery_idempotent", hidden_payload["failed_checks"])
            self.assertIn("type_normalized_correctly", hidden_payload["failed_checks"])
            self.assertIn("missing_fields_rejected", hidden_payload["failed_checks"])

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

    def test_uvicorn_and_httpx_dependencies_install_and_still_allow_functional_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace_with_manifest(
                workspace,
                GOOD_APP,
                ["fastapi", "pydantic", "pytest", "sqlalchemy", "httpx", "uvicorn"],
            )
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "webhook_out_of_spec_dep_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok, result.to_dict())
            self.assertEqual(result.execution_status, "valid")
            self.assertEqual(result.outcome_status, "success")
            self.assertEqual(result.classification_reason, "")
            self.assertIn("valid_signed_event_stored", result.passed_checks)

    def test_dependency_outside_wheelhouse_gets_install_based_preparation_failure_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace_with_manifest(
                workspace,
                GOOD_APP,
                ["fastapi", "pydantic", "pytest", "sqlalchemy", "pandas"],
            )
            run_path = temp_root / "run.json"
            _write_run(run_path, workspace, "webhook_out_of_wheelhouse_dep_001")

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertFalse(result.critical_ok)
            self.assertEqual(result.execution_status, "valid")
            self.assertEqual(result.outcome_status, "real_failure")
            self.assertEqual(result.classification_reason, "preparation_failed:dependency_not_in_wheelhouse")
            self.assertIn("offline wheelhouse", result.observations[0].detail)
            self.assertIn("pandas", result.observations[0].detail)

    def test_hidden_evaluator_outputs_match_declared_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = "webhook_schema_001"
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
