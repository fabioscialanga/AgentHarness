# Offline grading environment

This directory freezes the benchmark hidden-grading runtime used by `agentharness benchmark-evaluate-task`.

Contents:
- `allowed-top-level.in`: top-level dependency seed used to rebuild the offline wheelhouse.
- `constraints-py312.txt`: exact pinned dependency set for Python 3.12.
- `wheelhouse/`: offline wheel artifacts used during isolated grading.
- `wheelhouse-manifest.json`: filename + SHA256 manifest for the wheelhouse.
- `build_wheelhouse.py`: rebuild helper for the freeze artifacts.
- `wheelhouse_gate.py`: stdlib-only offline completeness gate for manifest integrity, root install, and runtime probes.
- `solution_grader_smoke.py`: helper that renders a held-out suite, runs `benchmark-evaluate-task`, then runs `evaluate` for one workspace.
- `STAGE_A_READINESS.md`: recorded Stage A readiness results and dependency decisions.

Environment overrides supported by the grader:
- `AGENTHARNESS_GRADING_ENV_DIR`
- `AGENTHARNESS_WHEELHOUSE_DIR`
- `AGENTHARNESS_CONSTRAINTS_FILE`
- `AGENTHARNESS_WHEELHOUSE_MANIFEST`

Policy:
- The wheelhouse is the only admission gate for solution dependencies.
- A solution manifest is required, but the grader does not enforce a task-specific hardcoded dependency allowlist.
- A dependency that installs offline from the wheelhouse is admitted and evaluated.
- A dependency that cannot be resolved offline from the wheelhouse is classified as `real_failure` for that solution.
- The wheelhouse seed includes `uvicorn` as a general in-spec support package for runnable FastAPI services.
- The wheelhouse seed constrains `pytest` to `<9.0` so common benchmark solution manifests that declare `pytest>=8,<9` still install offline.
- `uvicorn[standard]` is not included in the frozen wheelhouse. Solutions should declare plain `uvicorn` unless the wheelhouse is explicitly extended.
- The offline grading root also bundles `email-validator`, `dnspython`, and `sniffio` so legitimate `pydantic.EmailStr` and async or import paths work offline.

Known frozen limitation:
- The current Starlette and httpx pins emit a deprecation warning about `httpx2` during TestClient usage. This warning is expected and intentionally not addressed before the benchmark campaign.

Rebuild procedure from a clean environment:
1. Create a fresh venv outside the repository state you use for development.
2. Run `python benchmarks/grading-env/build_wheelhouse.py` from that fresh venv.
3. Run the root gate:
   `python benchmarks/grading-env/wheelhouse_gate.py --wheelhouse benchmarks/grading-env/wheelhouse --constraints benchmarks/grading-env/constraints-py312.txt --manifest benchmarks/grading-env/wheelhouse-manifest.json`
4. Run solution-level gates with `--solution` plus `solution_grader_smoke.py`.

Example solution-level gate:
`python benchmarks/grading-env/wheelhouse_gate.py --wheelhouse benchmarks/grading-env/wheelhouse --constraints benchmarks/grading-env/constraints-py312.txt --manifest benchmarks/grading-env/wheelhouse-manifest.json --solution support-ticket-api=/abs/path/to/workspace --grader-cmd "{python} benchmarks/grading-env/solution_grader_smoke.py --task-id support-ticket-api --workspace {solution}"`
