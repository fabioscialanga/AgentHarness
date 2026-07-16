# Quality gate for appointment-booking-api

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

Claims are process-only: forbidden scope, test execution, README presence, and manifest presence. They do not certify functional correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| appointment_create_and_filters | Creation, detail, and combined list filters are coherent. |
| appointment_interval_validation | Invalid intervals are rejected without mutation. |
| appointment_provider_conflicts | Conflict scope and half-open boundary behavior are correct. |
| appointment_reschedule_atomic | Rescheduling enforces conflicts atomically. |
| appointment_cancel_releases_slot | Cancellation is terminal and releases the provider interval. |

The sixth case validates only the stable result envelope. The campaign endpoint remains the frozen six-case score.

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| appointment_create_and_filters | Process claims do not certify this business behavior. |
| appointment_interval_validation | Process claims do not certify this business behavior. |
| appointment_provider_conflicts | Process claims do not certify this business behavior. |
| appointment_reschedule_atomic | Process claims do not certify this business behavior. |
| appointment_cancel_releases_slot | Process claims do not certify this business behavior. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during an agent run.
2. Keep this file, the held-out suite, evaluator code, fixtures, references, mutants, and expected outputs outside the visible workspace.
3. Create `.agentharness/evaluation/appointment-booking-api/` only after the agent run completes.
4. Reject visible bundles containing held-out case ids, pass/fail markers, fixture literals, prior run artifacts, or sibling solutions.
5. Validate semantic rather than merely lexical disjunction.
