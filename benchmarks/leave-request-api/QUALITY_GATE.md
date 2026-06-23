# Quality gate for leave-request-api

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify leave-workflow correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| valid_request_created | Basic submission and list behavior |
| overlap_rejected | Conflict detection for overlapping approved leave |
| personal_leave_limit_enforced | Leave-duration business rule |
| approval_sets_reviewed_at | Review side-effect correctness |
| terminal_state_blocks_second_review | Terminal workflow-state enforcement |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| valid_request_created | Visible claims do not cover workflow correctness. |
| overlap_rejected | Visible claims do not cover calendar conflict rules. |
| personal_leave_limit_enforced | Visible claims do not cover leave-duration business rules. |
| approval_sets_reviewed_at | Visible claims do not cover review-state side effects. |
| terminal_state_blocks_second_review | Visible claims do not cover terminal-state enforcement. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/leave-request-api/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.