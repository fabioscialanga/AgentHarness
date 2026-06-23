# Leave Request API Benchmark Spec

## Purpose
Measure whether the agent can implement a compact approval workflow with overlap checks and terminal-state rules.

## Project brief
Build an internal leave-request API with submission, review, and listing endpoints.

## Product context
HR operations need a small internal service for employee leave requests. The service must stay simple, but approval rules must be enforced because mistakes affect staffing coverage.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional requirements
### 1. Submit a leave request
- Each request includes employee_id, leave_type, start_date, end_date, and reason.
- Allowed leave_type values: vacation, sick, personal.

### 2. List and detail endpoints
- List requests by employee_id and status.
- Return a detail view for one request.

### 3. Review endpoint
- Allow a reviewer to approve or reject a request.
- Capture reviewer name and review note.
- Store reviewed_at when a decision is made.

## Non-functional requirements
- input validation
- clear error responses
- environment-based configuration
- automated tests

## Security and quality constraints
- start_date must not be after end_date
- approved leave for the same employee cannot overlap
- personal leave must not exceed 3 days
- approved or rejected requests are terminal for review

## Deliverables
- runnable FastAPI app
- tests
- README
- pyproject.toml

## Out of scope
- holiday calendars
- balance accrual calculations
- email notifications
- frontend UI

## Acceptance criteria
- valid requests can be created
- overlapping approved leave is rejected
- personal leave duration limit is enforced
- approval writes reviewed_at
- terminal review state cannot be changed again