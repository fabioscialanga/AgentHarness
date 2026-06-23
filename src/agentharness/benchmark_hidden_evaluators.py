from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "critical_ok": self.critical_ok,
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


def _extract_history_entries(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    for key in ("history", "events", "adjustments"):
        value = payload.get(key, [])
        if isinstance(value, list):
            return value
    return []


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
        with _working_directory(workspace), TestClient(app) as client:
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
        with _working_directory(workspace), TestClient(app) as client:
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


def evaluate_benchmark_task(run_path: str | Path, task_id: str) -> HiddenEvaluationResult:
    run = load_run(run_path)
    normalized_task_id = task_id.strip()
    if normalized_task_id == "support-ticket-api":
        return _evaluate_support_ticket_api(run.workspace)
    if normalized_task_id == "inventory-adjustment-api":
        return _evaluate_inventory_adjustment_api(run.workspace)
    raise ValueError(f"Unsupported benchmark task evaluator: {task_id}")
