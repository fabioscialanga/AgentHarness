#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"

TASKS = {
    "appointment-booking-api": {
        "title": "Appointment Booking API",
        "kind": "api",
        "purpose": "Measure implementation of interval scheduling, resource-scoped conflicts, atomic rescheduling, cancellation, and availability.",
        "brief": "Build an internal appointment-booking API for publishing provider slots and managing customer bookings.",
        "requirements": [
            "Create appointments with customer_id, provider_id, starts_at, ends_at, and reason.",
            "List appointments with optional customer_id, provider_id, and status filters, and return one appointment by id.",
            "Reschedule a scheduled appointment and cancel a scheduled appointment with a cancellation reason.",
            "Use RFC 3339 timestamps with an explicit offset or Z and compare them as instants.",
            "Require ends_at to be strictly later than starts_at.",
            "Scheduled appointments for the same provider use half-open intervals [starts_at, ends_at) and must not overlap; adjacent appointments are allowed.",
            "Appointments for different providers may occupy the same interval.",
            "A failed create or reschedule must not partially mutate persisted state.",
            "Cancellation is terminal, releases the interval, and records cancelled_at and cancel_reason.",
        ],
        "http": [
            "POST /appointments accepts customer_id, provider_id, starts_at, ends_at, and reason.",
            "GET /appointments supports customer_id, provider_id, and status query parameters.",
            "GET /appointments/{appointment_id} returns one appointment.",
            "PATCH /appointments/{appointment_id}/reschedule accepts starts_at and ends_at.",
            "POST /appointments/{appointment_id}/cancel accepts reason.",
        ],
        "checks": [
            ("appointment_create_and_filters", "Creation, detail, and combined list filters are coherent."),
            ("appointment_interval_validation", "Invalid intervals are rejected without mutation."),
            ("appointment_provider_conflicts", "Conflict scope and half-open boundary behavior are correct."),
            ("appointment_reschedule_atomic", "Rescheduling enforces conflicts atomically."),
            ("appointment_cancel_releases_slot", "Cancellation is terminal and releases the provider interval."),
        ],
        "forbidden": ["frontend/*", "ui/*", "k8s/*", "helm/*", "terraform/*", ".github/workflows/*", "billing/*"],
    },
    "shipment-event-api": {
        "title": "Shipment Event API",
        "kind": "api",
        "purpose": "Measure implementation of an append-only event log, ordered state projection, idempotency, and terminal-state invariants.",
        "brief": "Build an internal shipment-tracking API that projects shipment state from accepted lifecycle events.",
        "requirements": [
            "Create shipments with a unique tracking_number and carrier.",
            "List shipments with optional carrier and status filters and return detail by tracking number.",
            "Append events containing event_id, type, occurred_at, and location.",
            "Use the public transition sequence picked_up, in_transit, out_for_delivery, delivered from the initial created state.",
            "Each accepted event must be exactly the next transition and have occurred_at strictly later than the prior accepted event.",
            "The event history is append-only and returned in chronological acceptance order.",
            "event_id is unique per shipment. Repeating an identical event is idempotent; reusing the id with different content is a conflict.",
            "Rejected events must leave both projected state and event history unchanged.",
            "Delivered is terminal.",
        ],
        "http": [
            "POST /shipments accepts tracking_number and carrier.",
            "GET /shipments supports carrier and status query parameters.",
            "GET /shipments/{tracking_number} returns the shipment and its events.",
            "POST /shipments/{tracking_number}/events accepts event_id, type, occurred_at, and location.",
        ],
        "checks": [
            ("shipment_create_and_filters", "Creation, empty history, detail, and filters are coherent."),
            ("shipment_valid_transition_path", "The full ordered lifecycle updates state and history correctly."),
            ("shipment_skipped_transition_atomic", "Skipped transitions are rejected without mutation."),
            ("shipment_event_idempotency", "Identical replay is idempotent and conflicting replay is rejected."),
            ("shipment_time_and_terminal_invariants", "Timestamp monotonicity and delivered terminality are enforced."),
        ],
        "forbidden": ["frontend/*", "ui/*", "k8s/*", "helm/*", "terraform/*", ".github/workflows/*", "carrier-integrations/*"],
    },
    "jsonl-event-aggregation": {
        "title": "JSONL Event Aggregation",
        "kind": "cli",
        "purpose": "Measure deterministic streaming-style aggregation, UTC normalization, validation, duplicate semantics, and auditable rejection output.",
        "brief": "Build a CLI that aggregates JSONL events by UTC date and event type while preserving a deterministic rejection trail.",
        "requirements": [
            "Accept --input <events.jsonl> and --out-dir <directory>.",
            "Each valid JSON object has non-empty event_id, actor_id, event_type, an RFC 3339 occurred_at with explicit offset or Z, and a non-negative integer value; booleans are not valid integers.",
            "Group accepted events by UTC calendar date and exact event_type.",
            "For each group report event_count, unique_actor_count, and value_total.",
            "event_id is unique across the input. The first valid record acquires the id; an invalid record does not acquire it; later valid duplicates are rejected.",
            "Reject blank lines, malformed JSON, non-object JSON, missing required fields, invalid fields, and duplicate ids with a stable reason.",
            "Write aggregates.json and rejected.jsonl under --out-dir.",
            "Order groups by date then event_type and preserve input order for rejected records.",
            "Repeated execution on identical input must produce byte-identical outputs.",
        ],
        "cli": [
            "Entrypoint: app/aggregate_events.py, aggregate_events.py, or src/app/aggregate_events.py.",
            "Arguments: --input and --out-dir.",
            "aggregates.json contains groups plus summary with accepted_count, rejected_count, duplicate_count, group_count, and value_total.",
            "Each rejected.jsonl record contains one-based line_number, event_id or null, and reason.",
        ],
        "checks": [
            ("jsonl_grouped_counts", "Grouped counts, unique actors, and totals are correct."),
            ("jsonl_utc_date_normalization", "Offset timestamps are grouped by UTC date."),
            ("jsonl_invalid_and_duplicate_handling", "Invalid and duplicate records use the frozen precedence and first-valid semantics."),
            ("jsonl_summary_consistency", "Summary values reconcile with accepted groups and rejections."),
            ("jsonl_deterministic_outputs", "Required artifacts are byte-stable and missing input fails cleanly."),
        ],
        "forbidden": ["frontend/*", "ui/*", "api/*", "k8s/*", "helm/*", "terraform/*", ".github/workflows/*"],
    },
    "invoice-payment-reconciliation": {
        "title": "Invoice Payment Reconciliation",
        "kind": "cli",
        "purpose": "Measure exact decimal reconciliation, cutoff semantics, one-to-many matching, duplicate handling, and internally consistent financial outputs.",
        "brief": "Build a CLI that reconciles invoice and payment CSV files as of a supplied date.",
        "requirements": [
            "Accept --invoices <csv>, --payments <csv>, --as-of <YYYY-MM-DD>, and --out-dir <directory>.",
            "Invoices use invoice_id, customer_id, issued_date, due_date, and amount. Payments use payment_id, invoice_id, payment_date, and amount.",
            "Dates are strict calendar dates. IDs are non-empty. Amounts are positive decimals with no more than two fractional digits and must be calculated in integer cents or exact decimal arithmetic.",
            "Invoice ids are unique; invalid or duplicate invoice rows fail the command without partial outputs.",
            "Only invoices issued on or before as-of are reported. Payments after as-of are ignored.",
            "The first valid payment row acquires payment_id. Later duplicates are not applied and are reported as duplicate_payment_id.",
            "Payments through as-of for unknown invoices are reported as unknown_invoice.",
            "For every reported invoice calculate paid_amount, balance, and OPEN, PARTIAL, PAID, or OVERPAID status without clamping overpayments.",
            "Write reconciliation.csv, unmatched_payments.csv, and summary.json with deterministic ordering and two-decimal monetary strings.",
        ],
        "cli": [
            "Entrypoint: app/reconcile_invoices.py, reconcile_invoices.py, or src/app/reconcile_invoices.py.",
            "Arguments: --invoices, --payments, --as-of, and --out-dir.",
            "reconciliation.csv header: invoice_id,customer_id,invoice_amount,paid_amount,balance,status.",
            "unmatched_payments.csv header: payment_id,invoice_id,payment_date,amount,reason.",
            "summary.json reports as_of, invoice/status counts, exact totals, unmatched_payment_count, and duplicate_payment_count.",
        ],
        "checks": [
            ("reconciliation_rows_and_order", "Eligible invoice rows are complete and deterministically ordered."),
            ("reconciliation_cutoff_and_duplicates", "As-of cutoff and first-valid payment-id semantics are correct."),
            ("reconciliation_status_and_decimals", "Statuses, overpayments, and exact decimal arithmetic are correct."),
            ("reconciliation_unmatched_reporting", "Unknown and duplicate payments are reported while future payments are ignored."),
            ("reconciliation_summary_and_validation", "Summary reconciles and invalid invoice input fails without partial outputs."),
        ],
        "forbidden": ["frontend/*", "ui/*", "api/*", "k8s/*", "helm/*", "terraform/*", ".github/workflows/*", "bank-integrations/*"],
    },
}

