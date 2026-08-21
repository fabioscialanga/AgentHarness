from __future__ import annotations

"""Private, review-only V3 evaluator.

Only the preregistered target mechanism is executed here.  No heldout/guard
case is imported or evaluated.  The disposable-clone boundary prevents runtime
artifacts from crossing into either repair workspace, and the returned finding
uses only an opaque V3 ID.
"""

import csv
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .benchmark_hidden_evaluators import (
    _load_fastapi_app, _make_test_client, _run_python_entrypoint, _working_directory,
)
from .efficacy_v3 import TASK_DEFECTS, opaque_review_feedback, validate_opaque_feedback


def _payload(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _identifier(payload: Any) -> Any:
    return payload.get("appointment_id", payload.get("id")) if isinstance(payload, dict) else None


def _appointment(workspace: Path) -> tuple[bool, str]:
    _, app = _load_fastapi_app(workspace)
    with _working_directory(workspace), _make_test_client(app) as client:
        def create(customer: str, start: str, end: str) -> Any:
            return client.post("/appointments", json={"customer_id": customer, "provider_id": "P-V3",
                               "starts_at": start, "ends_at": end, "reason": "review"})
        occupied = create("C-1", "2031-06-01T08:00:00Z", "2031-06-01T09:00:00Z")
        movable = create("C-2", "2031-06-01T10:00:00Z", "2031-06-01T11:00:00Z")
        item_id = _identifier(_payload(movable))
        conflict = client.patch(f"/appointments/{item_id}/reschedule", json={
            "starts_at": "2031-06-01T08:30:00Z", "ends_at": "2031-06-01T09:30:00Z"})
        after = _payload(client.get(f"/appointments/{item_id}"))
        ok = (occupied.status_code in {200, 201} and movable.status_code in {200, 201}
              and conflict.status_code in {400, 409, 422} and isinstance(after, dict)
              and str(after.get("starts_at", "")).startswith("2031-06-01T10:00:00"))
        return ok, f"conflicting reschedule status={conflict.status_code}; prior interval preserved={ok}"


def _shipment(workspace: Path) -> tuple[bool, str]:
    _, app = _load_fastapi_app(workspace)
    with _working_directory(workspace), _make_test_client(app) as client:
        created = client.post("/shipments", json={"tracking_number": "TRK-V3", "carrier": "Review"})
        skipped = client.post("/shipments/TRK-V3/events", json={"event_id": "EV-V3", "type": "in_transit",
                              "occurred_at": "2032-02-01T10:00:00Z", "location": "Hub"})
        detail = _payload(client.get("/shipments/TRK-V3"))
        ok = (created.status_code in {200, 201} and skipped.status_code in {400, 409, 422}
              and isinstance(detail, dict) and detail.get("status") == "created" and detail.get("events") == [])
        return ok, f"skipped transition status={skipped.status_code}; state/history preserved={ok}"


def _jsonl(workspace: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="v3-review-jsonl-") as tmp:
        root = Path(tmp)
        source = root / "events.jsonl"
        source.write_text(
            '{"event_id":"e1","actor_id":"a1","event_type":"click","occurred_at":"2033-01-01T00:00:00Z","value":2}\n'
            '{"event_id":"e2","actor_id":"a2","event_type":"click","occurred_at":"2033-01-01T01:00:00Z","value":3}\n'
            '{bad}\n', encoding="utf-8")
        out = root / "out"
        run = _run_python_entrypoint(workspace, ["app/aggregate_events.py", "aggregate_events.py", "src/app/aggregate_events.py"],
                                     ["--input", str(source), "--out-dir", str(out)], env={"TZ": "UTC"})
        if run.returncode != 0:
            return False, f"aggregation exited {run.returncode}"
        aggregate = json.loads((out / "aggregates.json").read_text(encoding="utf-8"))
        rejected = [line for line in (out / "rejected.jsonl").read_text(encoding="utf-8").splitlines() if line]
        groups = aggregate.get("groups", [])
        summary = aggregate.get("summary", {})
        ok = (summary.get("accepted_count") == sum(int(group.get("event_count", 0)) for group in groups)
              and summary.get("rejected_count") == len(rejected)
              and summary.get("group_count") == len(groups)
              and summary.get("value_total") == sum(int(group.get("value_total", 0)) for group in groups))
        return ok, f"summary reconciles with classified rows/groups={ok}"


def _reconciliation(workspace: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="v3-review-reconcile-") as tmp:
        root = Path(tmp)
        invoices = root / "invoices.csv"
        payments = root / "payments.csv"
        invoices.write_text("invoice_id,customer_id,issued_date,due_date,amount\nI1,C1,2034-01-01,2034-01-31,10.00\n", encoding="utf-8")
        payments.write_text("payment_id,invoice_id,payment_date,amount\nP1,I1,2034-01-02,4.00\n", encoding="utf-8")
        out = root / "out"
        candidates = ["app/reconcile_invoices.py", "reconcile_invoices.py", "src/app/reconcile_invoices.py"]
        run = _run_python_entrypoint(workspace, candidates,
                                     ["--invoices", str(invoices), "--payments", str(payments),
                                      "--as-of", "2034-02-01", "--out-dir", str(out)], env={"TZ": "UTC"})
        if run.returncode != 0:
            return False, f"reconciliation exited {run.returncode}"
        with (out / "reconciliation.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        summary_ok = (summary.get("invoice_count") == len(rows)
                      and summary.get("total_invoice_amount") == "10.00"
                      and summary.get("total_paid_amount") == "4.00"
                      and summary.get("total_balance") == "6.00")
        bad = root / "bad.csv"
        bad.write_text("invoice_id,customer_id,issued_date,due_date,amount\nD,C1,2034-01-01,2034-01-02,1.00\nD,C2,2034-01-01,2034-01-02,2.00\n", encoding="utf-8")
        bad_out = root / "bad-out"
        invalid = _run_python_entrypoint(workspace, candidates,
                                         ["--invoices", str(bad), "--payments", str(payments),
                                          "--as-of", "2034-02-01", "--out-dir", str(bad_out)], env={"TZ": "UTC"})
        atomic = invalid.returncode != 0 and (not bad_out.exists() or not any(bad_out.iterdir()))
        return summary_ok and atomic, f"summary reconciles={summary_ok}; invalid input atomic={atomic}"


_TARGETS = {
    "appointment-booking-api": _appointment,
    "shipment-event-api": _shipment,
    "jsonl-event-aggregation": _jsonl,
    "invoice-payment-reconciliation": _reconciliation,
}


def evaluate_review(workspace: Path, task_id: str) -> dict[str, object]:
    if task_id not in TASK_DEFECTS:
        raise ValueError(f"unknown_v3_task:{task_id}")
    with tempfile.TemporaryDirectory(prefix="agentharness-v3-review-") as tmp:
        clone = Path(tmp) / "workspace"
        shutil.copytree(workspace, clone)
        try:
            target_ok, detail = _TARGETS[task_id](clone)
        except Exception as exc:
            raise ValueError(f"review_evaluator_invalid:{task_id}:{type(exc).__name__}") from exc
    if target_ok:
        raise ValueError(f"controlled_start_target_not_reproduced:{task_id}")
    feedback = opaque_review_feedback(task_id, observed=detail)
    validate_opaque_feedback(feedback, task_id=task_id)
    return feedback
