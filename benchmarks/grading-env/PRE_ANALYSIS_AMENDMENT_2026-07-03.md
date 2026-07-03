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
- `origin/main` verified at `336e7e79ee29e8f12af57f32b935fbfad87fb37b`
- Root wheelhouse gate: PASS
- Solution smoke: `support-ticket-api`: PASS
- Solution smoke: `inventory-adjustment-api`: PASS
- Solution smoke: `incident-escalation-api`: PASS
- Spot-check classification: `refund-approval-api` workspace is not positive wheelhouse evidence; its representative workspace is structurally invalid for hidden grading (`app.py` imports `refund_approval_api.main`, but that module tree is absent in the workspace), so this should be treated as a workspace/task artifact issue rather than more evidence that the shared freeze is broken.
- `pytest -q tests/test_inventory_benchmark_hidden_evaluator.py`: 4 passed

Claude review follow-up:
- Claude correctly flagged that the original evidence bundle was still too narrow because it lacked additional representative shared-wheelhouse smokes after the freeze refresh.
- That gap is now closed by the published-state spot-checks above.

Interpretation:
- Earlier failures attributable to stale freeze coverage or evaluator/packaged-wheel mismatch should not be read as treatment evidence.
- The refreshed freeze now has positive offline evidence on multiple representative API tasks (`support-ticket-api`, `inventory-adjustment-api`, `incident-escalation-api`).
- The observed `refund-approval-api` failure in this spot-check should not be collapsed into a wheelhouse failure bucket; it is currently best classified as a broken representative workspace artifact.
- A fresh benchmark rerun should use repo state `336e7e79ee29e8f12af57f32b935fbfad87fb37b` or later.
- No new A/B effect claims should be made from runs executed before these fixes.
