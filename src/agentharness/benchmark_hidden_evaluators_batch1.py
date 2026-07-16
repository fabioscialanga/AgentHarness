from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .benchmark_hidden_evaluators import (
    HiddenEvaluationObservation,
    HiddenEvaluationResult,
    _evaluation_dir,
    _finalize_hidden_evaluation,
    _interface_unreachable_result,
    _load_fastapi_app,
    _make_test_client,
    _run_python_entrypoint,
    _working_directory,
)

BATCH1_TASK_IDS = {
    "appointment-booking-api",
    "shipment-event-api",
    "jsonl-event-aggregation",
    "invoice-payment-reconciliation",
}


def _json_payload(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _identifier(payload: Any, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _cross_process_request(
    workspace: Path,
    *,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> tuple[int, Any, str]:
    request = {"method": method, "path": path, "json": json_body, "params": params}
    marker = "__AGENTHARNESS_HTTP_RESPONSE__="
    script = """
import json
import os
from pathlib import Path
from agentharness.benchmark_hidden_evaluators import _load_fastapi_app, _make_test_client
request = json.loads(os.environ["AGENTHARNESS_CROSS_PROCESS_REQUEST"])
_module_path, app = _load_fastapi_app(Path.cwd())
with _make_test_client(app) as client:
    response = client.request(request["method"], request["path"], json=request.get("json"), params=request.get("params"))
try:
    payload = response.json()
except Exception:
    payload = response.text
print("__AGENTHARNESS_HTTP_RESPONSE__=" + json.dumps({"status_code": response.status_code, "payload": payload}, sort_keys=True))
"""
    env = dict(os.environ)
    env["AGENTHARNESS_CROSS_PROCESS_REQUEST"] = json.dumps(request, sort_keys=True)
    env["AGENTHARNESS_CROSS_PROCESS_CHILD"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    response_line = next((line for line in reversed(completed.stdout.splitlines()) if line.startswith(marker)), "")
    if completed.returncode != 0 or not response_line:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"child exit {completed.returncode}"
        return 599, None, detail
    response_payload = json.loads(response_line[len(marker) :])
    return int(response_payload["status_code"]), response_payload.get("payload"), f"child_exit={completed.returncode}"


def _recorder() -> tuple[list[HiddenEvaluationObservation], list[str], list[str], Callable[[str, bool, str], None]]:
    observations: list[HiddenEvaluationObservation] = []
    passed: list[str] = []
    failed: list[str] = []

    def record(check_id: str, ok: bool, detail: str) -> None:
        observations.append(HiddenEvaluationObservation(id=check_id, status="pass" if ok else "fail", detail=detail))
        (passed if ok else failed).append(check_id)

    return observations, passed, failed, record


def evaluate_batch1_task(workspace: Path, task_id: str) -> HiddenEvaluationResult:
    evaluators = {
        "appointment-booking-api": _evaluate_appointment_booking_api,
        "shipment-event-api": _evaluate_shipment_event_api,
        "jsonl-event-aggregation": _evaluate_jsonl_event_aggregation,
        "invoice-payment-reconciliation": _evaluate_invoice_payment_reconciliation,
    }
    try:
        evaluator = evaluators[task_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported batch-1 benchmark task evaluator: {task_id}") from exc
    return evaluator(workspace)


def _evaluate_appointment_booking_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "appointment-booking-api"
    check_ids = (
        "appointment_create_and_filters",
        "appointment_interval_validation",
        "appointment_provider_conflicts",
        "appointment_reschedule_atomic",
        "appointment_cancel_releases_slot",
    )
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations, passed, failed, record = _recorder()
    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        return _interface_unreachable_result(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations, check_ids=check_ids, detail=f"app discovery failed: {exc}", reason="interface_unreachable:app_load_failed")

    def create(client: Any, *, customer: str, provider: str, start: str, end: str, reason: str = "consultation") -> Any:
        return client.post("/appointments", json={"customer_id": customer, "provider_id": provider, "starts_at": start, "ends_at": end, "reason": reason})

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            first_status, first_payload, first_child_detail = _cross_process_request(
                workspace,
                method="POST",
                path="/appointments",
                json_body={"customer_id": "C-A17", "provider_id": "P-FILTER", "starts_at": "2031-03-04T09:00:00Z", "ends_at": "2031-03-04T09:45:00Z", "reason": "consultation"},
            )
            first_id = _identifier(first_payload, "appointment_id", "id")
            detail = client.get(f"/appointments/{first_id}") if first_id is not None else None
            distractor = create(client, customer="C-OTHER", provider="P-OTHER-FILTER", start="2031-03-04T10:00:00Z", end="2031-03-04T10:45:00Z")
            filtered = client.get("/appointments", params={"customer_id": "C-A17", "provider_id": "P-FILTER", "status": "scheduled"})
            filtered_payload = _json_payload(filtered)
            filter_ok = isinstance(filtered_payload, list) and len(filtered_payload) == 1 and _identifier(filtered_payload[0], "appointment_id", "id") == first_id
            persistence_ok = detail is not None and detail.status_code == 200 and _identifier(_json_payload(detail), "appointment_id", "id") == first_id
            record(check_ids[0], bool(first_status in {200, 201} and distractor.status_code in {200, 201} and first_id is not None and isinstance(first_payload, dict) and first_payload.get("status") == "scheduled" and filtered.status_code == 200 and filter_ok and persistence_ok), f"module={module_path}; child_create={first_status}; detail={detail.status_code if detail is not None else None}; filtered={filter_ok}; cross_process_persisted={persistence_ok}; {first_child_detail}")

            before_invalid = _json_payload(client.get("/appointments", params={"provider_id": "P-INVALID"}))
            invalid = create(client, customer="C-I9", provider="P-INVALID", start="2031-04-01T10:00:00+00:00", end="2031-04-01T10:00:00Z")
            after_invalid = _json_payload(client.get("/appointments", params={"provider_id": "P-INVALID"}))
            time_target = create(client, customer="C-TIME", provider="P-TIME", start="2031-04-02T10:00:00Z", end="2031-04-02T11:00:00Z")
            time_target_id = _identifier(_json_payload(time_target), "appointment_id", "id")
            malformed_patch = client.patch(f"/appointments/{time_target_id}/reschedule", json={"starts_at": "2031-04-02T12:00:00", "ends_at": "2031-04-02T13:00:00Z"}) if time_target_id is not None else None
            time_after = _json_payload(client.get(f"/appointments/{time_target_id}")) if time_target_id is not None else None
            malformed_atomic = malformed_patch is not None and malformed_patch.status_code in {400, 409, 422} and isinstance(time_after, dict) and str(time_after.get("starts_at", "")).startswith("2031-04-02T10:00:00")
            record(check_ids[1], bool(invalid.status_code in {400, 409, 422} and isinstance(before_invalid, list) and isinstance(after_invalid, list) and len(before_invalid) == len(after_invalid) and time_target.status_code in {200, 201} and malformed_atomic), f"invalid_status={invalid.status_code}; before={len(before_invalid) if isinstance(before_invalid, list) else None}; after={len(after_invalid) if isinstance(after_invalid, list) else None}; malformed_atomic={malformed_atomic}")

            base = create(client, customer="C-B1", provider="P-SCOPE", start="2031-05-06T12:00:00Z", end="2031-05-06T13:00:00Z")
            overlap = create(client, customer="C-B2", provider="P-SCOPE", start="2031-05-06T12:30:00Z", end="2031-05-06T13:30:00Z")
            adjacent = create(client, customer="C-B3", provider="P-SCOPE", start="2031-05-06T13:00:00Z", end="2031-05-06T14:00:00Z")
            other = create(client, customer="C-B4", provider="P-OTHER", start="2031-05-06T12:00:00Z", end="2031-05-06T13:00:00Z")
            record(check_ids[2], bool(base.status_code in {200, 201} and overlap.status_code in {400, 409, 422} and adjacent.status_code in {200, 201} and other.status_code in {200, 201}), f"base={base.status_code}; overlap={overlap.status_code}; adjacent={adjacent.status_code}; other_provider={other.status_code}")

            occupied = create(client, customer="C-R1", provider="P-RESCHEDULE", start="2031-06-01T08:00:00Z", end="2031-06-01T09:00:00Z")
            movable = create(client, customer="C-R2", provider="P-RESCHEDULE", start="2031-06-01T10:00:00Z", end="2031-06-01T11:00:00Z")
            movable_id = _identifier(_json_payload(movable), "appointment_id", "id")
            conflict_patch = client.patch(f"/appointments/{movable_id}/reschedule", json={"starts_at": "2031-06-01T08:30:00Z", "ends_at": "2031-06-01T09:30:00Z"}) if movable_id is not None else None
            after_conflict = _json_payload(client.get(f"/appointments/{movable_id}")) if movable_id is not None else None
            safe_patch = client.patch(f"/appointments/{movable_id}/reschedule", json={"starts_at": "2031-06-01T11:00:00Z", "ends_at": "2031-06-01T12:00:00Z"}) if movable_id is not None else None
            safe_payload = _json_payload(safe_patch) if safe_patch is not None else None
            atomic_ok = isinstance(after_conflict, dict) and str(after_conflict.get("starts_at", "")).startswith("2031-06-01T10:00:00")
            record(check_ids[3], bool(occupied.status_code in {200, 201} and movable.status_code in {200, 201} and conflict_patch is not None and conflict_patch.status_code in {400, 409, 422} and atomic_ok and safe_patch is not None and safe_patch.status_code in {200, 201} and isinstance(safe_payload, dict) and str(safe_payload.get("starts_at", "")).startswith("2031-06-01T11:00:00")), f"conflict={conflict_patch.status_code if conflict_patch is not None else None}; atomic={atomic_ok}; safe={safe_patch.status_code if safe_patch is not None else None}")

            cancellable = create(client, customer="C-C1", provider="P-CANCEL", start="2031-07-02T15:00:00Z", end="2031-07-02T16:00:00Z")
            cancellable_id = _identifier(_json_payload(cancellable), "appointment_id", "id")
            cancel = client.post(f"/appointments/{cancellable_id}/cancel", json={"reason": "customer unavailable"}) if cancellable_id is not None else None
            cancel_payload = _json_payload(cancel) if cancel is not None else None
            forbidden_reschedule = client.patch(f"/appointments/{cancellable_id}/reschedule", json={"starts_at": "2031-07-02T16:00:00Z", "ends_at": "2031-07-02T17:00:00Z"}) if cancellable_id is not None else None
            replacement = create(client, customer="C-C2", provider="P-CANCEL", start="2031-07-02T15:00:00Z", end="2031-07-02T16:00:00Z")
            record(check_ids[4], bool(cancel is not None and cancel.status_code in {200, 201} and isinstance(cancel_payload, dict) and cancel_payload.get("status") == "cancelled" and bool(cancel_payload.get("cancelled_at")) and cancel_payload.get("cancel_reason") == "customer unavailable" and forbidden_reschedule is not None and forbidden_reschedule.status_code in {400, 409, 422} and replacement.status_code in {200, 201}), f"cancel={cancel.status_code if cancel is not None else None}; terminal={forbidden_reschedule.status_code if forbidden_reschedule is not None else None}; replacement={replacement.status_code}")
    except Exception as exc:
        seen = {item.id for item in observations}
        for check_id in check_ids:
            if check_id not in seen:
                record(check_id, False, f"runtime evaluation failed: {exc}")
    return _finalize_hidden_evaluation(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations)


def _evaluate_shipment_event_api(workspace: Path) -> HiddenEvaluationResult:
    task_id = "shipment-event-api"
    check_ids = (
        "shipment_create_and_filters",
        "shipment_valid_transition_path",
        "shipment_skipped_transition_atomic",
        "shipment_event_idempotency",
        "shipment_time_and_terminal_invariants",
    )
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations, passed, failed, record = _recorder()
    try:
        module_path, app = _load_fastapi_app(workspace)
    except Exception as exc:
        return _interface_unreachable_result(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations, check_ids=check_ids, detail=f"app discovery failed: {exc}", reason="interface_unreachable:app_load_failed")

    def create(client: Any, tracking: str, carrier: str = "Northstar") -> Any:
        return client.post("/shipments", json={"tracking_number": tracking, "carrier": carrier})

    def event(client: Any, tracking: str, event_id: str, event_type: str, occurred_at: str, location: str = "Hub-7") -> Any:
        return client.post(f"/shipments/{tracking}/events", json={"event_id": event_id, "type": event_type, "occurred_at": occurred_at, "location": location})

    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            created_status, created_payload, created_child_detail = _cross_process_request(
                workspace,
                method="POST",
                path="/shipments",
                json_body={"tracking_number": "TRK-FLT-91", "carrier": "Northstar"},
            )
            detail = client.get("/shipments/TRK-FLT-91")
            distractor = create(client, "TRK-NOISE-19", "OtherCarrier")
            listed = client.get("/shipments", params={"carrier": "Northstar", "status": "created"})
            listed_payload = _json_payload(listed)
            listed_ok = isinstance(listed_payload, list) and len(listed_payload) == 1 and listed_payload[0].get("tracking_number") == "TRK-FLT-91"
            persistence_ok = detail.status_code == 200 and isinstance(_json_payload(detail), dict) and _json_payload(detail).get("tracking_number") == "TRK-FLT-91"
            record(check_ids[0], bool(created_status in {200, 201} and distractor.status_code in {200, 201} and isinstance(created_payload, dict) and created_payload.get("status") == "created" and created_payload.get("events") in (None, []) and detail.status_code == 200 and listed.status_code == 200 and listed_ok and persistence_ok), f"module={module_path}; child_create={created_status}; detail={detail.status_code}; listed={listed_ok}; cross_process_persisted={persistence_ok}; {created_child_detail}")

            create(client, "TRK-PATH-37")
            path_types = ["picked_up", "in_transit", "out_for_delivery", "delivered"]
            path_statuses = []
            for index, kind in enumerate(path_types, 1):
                response = event(client, "TRK-PATH-37", f"EV-P-{index}", kind, f"2032-01-0{index}T10:00:00Z", f"L-{index}")
                payload = _json_payload(response)
                path_statuses.append((response.status_code, payload.get("status") if isinstance(payload, dict) else None))
            path_detail = _json_payload(client.get("/shipments/TRK-PATH-37"))
            path_events = path_detail.get("events") if isinstance(path_detail, dict) else None
            record(check_ids[1], bool(all(code in {200, 201} and status == expected for (code, status), expected in zip(path_statuses, path_types)) and isinstance(path_events, list) and [x.get("type") for x in path_events] == path_types), f"statuses={path_statuses}; history_types={[x.get('type') for x in path_events] if isinstance(path_events, list) else None}")

            create(client, "TRK-SKIP-42")
            skip = event(client, "TRK-SKIP-42", "EV-SKIP", "in_transit", "2032-02-01T10:00:00Z")
            skip_detail = _json_payload(client.get("/shipments/TRK-SKIP-42"))
            record(check_ids[2], bool(skip.status_code in {400, 409, 422} and isinstance(skip_detail, dict) and skip_detail.get("status") == "created" and skip_detail.get("events") == []), f"skip={skip.status_code}; state={skip_detail.get('status') if isinstance(skip_detail, dict) else None}; events={len(skip_detail.get('events', [])) if isinstance(skip_detail, dict) else None}")

            create(client, "TRK-IDEM-58")
            first_event = event(client, "TRK-IDEM-58", "EV-IDEM", "picked_up", "2032-03-01T08:00:00Z", "Alpha")
            replay = event(client, "TRK-IDEM-58", "EV-IDEM", "picked_up", "2032-03-01T08:00:00Z", "Alpha")
            conflict = event(client, "TRK-IDEM-58", "EV-IDEM", "picked_up", "2032-03-01T08:00:00Z", "Beta")
            idem_detail = _json_payload(client.get("/shipments/TRK-IDEM-58"))
            idem_events = idem_detail.get("events") if isinstance(idem_detail, dict) else None
            record(check_ids[3], bool(first_event.status_code in {200, 201} and replay.status_code in {200, 201} and conflict.status_code in {400, 409, 422} and isinstance(idem_events, list) and len(idem_events) == 1 and idem_events[0].get("location") == "Alpha"), f"first={first_event.status_code}; replay={replay.status_code}; conflict={conflict.status_code}; count={len(idem_events) if isinstance(idem_events, list) else None}")

            create(client, "TRK-TIME-64")
            event(client, "TRK-TIME-64", "EV-T1", "picked_up", "2032-04-02T12:00:00Z")
            stale = event(client, "TRK-TIME-64", "EV-T2", "in_transit", "2032-04-02T11:59:59Z")
            stale_detail = _json_payload(client.get("/shipments/TRK-TIME-64"))
            create(client, "TRK-END-73")
            for index, kind in enumerate(path_types, 1):
                event(client, "TRK-END-73", f"EV-E-{index}", kind, f"2032-05-0{index}T09:00:00Z")
            terminal = event(client, "TRK-END-73", "EV-E-5", "in_transit", "2032-05-05T09:00:00Z")
            terminal_detail = _json_payload(client.get("/shipments/TRK-END-73"))
            create(client, "TRK-MALFORMED-82")
            malformed = event(client, "TRK-MALFORMED-82", "EV-MAL", "picked_up", "2032-06-01T09:00:00")
            malformed_detail = _json_payload(client.get("/shipments/TRK-MALFORMED-82"))
            malformed_atomic = malformed.status_code in {400, 409, 422} and isinstance(malformed_detail, dict) and malformed_detail.get("status") == "created" and malformed_detail.get("events") == []
            record(check_ids[4], bool(stale.status_code in {400, 409, 422} and isinstance(stale_detail, dict) and stale_detail.get("status") == "picked_up" and len(stale_detail.get("events", [])) == 1 and terminal.status_code in {400, 409, 422} and isinstance(terminal_detail, dict) and terminal_detail.get("status") == "delivered" and len(terminal_detail.get("events", [])) == 4 and malformed_atomic), f"stale={stale.status_code}; stale_state={stale_detail.get('status') if isinstance(stale_detail, dict) else None}; terminal={terminal.status_code}; terminal_state={terminal_detail.get('status') if isinstance(terminal_detail, dict) else None}; malformed_atomic={malformed_atomic}")
    except Exception as exc:
        seen = {item.id for item in observations}
        for check_id in check_ids:
            if check_id not in seen:
                record(check_id, False, f"runtime evaluation failed: {exc}")
    return _finalize_hidden_evaluation(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[Any]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _evaluate_jsonl_event_aggregation(workspace: Path) -> HiddenEvaluationResult:
    task_id = "jsonl-event-aggregation"
    check_ids = ("jsonl_grouped_counts", "jsonl_utc_date_normalization", "jsonl_invalid_and_duplicate_handling", "jsonl_summary_consistency", "jsonl_deterministic_outputs")
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations, passed, failed, record = _recorder()
    candidates = ["app/aggregate_events.py", "aggregate_events.py", "src/app/aggregate_events.py"]
    lines = [
        '{"event_id":"evt-a91","actor_id":"actor-1","event_type":"offset_probe","occurred_at":"2033-07-01T00:30:00+02:00","value":2}',
        '{"event_id":"evt-b82","actor_id":"actor-1","event_type":"click","occurred_at":"2033-06-30T23:00:00Z","value":3}',
        '{"event_id":"evt-c73","actor_id":"actor-2","event_type":"click","occurred_at":"2033-06-30T20:00:00-04:00","value":5}',
        '{"event_id":"evt-d64","actor_id":"actor-3","event_type":"view","occurred_at":"2033-07-01T07:00:00Z","value":7}',
        '{not-json}',
        '17',
        '{"event_id":"evt-missing","event_type":"view","occurred_at":"2033-07-01T08:00:00Z","value":1}',
        '{"event_id":"evt-bool","actor_id":"actor-4","event_type":"view","occurred_at":"2033-07-01T09:00:00Z","value":true}',
        '{"event_id":"evt-a91","actor_id":"actor-9","event_type":"click","occurred_at":"2033-07-02T00:00:00Z","value":9}',
        '{"event_id":"evt-first-valid","actor_id":"actor-5","event_type":"click","occurred_at":"2033-07-01T10:00:00Z","value":-1}',
        '{"event_id":"evt-first-valid","actor_id":"actor-5","event_type":"click","occurred_at":"2033-07-01T10:00:00Z","value":1}',
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="agentharness-jsonl-eval-") as tmp:
            root = Path(tmp)
            input_path = root / "events.jsonl"
            input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            output_one = root / "out-one"
            output_two = root / "out-two"
            first = _run_python_entrypoint(workspace, candidates, ["--input", str(input_path), "--out-dir", str(output_one)], env={"PYTHONHASHSEED": "17", "TZ": "UTC"})
            if first.returncode != 0:
                raise RuntimeError(f"CLI failed: exit={first.returncode}; stderr={first.stderr.strip()}")
            aggregates = _read_json(output_one / "aggregates.json")
            rejected = _read_jsonl(output_one / "rejected.jsonl")
            groups = aggregates.get("groups") if isinstance(aggregates, dict) else None
            summary = aggregates.get("summary") if isinstance(aggregates, dict) else None
            expected_groups = [
                {"date": "2033-06-30", "event_type": "click", "event_count": 1, "unique_actor_count": 1, "value_total": 3},
                {"date": "2033-06-30", "event_type": "offset_probe", "event_count": 1, "unique_actor_count": 1, "value_total": 2},
                {"date": "2033-07-01", "event_type": "click", "event_count": 2, "unique_actor_count": 2, "value_total": 6},
                {"date": "2033-07-01", "event_type": "view", "event_count": 1, "unique_actor_count": 1, "value_total": 7},
            ]
            record(check_ids[0], groups == expected_groups, f"groups={groups}")
            utc_ok = isinstance(groups, list) and any(g.get("date") == "2033-06-30" and g.get("event_type") == "offset_probe" and g.get("event_count") == 1 for g in groups if isinstance(g, dict)) and not any(g.get("date") == "2033-07-01" and g.get("event_type") == "offset_probe" for g in groups if isinstance(g, dict))
            record(check_ids[1], utc_ok, f"dates={[g.get('date') for g in groups] if isinstance(groups, list) else None}")
            reasons = [item.get("reason") for item in rejected if isinstance(item, dict)]
            rejected_lines = [item.get("line_number") for item in rejected if isinstance(item, dict)]
            invalid_ok = len(rejected) == 6 and rejected_lines == [5, 6, 7, 8, 9, 10] and reasons[-2:] == ["duplicate_event_id", "invalid_field"]
            record(check_ids[2], invalid_ok, f"rejected_lines={rejected_lines}; reasons={reasons}")
            expected_summary = {"accepted_count": 5, "rejected_count": 6, "duplicate_count": 1, "group_count": 4, "value_total": 18}
            summary_ok = isinstance(summary, dict) and all(summary.get(k) == v for k, v in expected_summary.items())
            record(check_ids[3], summary_ok, f"summary={summary}")
            second = _run_python_entrypoint(workspace, candidates, ["--input", str(input_path), "--out-dir", str(output_two)], env={"PYTHONHASHSEED": "91", "TZ": "UTC"})
            missing = _run_python_entrypoint(workspace, candidates, ["--input", str(root / "absent.jsonl"), "--out-dir", str(root / "missing-out")], env={"PYTHONHASHSEED": "33", "TZ": "UTC"})
            deterministic = second.returncode == 0 and (output_one / "aggregates.json").read_bytes() == (output_two / "aggregates.json").read_bytes() and (output_one / "rejected.jsonl").read_bytes() == (output_two / "rejected.jsonl").read_bytes() and missing.returncode != 0 and "Traceback" not in missing.stderr
            record(check_ids[4], deterministic, f"second_exit={second.returncode}; missing_exit={missing.returncode}; traceback={'Traceback' in missing.stderr}")
    except FileNotFoundError as exc:
        return _interface_unreachable_result(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations, check_ids=check_ids, detail=f"CLI artifact or entrypoint missing: {exc}", reason="interface_unreachable:cli_or_output_missing")
    except Exception as exc:
        seen = {item.id for item in observations}
        for check_id in check_ids:
            if check_id not in seen:
                record(check_id, False, f"runtime evaluation failed: {exc}")
    return _finalize_hidden_evaluation(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations)


def _evaluate_invoice_payment_reconciliation(workspace: Path) -> HiddenEvaluationResult:
    task_id = "invoice-payment-reconciliation"
    check_ids = ("reconciliation_rows_and_order", "reconciliation_cutoff_and_duplicates", "reconciliation_status_and_decimals", "reconciliation_unmatched_reporting", "reconciliation_summary_and_validation")
    evaluation_dir = _evaluation_dir(workspace, task_id)
    observations, passed, failed, record = _recorder()
    candidates = ["app/reconcile_invoices.py", "reconcile_invoices.py", "src/app/reconcile_invoices.py"]
    invoice_text = "invoice_id,customer_id,issued_date,due_date,amount\nINV-500,C-5,2034-08-01,2034-08-20,20.00\nINV-200,C-2,2034-07-01,2034-07-31,50.00\nINV-400,C-4,2034-07-02,2034-07-20,10.00\nINV-100,C-1,2034-06-01,2034-06-30,100.00\nINV-300,C-3,2034-08-16,2034-09-01,70.00\n"
    payment_text = "payment_id,invoice_id,payment_date,amount\nPAY-1,INV-100,2034-08-10,33.33\nPAY-2,INV-100,2034-08-15,66.67\nPAY-3,INV-200,2034-08-14,20.00\nPAY-4,INV-400,2034-08-15,12.00\nPAY-5,INV-UNKNOWN,2034-08-11,5.00\nPAY-6,INV-500,2034-08-16,7.00\nPAY-5,INV-500,2034-08-12,3.00\n"
    try:
        with tempfile.TemporaryDirectory(prefix="agentharness-reconcile-eval-") as tmp:
            root = Path(tmp)
            invoices = root / "invoices.csv"
            payments = root / "payments.csv"
            invoices.write_text(invoice_text, encoding="utf-8")
            payments.write_text(payment_text, encoding="utf-8")
            output = root / "out"
            completed = _run_python_entrypoint(workspace, candidates, ["--invoices", str(invoices), "--payments", str(payments), "--as-of", "2034-08-15", "--out-dir", str(output)], env={"PYTHONHASHSEED": "21", "TZ": "UTC"})
            if completed.returncode != 0:
                raise RuntimeError(f"CLI failed: exit={completed.returncode}; stderr={completed.stderr.strip()}")
            reconciliation = _read_csv(output / "reconciliation.csv")
            unmatched = _read_csv(output / "unmatched_payments.csv")
            summary = _read_json(output / "summary.json")
            row_ids = [row.get("invoice_id") for row in reconciliation]
            record(check_ids[0], row_ids == ["INV-100", "INV-200", "INV-400", "INV-500"], f"invoice_ids={row_ids}")
            by_id = {row.get("invoice_id"): row for row in reconciliation}
            cutoff_ok = by_id.get("INV-500", {}).get("paid_amount") == "0.00" and isinstance(summary, dict) and summary.get("duplicate_payment_count") == 1
            record(check_ids[1], cutoff_ok, f"inv500={by_id.get('INV-500')}; unmatched_ids={[row.get('payment_id') for row in unmatched]}")
            expected_rows = {
                "INV-100": ("100.00", "0.00", "PAID"),
                "INV-200": ("20.00", "30.00", "PARTIAL"),
                "INV-400": ("12.00", "-2.00", "OVERPAID"),
                "INV-500": ("0.00", "20.00", "OPEN"),
            }
            decimal_ok = all((by_id.get(key, {}).get("paid_amount"), by_id.get(key, {}).get("balance"), by_id.get(key, {}).get("status")) == expected for key, expected in expected_rows.items())
            record(check_ids[2], decimal_ok, f"rows={by_id}")
            unmatched_expected = [("PAY-5", "unknown_invoice"), ("PAY-5", "duplicate_payment_id")]
            unmatched_actual = [(row.get("payment_id"), row.get("reason")) for row in unmatched]
            record(check_ids[3], unmatched_actual == unmatched_expected, f"unmatched={unmatched_actual}")
            expected_summary = {"as_of": "2034-08-15", "invoice_count": 4, "open_count": 1, "partial_count": 1, "paid_count": 1, "overpaid_count": 1, "total_invoice_amount": "180.00", "total_paid_amount": "132.00", "total_balance": "48.00", "unmatched_payment_count": 2, "duplicate_payment_count": 1}
            summary_ok = isinstance(summary, dict) and all(summary.get(k) == v for k, v in expected_summary.items())
            bad_invoices = root / "bad-invoices.csv"
            bad_invoices.write_text("invoice_id,customer_id,issued_date,due_date,amount\nDUP,C-1,2034-01-01,2034-01-02,1.00\nDUP,C-2,2034-01-01,2034-01-02,2.00\n", encoding="utf-8")
            bad_out = root / "bad-out"
            invalid = _run_python_entrypoint(workspace, candidates, ["--invoices", str(bad_invoices), "--payments", str(payments), "--as-of", "2034-08-15", "--out-dir", str(bad_out)], env={"PYTHONHASHSEED": "84", "TZ": "UTC"})
            no_partial = not bad_out.exists() or not any(bad_out.iterdir())
            record(check_ids[4], bool(summary_ok and invalid.returncode != 0 and "Traceback" not in invalid.stderr and no_partial), f"summary={summary}; invalid_exit={invalid.returncode}; traceback={'Traceback' in invalid.stderr}; no_partial={no_partial}")
    except FileNotFoundError as exc:
        return _interface_unreachable_result(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations, check_ids=check_ids, detail=f"CLI artifact or entrypoint missing: {exc}", reason="interface_unreachable:cli_or_output_missing")
    except Exception as exc:
        seen = {item.id for item in observations}
        for check_id in check_ids:
            if check_id not in seen:
                record(check_id, False, f"runtime evaluation failed: {exc}")
    return _finalize_hidden_evaluation(task_id=task_id, evaluation_dir=evaluation_dir, passed_checks=passed, failed_checks=failed, observations=observations)
