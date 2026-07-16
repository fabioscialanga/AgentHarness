# Invoice Payment Reconciliation Benchmark Spec

## Purpose
Measure exact decimal reconciliation, cutoff semantics, one-to-many matching, duplicate handling, and internally consistent financial outputs.

## Project brief
Build a CLI that reconciles invoice and payment CSV files as of a supplied date.

## Required stack
- Python 3.12
- pytest

## Functional and quality requirements
- Accept --invoices <csv>, --payments <csv>, --as-of <YYYY-MM-DD>, and --out-dir <directory>.
- Invoices use invoice_id, customer_id, issued_date, due_date, and amount. Payments use payment_id, invoice_id, payment_date, and amount.
- Dates are strict calendar dates. IDs are non-empty. Amounts are positive decimals with no more than two fractional digits and must be calculated in integer cents or exact decimal arithmetic.
- Invoice ids are unique; invalid or duplicate invoice rows fail the command without partial outputs.
- Only invoices issued on or before as-of are reported. Payments after as-of are ignored.
- The first valid payment row acquires payment_id. Later duplicates are not applied and are reported as duplicate_payment_id.
- Payments through as-of for unknown invoices are reported as unknown_invoice.
- For every reported invoice calculate paid_amount, balance, and OPEN, PARTIAL, PAID, or OVERPAID status without clamping overpayments.
- Write reconciliation.csv, unmatched_payments.csv, and summary.json with deterministic ordering and two-decimal monetary strings.

## Non-functional requirements
- deterministic behavior
- clear validation errors without tracebacks in normal invalid-input paths
- environment-based configuration where applicable
- automated tests
- README with exact run instructions

## CLI and output contract
- Entrypoint: app/reconcile_invoices.py, reconcile_invoices.py, or src/app/reconcile_invoices.py.
- Arguments: --invoices, --payments, --as-of, and --out-dir.
- reconciliation.csv header: invoice_id,customer_id,invoice_amount,paid_amount,balance,status.
- unmatched_payments.csv header: payment_id,invoice_id,payment_date,amount,reason.
- summary.json reports as_of, invoice/status counts, exact totals, unmatched_payment_count, and duplicate_payment_count.

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
