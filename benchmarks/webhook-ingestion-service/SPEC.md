# Webhook Ingestion Service Benchmark Spec

## Purpose
Measure whether the agent can implement a compact event-ingestion service with signature checking, idempotency, and normalization rules.

## Project brief
Build a service that receives partner webhooks, verifies signatures, stores normalized events, and exposes lookup endpoints.

## Product context
An internal integrations team receives webhooks from an external partner. The service must preserve raw payloads for audit, reject forged traffic, and collapse repeated deliveries without duplicating side effects.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional requirements
### 1. Receive webhook events
- Accept POST requests containing event_id, source, occurred_at, type, and payload.
- Require an HMAC signature header.

### 2. Persist normalized events
- Store the raw payload and a normalized_status field.
- Map partner event types into canonical statuses: created, updated, cancelled.

### 3. Handle duplicate delivery
- Repeated deliveries of the same event_id must be idempotent.
- A duplicate must not create a second stored event.

### 4. Read APIs
- Provide lookup by event_id.
- Provide list filtering by normalized_status and source.

## Non-functional requirements
- input validation
- clear signature-failure responses
- automated tests
- README with local run instructions

## Security and quality constraints
- invalid signatures must be rejected
- missing required fields must be rejected
- raw payloads must remain reviewable for audit
- avoid unsafe raw SQL
- include tests for duplicate delivery and invalid signatures

## Deliverables
- runnable FastAPI application
- storage layer
- tests
- README
- pyproject.toml

## Out of scope
- async message brokers
- retry queues
- frontend dashboards
- multi-tenant auth

## Interface contract evaluated by the grader
The hidden evaluator invokes the deliverable through the following interface contract.

### Application loading contract
- The workspace must contain a Python module that defines a FastAPI application.
- The evaluator loads that module from the workspace root or `src/` and looks for a FastAPI object named `app`, `api`, or `application`, or another FastAPI object exposed at module top level.
- Package-relative imports used by that module must resolve when the project is loaded from the workspace.

### HTTP contract
- `POST /webhooks` accepts a JSON request body containing `event_id`, `source`, `occurred_at`, `type`, and `payload`.
- Signed webhook requests use the `X-Signature` header carrying the HMAC SHA-256 hex digest of the raw JSON body.
- `GET /events/{event_id}` returns one stored event.
- `GET /events` supports query parameters `normalized_status` and `source`.
- The stored event payload returned by the API must expose an event identifier and normalized status in JSON.

### Runtime configuration contract
- The application must honor the `WEBHOOK_SECRET` environment variable for signature verification.

### Packaging contract
- The project manifest must declare the dependencies needed to run the application and tests in the grading environment, including FastAPI, Pydantic, SQLAlchemy, and pytest.

## Acceptance criteria
- valid signed events are stored
- invalid signatures are rejected
- duplicate event_id is idempotent
- canonical status mapping is correct
- filtering works on normalized fields