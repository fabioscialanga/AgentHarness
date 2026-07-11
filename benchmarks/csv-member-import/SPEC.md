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

## Interface contract evaluated by the grader
The hidden evaluator invokes the deliverable through the following interface contract.

### CLI contract
- The workspace must expose one of these Python entrypoints: `app/import_members.py`, `import_members.py`, or `src/app/import_members.py`.
- The evaluator first invokes the entrypoint as a Python module, then falls back to `python <entrypoint.py>` if needed.
- The CLI must accept these arguments exactly:
  - `--input <path_to_csv>`
  - `--out-dir <path_to_output_directory>`

### Project structure and CLI importability contract
- The repository root submitted to the benchmark must itself be a runnable Python project. Do not require an extra parent directory around the delivered files.
- If the CLI is implemented as a package module, place the importable package either directly under the workspace root or under `src/`.
- If the CLI is implemented as a single script, place that script at the workspace root or at one of the explicit entrypoint paths listed above.
- The grading environment must be able to invoke the CLI from the submitted workspace without editing `PYTHONPATH`, renaming files after submission, or running a custom bootstrap step outside normal Python package loading.
- Keep the entrypoint module and the modules it imports inside the submitted workspace.

### Output artifact contract
- The CLI must write these files inside the directory passed to `--out-dir`:
  - `accepted.json`
  - `rejected.csv`
  - `summary.json`

### Packaging contract
- The project manifest must declare the dependencies needed to run the implementation and tests in the grading environment, including pytest.
- Accepted manifests are `pyproject.toml` or `requirements.txt` at the workspace root.
- The manifest must include every runtime and test dependency needed for a clean install in the grading environment. Do not rely on undeclared transitive dependencies or globally installed packages.

## Acceptance criteria
- valid rows are normalized
- duplicates are handled correctly
- invalid rows are rejected with explicit reasons
- summary counts are accurate
- all expected output files are written