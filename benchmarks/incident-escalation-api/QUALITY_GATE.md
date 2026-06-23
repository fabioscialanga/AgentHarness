# Quality gate for incident-escalation-api

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify escalation correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| sev1_escalates_on_time | Time-threshold escalation behavior |
| ack_stops_escalation | Effect of acknowledgement on escalation |
| resolved_stops_escalation | Post-resolution escalation behavior |
| sev3_not_auto_escalated | Severity-specific policy |
| invalid_as_of_rejected | Validation on evaluation-time inputs |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| sev1_escalates_on_time | Visible claims do not cover time-threshold business logic. |
| ack_stops_escalation | Visible claims do not cover computed escalation status. |
| resolved_stops_escalation | Visible claims do not cover post-resolution behavior. |
| sev3_not_auto_escalated | Visible claims do not cover severity-specific policy. |
| invalid_as_of_rejected | Visible claims do not cover validation of evaluation-time parameters. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/incident-escalation-api/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.