RESULT_SCHEMA = {
    "type": "object",
    "required": ["task_id", "critical_ok", "execution_status", "outcome_status", "classification_reason", "passed_checks", "failed_checks", "observations"],
    "properties": {
        "task_id": {"type": "string"},
        "critical_ok": {"type": "boolean"},
        "execution_status": {"type": "string"},
        "outcome_status": {"type": "string"},
        "classification_reason": {"type": "string"},
        "passed_checks": {"type": "array", "items": {"type": "string"}},
        "failed_checks": {"type": "array", "items": {"type": "string"}},
        "observations": {"type": "array", "items": {"type": "object", "required": ["id", "status", "detail"], "properties": {"id": {"type": "string"}, "status": {"type": "string"}, "detail": {"type": "string"}}, "additionalProperties": False}},
    },
    "additionalProperties": False,
}


def spec_text(task_id: str, cfg: dict) -> str:
    stack = ["- Python 3.12", "- pytest"]
    if cfg["kind"] == "api":
        stack[1:1] = ["- FastAPI", "- SQLite", "- SQLAlchemy"]
    interface_title = "HTTP contract" if cfg["kind"] == "api" else "CLI and output contract"
    interface_lines = cfg.get("http", cfg.get("cli", []))
    return "\n".join([
        f"# {cfg['title']} Benchmark Spec", "", "## Purpose", cfg["purpose"], "", "## Project brief", cfg["brief"], "", "## Required stack", *stack, "", "## Functional and quality requirements", *[f"- {item}" for item in cfg["requirements"]], "", "## Non-functional requirements", "- deterministic behavior", "- clear validation errors without tracebacks in normal invalid-input paths", "- environment-based configuration where applicable", "- automated tests", "- README with exact run instructions", "", f"## {interface_title}", *[f"- {item}" for item in interface_lines], "", "## Project structure and packaging contract", "- The workspace root must itself be the runnable project; do not require an extra parent directory.", "- Put an importable package at the workspace root or under src/, or use one of the explicit single-file entrypoints.", "- The grader must invoke the public interface without editing PYTHONPATH, renaming files, or running a custom bootstrap step.", "- Declare every runtime and test dependency in pyproject.toml or requirements.txt at the workspace root.", "", "## Deliverables", "- implementation", "- automated tests", "- README.md", "- pyproject.toml or requirements.txt", "", "## Out of scope", "- frontend UI", "- external network integrations", "- background orchestration", "- deployment infrastructure", ""])


