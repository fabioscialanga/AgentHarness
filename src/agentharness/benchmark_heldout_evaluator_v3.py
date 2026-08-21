from __future__ import annotations

"""Private V3 heldout evaluator.

This module deliberately owns its cases and fixtures.  It does not delegate to
any earlier benchmark evaluator and publishes no case identifiers or details;
only the aggregate target/guard endpoint crosses the heldout boundary.
"""

import csv
import json
import multiprocessing
import queue as queue_module
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .benchmark_hidden_evaluators import (
    _load_fastapi_app,
    _make_test_client,
    _run_python_entrypoint,
    _working_directory,
)
from .efficacy_v3 import TASK_DEFECTS

# Private accounting labels.  They are intentionally unrelated to the defect
# selector/check labels and never occur in evaluate_heldout's return value.
_HELDOUT_CASE_IDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "appointment-booking-api": ("h3-ap-71", ("h3-ap-12", "h3-ap-38", "h3-ap-94")),
    "shipment-event-api": ("h3-sh-63", ("h3-sh-17", "h3-sh-42", "h3-sh-89")),
    "jsonl-event-aggregation": ("h3-js-58", ("h3-js-21", "h3-js-46", "h3-js-83")),
    "invoice-payment-reconciliation": ("h3-in-67", ("h3-in-14", "h3-in-39", "h3-in-92")),
}
if set(TASK_DEFECTS.values()) & {case for target, guards in _HELDOUT_CASE_IDS.values() for case in (target, *guards)}:
    raise RuntimeError("v3_private_case_identity_collision")


