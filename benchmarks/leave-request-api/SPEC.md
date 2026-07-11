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

## Interface contract evaluated by the grader
The hidden evaluator invokes the deliverable through the following interface contract.

### Application loading contract
- The workspace must contain a Python module that defines a FastAPI application.
- The evaluator loads that module from the workspace root or `src/` and looks for a FastAPI object named `app`, `api`, or `application`, or another FastAPI object exposed at module top level.
- Package-relative imports used by that module must resolve when the project is loaded from the workspace.

### Project structure and importability contract
- The repository root submitted to the benchmark must itself be a runnable Python project. Do not require an extra parent directory around the delivered files.
- If the project uses a package layout, place the importable package either directly under the workspace root or under `src/`.
- If the project uses a single-file entry module, place that module at the workspace root.
- The FastAPI object exposed for grading must be importable without editing `PYTHONPATH`, renaming files after submission, or running a custom bootstrap step outside normal Python package loading.
- Keep the module that exposes the FastAPI object and the package modules it imports inside the submitted workspace.

### HTTP contract
- `POST /requests` accepts JSON with `employee_id`, `leave_type`, `start_date`, `end_date`, and `reason`.
- `GET /requests` supports query parameters `employee_id` and `status`.
- `GET /requests/{request_id}` returns one request.
- `POST /requests/{request_id}/review` accepts JSON with `decision`, `reviewer`, and `note`.

### Packaging contract
- The project manifest must declare the dependencies needed to run the application and tests in the grading environment, including FastAPI, Pydantic, SQLAlchemy, and pytest.
- Accepted manifests are `pyproject.toml` or `requirements.txt` at the workspace root.
- The manifest must include every runtime and test dependency needed for a clean install in the grading environment. Do not rely on undeclared transitive dependencies or globally installed packages.

## Acceptance criteria
- valid requests can be created
- overlapping approved leave is rejected
- personal leave duration limit is enforced
- approval writes reviewed_at
- terminal review state cannot be changed again