def claims(task_id: str, cfg: dict) -> dict:
    return {"run_id": "__RUN_ID__", "claims": [
        {"id": "claim_scope_forbidden", "type": "forbidden_paths", "statement": "The run stayed out of clearly forbidden non-task paths.", "expected": {"forbidden_paths": cfg["forbidden"]}},
        {"id": "claim_tests", "type": "tests_executed", "statement": "The required automated test suite was executed.", "expected": {"required_commands": ["pytest -q"]}},
        {"id": "claim_readme", "type": "artifact_present", "statement": "A README with run instructions was produced.", "expected": {"required_outputs": ["README.md"]}},
        {"id": "claim_manifest", "type": "artifact_present", "statement": "A dependency manifest was produced.", "expected": {"required_outputs": ["pyproject.toml"]}},
    ]}


def suite(task_id: str, cfg: dict) -> dict:
    summary = f".agentharness/evaluation/{task_id}/summary.txt"
    result = f".agentharness/evaluation/{task_id}/result.json"
    cases = []
    for check_id, description in cfg["checks"]:
        cases.append({"id": check_id, "type": "text_contains", "path": summary, "description": description, "expected": {"contains": [f"{check_id}=pass"], "forbidden": [f"{check_id}=fail", "Traceback"]}})
    cases.append({"id": "evaluation_result_schema", "type": "json_schema", "path": result, "description": "The hidden evaluator emits the frozen result envelope.", "expected": {"schema": RESULT_SCHEMA}})
    return {"suite_id": f"{task_id}_heldout_eval", "run_id": "__RUN_ID__", "cases": cases}


def quality_text(task_id: str, cfg: dict) -> str:
    rows = "\n".join(f"| {check_id} | {description} |" for check_id, description in cfg["checks"])
    disjoint = "\n".join(f"| {check_id} | Process claims do not certify this business behavior. |" for check_id, _ in cfg["checks"])
    return f"""# Quality gate for {task_id}

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

Claims are process-only: forbidden scope, test execution, README presence, and manifest presence. They do not certify functional correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
{rows}

The sixth case validates only the stable result envelope. The campaign endpoint remains the frozen six-case score.

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
{disjoint}

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during an agent run.
2. Keep this file, the held-out suite, evaluator code, fixtures, references, mutants, and expected outputs outside the visible workspace.
3. Create `.agentharness/evaluation/{task_id}/` only after the agent run completes.
4. Reject visible bundles containing held-out case ids, pass/fail markers, fixture literals, prior run artifacts, or sibling solutions.
5. Validate semantic rather than merely lexical disjunction.
"""


def main() -> int:
    written = []
    for task_id, cfg in TASKS.items():
        root = BENCHMARKS / task_id
        root.mkdir(parents=True, exist_ok=True)
        files = {
            "SPEC.md": spec_text(task_id, cfg),
            "CLAIMS_CONTRACT.template.json": json.dumps(claims(task_id, cfg), indent=2) + "\n",
            "HELDOUT_EVALUATION_SUITE.template.json": json.dumps(suite(task_id, cfg), indent=2) + "\n",
            "QUALITY_GATE.md": quality_text(task_id, cfg),
        }
        for name, content in files.items():
            path = root / name
            path.write_text(content, encoding="utf-8")
            written.append(str(path.relative_to(REPO_ROOT)))
    print(json.dumps({"ok": True, "tasks": sorted(TASKS), "files": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
