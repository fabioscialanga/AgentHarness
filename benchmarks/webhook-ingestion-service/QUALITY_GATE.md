# Quality gate for webhook-ingestion-service

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify signature handling, idempotency, or normalization correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| valid_signed_event_stored | Valid signed event acceptance and persistence |
| invalid_signature_rejected | Signature rejection behavior |
| duplicate_delivery_idempotent | Idempotency for repeated deliveries |
| type_normalized_correctly | Correct business normalization of partner event types |
| missing_fields_rejected | Payload validation for required fields |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| valid_signed_event_stored | Visible claims do not cover signature semantics or storage correctness. |
| invalid_signature_rejected | Visible claims do not cover authenticity checks. |
| duplicate_delivery_idempotent | Visible claims do not cover idempotency behavior. |
| type_normalized_correctly | Visible claims do not cover business normalization rules. |
| missing_fields_rejected | Visible claims do not cover payload-validation outcomes. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/webhook-ingestion-service/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.