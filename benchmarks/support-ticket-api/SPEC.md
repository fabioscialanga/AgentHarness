# Support Ticket API Benchmark Spec

## Purpose
This benchmark is designed to test whether AgentHarness produces a materially better engineering outcome than a no-framework baseline when both start from the same product intent.

The goal is not to prove that the framework writes more code.
The goal is to test whether the framework improves:
- clarity
- consistency
- adherence to constraints
- verification discipline
- reviewability

## Project brief
Build a small backend service for handling internal support tickets.

The service should be realistic enough to expose ambiguity, validation, testing, and workflow quality, but small enough to complete in a focused implementation session.

## Product context
A company needs a lightweight internal API to track support tickets opened by employees for operational issues.

Examples:
- laptop setup requests
- VPN access issues
- account access problems
- broken internal tooling

The first version is for internal use only.
No frontend is required.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional requirements
The API must support the following.

### 1. Create a ticket
Create a new support ticket with:
- title
- description
- requester_email
- category
- priority

Rules:
- title is required
- description is required
- requester_email must be validated
- category must be one of: hardware, software, access, network, other
- priority must be one of: low, medium, high, urgent
- initial status is always `open`

### 2. List tickets
Return a list of tickets.

Supported filters:
- status
- priority
- category

Sorting:
- newest first by default

### 3. Get a ticket by ID
Return the ticket plus its comments.

### 4. Update ticket status and assignee
Support partial updates for:
- status
- assignee

Allowed statuses:
- open
- in_progress
- resolved
- closed

Rules:
- closed tickets cannot be moved back to open
- assignee is optional
- if status becomes resolved or closed, record an `updated_at` change

### 5. Add a comment to a ticket
A ticket can have multiple comments.
Each comment must include:
- author
- body

Rules:
- empty comments are not allowed
- comments must be returned with the ticket detail endpoint

## Non-functional requirements
The implementation must include:
- input validation
- clear error responses
- structured logging for create/update operations
- environment-based configuration
- database initialization instructions
- automated tests

## Security and quality constraints
The implementation must:
- avoid hardcoded secrets
- validate input data explicitly
- avoid unsafe raw SQL
- keep the API structure understandable for human review
- include at least one negative-path test for invalid input
- include at least one test for business-rule enforcement

## Deliverables
A valid submission should contain:
- runnable FastAPI application
- data models
- persistence layer
- API routes
- tests
- README with run instructions
- dependency file (`pyproject.toml` or `requirements.txt`)

## Out of scope
Do not include:
- authentication/authorization beyond simple placeholders if needed
- background workers
- frontend UI
- file uploads
- email sending
- Docker unless the implementation chooses to add it without harming focus

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
- `POST /tickets` accepts JSON with `title`, `description`, `requester_email`, `category`, and `priority`.
- `GET /tickets` supports query parameters `status`, `priority`, and `category`.
- `GET /tickets/{ticket_id}` returns one ticket and its comments.
- `PATCH /tickets/{ticket_id}` accepts partial JSON updates for `status` and `assignee`.
- `POST /tickets/{ticket_id}/comments` accepts JSON with `author` and `body`.

### Packaging contract
- The project manifest must declare the dependencies needed to run the application and tests in the grading environment, including FastAPI, Pydantic, SQLAlchemy, and pytest.
- Accepted manifests are `pyproject.toml` or `requirements.txt` at the workspace root.
- The manifest must include every runtime and test dependency needed for a clean install in the grading environment. Do not rely on undeclared transitive dependencies or globally installed packages.

## Acceptance criteria
A strong result should satisfy the following:
- the app runs locally
- the API contract matches the spec
- tests run successfully
- the codebase is easy to inspect
- business rules are enforced
- validation failures are handled cleanly

## Benchmark question
After implementing this exact spec twice, ask:

"Did AgentHarness produce an outcome that is meaningfully more controlled, consistent, and reviewable than the no-framework baseline?"
