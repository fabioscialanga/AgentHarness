# CSV Member Import Benchmark Spec

## Purpose
Measure whether the agent can implement a deterministic import utility where correctness depends on normalization, duplicate handling, and rejection reporting.

## Project brief
Build a CLI utility that imports members from CSV and writes accepted, rejected, and summary outputs.

## Product context
Operations staff receive manual member CSVs from different sources. The import utility must normalize data, reject bad rows clearly, and produce auditable outputs for accepted and rejected entries.

## Required stack
- Python 3.12
- pytest

## Functional requirements
### 1. Command-line entrypoint
- Expose a CLI such as `python -m app.import_members --input members.csv --out-dir <path>`.

### 2. Accepted output
- Write accepted.json containing normalized accepted rows.
- Normalize email to lowercase and trim surrounding whitespace.

### 3. Rejected output
- Write rejected.csv with the original row and a rejection reason.

### 4. Summary output
- Write summary.json with accepted_count, rejected_count, duplicate_count, and processed_count.

## Non-functional requirements
- automated tests
- clear CLI usage in README
- deterministic output ordering

## Security and quality constraints
- required columns are name, email, role
- allowed roles are admin, member, viewer
- duplicate emails are case-insensitive and keep the first valid row only
- invalid email rows are rejected with a reason

## Deliverables
- CLI implementation
- tests
- README
- pyproject.toml

## Out of scope
- REST API
- database persistence
- background workers
- GUI upload flow

## Acceptance criteria
- valid rows are normalized
- duplicates are handled correctly
- invalid rows are rejected with explicit reasons
- summary counts are accurate
- all expected output files are written