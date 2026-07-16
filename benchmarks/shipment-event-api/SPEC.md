# Shipment Event API Benchmark Spec

## Purpose
Measure implementation of an append-only event log, ordered state projection, idempotency, and terminal-state invariants.

## Project brief
Build an internal shipment-tracking API that projects shipment state from accepted lifecycle events.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional and quality requirements
- Create shipments with a unique tracking_number and carrier.
- List shipments with optional carrier and status filters and return detail by tracking number.
- Append events containing event_id, type, occurred_at, and location.
- Use the public transition sequence picked_up, in_transit, out_for_delivery, delivered from the initial created state.
- Each accepted event must be exactly the next transition and have occurred_at strictly later than the prior accepted event.
- The event history is append-only and returned in chronological acceptance order.
- event_id is unique per shipment. Repeating an identical event is idempotent; reusing the id with different content is a conflict.
- Rejected events must leave both projected state and event history unchanged.
- Delivered is terminal.

## Non-functional requirements
- deterministic behavior
- clear validation errors without tracebacks in normal invalid-input paths
- environment-based configuration where applicable
- automated tests
- README with exact run instructions

## HTTP contract
- POST /shipments accepts tracking_number and carrier.
- GET /shipments supports carrier and status query parameters.
- GET /shipments/{tracking_number} returns the shipment and its events.
- POST /shipments/{tracking_number}/events accepts event_id, type, occurred_at, and location.

## Project structure and packaging contract
- The workspace root must itself be the runnable project; do not require an extra parent directory.
- Put an importable package at the workspace root or under src/, or use one of the explicit single-file entrypoints.
- The grader must invoke the public interface without editing PYTHONPATH, renaming files, or running a custom bootstrap step.
- Declare every runtime and test dependency in pyproject.toml or requirements.txt at the workspace root.

## Deliverables
- implementation
- automated tests
- README.md
- pyproject.toml or requirements.txt

## Out of scope
- frontend UI
- external network integrations
- background orchestration
- deployment infrastructure
