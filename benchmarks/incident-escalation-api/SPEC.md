# Incident Escalation API Benchmark Spec

## Purpose
Measure whether the agent can implement time-based escalation rules that are easy to mishandle in edge cases.

## Project brief
Build an incident API with acknowledgement, resolution, and computed escalation status.

## Product context
An internal operations team needs a tiny incident tracker to reason about whether an incident should be escalated. The tricky part is not CRUD but computing status correctly as time passes.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional requirements
### 1. Create incidents
- Each incident includes service, severity, opened_at, and summary.
- Allowed severities: sev1, sev2, sev3.

### 2. Acknowledge incidents
- Store responder and acknowledged_at.

### 3. Resolve incidents
- Store resolution note and resolved_at.

### 4. Compute escalation status
- Expose an endpoint that returns the escalation status as of a caller-provided timestamp.
- Return whether the incident is escalated and why.

## Non-functional requirements
- input validation
- clear error responses
- automated tests

## Security and quality constraints
- sev1 escalates after 15 minutes if unacknowledged
- sev2 escalates after 60 minutes if unacknowledged
- sev3 never auto-escalates
- acknowledgement stops auto-escalation
- resolved incidents never escalate

## Deliverables
- runnable FastAPI app
- tests
- README
- pyproject.toml

## Out of scope
- paging integrations
- chat notifications
- frontend dashboards

## Acceptance criteria
- sev1 escalation timing is correct
- acknowledgement stops escalation
- resolved incidents never escalate
- sev3 incidents do not auto-escalate
- invalid as_of inputs are rejected