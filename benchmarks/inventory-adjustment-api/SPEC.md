# Inventory Adjustment API Benchmark Spec

## Purpose
Measure whether the agent can implement inventory business rules that are easy to violate subtly, while still producing reviewable run artifacts.

## Project brief
Build an internal inventory API for stock adjustments, reservations, and release flows.

## Product context
Operations teams need a lightweight service to track item stock, manual adjustments, and temporary reservations for internal orders. The system is not customer-facing, but inventory correctness matters because mistakes create downstream fulfillment noise.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional requirements
### 1. Create and list inventory items
- Each item includes sku, name, on_hand, and reserved quantities.
- Listing supports filtering by sku and low-stock status.

### 2. Post an inventory adjustment
- Support adjustment reasons: receive, damage, recount.
- Receive and damage change inventory by a delta using the request field `quantity`.
- Recount sets on_hand to an explicit counted quantity and must record the reason.
- For recount, the request body must use `counted_quantity` rather than `quantity`.
- Common pitfall to avoid: do not overload `quantity` for recount, and do not treat recount as a delta update.


### 3. Reserve stock
- Reserve quantity for an order_id against a sku.
- Available stock is on_hand minus reserved.

### 4. Release reserved stock
- Release some or all reserved quantity for an order_id.
- A release must not exceed the currently reserved quantity.

### 5. Item detail and history
- Return the item plus adjustment and reservation history.
- Newest history entries appear first.

## Non-functional requirements
- input validation
- clear error responses
- database initialization instructions
- environment-based configuration
- automated tests

## Security and quality constraints
- never allow on_hand below zero
- never allow reserved above available inventory
- avoid unsafe raw SQL
- include at least one negative-path test for over-reservation
- keep the API structure easy to review

## Deliverables
- runnable FastAPI application
- data models
- routes and persistence layer
- tests
- README with run instructions
- pyproject.toml

## Out of scope
- authentication
- warehouse UI
- background workers
- batch CSV imports

## Interface contract evaluated by the grader
The hidden evaluator invokes the deliverable through the following interface contract.

### Application loading contract
- The workspace must contain a Python module that defines a FastAPI application.
- The evaluator loads that module from the workspace root or `src/` and looks for a FastAPI object named `app`, `api`, or `application`, or another FastAPI object exposed at module top level.
- Package-relative imports used by that module must resolve when the project is loaded from the workspace.

### HTTP contract
- `POST /items` accepts JSON with `sku`, `name`, and `on_hand`.
- `GET /items` supports query parameters `sku` and `low_stock`.
- `GET /items/{sku}` returns one item with adjustment and reservation history.
- `POST /items/{sku}/adjustments` accepts JSON with `reason`, and either a delta-based `quantity` for receive or damage, or a `counted_quantity` field for recount.
  - Example receive/damage body: `{ "reason": "receive", "quantity": 5 }`
  - Example recount body: `{ "reason": "recount", "counted_quantity": 8 }`
- `POST /items/{sku}/reservations` accepts JSON with `order_id` and `quantity`.
- `POST /items/{sku}/reservations/{order_id}/release` accepts JSON with `quantity`.

### Packaging contract
- The project manifest must declare the dependencies needed to run the application and tests in the grading environment, including FastAPI, Pydantic, SQLAlchemy, and pytest.

## Acceptance criteria
- valid reservations succeed when stock is available
- over-reservation is rejected
- damage adjustments cannot drive stock below zero
- recount sets exact counted quantity
- release logic respects reserved quantity