from __future__ import annotations

import csv
import hashlib
import hmac
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from .verify import load_run


@dataclass
class HiddenEvaluationObservation:
    id: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class HiddenEvaluationResult:
    task_id: str
    critical_ok: bool
    passed_checks: list[str]
    failed_checks: list[str]
    observations: list[HiddenEvaluationObservation]
    summary_path: Path
    result_path: Path

    execution_status: str = "valid"
    outcome_status: str = "success"
    classification_reason: str = ""

    def __post_init__(self) -> None:
        if self.execution_status == "valid" and self.outcome_status == "success" and not self.critical_ok:
            self.outcome_status = "real_failure"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "critical_ok": self.critical_ok,
            "execution_status": self.execution_status,
            "outcome_status": self.outcome_status,
            "classification_reason": self.classification_reason,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "observations": [item.to_dict() for item in self.observations],
            "summary_path": str(self.summary_path),
            "result_path": str(self.result_path),
        }


def _evaluation_dir(workspace: Path, task_id: str) -> Path:
    return workspace / ".agentharness" / "evaluation" / task_id


def _persist_hidden_evaluation(result: HiddenEvaluationResult) -> HiddenEvaluationResult:
    result.summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_lines = [f"{item.id}={'pass' if item.status == 'pass' else 'fail'}" for item in result.observations]
    result.summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    result.result_path.write_text(
        json.dumps(
            {
                "task_id": result.task_id,
                "critical_ok": result.critical_ok,
                "execution_status": result.execution_status,
                "outcome_status": result.outcome_status,
                "classification_reason": result.classification_reason,
                "passed_checks": result.passed_checks,
                "failed_checks": result.failed_checks,
                "observations": [item.to_dict() for item in result.observations],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


@contextmanager
def _temporary_sys_path(paths: list[Path]):
    original = list(sys.path)
    for candidate in reversed(paths):
        as_text = str(candidate)
        if candidate.exists() and as_text not in sys.path:
            sys.path.insert(0, as_text)
    try:
        yield
    finally:
        sys.path[:] = original


@contextmanager
def _working_directory(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


@contextmanager
def _load_module_from_path(module_path: Path, workspace: Path):
    module_name = f"agentharness_benchmark_{module_path.stem}_{uuid.uuid4().hex}"
    import_roots = [workspace, workspace / "src", module_path.parent]
    with _temporary_sys_path(import_roots), _working_directory(workspace):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load module spec from {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            yield module
        finally:
            sys.modules.pop(module_name, None)


def _discover_fastapi_module(workspace: Path) -> Path:
    candidates: list[tuple[int, Path]] = []
    for path in workspace.rglob("*.py"):
        if any(part.startswith(".") for part in path.relative_to(workspace).parts):
            continue
        if "tests" in path.parts or "site-packages" in path.parts or ".venv" in path.parts:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "FastAPI(" not in content:
            continue
        score = 0
        if path.name == "main.py":
            score += 30
        if path.name == "app.py":
            score += 20
        lowered_parts = {part.lower() for part in path.parts}
        if "app" in lowered_parts:
            score += 10
        if "src" in lowered_parts:
            score += 5
        candidates.append((score, path))
    if not candidates:
        raise RuntimeError("Could not find a Python module defining a FastAPI application in the workspace")
    candidates.sort(key=lambda item: (-item[0], len(item[1].parts), str(item[1])))
    return candidates[0][1]


def _load_fastapi_app(workspace: Path) -> tuple[Path, Any]:
    module_path = _discover_fastapi_module(workspace)
    with _load_module_from_path(module_path, workspace) as module:
        for attribute_name in ("app", "api", "application"):
            candidate = getattr(module, attribute_name, None)
            if candidate is not None and candidate.__class__.__name__ == "FastAPI":
                return module_path, candidate
        for value in module.__dict__.values():
            if value is not None and value.__class__.__name__ == "FastAPI":
                return module_path, value
    raise RuntimeError(f"Could not locate a FastAPI app object inside {module_path}")


def _make_test_client(app: Any):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _normalize_ticket_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("id", "ticket_id"):
            if key in payload:
                return payload[key]
    return None


def _extract_comments(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    comments = payload.get("comments", [])
    if isinstance(comments, list):
        return comments
    return []


def _normalize_item_ref(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("sku", "id", "item_id"):
            if key in payload:
                return payload[key]
    return None


def _normalize_leave_request_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("id", "request_id", "leave_request_id"):
            if key in payload:
                return payload[key]
    return None


def _normalize_refund_request_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("id", "refund_id", "request_id"):
            if key in payload:
                return payload[key]
    return None


def _normalize_event_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("event_id", "id"):
            if key in payload:
                return payload[key]
    return None


def _extract_event_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "events", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _sign_webhook_payload(payload: dict[str, Any], secret: str) -> tuple[str, str]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body.decode("utf-8"), digest


def _discover_entrypoint(workspace: Path, candidates: list[str]) -> Path:
    for relative in candidates:
        candidate = workspace / relative
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"Could not find an entrypoint in workspace matching candidates: {candidates}")


def _run_python_entrypoint(workspace: Path, candidates: list[str], args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    entrypoint = _discover_entrypoint(workspace, candidates)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    module_name = ".".join(entrypoint.relative_to(workspace).with_suffix("").parts)
    module_result = subprocess.run(
        [sys.executable, "-m", module_name, *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )
    if module_result.returncode == 0:
        return module_result
    return subprocess.run(
        [sys.executable, str(entrypoint), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )


def _extract_history_entries(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    for key in ("history", "events", "adjustments"):
        value = payload.get(key, [])
        if isinstance(value, list):
            return value
    return []


API_BENCHMARK_TASK_IDS = {
    "support-ticket-api",
    "inventory-adjustment-api",
    "leave-request-api",
    "refund-approval-api",
    "incident-escalation-api",
    "webhook-ingestion-service",
}

WORKER_SENTINEL = "agentharness-benchmark-hidden-worker"
WORKER_PROTOCOL_VERSION = "1"


@dataclass
class _ManifestSpec:
    kind: str
    path: Path
    dependencies: list[str]


@dataclass
class _IsolationPreparation:
    ok: bool
    workspace: Path
    venv_dir: Path
    manifest: _ManifestSpec | None
    detail: str
    install_stdout: str = ""
    install_stderr: str = ""


def _required_manifest_dependencies(task_id: str) -> set[str]:
    if task_id in API_BENCHMARK_TASK_IDS:
        return {"fastapi", "pydantic"}
    return set()


def _canonical_dependency_name(spec: str) -> str:
    candidate = spec.strip()
    for separator in ("[", ";", "<", ">", "=", "!", "~", " "):
        candidate = candidate.split(separator, 1)[0]
    return candidate.replace("_", "-").lower()


def _discover_manifest(workspace: Path) -> _ManifestSpec | None:
    pyproject_path = workspace / "pyproject.toml"
    if pyproject_path.is_file():
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = payload.get("project", {})
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []
        return _ManifestSpec(kind="pyproject", path=pyproject_path, dependencies=[str(item) for item in dependencies])

    requirements_path = workspace / "requirements.txt"
    if requirements_path.is_file():
        dependencies = [
            line.strip()
            for line in requirements_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return _ManifestSpec(kind="requirements", path=requirements_path, dependencies=dependencies)

    return None


def _ensure_required_manifest_dependencies(task_id: str, manifest: _ManifestSpec | None) -> str | None:
    required = _required_manifest_dependencies(task_id)
    if not required:
        return None
    if manifest is None:
        return f"missing manifest: task {task_id} requires declared dependencies {sorted(required)}"
    declared = {_canonical_dependency_name(item) for item in manifest.dependencies}
    missing = sorted(required - declared)
    if missing:
        return f"manifest {manifest.path.name} is missing required dependencies for task {task_id}: {missing}"
    return None


def _manifest_hash(manifest: _ManifestSpec | None, task_id: str) -> str:
    seed = task_id
    if manifest is None:
        seed += "::no-manifest"
    else:
        seed += f"::{manifest.kind}::{manifest.path.read_text(encoding='utf-8')}"
    seed += f"::python={sys.version_info.major}.{sys.version_info.minor}"
    seed += f"::protocol={WORKER_PROTOCOL_VERSION}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _prepare_isolated_environment(workspace: Path, task_id: str) -> _IsolationPreparation:
    manifest = _discover_manifest(workspace)
    dependency_error = _ensure_required_manifest_dependencies(task_id, manifest)
    env_root = workspace / ".agentharness" / "eval_envs"
    env_root.mkdir(parents=True, exist_ok=True)
    venv_dir = env_root / _manifest_hash(manifest, task_id)
    if dependency_error is not None:
        return _IsolationPreparation(ok=False, workspace=workspace, venv_dir=venv_dir, manifest=manifest, detail=dependency_error)

    try:
        if not venv_dir.exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return _IsolationPreparation(
            ok=False,
            workspace=workspace,
            venv_dir=venv_dir,
            manifest=manifest,
            detail=f"harness failed creating isolated environment: {exc}",
            install_stdout=exc.stdout,
            install_stderr=exc.stderr,
        )
    except Exception as exc:
        return _IsolationPreparation(
            ok=False,
            workspace=workspace,
            venv_dir=venv_dir,
            manifest=manifest,
            detail=f"harness failed creating isolated environment: {exc}",
        )

    python_bin = venv_dir / "bin" / "python"
    marker_path = venv_dir / ".agentharness-ready.json"
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            marker = None
        if isinstance(marker, dict) and marker.get("protocol_version") == WORKER_PROTOCOL_VERSION:
            return _IsolationPreparation(ok=True, workspace=workspace, venv_dir=venv_dir, manifest=manifest, detail=f"reused isolated environment {venv_dir}")

    install_commands: list[list[str]] = [
        [str(python_bin), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"],
        [str(python_bin), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(Path(__file__).resolve().parents[2])],
    ]
    if manifest is not None:
        if manifest.kind == "pyproject" and manifest.dependencies:
            install_commands.append([str(python_bin), "-m", "pip", "install", "--disable-pip-version-check", *manifest.dependencies])
        elif manifest.kind == "requirements":
            install_commands.append([str(python_bin), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(manifest.path)])

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    try:
        for command in install_commands:
            completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, check=False)
            stdout_chunks.append(completed.stdout)
            stderr_chunks.append(completed.stderr)
            if completed.returncode != 0:
                return _IsolationPreparation(
                    ok=False,
                    workspace=workspace,
                    venv_dir=venv_dir,
                    manifest=manifest,
                    detail=f"solution environment install failed with exit code {completed.returncode}",
                    install_stdout="\n".join(stdout_chunks),
                    install_stderr="\n".join(stderr_chunks),
                )
        marker_path.write_text(
            json.dumps(
                {
                    "protocol_version": WORKER_PROTOCOL_VERSION,
                    "task_id": task_id,
                    "manifest_path": str(manifest.path) if manifest is not None else None,
                    "python": str(python_bin),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return _IsolationPreparation(
            ok=True,
            workspace=workspace,
            venv_dir=venv_dir,
            manifest=manifest,
            detail=f"prepared isolated environment {venv_dir}",
            install_stdout="\n".join(stdout_chunks),
            install_stderr="\n".join(stderr_chunks),
        )
    except Exception as exc:
        return _IsolationPreparation(
            ok=False,
            workspace=workspace,
            venv_dir=venv_dir,
            manifest=manifest,
            detail=f"harness failed while preparing isolated environment: {exc}",
            install_stdout="\n".join(stdout_chunks),
            install_stderr="\n".join(stderr_chunks),
        )


def _result_from_isolation_failure(preparation: _IsolationPreparation, task_id: str) -> HiddenEvaluationResult:
    evaluation_dir = _evaluation_dir(preparation.workspace, task_id)
    looks_like_harness_fault = preparation.detail.startswith("harness failed")
    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=False,
            execution_status="harness_invalid" if looks_like_harness_fault else "valid",
            outcome_status="real_failure",
            classification_reason=preparation.detail,
            passed_checks=[],
            failed_checks=[],
            observations=[
                HiddenEvaluationObservation(
                    id="environment_preparation",
                    status="fail",
                    detail="; ".join(
                        item
                        for item in (
                            preparation.detail,
                            preparation.install_stdout.strip() or None,
                            preparation.install_stderr.strip() or None,
                        )
                        if item
                    ),
                )
            ],
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _run_worker_in_isolated_environment(preparation: _IsolationPreparation, task_id: str) -> HiddenEvaluationResult:
    output_path = preparation.workspace / ".agentharness" / "evaluation" / task_id / "worker-result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    python_bin = preparation.venv_dir / "bin" / "python"
    env = os.environ.copy()
    repo_src = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(repo_src), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    command = [
        str(python_bin),
        "-m",
        "agentharness.benchmark_hidden_evaluators",
        WORKER_SENTINEL,
        "--task-id",
        task_id,
        "--workspace",
        str(preparation.workspace),
        "--output",
        str(output_path),
    ]
    completed = subprocess.run(command, cwd=preparation.workspace, capture_output=True, text=True, env=env, check=False)
    if output_path.is_file():
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        return HiddenEvaluationResult(
            task_id=str(payload.get("task_id", task_id)),
            critical_ok=bool(payload.get("critical_ok", False)),
            execution_status=str(payload.get("execution_status", "valid")),
            outcome_status=str(payload.get("outcome_status", "success")),
            classification_reason=str(payload.get("classification_reason", "")),
            passed_checks=[str(item) for item in payload.get("passed_checks", [])],
            failed_checks=[str(item) for item in payload.get("failed_checks", [])],
            observations=[
                HiddenEvaluationObservation(
                    id=str(item.get("id", "")),
                    status=str(item.get("status", "fail")),
                    detail=str(item.get("detail", "")),
                )
                for item in payload.get("observations", [])
                if isinstance(item, dict)
            ],
            summary_path=Path(str(payload.get("summary_path", _evaluation_dir(preparation.workspace, task_id) / "summary.txt"))),
            result_path=Path(str(payload.get("result_path", _evaluation_dir(preparation.workspace, task_id) / "result.json"))),
        )

    evaluation_dir = _evaluation_dir(preparation.workspace, task_id)
    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=False,
            execution_status="harness_invalid",
            outcome_status="real_failure",
            classification_reason="worker protocol failed before producing a result payload",
            passed_checks=[],
            failed_checks=[],
            observations=[
                HiddenEvaluationObservation(
                    id="worker_protocol",
                    status="fail",
                    detail=f"exit_code={completed.returncode}; stdout={completed.stdout.strip()}; stderr={completed.stderr.strip()}",
                )
            ],
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _evaluate_benchmark_task_in_worker(workspace: Path, task_id: str) -> HiddenEvaluationResult:
    normalized_task_id = task_id.strip()
    if normalized_task_id == "support-ticket-api":
        return _evaluate_support_ticket_api(workspace)
    if normalized_task_id == "inventory-adjustment-api":
        return _evaluate_inventory_adjustment_api(workspace)
    if normalized_task_id == "leave-request-api":
        return _evaluate_leave_request_api(workspace)
    if normalized_task_id == "refund-approval-api":
        return _evaluate_refund_approval_api(workspace)
    if normalized_task_id == "incident-escalation-api":
        return _evaluate_incident_escalation_api(workspace)
    if normalized_task_id == "csv-member-import":
        return _evaluate_csv_member_import(workspace)
    if normalized_task_id == "report-export-job":
        return _evaluate_report_export_job(workspace)
    if normalized_task_id == "webhook-ingestion-service":
        return _evaluate_webhook_ingestion_service(workspace)
    raise ValueError(f"Unsupported benchmark task evaluator: {task_id}")


def _evaluate_support_ticket_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "support-ticket-api"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        detail = f"app discovery failed: {exc}"
        for check_id in (
            "create_valid_ticket",
            "list_filters_work",
            "closed_ticket_reopen_blocked",
            "comments_embedded_in_detail",
            "invalid_email_rejected",
        ):
            record(check_id, False, detail)
        return _persist_hidden_evaluation(
            HiddenEvaluationResult(
                task_id=task_id,
                critical_ok=False,
                passed_checks=passed_checks,
                failed_checks=failed_checks,
                observations=observations,
                summary_path=evaluation_dir / "summary.txt",
                result_path=evaluation_dir / "result.json",
            )
        )

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            base_ticket = {
                "title": "VPN access request",
                "description": "Cannot connect to internal VPN",
                "requester_email": "alice@example.com",
                "category": "access",
                "priority": "high",
            }
            create_response = client.post("/tickets", json=base_ticket)
            create_ok = create_response.status_code in {200, 201}
            create_payload: Any = create_response.json() if create_ok else {}
            ticket_id = _normalize_ticket_id(create_payload)
            default_status_ok = isinstance(create_payload, dict) and create_payload.get("status") == "open"
            record(
                "create_valid_ticket",
                bool(create_ok and ticket_id is not None and default_status_ok),
                f"status_code={create_response.status_code}; module={module_path}; ticket_id={ticket_id}; default_status={create_payload.get('status') if isinstance(create_payload, dict) else None}",
            )

            filter_ok = False
            filter_detail = "ticket creation precondition failed"
            reopen_ok = False
            reopen_detail = "ticket creation precondition failed"
            comments_ok = False
            comments_detail = "ticket creation precondition failed"

            if ticket_id is not None:
                network_response = client.post(
                    "/tickets",
                    json={
                        "title": "Broken Wi-Fi in office",
                        "description": "Laptop disconnects every 2 minutes",
                        "requester_email": "bob@example.com",
                        "category": "network",
                        "priority": "urgent",
                    },
                )
                other_ticket_payload = network_response.json() if network_response.status_code in {200, 201} else {}
                second_ticket_id = _normalize_ticket_id(other_ticket_payload)
                patch_closed = client.patch(f"/tickets/{ticket_id}", json={"status": "closed", "assignee": "ops1"})
                patch_second = None
                if second_ticket_id is not None:
                    patch_second = client.patch(f"/tickets/{second_ticket_id}", json={"status": "in_progress", "assignee": "net1"})
                filters_response = client.get("/tickets", params={"status": "closed", "priority": "high", "category": "access"})
                listed = filters_response.json() if filters_response.status_code == 200 else []
                filter_match = False
                if isinstance(listed, list):
                    for item in listed:
                        if isinstance(item, dict) and _normalize_ticket_id(item) == ticket_id:
                            filter_match = (
                                item.get("status") == "closed"
                                and item.get("priority") == "high"
                                and item.get("category") == "access"
                            )
                            break
                filter_ok = (
                    network_response.status_code in {200, 201}
                    and patch_closed.status_code in {200, 201}
                    and patch_second is not None
                    and patch_second.status_code in {200, 201}
                    and filters_response.status_code == 200
                    and filter_match
                )
                filter_detail = (
                    f"create_second={network_response.status_code}; patch_closed={patch_closed.status_code}; "
                    f"patch_second={patch_second.status_code if patch_second is not None else None}; filters={filters_response.status_code}; match={filter_match}"
                )

                reopen_response = client.patch(f"/tickets/{ticket_id}", json={"status": "open"})
                reopen_payload: Any = None
                if reopen_response.headers.get("content-type", "").startswith("application/json"):
                    reopen_payload = reopen_response.json()
                still_closed = isinstance(reopen_payload, dict) and reopen_payload.get("status") == "closed"
                reopen_ok = reopen_response.status_code in {400, 409, 422} or still_closed
                reopen_detail = f"status_code={reopen_response.status_code}; payload_status={reopen_payload.get('status') if isinstance(reopen_payload, dict) else None}"

                comment_response = client.post(
                    f"/tickets/{ticket_id}/comments",
                    json={"author": "ops1", "body": "Investigating the access issue."},
                )
                detail_response = client.get(f"/tickets/{ticket_id}")
                detail_payload = detail_response.json() if detail_response.status_code == 200 else {}
                comments = _extract_comments(detail_payload)
                comment_found = any(
                    isinstance(item, dict)
                    and item.get("author") == "ops1"
                    and item.get("body") == "Investigating the access issue."
                    for item in comments
                )
                comments_ok = comment_response.status_code in {200, 201} and detail_response.status_code == 200 and comment_found
                comments_detail = (
                    f"comment_status={comment_response.status_code}; detail_status={detail_response.status_code}; comment_found={comment_found}"
                )

            record("list_filters_work", filter_ok, filter_detail)
            record("closed_ticket_reopen_blocked", reopen_ok, reopen_detail)
            record("comments_embedded_in_detail", comments_ok, comments_detail)

            invalid_email_response = client.post(
                "/tickets",
                json={
                    "title": "Bad email case",
                    "description": "Should be rejected",
                    "requester_email": "not-an-email",
                    "category": "access",
                    "priority": "medium",
                },
            )
            invalid_email_ok = invalid_email_response.status_code in {400, 422}
            record(
                "invalid_email_rejected",
                invalid_email_ok,
                f"status_code={invalid_email_response.status_code}",
            )
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        seen_ids = {item.id for item in observations}
        for check_id in (
            "create_valid_ticket",
            "list_filters_work",
            "closed_ticket_reopen_blocked",
            "comments_embedded_in_detail",
            "invalid_email_rejected",
        ):
            if check_id not in seen_ids:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=not failed_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            observations=observations,
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _evaluate_inventory_adjustment_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "inventory-adjustment-api"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        detail = f"app discovery failed: {exc}"
        for check_id in (
            "reserve_within_available",
            "over_reserve_rejected",
            "damage_cannot_go_negative",
            "recount_sets_exact_quantity",
            "release_cannot_exceed_reserved",
        ):
            record(check_id, False, detail)
        return _persist_hidden_evaluation(
            HiddenEvaluationResult(
                task_id=task_id,
                critical_ok=False,
                passed_checks=passed_checks,
                failed_checks=failed_checks,
                observations=observations,
                summary_path=evaluation_dir / "summary.txt",
                result_path=evaluation_dir / "result.json",
            )
        )

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            create_item = client.post(
                "/items",
                json={"sku": "SKU-001", "name": "Widget", "on_hand": 10, "reserved": 0},
            )
            create_ok = create_item.status_code in {200, 201}
            create_payload: Any = create_item.json() if create_ok else {}
            sku = _normalize_item_ref(create_payload)
            create_detail = f"status_code={create_item.status_code}; module={module_path}; sku={sku}"

            reserve_ok = False
            reserve_detail = "item creation precondition failed"
            over_reserve_ok = False
            over_reserve_detail = "item creation precondition failed"
            damage_ok = False
            damage_detail = "item creation precondition failed"
            recount_ok = False
            recount_detail = "item creation precondition failed"
            release_ok = False
            release_detail = "item creation precondition failed"

            if sku is not None:
                reserve_response = client.post(
                    "/reservations",
                    json={"sku": sku, "order_id": "ORDER-1", "quantity": 4},
                )
                detail_after_reserve = client.get(f"/items/{sku}")
                detail_payload = detail_after_reserve.json() if detail_after_reserve.status_code == 200 else {}
                reserved_quantity = detail_payload.get("reserved") if isinstance(detail_payload, dict) else None
                reserve_ok = (
                    reserve_response.status_code in {200, 201}
                    and detail_after_reserve.status_code == 200
                    and reserved_quantity == 4
                )
                reserve_detail = (
                    f"reserve_status={reserve_response.status_code}; detail_status={detail_after_reserve.status_code}; reserved={reserved_quantity}"
                )

                over_reserve_response = client.post(
                    "/reservations",
                    json={"sku": sku, "order_id": "ORDER-2", "quantity": 7},
                )
                over_reserve_ok = over_reserve_response.status_code in {400, 409, 422}
                over_reserve_detail = f"status_code={over_reserve_response.status_code}"

                damage_response = client.post(
                    "/adjustments",
                    json={"sku": sku, "reason": "damage", "delta": -20},
                )
                damage_ok = damage_response.status_code in {400, 409, 422}
                damage_detail = f"status_code={damage_response.status_code}"

                recount_response = client.post(
                    "/adjustments",
                    json={"sku": sku, "reason": "recount", "counted_quantity": 8},
                )
                detail_after_recount = client.get(f"/items/{sku}")
                detail_after_recount_payload = detail_after_recount.json() if detail_after_recount.status_code == 200 else {}
                recount_on_hand = detail_after_recount_payload.get("on_hand") if isinstance(detail_after_recount_payload, dict) else None
                history = _extract_history_entries(detail_after_recount_payload)
                recount_history_ok = any(
                    isinstance(entry, dict)
                    and entry.get("reason") == "recount"
                    and entry.get("counted_quantity") == 8
                    for entry in history
                )
                recount_ok = (
                    recount_response.status_code in {200, 201}
                    and detail_after_recount.status_code == 200
                    and recount_on_hand == 8
                    and recount_history_ok
                )
                recount_detail = (
                    f"adjust_status={recount_response.status_code}; detail_status={detail_after_recount.status_code}; on_hand={recount_on_hand}; recount_history={recount_history_ok}"
                )

                release_response = client.post(
                    "/releases",
                    json={"sku": sku, "order_id": "ORDER-1", "quantity": 10},
                )
                release_ok = release_response.status_code in {400, 409, 422}
                release_detail = f"status_code={release_response.status_code}"

            record("reserve_within_available", reserve_ok and create_ok, create_detail + "; " + reserve_detail)
            record("over_reserve_rejected", over_reserve_ok, over_reserve_detail)
            record("damage_cannot_go_negative", damage_ok, damage_detail)
            record("recount_sets_exact_quantity", recount_ok, recount_detail)
            record("release_cannot_exceed_reserved", release_ok, release_detail)
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        seen_ids = {item.id for item in observations}
        for check_id in (
            "reserve_within_available",
            "over_reserve_rejected",
            "damage_cannot_go_negative",
            "recount_sets_exact_quantity",
            "release_cannot_exceed_reserved",
        ):
            if check_id not in seen_ids:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=not failed_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            observations=observations,
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _evaluate_leave_request_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "leave-request-api"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        detail = f"app discovery failed: {exc}"
        for check_id in (
            "valid_request_created",
            "overlap_rejected",
            "personal_leave_limit_enforced",
            "approval_sets_reviewed_at",
            "terminal_state_blocks_second_review",
        ):
            record(check_id, False, detail)
        return _persist_hidden_evaluation(
            HiddenEvaluationResult(
                task_id=task_id,
                critical_ok=False,
                passed_checks=passed_checks,
                failed_checks=failed_checks,
                observations=observations,
                summary_path=evaluation_dir / "summary.txt",
                result_path=evaluation_dir / "result.json",
            )
        )

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            create_response = client.post(
                "/requests",
                json={
                    "employee_id": "EMP-001",
                    "leave_type": "vacation",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-03",
                    "reason": "Family trip",
                },
            )
            create_ok = create_response.status_code in {200, 201}
            create_payload: Any = create_response.json() if create_ok else {}
            request_id = _normalize_leave_request_id(create_payload)
            create_status = create_payload.get("status") if isinstance(create_payload, dict) else None
            list_response = client.get("/requests", params={"employee_id": "EMP-001", "status": create_status or "pending"})
            listed_payload: Any = list_response.json() if list_response.status_code == 200 else []
            listed_ok = isinstance(listed_payload, list) and any(
                isinstance(item, dict) and _normalize_leave_request_id(item) == request_id for item in listed_payload
            )
            record(
                "valid_request_created",
                bool(create_ok and request_id is not None and listed_ok),
                (
                    f"status_code={create_response.status_code}; module={module_path}; request_id={request_id}; "
                    f"create_status={create_status}; list_status={list_response.status_code}; listed_ok={listed_ok}"
                ),
            )

            overlap_ok = False
            overlap_detail = "request creation precondition failed"
            personal_limit_ok = False
            personal_limit_detail = "request creation precondition failed"
            approval_ok = False
            approval_detail = "request creation precondition failed"
            terminal_ok = False
            terminal_detail = "request creation precondition failed"

            if request_id is not None:
                approve_response = client.post(
                    f"/requests/{request_id}/review",
                    json={"decision": "approve", "reviewer": "manager1", "note": "Coverage confirmed"},
                )
                detail_response = client.get(f"/requests/{request_id}")
                detail_payload: Any = detail_response.json() if detail_response.status_code == 200 else {}
                detail_status = detail_payload.get("status") if isinstance(detail_payload, dict) else None
                reviewed_at = detail_payload.get("reviewed_at") if isinstance(detail_payload, dict) else None
                reviewer_name = detail_payload.get("reviewer") if isinstance(detail_payload, dict) else None
                approval_ok = (
                    approve_response.status_code in {200, 201}
                    and detail_response.status_code == 200
                    and detail_status == "approved"
                    and isinstance(reviewed_at, str)
                    and bool(reviewed_at.strip())
                    and reviewer_name == "manager1"
                )
                approval_detail = (
                    f"review_status={approve_response.status_code}; detail_status={detail_response.status_code}; "
                    f"status={detail_status}; reviewed_at_present={bool(reviewed_at)}; reviewer={reviewer_name}"
                )

                overlap_create_response = client.post(
                    "/requests",
                    json={
                        "employee_id": "EMP-001",
                        "leave_type": "vacation",
                        "start_date": "2026-07-02",
                        "end_date": "2026-07-04",
                        "reason": "Overlap test",
                    },
                )
                overlap_create_payload: Any = overlap_create_response.json() if overlap_create_response.status_code in {200, 201} else {}
                overlap_request_id = _normalize_leave_request_id(overlap_create_payload)
                overlap_review_status = None
                overlap_review_payload: Any = None
                if overlap_request_id is not None:
                    overlap_review_response = client.post(
                        f"/requests/{overlap_request_id}/review",
                        json={"decision": "approve", "reviewer": "manager2", "note": "Try overlap"},
                    )
                    overlap_review_status = overlap_review_response.status_code
                    if overlap_review_response.headers.get("content-type", "").startswith("application/json"):
                        overlap_review_payload = overlap_review_response.json()
                overlap_payload_status = overlap_review_payload.get("status") if isinstance(overlap_review_payload, dict) else None
                overlap_ok = (
                    overlap_create_response.status_code in {400, 409, 422}
                    or overlap_review_status in {400, 409, 422}
                    or overlap_payload_status in {"pending", "rejected"}
                )
                overlap_detail = (
                    f"create_status={overlap_create_response.status_code}; overlap_request_id={overlap_request_id}; "
                    f"review_status={overlap_review_status}; review_payload_status={overlap_payload_status}"
                )

                personal_response = client.post(
                    "/requests",
                    json={
                        "employee_id": "EMP-002",
                        "leave_type": "personal",
                        "start_date": "2026-07-10",
                        "end_date": "2026-07-14",
                        "reason": "Personal travel",
                    },
                )
                personal_payload: Any = personal_response.json() if personal_response.status_code in {200, 201} else {}
                personal_request_id = _normalize_leave_request_id(personal_payload)
                personal_review_status = None
                personal_review_payload: Any = None
                if personal_request_id is not None:
                    personal_review_response = client.post(
                        f"/requests/{personal_request_id}/review",
                        json={"decision": "approve", "reviewer": "manager2", "note": "Too long"},
                    )
                    personal_review_status = personal_review_response.status_code
                    if personal_review_response.headers.get("content-type", "").startswith("application/json"):
                        personal_review_payload = personal_review_response.json()
                personal_payload_status = personal_review_payload.get("status") if isinstance(personal_review_payload, dict) else None
                personal_limit_ok = (
                    personal_response.status_code in {400, 409, 422}
                    or personal_review_status in {400, 409, 422}
                    or personal_payload_status in {"pending", "rejected"}
                )
                personal_limit_detail = (
                    f"create_status={personal_response.status_code}; personal_request_id={personal_request_id}; "
                    f"review_status={personal_review_status}; review_payload_status={personal_payload_status}"
                )

                second_review_response = client.post(
                    f"/requests/{request_id}/review",
                    json={"decision": "reject", "reviewer": "manager3", "note": "Second review attempt"},
                )
                second_review_payload: Any = None
                if second_review_response.headers.get("content-type", "").startswith("application/json"):
                    second_review_payload = second_review_response.json()
                final_detail_response = client.get(f"/requests/{request_id}")
                final_detail_payload: Any = final_detail_response.json() if final_detail_response.status_code == 200 else {}
                final_status = final_detail_payload.get("status") if isinstance(final_detail_payload, dict) else None
                second_payload_status = second_review_payload.get("status") if isinstance(second_review_payload, dict) else None
                terminal_ok = (
                    second_review_response.status_code in {400, 409, 422}
                    or second_payload_status == "approved"
                ) and final_status == "approved"
                terminal_detail = (
                    f"second_review_status={second_review_response.status_code}; payload_status={second_payload_status}; "
                    f"final_detail_status={final_detail_response.status_code}; final_status={final_status}"
                )

            record("overlap_rejected", overlap_ok, overlap_detail)
            record("personal_leave_limit_enforced", personal_limit_ok, personal_limit_detail)
            record("approval_sets_reviewed_at", approval_ok, approval_detail)
            record("terminal_state_blocks_second_review", terminal_ok, terminal_detail)
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        seen_ids = {item.id for item in observations}
        for check_id in (
            "valid_request_created",
            "overlap_rejected",
            "personal_leave_limit_enforced",
            "approval_sets_reviewed_at",
            "terminal_state_blocks_second_review",
        ):
            if check_id not in seen_ids:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=not failed_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            observations=observations,
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _evaluate_refund_approval_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "refund-approval-api"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        detail = f"app discovery failed: {exc}"
        for check_id in (
            "small_refund_auto_approved",
            "medium_refund_needs_manager",
            "large_refund_needs_finance",
            "invalid_amount_rejected",
            "terminal_state_blocks_reapproval",
        ):
            record(check_id, False, detail)
        return _persist_hidden_evaluation(
            HiddenEvaluationResult(
                task_id=task_id,
                critical_ok=False,
                passed_checks=passed_checks,
                failed_checks=failed_checks,
                observations=observations,
                summary_path=evaluation_dir / "summary.txt",
                result_path=evaluation_dir / "result.json",
            )
        )

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            create_small = client.post(
                "/refunds",
                json={
                    "order_id": "ORD-SMALL-001",
                    "amount": 45,
                    "currency": "EUR",
                    "reason": "duplicate charge",
                    "requested_by": "agent.small",
                },
            )
            small_ok = create_small.status_code in {200, 201}
            small_payload: Any = create_small.json() if create_small.headers.get("content-type", "").startswith("application/json") else {}
            small_id = _normalize_refund_request_id(small_payload)
            small_status = small_payload.get("status") if isinstance(small_payload, dict) else None
            small_lookup = client.get(f"/refunds/{small_id}") if small_id is not None else None
            small_lookup_payload: Any = small_lookup.json() if small_lookup is not None and small_lookup.status_code == 200 else {}
            lookup_small_status = small_lookup_payload.get("status") if isinstance(small_lookup_payload, dict) else None
            small_auto_ok = (
                small_ok
                and small_id is not None
                and small_status == "approved"
                and small_lookup is not None
                and small_lookup.status_code == 200
                and lookup_small_status == "approved"
            )
            record(
                "small_refund_auto_approved",
                small_auto_ok,
                (
                    f"status_code={create_small.status_code}; module={module_path}; refund_id={small_id}; "
                    f"create_status={small_status}; detail_status={small_lookup.status_code if small_lookup is not None else None}; "
                    f"detail_refund_status={lookup_small_status}"
                ),
            )

            medium_ok = False
            medium_detail = "not evaluated"
            large_ok = False
            large_detail = "not evaluated"
            invalid_amount_ok = False
            invalid_amount_detail = "not evaluated"
            terminal_ok = False
            terminal_detail = "not evaluated"

            create_medium = client.post(
                "/refunds",
                json={
                    "order_id": "ORD-MEDIUM-001",
                    "amount": 120,
                    "currency": "EUR",
                    "reason": "damaged item",
                    "requested_by": "agent.medium",
                },
            )
            medium_payload: Any = create_medium.json() if create_medium.headers.get("content-type", "").startswith("application/json") else {}
            medium_id = _normalize_refund_request_id(medium_payload)
            medium_initial_status = medium_payload.get("status") if isinstance(medium_payload, dict) else None
            medium_lookup = client.get(f"/refunds/{medium_id}") if medium_id is not None else None
            medium_lookup_payload: Any = medium_lookup.json() if medium_lookup is not None and medium_lookup.status_code == 200 else {}
            medium_detail_status = medium_lookup_payload.get("status") if isinstance(medium_lookup_payload, dict) else None
            medium_pre_review_ok = (
                create_medium.status_code in {200, 201}
                and medium_id is not None
                and medium_initial_status in {"pending_manager", "pending_manager_review", "pending"}
                and medium_lookup is not None
                and medium_lookup.status_code == 200
                and medium_detail_status in {"pending_manager", "pending_manager_review", "pending"}
            )
            manager_review_status = None
            manager_payload_status = None
            medium_final_status = None
            if medium_id is not None:
                manager_review = client.post(
                    f"/refunds/{medium_id}/manager-review",
                    json={"decision": "approve", "approver": "manager1", "note": "policy ok"},
                )
                manager_review_status = manager_review.status_code
                manager_review_payload: Any = manager_review.json() if manager_review.headers.get("content-type", "").startswith("application/json") else {}
                manager_payload_status = manager_review_payload.get("status") if isinstance(manager_review_payload, dict) else None
                medium_post_review = client.get(f"/refunds/{medium_id}")
                medium_post_review_payload: Any = medium_post_review.json() if medium_post_review.status_code == 200 else {}
                medium_final_status = medium_post_review_payload.get("status") if isinstance(medium_post_review_payload, dict) else None
                medium_ok = medium_pre_review_ok and manager_review.status_code in {200, 201} and medium_final_status == "approved"
            medium_detail = (
                f"create_status={create_medium.status_code}; refund_id={medium_id}; initial_status={medium_initial_status}; "
                f"detail_status={medium_lookup.status_code if medium_lookup is not None else None}; detail_refund_status={medium_detail_status}; "
                f"manager_status={manager_review_status}; manager_payload_status={manager_payload_status}; final_status={medium_final_status}"
            )

            create_large = client.post(
                "/refunds",
                json={
                    "order_id": "ORD-LARGE-001",
                    "amount": 900,
                    "currency": "EUR",
                    "reason": "fraud reversal",
                    "requested_by": "agent.large",
                },
            )
            large_payload: Any = create_large.json() if create_large.headers.get("content-type", "").startswith("application/json") else {}
            large_id = _normalize_refund_request_id(large_payload)
            large_initial_status = large_payload.get("status") if isinstance(large_payload, dict) else None
            finance_before_status = None
            finance_before_payload_status = None
            manager_large_status = None
            after_manager_payload_status = None
            finance_after_status = None
            finance_after_payload_status = None
            final_large_status = None
            if large_id is not None:
                finance_before = client.post(
                    f"/refunds/{large_id}/finance-review",
                    json={"decision": "approve", "approver": "finance0", "note": "premature"},
                )
                finance_before_status = finance_before.status_code
                finance_before_payload: Any = finance_before.json() if finance_before.headers.get("content-type", "").startswith("application/json") else {}
                finance_before_payload_status = finance_before_payload.get("status") if isinstance(finance_before_payload, dict) else None

                manager_large = client.post(
                    f"/refunds/{large_id}/manager-review",
                    json={"decision": "approve", "approver": "manager2", "note": "needs finance"},
                )
                manager_large_status = manager_large.status_code
                after_manager_payload: Any = manager_large.json() if manager_large.headers.get("content-type", "").startswith("application/json") else {}
                after_manager_payload_status = after_manager_payload.get("status") if isinstance(after_manager_payload, dict) else None

                finance_after = client.post(
                    f"/refunds/{large_id}/finance-review",
                    json={"decision": "approve", "approver": "finance1", "note": "approved by finance"},
                )
                finance_after_status = finance_after.status_code
                finance_after_payload: Any = finance_after.json() if finance_after.headers.get("content-type", "").startswith("application/json") else {}
                finance_after_payload_status = finance_after_payload.get("status") if isinstance(finance_after_payload, dict) else None
                large_detail_response = client.get(f"/refunds/{large_id}")
                large_detail_payload: Any = large_detail_response.json() if large_detail_response.status_code == 200 else {}
                final_large_status = large_detail_payload.get("status") if isinstance(large_detail_payload, dict) else None
                large_ok = (
                    create_large.status_code in {200, 201}
                    and large_initial_status in {"pending_manager", "pending_manager_review", "pending"}
                    and finance_before.status_code in {400, 409, 422}
                    and manager_large.status_code in {200, 201}
                    and after_manager_payload_status in {"pending_finance", "pending_finance_review", "pending_finance_approval"}
                    and finance_after.status_code in {200, 201}
                    and finance_after_payload_status == "approved"
                    and final_large_status == "approved"
                )
            large_detail = (
                f"create_status={create_large.status_code}; refund_id={large_id}; initial_status={large_initial_status}; "
                f"finance_before_status={finance_before_status}; finance_before_payload_status={finance_before_payload_status}; "
                f"manager_status={manager_large_status}; after_manager_status_value={after_manager_payload_status}; "
                f"final_finance_status={finance_after_status}; final_finance_payload_status={finance_after_payload_status}; final_status={final_large_status}"
            )

            invalid_amount = client.post(
                "/refunds",
                json={
                    "order_id": "ORD-BAD-001",
                    "amount": 0,
                    "currency": "EUR",
                    "reason": "bad amount",
                    "requested_by": "agent.bad",
                },
            )
            invalid_amount_ok = invalid_amount.status_code in {400, 422}
            invalid_amount_detail = f"status_code={invalid_amount.status_code}"

            if medium_id is not None:
                second_terminal_review = client.post(
                    f"/refunds/{medium_id}/manager-review",
                    json={"decision": "reject", "approver": "manager3", "note": "second decision"},
                )
                second_terminal_payload: Any = second_terminal_review.json() if second_terminal_review.headers.get("content-type", "").startswith("application/json") else {}
                second_terminal_status = second_terminal_payload.get("status") if isinstance(second_terminal_payload, dict) else None
                medium_terminal_detail = client.get(f"/refunds/{medium_id}")
                medium_terminal_payload: Any = medium_terminal_detail.json() if medium_terminal_detail.status_code == 200 else {}
                medium_terminal_status = medium_terminal_payload.get("status") if isinstance(medium_terminal_payload, dict) else None
                terminal_ok = (
                    second_terminal_review.status_code in {400, 409, 422}
                    or second_terminal_status == "approved"
                ) and medium_terminal_status == "approved"
                terminal_detail = (
                    f"second_review_status={second_terminal_review.status_code}; payload_status={second_terminal_status}; "
                    f"detail_status={medium_terminal_detail.status_code}; final_status={medium_terminal_status}"
                )

            record("medium_refund_needs_manager", medium_ok, medium_detail)
            record("large_refund_needs_finance", large_ok, large_detail)
            record("invalid_amount_rejected", invalid_amount_ok, invalid_amount_detail)
            record("terminal_state_blocks_reapproval", terminal_ok, terminal_detail)
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        seen_ids = {item.id for item in observations}
        for check_id in (
            "small_refund_auto_approved",
            "medium_refund_needs_manager",
            "large_refund_needs_finance",
            "invalid_amount_rejected",
            "terminal_state_blocks_reapproval",
        ):
            if check_id not in seen_ids:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=not failed_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            observations=observations,
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _evaluate_webhook_ingestion_service(workspace: Path) -> HiddenEvaluationResult:
    task_id = "webhook-ingestion-service"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []
    secret = os.environ.setdefault("WEBHOOK_SECRET", "agentharness-test-secret")

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        detail = f"app discovery failed: {exc}"
        for check_id in (
            "valid_signed_event_stored",
            "invalid_signature_rejected",
            "duplicate_delivery_idempotent",
            "type_normalized_correctly",
            "missing_fields_rejected",
        ):
            record(check_id, False, detail)
        return _persist_hidden_evaluation(
            HiddenEvaluationResult(
                task_id=task_id,
                critical_ok=False,
                passed_checks=passed_checks,
                failed_checks=failed_checks,
                observations=observations,
                summary_path=evaluation_dir / "summary.txt",
                result_path=evaluation_dir / "result.json",
            )
        )

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            ingest_path = "/webhooks"
            base_payload = {
                "event_id": "evt_001",
                "source": "billing",
                "occurred_at": "2026-07-01T10:00:00Z",
                "type": "partner.created",
                "payload": {"customer_id": "cust_123", "amount": 42},
            }
            body_text, digest = _sign_webhook_payload(base_payload, secret)
            headers = {"content-type": "application/json", "x-signature": digest}
            create_response = client.post(ingest_path, content=body_text, headers=headers)
            create_ok = create_response.status_code in {200, 201}
            create_payload: Any = create_response.json() if create_response.headers.get("content-type", "").startswith("application/json") else {}
            event_id = _normalize_event_id(create_payload) or base_payload["event_id"]

            lookup_response = client.get(f"/events/{event_id}")
            lookup_payload: Any = lookup_response.json() if lookup_response.status_code == 200 else {}
            normalized_status = lookup_payload.get("normalized_status") if isinstance(lookup_payload, dict) else None
            raw_payload_ok = isinstance(lookup_payload, dict) and isinstance(lookup_payload.get("payload"), dict)
            valid_signed_ok = create_ok and lookup_response.status_code == 200 and raw_payload_ok
            record(
                "valid_signed_event_stored",
                valid_signed_ok,
                (
                    f"status_code={create_response.status_code}; module={module_path}; event_id={event_id}; "
                    f"lookup_status={lookup_response.status_code}; normalized_status={normalized_status}; raw_payload_ok={raw_payload_ok}"
                ),
            )

            bad_headers = {"content-type": "application/json", "x-signature": "bad-signature"}
            invalid_payload = {
                "event_id": "evt_bad_sig",
                "source": "billing",
                "occurred_at": "2026-07-01T10:01:00Z",
                "type": "partner.updated",
                "payload": {"customer_id": "cust_999"},
            }
            invalid_response = client.post(ingest_path, content=json.dumps(invalid_payload), headers=bad_headers)
            invalid_lookup_response = client.get(f"/events/{invalid_payload['event_id']}")
            invalid_signature_ok = invalid_response.status_code in {400, 401, 403, 422} and invalid_lookup_response.status_code in {404, 400}
            record(
                "invalid_signature_rejected",
                invalid_signature_ok,
                f"post_status={invalid_response.status_code}; lookup_status={invalid_lookup_response.status_code}",
            )

            duplicate_response = client.post(ingest_path, content=body_text, headers=headers)
            list_response = client.get("/events", params={"normalized_status": normalized_status or "created", "source": "billing"})
            listed_payload = _extract_event_list(list_response.json() if list_response.status_code == 200 else [])
            duplicate_count = sum(1 for item in listed_payload if isinstance(item, dict) and _normalize_event_id(item) == event_id)
            duplicate_idempotent_ok = duplicate_response.status_code in {200, 201, 202, 409} and duplicate_count == 1
            record(
                "duplicate_delivery_idempotent",
                duplicate_idempotent_ok,
                f"duplicate_status={duplicate_response.status_code}; list_status={list_response.status_code}; duplicate_count={duplicate_count}",
            )

            type_payload = {
                "event_id": "evt_002",
                "source": "crm",
                "occurred_at": "2026-07-01T10:05:00Z",
                "type": "partner.cancelled",
                "payload": {"customer_id": "cust_555"},
            }
            type_body_text, type_digest = _sign_webhook_payload(type_payload, secret)
            type_response = client.post(ingest_path, content=type_body_text, headers={"content-type": "application/json", "x-signature": type_digest})
            type_lookup = client.get(f"/events/{type_payload['event_id']}")
            type_lookup_payload: Any = type_lookup.json() if type_lookup.status_code == 200 else {}
            mapped_status = type_lookup_payload.get("normalized_status") if isinstance(type_lookup_payload, dict) else None
            type_normalized_ok = type_response.status_code in {200, 201} and mapped_status == "cancelled"
            record(
                "type_normalized_correctly",
                type_normalized_ok,
                f"create_status={type_response.status_code}; lookup_status={type_lookup.status_code}; normalized_status={mapped_status}",
            )

            missing_payload = {
                "event_id": "evt_missing",
                "source": "crm",
                "occurred_at": "2026-07-01T10:06:00Z",
                "payload": {"customer_id": "cust_777"},
            }
            missing_body_text, missing_digest = _sign_webhook_payload(missing_payload, secret)
            missing_response = client.post(ingest_path, content=missing_body_text, headers={"content-type": "application/json", "x-signature": missing_digest})
            missing_lookup = client.get(f"/events/{missing_payload['event_id']}")
            missing_fields_ok = missing_response.status_code in {400, 422} and missing_lookup.status_code in {404, 400}
            record(
                "missing_fields_rejected",
                missing_fields_ok,
                f"post_status={missing_response.status_code}; lookup_status={missing_lookup.status_code}",
            )
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        seen_ids = {item.id for item in observations}
        for check_id in (
            "valid_signed_event_stored",
            "invalid_signature_rejected",
            "duplicate_delivery_idempotent",
            "type_normalized_correctly",
            "missing_fields_rejected",
        ):
            if check_id not in seen_ids:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(
        HiddenEvaluationResult(
            task_id=task_id,
            critical_ok=not failed_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            observations=observations,
            summary_path=evaluation_dir / "summary.txt",
            result_path=evaluation_dir / "result.json",
        )
    )


def _evaluate_incident_escalation_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "incident-escalation-api"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        detail = f"app discovery failed: {exc}"
        for check_id in (
            "sev1_escalates_on_time",
            "ack_stops_escalation",
            "resolved_stops_escalation",
            "sev3_not_auto_escalated",
            "invalid_as_of_rejected",
        ):
            record(check_id, False, detail)
        return _persist_hidden_evaluation(HiddenEvaluationResult(task_id=task_id, critical_ok=False, passed_checks=passed_checks, failed_checks=failed_checks, observations=observations, summary_path=evaluation_dir / "summary.txt", result_path=evaluation_dir / "result.json"))

    def _is_escalated(payload: Any) -> Any:
        if isinstance(payload, dict):
            for key in ("escalated", "is_escalated"):
                if key in payload:
                    return payload[key]
        return None

    def _extract_incident_id(payload: Any) -> Any:
        if isinstance(payload, dict):
            for key in ("id", "incident_id"):
                if key in payload:
                    return payload[key]
        return None

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            create_sev1 = client.post("/incidents", json={"service": "payments", "severity": "sev1", "opened_at": "2026-07-01T10:00:00Z", "summary": "primary processor down"})
            sev1_payload: Any = create_sev1.json() if create_sev1.headers.get("content-type", "").startswith("application/json") else {}
            sev1_id = _extract_incident_id(sev1_payload)
            before = client.get(f"/incidents/{sev1_id}/escalation", params={"as_of": "2026-07-01T10:10:00Z"}) if sev1_id is not None else None
            after = client.get(f"/incidents/{sev1_id}/escalation", params={"as_of": "2026-07-01T10:16:00Z"}) if sev1_id is not None else None
            before_payload: Any = before.json() if before is not None and before.headers.get("content-type", "").startswith("application/json") else {}
            after_payload: Any = after.json() if after is not None and after.headers.get("content-type", "").startswith("application/json") else {}
            sev1_ok = create_sev1.status_code in {200, 201} and before is not None and after is not None and before.status_code == 200 and after.status_code == 200 and _is_escalated(before_payload) is False and _is_escalated(after_payload) is True
            record("sev1_escalates_on_time", sev1_ok, f"status_code={create_sev1.status_code}; module={module_path}; incident_id={sev1_id}; before_status={before.status_code if before is not None else None}; before_escalated={_is_escalated(before_payload)}; after_status={after.status_code if after is not None else None}; after_escalated={_is_escalated(after_payload)}")

            ack_ok = False
            ack_detail = "not evaluated"
            resolved_ok = False
            resolved_detail = "not evaluated"
            sev3_ok = False
            sev3_detail = "not evaluated"
            invalid_ok = False
            invalid_detail = "not evaluated"

            create_ack = client.post("/incidents", json={"service": "auth", "severity": "sev2", "opened_at": "2026-07-01T11:00:00Z", "summary": "login latency spike"})
            ack_payload: Any = create_ack.json() if create_ack.headers.get("content-type", "").startswith("application/json") else {}
            ack_id = _extract_incident_id(ack_payload)
            if ack_id is not None:
                ack_response = client.post(f"/incidents/{ack_id}/acknowledge", json={"responder": "oncall1", "acknowledged_at": "2026-07-01T11:20:00Z"})
                ack_escalation = client.get(f"/incidents/{ack_id}/escalation", params={"as_of": "2026-07-01T12:30:00Z"})
                ack_escalation_payload: Any = ack_escalation.json() if ack_escalation.headers.get("content-type", "").startswith("application/json") else {}
                ack_ok = create_ack.status_code in {200, 201} and ack_response.status_code in {200, 201} and ack_escalation.status_code == 200 and _is_escalated(ack_escalation_payload) is False
                ack_detail = f"create_status={create_ack.status_code}; incident_id={ack_id}; ack_status={ack_response.status_code}; escalation_status={ack_escalation.status_code}; escalated={_is_escalated(ack_escalation_payload)}"

            create_resolved = client.post("/incidents", json={"service": "search", "severity": "sev1", "opened_at": "2026-07-01T12:00:00Z", "summary": "index lag"})
            resolved_payload: Any = create_resolved.json() if create_resolved.headers.get("content-type", "").startswith("application/json") else {}
            resolved_id = _extract_incident_id(resolved_payload)
            if resolved_id is not None:
                resolve_response = client.post(f"/incidents/{resolved_id}/resolve", json={"resolution_note": "fixed", "resolved_at": "2026-07-01T12:05:00Z"})
                resolved_escalation = client.get(f"/incidents/{resolved_id}/escalation", params={"as_of": "2026-07-01T14:00:00Z"})
                resolved_escalation_payload: Any = resolved_escalation.json() if resolved_escalation.headers.get("content-type", "").startswith("application/json") else {}
                resolved_ok = create_resolved.status_code in {200, 201} and resolve_response.status_code in {200, 201} and resolved_escalation.status_code == 200 and _is_escalated(resolved_escalation_payload) is False
                resolved_detail = f"create_status={create_resolved.status_code}; incident_id={resolved_id}; resolve_status={resolve_response.status_code}; escalation_status={resolved_escalation.status_code}; escalated={_is_escalated(resolved_escalation_payload)}"

            create_sev3 = client.post("/incidents", json={"service": "docs", "severity": "sev3", "opened_at": "2026-07-01T09:00:00Z", "summary": "minor admin issue"})
            sev3_payload: Any = create_sev3.json() if create_sev3.headers.get("content-type", "").startswith("application/json") else {}
            sev3_id = _extract_incident_id(sev3_payload)
            if sev3_id is not None:
                sev3_escalation = client.get(f"/incidents/{sev3_id}/escalation", params={"as_of": "2026-07-01T18:00:00Z"})
                sev3_escalation_payload: Any = sev3_escalation.json() if sev3_escalation.headers.get("content-type", "").startswith("application/json") else {}
                sev3_ok = create_sev3.status_code in {200, 201} and sev3_escalation.status_code == 200 and _is_escalated(sev3_escalation_payload) is False
                sev3_detail = f"create_status={create_sev3.status_code}; incident_id={sev3_id}; escalation_status={sev3_escalation.status_code}; escalated={_is_escalated(sev3_escalation_payload)}"

            if sev1_id is not None:
                invalid_response = client.get(f"/incidents/{sev1_id}/escalation", params={"as_of": "not-a-timestamp"})
                invalid_ok = invalid_response.status_code in {400, 422}
                invalid_detail = f"status_code={invalid_response.status_code}"

            record("ack_stops_escalation", ack_ok, ack_detail)
            record("resolved_stops_escalation", resolved_ok, resolved_detail)
            record("sev3_not_auto_escalated", sev3_ok, sev3_detail)
            record("invalid_as_of_rejected", invalid_ok, invalid_detail)
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        seen_ids = {item.id for item in observations}
        for check_id in ("sev1_escalates_on_time", "ack_stops_escalation", "resolved_stops_escalation", "sev3_not_auto_escalated", "invalid_as_of_rejected"):
            if check_id not in seen_ids:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(HiddenEvaluationResult(task_id=task_id, critical_ok=not failed_checks, passed_checks=passed_checks, failed_checks=failed_checks, observations=observations, summary_path=evaluation_dir / "summary.txt", result_path=evaluation_dir / "result.json"))


def _evaluate_csv_member_import(workspace: Path) -> HiddenEvaluationResult:
    task_id = "csv-member-import"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        with tempfile.TemporaryDirectory(dir=workspace) as tmp_dir:
            temp_root = Path(tmp_dir)
            input_path = temp_root / "members.csv"
            out_dir = temp_root / "out"
            input_path.write_text(
                "name,email,role\n"
                "Alice, Alice@Example.com ,admin\n"
                "Bob,bob@example.com,viewer\n"
                "Charlie,BOB@example.com,member\n"
                "Dora,not-an-email,member\n"
                "Eve,eve@example.com,owner\n",
                encoding="utf-8",
            )
            command = _run_python_entrypoint(workspace, ["app/import_members.py", "import_members.py", "src/app/import_members.py"], ["--input", str(input_path), "--out-dir", str(out_dir)])
            accepted_path = out_dir / "accepted.json"
            rejected_path = out_dir / "rejected.csv"
            summary_path = out_dir / "summary.json"
            accepted: Any = json.loads(accepted_path.read_text(encoding="utf-8")) if accepted_path.is_file() else []
            summary: Any = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
            rejected_rows: list[dict[str, str]] = []
            if rejected_path.is_file():
                with rejected_path.open(encoding="utf-8", newline="") as handle:
                    rejected_rows = list(csv.DictReader(handle))

            emails = [item.get("email") for item in accepted if isinstance(item, dict)] if isinstance(accepted, list) else []
            normalized_ok = command.returncode == 0 and emails == ["alice@example.com", "bob@example.com"]
            duplicate_ok = command.returncode == 0 and emails.count("bob@example.com") == 1 and isinstance(summary, dict) and summary.get("duplicate_count") == 1
            reasons = [row.get("reason", "") for row in rejected_rows]
            invalid_reason_ok = command.returncode == 0 and len(rejected_rows) >= 2 and any(reason.strip() for reason in reasons)
            summary_counts_ok = command.returncode == 0 and isinstance(summary, dict) and summary.get("accepted_count") == len(accepted if isinstance(accepted, list) else []) and summary.get("rejected_count") == len(rejected_rows) and summary.get("duplicate_count") == 1 and summary.get("processed_count") == 5
            outputs_ok = accepted_path.is_file() and rejected_path.is_file() and summary_path.is_file()

            record("valid_rows_normalized", normalized_ok, f"exit_code={command.returncode}; stdout={command.stdout.strip()}; stderr={command.stderr.strip()}; emails={emails}")
            record("duplicate_handling_correct", duplicate_ok, f"exit_code={command.returncode}; emails={emails}; duplicate_count={summary.get('duplicate_count') if isinstance(summary, dict) else None}")
            record("invalid_rows_rejected_with_reason", invalid_reason_ok, f"exit_code={command.returncode}; rejected_rows={len(rejected_rows)}; reasons={reasons}")
            record("summary_counts_correct", summary_counts_ok, f"exit_code={command.returncode}; summary={summary}; accepted_len={len(accepted if isinstance(accepted, list) else [])}; rejected_len={len(rejected_rows)}")
            record("output_files_present", outputs_ok, f"accepted_exists={accepted_path.is_file()}; rejected_exists={rejected_path.is_file()}; summary_exists={summary_path.is_file()}")
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        for check_id in ("valid_rows_normalized", "duplicate_handling_correct", "invalid_rows_rejected_with_reason", "summary_counts_correct", "output_files_present"):
            if check_id not in {item.id for item in observations}:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(HiddenEvaluationResult(task_id=task_id, critical_ok=not failed_checks, passed_checks=passed_checks, failed_checks=failed_checks, observations=observations, summary_path=evaluation_dir / "summary.txt", result_path=evaluation_dir / "result.json"))


def _evaluate_report_export_job(workspace: Path) -> HiddenEvaluationResult:
    task_id = "report-export-job"
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations: list[HiddenEvaluationObservation] = []
    passed_checks: list[str] = []
    failed_checks: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        if ok:
            passed_checks.append(check_id)
        else:
            failed_checks.append(check_id)

    try:
        with tempfile.TemporaryDirectory(dir=workspace) as tmp_dir:
            temp_root = Path(tmp_dir)
            db_path = temp_root / "report.db"
            out_dir = temp_root / "out"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE records (record_date TEXT NOT NULL, merchant_id TEXT NOT NULL, payout_amount REAL NOT NULL, refund_amount REAL NOT NULL)")
                connection.executemany(
                    "INSERT INTO records (record_date, merchant_id, payout_amount, refund_amount) VALUES (?, ?, ?, ?)",
                    [
                        ("2026-07-01", "m001", 100.0, 10.0),
                        ("2026-07-01", "m001", 50.0, 0.0),
                        ("2026-07-01", "m002", 80.0, 5.0),
                        ("2026-07-02", "m003", 200.0, 20.0),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            command = _run_python_entrypoint(workspace, ["app/export.py", "export.py", "src/app/export.py"], ["--date", "2026-07-01", "--out-dir", str(out_dir)], env={"REPORT_DB_PATH": str(db_path)})
            csv_path = out_dir / "report.csv"
            summary_json_path = out_dir / "summary.json"
            rows: list[dict[str, str]] = []
            if csv_path.is_file():
                with csv_path.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
            summary: Any = json.loads(summary_json_path.read_text(encoding="utf-8")) if summary_json_path.is_file() else {}

            merchant_ids = [str(row.get("merchant_id", "")) for row in rows]
            sorted_complete_ok = command.returncode == 0 and bool(rows) and merchant_ids == sorted(merchant_ids) and all({"merchant_id", "gross_payout", "refund_total", "net_payout", "transaction_count"}.issubset(row.keys()) for row in rows)
            net_ok = command.returncode == 0 and all(abs(float(row["gross_payout"]) - float(row["refund_total"]) - float(row["net_payout"])) < 1e-9 for row in rows)
            date_filter_ok = command.returncode == 0 and {row.get("merchant_id") for row in rows} == {"m001", "m002"} and isinstance(summary, dict) and summary.get("export_date") == "2026-07-01"
            gross_total = sum(float(row["gross_payout"]) for row in rows) if rows else 0.0
            refund_total = sum(float(row["refund_total"]) for row in rows) if rows else 0.0
            net_total = sum(float(row["net_payout"]) for row in rows) if rows else 0.0
            summary_totals_ok = command.returncode == 0 and isinstance(summary, dict) and summary.get("merchant_count") == len(rows) and abs(float(summary.get("total_gross", 0.0)) - gross_total) < 1e-9 and abs(float(summary.get("total_refunds", 0.0)) - refund_total) < 1e-9 and abs(float(summary.get("total_net", 0.0)) - net_total) < 1e-9
            invalid_date = _run_python_entrypoint(workspace, ["app/export.py", "export.py", "src/app/export.py"], ["--date", "2026/07/01", "--out-dir", str(temp_root / "bad-out")], env={"REPORT_DB_PATH": str(db_path)})
            invalid_date_ok = invalid_date.returncode != 0

            record("csv_rows_sorted_complete", sorted_complete_ok, f"exit_code={command.returncode}; rows={rows}")
            record("net_totals_correct", net_ok, f"exit_code={command.returncode}; rows={rows}")
            record("date_filter_applied", date_filter_ok, f"exit_code={command.returncode}; merchants={[row.get('merchant_id') for row in rows]}; summary={summary}")
            record("summary_totals_match", summary_totals_ok, f"exit_code={command.returncode}; summary={summary}; gross_total={gross_total}; refund_total={refund_total}; net_total={net_total}")
            record("invalid_date_rejected", invalid_date_ok, f"exit_code={invalid_date.returncode}; stdout={invalid_date.stdout.strip()}; stderr={invalid_date.stderr.strip()}")
    except Exception as exc:
        detail = f"runtime evaluation failed: {exc}"
        for check_id in ("csv_rows_sorted_complete", "net_totals_correct", "date_filter_applied", "summary_totals_match", "invalid_date_rejected"):
            if check_id not in {item.id for item in observations}:
                record(check_id, False, detail)

    return _persist_hidden_evaluation(HiddenEvaluationResult(task_id=task_id, critical_ok=not failed_checks, passed_checks=passed_checks, failed_checks=failed_checks, observations=observations, summary_path=evaluation_dir / "summary.txt", result_path=evaluation_dir / "result.json"))


def evaluate_benchmark_task(run_path: str | Path, task_id: str) -> HiddenEvaluationResult:
    run = load_run(run_path)
    preparation = _prepare_isolated_environment(run.workspace, task_id.strip())
    if not preparation.ok:
        return _result_from_isolation_failure(preparation, task_id.strip())
    return _run_worker_in_isolated_environment(preparation, task_id.strip())


def _run_worker_main(argv: list[str]) -> int:
    if len(argv) != 7 or argv[0] != WORKER_SENTINEL or argv[1] != "--task-id" or argv[3] != "--workspace" or argv[5] != "--output":
        raise ValueError("Invalid benchmark hidden evaluator worker invocation")
    task_id = argv[2]
    workspace = Path(argv[4])
    output_path = Path(argv[6])
    result = _evaluate_benchmark_task_in_worker(workspace, task_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_SENTINEL:
        sys.exit(_run_worker_main(sys.argv[1:]))
    raise SystemExit("This module is intended to run as an internal worker only")
