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
- `git push origin main` verified at `ab5e49200e7cb78f3641aaed72f7717069c475af`
- Root wheelhouse gate: PASS
- Solution smoke: `support-ticket-api`: PASS
- Solution smoke: `inventory-adjustment-api`: PASS
- `pytest -q tests/test_inventory_benchmark_hidden_evaluator.py`: 4 passed

Interpretation:
- Earlier failures attributable to stale freeze coverage or evaluator/packaged-wheel mismatch should not be read as treatment evidence.
- A fresh benchmark rerun should use repo state `ab5e49200e7cb78f3641aaed72f7717069c475af` or later.
- No new A/B effect claims should be made from runs executed before these fixes.
