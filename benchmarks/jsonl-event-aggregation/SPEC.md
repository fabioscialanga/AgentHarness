# JSONL Event Aggregation Benchmark Spec

## Purpose
Measure deterministic streaming-style aggregation, UTC normalization, validation, duplicate semantics, and auditable rejection output.

## Project brief
Build a CLI that aggregates JSONL events by UTC date and event type while preserving a deterministic rejection trail.

## Required stack
- Python 3.12
- pytest

## Functional and quality requirements
- Accept --input <events.jsonl> and --out-dir <directory>.
- Each valid JSON object has non-empty event_id, actor_id, event_type, an RFC 3339 occurred_at with explicit offset or Z, and a non-negative integer value; booleans are not valid integers.
- Group accepted events by UTC calendar date and exact event_type.
- For each group report event_count, unique_actor_count, and value_total.
- event_id is unique across the input. The first valid record acquires the id; an invalid record does not acquire it; later valid duplicates are rejected.
- Reject blank lines, malformed JSON, non-object JSON, missing required fields, invalid fields, and duplicate ids with a stable reason.
- Write aggregates.json and rejected.jsonl under --out-dir.
- Order groups by date then event_type and preserve input order for rejected records.
- Repeated execution on identical input must produce byte-identical outputs.

## Non-functional requirements
- deterministic behavior
- clear validation errors without tracebacks in normal invalid-input paths
- environment-based configuration where applicable
- automated tests
- README with exact run instructions

## CLI and output contract
- Entrypoint: app/aggregate_events.py, aggregate_events.py, or src/app/aggregate_events.py.
- Arguments: --input and --out-dir.
- aggregates.json contains groups plus summary with accepted_count, rejected_count, duplicate_count, group_count, and value_total.
- Each rejected.jsonl record contains one-based line_number, event_id or null, and reason.

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
