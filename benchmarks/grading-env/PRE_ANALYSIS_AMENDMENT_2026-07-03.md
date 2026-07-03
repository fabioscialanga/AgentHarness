# Pre-analysis amendment — 2026-07-03

Context: before approving any renewed A/B benchmark run, we revalidated the frozen offline grading environment and representative hidden-grader paths on the current published repo state.

Amendments and verified fixes:

1. Frozen grading wheelhouse extended for legitimate API-solution dependency coverage.
   - Added `pydantic-settings` to the API solution seed.
   - Rebuilt `constraints-py312.txt`, `wheelhouse-manifest.json`, and the frozen wheelhouse.
   - Result: representative `support-ticket-api` workspace now installs and grades offline successfully.

2. Hidden evaluator for `inventory-adjustment-api` aligned to the public task contract and real workspace response shape.
   - Uses nested resource routes from `SPEC.md`.
   - Uses collision-resistant SKU generation during evaluation.
   - Accepts nested item payloads and recount history represented via `quantity` in adjustment entries.
   - Fixed helper behavior so history extraction no longer returns early on missing keys.
   - Result: representative `inventory-adjustment-api` workspace now grades successfully end-to-end.

3. Frozen wheelhouse refreshed after the evaluator fix so the offline root package matches published source.
   - Rebuilt the frozen `agentharness` wheel and updated `wheelhouse-manifest.json`.

Verification performed on published state:
- `origin/main` verified at `55ce6831933a28d53001b42198d45d75f8133485`
- Root wheelhouse gate: PASS
- Solution smoke: `support-ticket-api`: PASS
- Solution smoke: `inventory-adjustment-api`: PASS
- Solution smoke: `incident-escalation-api`: PASS
- Solution smoke: `refund-approval-api`: PASS (using `benchmarks/fixtures/refund-approval-api-success` as a representative workspace outside `tests/`, because FastAPI module autodiscovery intentionally skips paths nested under a `tests` directory)
- `pytest -q tests/test_inventory_benchmark_hidden_evaluator.py`: 4 passed

Claude review follow-up:
- Claude correctly flagged that the original evidence bundle was still too narrow because it lacked additional representative shared-wheelhouse smokes after the freeze refresh.
- That gap is now closed by the published-state spot-checks above.

Interpretation:
- Earlier failures attributable to stale freeze coverage or evaluator/packaged-wheel mismatch should not be read as treatment evidence.
- The refreshed freeze now has positive offline evidence on multiple representative API tasks (`support-ticket-api`, `inventory-adjustment-api`, `incident-escalation-api`, `refund-approval-api`).
- The earlier `refund-approval-api` false negative came from using a representative workspace nested under `tests/`, which the hidden grader intentionally excludes during FastAPI module autodiscovery; the benchmark fixture under `benchmarks/fixtures/` passes offline end-to-end.
- A fresh benchmark rerun should use repo state `55ce6831933a28d53001b42198d45d75f8133485` or later.
- No new A/B effect claims should be made from runs executed before these fixes.
