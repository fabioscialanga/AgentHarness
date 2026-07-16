# Quality gate for invoice-payment-reconciliation

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

Claims are process-only: forbidden scope, test execution, README presence, and manifest presence. They do not certify functional correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| reconciliation_rows_and_order | Eligible invoice rows are complete and deterministically ordered. |
| reconciliation_cutoff_and_duplicates | As-of cutoff and first-valid payment-id semantics are correct. |
| reconciliation_status_and_decimals | Statuses, overpayments, and exact decimal arithmetic are correct. |
| reconciliation_unmatched_reporting | Unknown and duplicate payments are reported while future payments are ignored. |
| reconciliation_summary_and_validation | Summary reconciles and invalid invoice input fails without partial outputs. |

The sixth case validates only the stable result envelope. The campaign endpoint remains the frozen six-case score.

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| reconciliation_rows_and_order | Process claims do not certify this business behavior. |
| reconciliation_cutoff_and_duplicates | Process claims do not certify this business behavior. |
| reconciliation_status_and_decimals | Process claims do not certify this business behavior. |
| reconciliation_unmatched_reporting | Process claims do not certify this business behavior. |
| reconciliation_summary_and_validation | Process claims do not certify this business behavior. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during an agent run.
2. Keep this file, the held-out suite, evaluator code, fixtures, references, mutants, and expected outputs outside the visible workspace.
3. Create `.agentharness/evaluation/invoice-payment-reconciliation/` only after the agent run completes.
4. Reject visible bundles containing held-out case ids, pass/fail markers, fixture literals, prior run artifacts, or sibling solutions.
5. Validate semantic rather than merely lexical disjunction.
