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
- Receive and damage change inventory by a delta.
- Recount sets on_hand to an explicit counted quantity and must record the reason.

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

## Acceptance criteria
- valid reservations succeed when stock is available
- over-reservation is rejected
- damage adjustments cannot drive stock below zero
- recount sets exact counted quantity
- release logic respects reserved quantity