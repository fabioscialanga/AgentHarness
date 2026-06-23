# Quality gate for report-export-job

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify export correctness, totals, or date filtering.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| csv_rows_sorted_complete | Report completeness and deterministic ordering |
| net_totals_correct | Merchant-level payout arithmetic |
| date_filter_applied | Correct filtering to the target export date |
| summary_totals_match | Consistency between summary and CSV outputs |
| invalid_date_rejected | Controlled validation behavior on CLI input |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| csv_rows_sorted_complete | Visible claims do not cover report content or row ordering. |
| net_totals_correct | Visible claims do not cover arithmetic outcomes. |
| date_filter_applied | Visible claims do not cover selection semantics. |
| summary_totals_match | Visible claims do not cover aggregate consistency. |
| invalid_date_rejected | Visible claims do not cover CLI validation behavior. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/report-export-job/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.