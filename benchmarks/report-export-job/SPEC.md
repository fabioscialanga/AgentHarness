# Report Export Job Benchmark Spec

## Purpose
Measure whether the agent can build a deterministic export job where business correctness lives in totals, filters, and output formatting rather than HTTP scaffolding.

## Project brief
Build a CLI job that exports a daily merchant payout reconciliation report from SQLite data into CSV and JSON outputs.

## Product context
Operations analysts need a lightweight daily export that reconciles payouts and refunds per merchant for a single date. The job must be deterministic because downstream spreadsheets depend on exact totals and row ordering.

## Required stack
- Python 3.12
- SQLite
- pytest

## Functional requirements
### 1. Command-line entrypoint
- Expose a CLI such as `python -m app.export --date YYYY-MM-DD --out-dir <path>`.
- Reject invalid date formats clearly.

### 2. Daily filter
- Use only records for the requested date.
- Ignore rows from other dates.

### 3. CSV export
- Produce one row per merchant.
- Include merchant_id, gross_payout, refund_total, net_payout, and transaction_count.
- Sort rows by merchant_id ascending.

### 4. JSON summary
- Write a summary.json containing the export date and aggregate totals.
- Include merchant count and total gross, refunds, and net values.

## Non-functional requirements
- clear CLI usage in README
- automated tests
- deterministic output formatting

## Security and quality constraints
- the same input must produce byte-stable output ordering
- refunds must reduce net payout correctly
- the job must not require network access
- include at least one negative-path test for invalid date input

## Deliverables
- CLI implementation
- tests
- README
- pyproject.toml

## Out of scope
- REST API
- background scheduler
- cloud storage uploads
- spreadsheet UI

## Acceptance criteria
- CSV rows are complete and sorted
- summary totals match the CSV
- date filtering is correct
- invalid date input is rejected cleanly