def _payload(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _identifier(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    return payload.get("appointment_id", payload.get("id"))


def _appointment_cases(workspace: Path) -> dict[str, bool]:
    target_id, guards = _HELDOUT_CASE_IDS["appointment-booking-api"]
    results = {target_id: False, **dict.fromkeys(guards, False)}
    _, app = _load_fastapi_app(workspace)
    with _working_directory(workspace), _make_test_client(app) as client:
        def create(customer: str, provider: str, start: str, end: str) -> Any:
            return client.post("/appointments", json={
                "customer_id": customer, "provider_id": provider,
                "starts_at": start, "ends_at": end, "reason": "heldout-probe",
            })

        # Target: fixtures and interval geometry differ from the review probe.
        anchor = create("HC-71", "HP-71", "2041-09-17T14:15:00Z", "2041-09-17T15:45:00Z")
        moving = create("HC-72", "HP-71", "2041-09-17T17:00:00Z", "2041-09-17T18:00:00Z")
        moving_id = _identifier(_payload(moving))
        rejected = client.patch(f"/appointments/{moving_id}/reschedule", json={
            "starts_at": "2041-09-17T15:30:00Z", "ends_at": "2041-09-17T16:30:00Z",
        })
        preserved = _payload(client.get(f"/appointments/{moving_id}"))
        accepted = client.patch(f"/appointments/{moving_id}/reschedule", json={
            "starts_at": "2041-09-17T18:00:00Z", "ends_at": "2041-09-17T19:00:00Z",
        })
        results[target_id] = bool(
            anchor.status_code in {200, 201} and moving.status_code in {200, 201}
            and rejected.status_code in {400, 409, 422}
            and isinstance(preserved, dict)
            and str(preserved.get("starts_at", "")).startswith("2041-09-17T17:00:00")
            and accepted.status_code in {200, 201}
        )

        listed_item = create("HC-LIST", "HP-LIST", "2041-10-03T07:00:00Z", "2041-10-03T07:30:00Z")
        listed = _payload(client.get("/appointments", params={"customer_id": "HC-LIST", "status": "scheduled"}))
        results[guards[0]] = bool(listed_item.status_code in {200, 201} and isinstance(listed, list)
                                  and len(listed) == 1 and _identifier(listed[0]) == _identifier(_payload(listed_item)))

        base = create("HC-B1", "HP-SCOPE", "2041-11-08T10:00:00Z", "2041-11-08T11:00:00Z")
        overlap = create("HC-B2", "HP-SCOPE", "2041-11-08T10:59:00Z", "2041-11-08T11:30:00Z")
        adjacent = create("HC-B3", "HP-SCOPE", "2041-11-08T11:00:00Z", "2041-11-08T12:00:00Z")
        invalid = create("HC-B4", "HP-INVALID", "2041-11-09T12:00:00Z", "2041-11-09T11:00:00Z")
        results[guards[1]] = bool(base.status_code in {200, 201} and overlap.status_code in {400, 409, 422}
                                  and adjacent.status_code in {200, 201} and invalid.status_code in {400, 409, 422})

        cancellable = create("HC-C1", "HP-CANCEL", "2041-12-12T09:00:00Z", "2041-12-12T10:00:00Z")
        cancellable_id = _identifier(_payload(cancellable))
        cancelled = client.post(f"/appointments/{cancellable_id}/cancel", json={"reason": "heldout cancellation"})
        replacement = create("HC-C2", "HP-CANCEL", "2041-12-12T09:00:00Z", "2041-12-12T10:00:00Z")
        results[guards[2]] = bool(cancellable.status_code in {200, 201} and cancelled.status_code in {200, 201}
                                  and replacement.status_code in {200, 201})
    return results


def _shipment_cases(workspace: Path) -> dict[str, bool]:
    target_id, guards = _HELDOUT_CASE_IDS["shipment-event-api"]
    results = {target_id: False, **dict.fromkeys(guards, False)}
    _, app = _load_fastapi_app(workspace)
    with _working_directory(workspace), _make_test_client(app) as client:
        def create(tracking: str, carrier: str = "HeldoutCarrier") -> Any:
            return client.post("/shipments", json={"tracking_number": tracking, "carrier": carrier})

        def event(tracking: str, event_id: str, kind: str, when: str, location: str = "H-Zone") -> Any:
            return client.post(f"/shipments/{tracking}/events", json={
                "event_id": event_id, "type": kind, "occurred_at": when, "location": location,
            })

        created = create("H3-SKIP-71")
        skipped = event("H3-SKIP-71", "H3-E-71", "out_for_delivery", "2042-03-11T16:20:00Z")
        after = _payload(client.get("/shipments/H3-SKIP-71"))
        results[target_id] = bool(created.status_code in {200, 201} and skipped.status_code in {400, 409, 422}
                                  and isinstance(after, dict) and after.get("status") == "created"
                                  and after.get("events") == [])

        create("H3-PATH-17")
        path = ("picked_up", "in_transit", "out_for_delivery", "delivered")
        responses = [event("H3-PATH-17", f"H3-P-{index}", kind,
                           f"2042-04-{index + 1:02d}T08:00:00Z") for index, kind in enumerate(path)]
        detail = _payload(client.get("/shipments/H3-PATH-17"))
        results[guards[0]] = bool(all(response.status_code in {200, 201} for response in responses)
                                  and isinstance(detail, dict) and detail.get("status") == "delivered"
                                  and [item.get("type") for item in detail.get("events", [])] == list(path))

        create("H3-IDEM-42")
        first = event("H3-IDEM-42", "H3-DUP", "picked_up", "2042-05-02T10:00:00Z", "Alpha-H")
        replay = event("H3-IDEM-42", "H3-DUP", "picked_up", "2042-05-02T10:00:00Z", "Alpha-H")
        conflict = event("H3-IDEM-42", "H3-DUP", "picked_up", "2042-05-02T10:00:00Z", "Beta-H")
        idem = _payload(client.get("/shipments/H3-IDEM-42"))
        results[guards[1]] = bool(first.status_code in {200, 201} and replay.status_code in {200, 201}
                                  and conflict.status_code in {400, 409, 422} and isinstance(idem, dict)
                                  and len(idem.get("events", [])) == 1)

        create("H3-TIME-89")
        event("H3-TIME-89", "H3-T1", "picked_up", "2042-06-09T12:00:00Z")
        stale = event("H3-TIME-89", "H3-T2", "in_transit", "2042-06-09T11:59:00Z")
        stale_detail = _payload(client.get("/shipments/H3-TIME-89"))
        results[guards[2]] = bool(stale.status_code in {400, 409, 422} and isinstance(stale_detail, dict)
                                  and stale_detail.get("status") == "picked_up" and len(stale_detail.get("events", [])) == 1)
    return results


def _jsonl_cases(workspace: Path) -> dict[str, bool]:
    target_id, guards = _HELDOUT_CASE_IDS["jsonl-event-aggregation"]
    results = {target_id: False, **dict.fromkeys(guards, False)}
    with tempfile.TemporaryDirectory(prefix="v3-heldout-json-") as tmp:
        root = Path(tmp)
        source = root / "heldout-events.jsonl"
        source.write_text("\n".join([
            '{"event_id":"h71","actor_id":"u1","event_type":"open","occurred_at":"2043-07-01T00:20:00+02:00","value":4}',
            '{"event_id":"h72","actor_id":"u1","event_type":"open","occurred_at":"2043-06-30T23:10:00Z","value":6}',
            '{"event_id":"h73","actor_id":"u2","event_type":"close","occurred_at":"2043-07-01T02:00:00Z","value":5}',
            '{"event_id":"h73","actor_id":"u9","event_type":"close","occurred_at":"2043-07-02T02:00:00Z","value":9}',
            'not-json',
        ]) + "\n", encoding="utf-8")
        candidates = ["app/aggregate_events.py", "aggregate_events.py", "src/app/aggregate_events.py"]
        out_one, out_two = root / "one", root / "two"
        first = _run_python_entrypoint(workspace, candidates, ["--input", str(source), "--out-dir", str(out_one)],
                                       env={"PYTHONHASHSEED": "271", "TZ": "Pacific/Honolulu"})
        if first.returncode != 0:
            return results
        aggregate = json.loads((out_one / "aggregates.json").read_text(encoding="utf-8"))
        rejected = [json.loads(line) for line in (out_one / "rejected.jsonl").read_text(encoding="utf-8").splitlines() if line]
        groups, summary = aggregate.get("groups", []), aggregate.get("summary", {})
        results[target_id] = bool(summary.get("accepted_count") == sum(item.get("event_count", 0) for item in groups)
                                  and summary.get("rejected_count") == len(rejected)
                                  and summary.get("group_count") == len(groups)
                                  and summary.get("value_total") == sum(item.get("value_total", 0) for item in groups))
        expected = [
            {"date": "2043-06-30", "event_type": "open", "event_count": 2, "unique_actor_count": 1, "value_total": 10},
            {"date": "2043-07-01", "event_type": "close", "event_count": 1, "unique_actor_count": 1, "value_total": 5},
        ]
        results[guards[0]] = groups == expected
        results[guards[1]] = bool([item.get("line_number") for item in rejected] == [4, 5]
                                  and [item.get("reason") for item in rejected] == ["duplicate_event_id", "malformed_json"])
        second = _run_python_entrypoint(workspace, candidates, ["--input", str(source), "--out-dir", str(out_two)],
                                        env={"PYTHONHASHSEED": "814", "TZ": "Europe/Rome"})
        results[guards[2]] = bool(second.returncode == 0
                                  and (out_one / "aggregates.json").read_bytes() == (out_two / "aggregates.json").read_bytes()
                                  and (out_one / "rejected.jsonl").read_bytes() == (out_two / "rejected.jsonl").read_bytes())
    return results


def _reconciliation_cases(workspace: Path) -> dict[str, bool]:
    target_id, guards = _HELDOUT_CASE_IDS["invoice-payment-reconciliation"]
    results = {target_id: False, **dict.fromkeys(guards, False)}
    with tempfile.TemporaryDirectory(prefix="v3-heldout-invoice-") as tmp:
        root = Path(tmp)
        invoices, payments = root / "heldout-invoices.csv", root / "heldout-payments.csv"
        invoices.write_text(
            "invoice_id,customer_id,issued_date,due_date,amount\n"
            "H-20,C-2,2044-01-02,2044-01-31,40.00\n"
            "H-10,C-1,2044-01-01,2044-01-20,25.00\n"
            "H-30,C-3,2044-03-01,2044-03-20,70.00\n", encoding="utf-8")
        payments.write_text(
            "payment_id,invoice_id,payment_date,amount\n"
            "HP-1,H-10,2044-02-01,25.00\n"
            "HP-2,H-20,2044-02-02,10.00\n"
            "HP-X,UNKNOWN,2044-02-03,3.00\n"
            "HP-2,H-20,2044-02-04,5.00\n"
            "HP-L,H-20,2044-02-16,7.00\n", encoding="utf-8")
        candidates = ["app/reconcile_invoices.py", "reconcile_invoices.py", "src/app/reconcile_invoices.py"]
        out = root / "out"
        run = _run_python_entrypoint(workspace, candidates,
                                     ["--invoices", str(invoices), "--payments", str(payments),
                                      "--as-of", "2044-02-15", "--out-dir", str(out)], env={"TZ": "UTC"})
        if run.returncode != 0:
            return results
        with (out / "reconciliation.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        with (out / "unmatched_payments.csv").open(encoding="utf-8", newline="") as stream:
            unmatched = list(csv.DictReader(stream))
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        results[target_id] = bool(summary.get("invoice_count") == len(rows)
                                  and summary.get("total_invoice_amount") == "65.00"
                                  and summary.get("total_paid_amount") == "35.00"
                                  and summary.get("total_balance") == "30.00")
        results[guards[0]] = bool([row.get("invoice_id") for row in rows] == ["H-10", "H-20"]
                                  and [row.get("status") for row in rows] == ["PAID", "PARTIAL"])
        results[guards[1]] = bool(summary.get("duplicate_payment_count") == 1
                                  and next(row for row in rows if row["invoice_id"] == "H-20")["paid_amount"] == "10.00")
        results[guards[2]] = [(row.get("payment_id"), row.get("reason")) for row in unmatched] == [
            ("HP-2", "duplicate_payment_id"), ("HP-X", "unknown_invoice")]

        invalid_invoices = root / "invalid-invoices.csv"
        invalid_invoices.write_text(
            "invoice_id,customer_id,issued_date,due_date,amount\nBAD,C-9,2044-01-01,2044-01-02,-1.00\n",
            encoding="utf-8")
        invalid_out = root / "invalid-out"
        invalid = _run_python_entrypoint(workspace, candidates,
                                         ["--invoices", str(invalid_invoices), "--payments", str(payments),
                                          "--as-of", "2044-02-15", "--out-dir", str(invalid_out)], env={"TZ": "UTC"})
        results[guards[2]] = bool(results[guards[2]] and invalid.returncode != 0
                                  and (not invalid_out.exists() or not any(invalid_out.iterdir())))
    return results


_EVALUATORS: dict[str, Callable[[Path], dict[str, bool]]] = {
    "appointment-booking-api": _appointment_cases,
    "shipment-event-api": _shipment_cases,
    "jsonl-event-aggregation": _jsonl_cases,
    "invoice-payment-reconciliation": _reconciliation_cases,
}


def _heldout_worker(task_id: str, workspace: str, queue: object) -> None:
    try:
        result = _EVALUATORS[task_id](Path(workspace))
        queue.put(("ok", result))  # type: ignore[attr-defined]
    except BaseException as exc:
        queue.put(("error", type(exc).__name__))  # type: ignore[attr-defined]


def _evaluate_isolated(workspace: Path, task_id: str, *, timeout_seconds: int = 120) -> dict[str, bool]:
    context = multiprocessing.get_context("fork")
    queue = context.Queue(maxsize=1)
    process = context.Process(target=_heldout_worker, args=(task_id, str(workspace), queue), daemon=True)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10)
        raise ValueError(f"heldout_evaluator_timeout:{task_id}")
    if process.exitcode != 0:
        raise ValueError(f"heldout_evaluator_process_invalid:{task_id}:{process.exitcode}")
    try:
        status, payload = queue.get(timeout=5)
    except queue_module.Empty as exc:
        raise ValueError(f"heldout_evaluator_process_invalid:{task_id}:missing_payload") from exc
    finally:
        queue.close()
        queue.join_thread()
    if status != "ok" or not isinstance(payload, dict):
        raise ValueError(f"heldout_evaluator_invalid:{task_id}:{payload}")
    return payload


def evaluate_heldout(workspace: Path, task_id: str) -> dict[str, object]:
    """Evaluate private cases in a disposable clone and return aggregates only."""
    if task_id not in TASK_DEFECTS:
        raise ValueError(f"unknown_v3_task:{task_id}")
    target_id, guard_ids = _HELDOUT_CASE_IDS[task_id]
    with tempfile.TemporaryDirectory(prefix="agentharness-v3-heldout-") as tmp:
        clone = Path(tmp) / "workspace"
        shutil.copytree(workspace, clone)
        statuses = _evaluate_isolated(clone, task_id)
    if set(statuses) != {target_id, *guard_ids} or any(not isinstance(value, bool) for value in statuses.values()):
        raise ValueError("heldout_evaluator_shape_invalid")
    target_passed = statuses[target_id]
    guards_passed = all(statuses[guard_id] for guard_id in guard_ids)
    return {
        "target_evaluated": True,
        "guards_evaluated": True,
        "target_passed": target_passed,
        "guards_passed": guards_passed,
        "binary_endpoint": int(target_passed and guards_passed),
    }
