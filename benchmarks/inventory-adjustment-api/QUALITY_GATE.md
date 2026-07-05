# Quality gate for inventory-adjustment-api

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify inventory math or business invariants.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| reserve_within_available | Reservation math and state update correctness |
| over_reserve_rejected | Negative-path validation on insufficient available stock |
| damage_cannot_go_negative | Invariant that stock never drops below zero |
| recount_sets_exact_quantity | Correct semantics of recount versus delta adjustment; the API must accept `counted_quantity` for recount and set `on_hand` exactly to that value |
| release_cannot_exceed_reserved | Reservation-release state transition correctness |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| reserve_within_available | Visible claims do not assert quantity math or reservation semantics. |
| over_reserve_rejected | Visible claims do not cover business validation outcomes. |
| damage_cannot_go_negative | Visible claims do not cover inventory invariants. |
| recount_sets_exact_quantity | Visible claims do not cover adjustment interpretation rules. |
| release_cannot_exceed_reserved | Visible claims do not cover reservation state transitions. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/inventory-adjustment-api/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.