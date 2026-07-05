# Refund Approval API Benchmark Spec

## Purpose
Measure whether the agent can implement a threshold-based approval flow with staged authorization rules.

## Project brief
Build an internal refund-request API with automatic, manager, and finance approval paths based on amount.

## Product context
Support agents submit refund requests, but approval thresholds differ by amount. The service must enforce the progression cleanly because silent mistakes become real money errors.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional requirements
### 1. Create a refund request
- Each request includes order_id, amount, currency, reason, and requested_by.

### 2. List and detail endpoints
- List by status and requester.
- Return the current approval state for one request.

### 3. Manager review endpoint
- Allow manager approval or rejection.
- Capture reviewer and note.

### 4. Finance approval endpoint
- Allow finance approval only when the request already passed manager review and the amount requires finance approval.

## Non-functional requirements
- input validation
- clear error responses
- automated tests

## Security and quality constraints
- amount must be greater than zero
- amounts up to 50 auto-approve on create
- amounts above 50 and up to 500 require manager approval
- amounts above 500 require manager approval and then finance approval
- terminal states cannot transition again

## Deliverables
- runnable FastAPI app
- tests
- README
- pyproject.toml

## Out of scope
- actual payment gateway calls
- chargeback workflows
- email notifications

## Interface contract evaluated by the grader
The hidden evaluator invokes the deliverable through the following interface contract.

### Application loading contract
- The workspace must contain a Python module that defines a FastAPI application.
- The evaluator loads that module from the workspace root or `src/` and looks for a FastAPI object named `app`, `api`, or `application`, or another FastAPI object exposed at module top level.
- Package-relative imports used by that module must resolve when the project is loaded from the workspace.

### HTTP contract
- `POST /refunds` accepts JSON with `order_id`, `amount`, `currency`, `reason`, and `requested_by`.
- `GET /refunds` supports query parameters `status` and `requested_by`.
- `GET /refunds/{refund_id}` returns one refund request.
- `POST /refunds/{refund_id}/manager-review` accepts JSON with `decision`, `reviewer`, and `note`.
- `POST /refunds/{refund_id}/finance-review` accepts JSON with `decision`, `reviewer`, and `note`.

### Packaging contract
- The project manifest must declare the dependencies needed to run the application and tests in the grading environment, including FastAPI, Pydantic, SQLAlchemy, and pytest.

## Acceptance criteria
- small refunds auto-approve
- medium refunds stay pending manager review until approved
- large refunds need finance after manager approval
- invalid amount is rejected
- terminal requests cannot be re-approved