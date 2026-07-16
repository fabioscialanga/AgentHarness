# Appointment Booking API Benchmark Spec

## Purpose
Measure implementation of interval scheduling, resource-scoped conflicts, atomic rescheduling, cancellation, and availability.

## Project brief
Build an internal appointment-booking API for publishing provider slots and managing customer bookings.

## Required stack
- Python 3.12
- FastAPI
- SQLite
- SQLAlchemy
- pytest

## Functional and quality requirements
- Create appointments with customer_id, provider_id, starts_at, ends_at, and reason.
- List appointments with optional customer_id, provider_id, and status filters, and return one appointment by id.
- Reschedule a scheduled appointment and cancel a scheduled appointment with a cancellation reason.
- Use RFC 3339 timestamps with an explicit offset or Z and compare them as instants.
- Require ends_at to be strictly later than starts_at.
- Scheduled appointments for the same provider use half-open intervals [starts_at, ends_at) and must not overlap; adjacent appointments are allowed.
- Appointments for different providers may occupy the same interval.
- A failed create or reschedule must not partially mutate persisted state.
- Cancellation is terminal, releases the interval, and records cancelled_at and cancel_reason.

## Non-functional requirements
- deterministic behavior
- clear validation errors without tracebacks in normal invalid-input paths
- environment-based configuration where applicable
- automated tests
- README with exact run instructions

## HTTP contract
- POST /appointments accepts customer_id, provider_id, starts_at, ends_at, and reason.
- GET /appointments supports customer_id, provider_id, and status query parameters.
- GET /appointments/{appointment_id} returns one appointment.
- PATCH /appointments/{appointment_id}/reschedule accepts starts_at and ends_at.
- POST /appointments/{appointment_id}/cancel accepts reason.

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
