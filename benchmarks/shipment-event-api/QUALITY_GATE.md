# Quality gate for shipment-event-api

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

Claims are process-only: forbidden scope, test execution, README presence, and manifest presence. They do not certify functional correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| shipment_create_and_filters | Creation, empty history, detail, and filters are coherent. |
| shipment_valid_transition_path | The full ordered lifecycle updates state and history correctly. |
| shipment_skipped_transition_atomic | Skipped transitions are rejected without mutation. |
| shipment_event_idempotency | Identical replay is idempotent and conflicting replay is rejected. |
| shipment_time_and_terminal_invariants | Timestamp monotonicity and delivered terminality are enforced. |

The sixth case validates only the stable result envelope. The campaign endpoint remains the frozen six-case score.

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| shipment_create_and_filters | Process claims do not certify this business behavior. |
| shipment_valid_transition_path | Process claims do not certify this business behavior. |
| shipment_skipped_transition_atomic | Process claims do not certify this business behavior. |
| shipment_event_idempotency | Process claims do not certify this business behavior. |
| shipment_time_and_terminal_invariants | Process claims do not certify this business behavior. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during an agent run.
2. Keep this file, the held-out suite, evaluator code, fixtures, references, mutants, and expected outputs outside the visible workspace.
3. Create `.agentharness/evaluation/shipment-event-api/` only after the agent run completes.
4. Reject visible bundles containing held-out case ids, pass/fail markers, fixture literals, prior run artifacts, or sibling solutions.
5. Validate semantic rather than merely lexical disjunction.
