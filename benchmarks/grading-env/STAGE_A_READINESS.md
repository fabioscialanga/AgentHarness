# Stage A readiness record

Status: complete on the current repository state.

## 1. Solution-level gate

The offline gate was executed with `wheelhouse_gate.py --solution` plus `solution_grader_smoke.py`, which renders the held-out suite, runs `benchmark-evaluate-task`, then runs `evaluate`.

Checked workspaces:
- `support-ticket-api`, reference FastAPI solution
- `support-ticket-emailstr`, in-spec variant that uses `pydantic.EmailStr` and declares `email-validator`
- `inventory-adjustment-api`, reference FastAPI solution
- `csv-member-import`, reference CLI solution

Recorded outputs:
- `stage-a-solution-gate-report.json`
- `stage-a-clean-rebuild-report.json`

Observed result:
- all four workspaces installed offline from their own manifest
- all four workspaces installed the grader offline
- all four workspaces passed hidden grading and held-out evaluation

Important fix discovered by this gate:
- solution-level grading from an installed `agentharness` wheel originally failed because the hidden evaluator only loaded the version from the repository `pyproject.toml`
- the grader now falls back to installed package metadata when the repository root is not available inside the isolated environment

## 2. Task dependency decisions, uvicorn and python-multipart

Decision summary:

| Task | Type | uvicorn required | python-multipart required | Reason |
| --- | --- | --- | --- | --- |
| support-ticket-api | API | yes | no | Runnable FastAPI services may legitimately declare `uvicorn`; no held-out evaluator path uses multipart or file upload. |
| inventory-adjustment-api | API | yes | no | Runnable FastAPI services may legitimately declare `uvicorn`; no held-out evaluator path uses multipart or file upload. |
| webhook-ingestion-service | API | yes | no | Runnable FastAPI services may legitimately declare `uvicorn`; the held-out evaluator sends JSON requests only. |
| incident-escalation-api | API | yes | no | Runnable FastAPI services may legitimately declare `uvicorn`; no held-out evaluator path uses multipart or file upload. |
| leave-request-api | API | yes | no | Runnable FastAPI services may legitimately declare `uvicorn`; no held-out evaluator path uses multipart or file upload. |
| refund-approval-api | API | yes | no | Runnable FastAPI services may legitimately declare `uvicorn`; no held-out evaluator path uses multipart or file upload. |
| csv-member-import | CLI | no | no | This task is CLI-only, not FastAPI. |
| report-export-job | CLI | no | no | This task is CLI-only, not FastAPI. |

Result:
- `uvicorn` was added to the wheelhouse as general API support
- `python-multipart` was not added to the wheelhouse
- the wheelhouse seed constrains `pytest` to `<9.0` so common benchmark manifests that declare `pytest>=8,<9` still install offline
- no held-out evaluator currently exercises multipart form-data or file upload paths

## 3. Wheelhouse seed and grader admission decisions

Wheelhouse seed for API solutions:
- `email-validator`
- `fastapi`
- `pydantic`
- `pytest`
- `sqlalchemy`
- `uvicorn`

Wheelhouse seed for CLI solutions:
- `pytest`

Runtime-only support bundled by the grading root:
- `email-validator`
- `dnspython`
- `sniffio`

Admission policy now enforced by the grader:
- the wheelhouse is the only dependency admission gate
- a dependency that installs offline is admitted and evaluated
- a dependency that cannot be resolved from the wheelhouse is `real_failure`
- the grader no longer applies a separate task-specific allowlist or minimum dependency gate

Why `email-validator` remains in the API seed:
- the `support-ticket-emailstr` workspace is a legitimate in-spec implementation path
- that path requires `email-validator` at solution-install time, not only in the grader root

## 4. Clean rebuild confirmation

Clean rebuild procedure that was exercised:
1. create a fresh external venv
2. run `python benchmarks/grading-env/build_wheelhouse.py`
3. rerun `wheelhouse_gate.py` against the rebuilt artifacts
4. rerun solution-level gates for the four checked workspaces

Observed result:
- root gate passed after the clean rebuild
- all four solution-level gates passed after the clean rebuild

## 5. Frozen limitation

The current Starlette and httpx pins emit a deprecation warning about `httpx2` during `TestClient` usage. This warning is known, expected, and left untouched until after the benchmark campaign.
