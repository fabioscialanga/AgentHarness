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
- The export date field may be named `export_date` or `date`.
- The total fields may use either concise keys (`total_gross`, `total_refunds`, `total_net`) or descriptive keys (`total_gross_payout`, `total_refund_total`, `total_net_payout`).

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

## Interface contract evaluated by the grader
The hidden evaluator invokes the deliverable through the following interface contract.

### CLI contract
- The workspace must expose one of these Python entrypoints: `app/export.py`, `export.py`, or `src/app/export.py`.
- The evaluator first invokes the entrypoint as a Python module, then falls back to `python <entrypoint.py>` if needed.
- The CLI must accept these arguments exactly:
  - `--date <YYYY-MM-DD>`
  - `--out-dir <path_to_output_directory>`

### Project structure and CLI importability contract
- The repository root submitted to the benchmark must itself be a runnable Python project. Do not require an extra parent directory around the delivered files.
- If the CLI is implemented as a package module, place the importable package either directly under the workspace root or under `src/`.
- If the CLI is implemented as a single script, place that script at the workspace root or at one of the explicit entrypoint paths listed above.
- The grading environment must be able to invoke the CLI from the submitted workspace without editing `PYTHONPATH`, renaming files after submission, or running a custom bootstrap step outside normal Python package loading.
- Keep the entrypoint module and the modules it imports inside the submitted workspace.

### Runtime configuration contract
- The export job must read the SQLite database path from the `REPORT_DB_PATH` environment variable.

### Output artifact contract
- The CLI must write these files inside the directory passed to `--out-dir`:
  - `report.csv`
  - `summary.json`

### Packaging contract
- The project manifest must declare the dependencies needed to run the implementation and tests in the grading environment, including pytest.
- Accepted manifests are `pyproject.toml` or `requirements.txt` at the workspace root.
- The manifest must include every runtime and test dependency needed for a clean install in the grading environment. Do not rely on undeclared transitive dependencies or globally installed packages.

## Acceptance criteria
- CSV rows are complete and sorted
- summary totals match the CSV
- date filtering is correct
- invalid date input is rejected cleanly