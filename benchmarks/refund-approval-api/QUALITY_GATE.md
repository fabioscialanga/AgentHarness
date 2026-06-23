# Quality gate for refund-approval-api

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify monetary approval semantics.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| small_refund_auto_approved | Auto-approval threshold for small refunds |
| medium_refund_needs_manager | Manager-review threshold for medium refunds |
| large_refund_needs_finance | Two-stage approval rule for large refunds |
| invalid_amount_rejected | Numeric validation on refund amount |
| terminal_state_blocks_reapproval | Terminal workflow-state enforcement |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| small_refund_auto_approved | Visible claims do not cover monetary threshold behavior. |
| medium_refund_needs_manager | Visible claims do not cover staged workflow semantics. |
| large_refund_needs_finance | Visible claims do not cover multi-step threshold rules. |
| invalid_amount_rejected | Visible claims do not cover numeric validation semantics. |
| terminal_state_blocks_reapproval | Visible claims do not cover terminal workflow rules. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/refund-approval-api/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.