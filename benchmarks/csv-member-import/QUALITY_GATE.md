# Quality gate for csv-member-import

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden non-task paths. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are process-only and do not certify import-output correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| valid_rows_normalized | Normalization of accepted rows |
| duplicate_handling_correct | Duplicate-resolution semantics |
| invalid_rows_rejected_with_reason | Rejection reporting correctness |
| summary_counts_correct | Aggregate count correctness |
| output_files_present | Presence and meaning of import-result outputs |

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| valid_rows_normalized | Visible claims do not cover normalization correctness. |
| duplicate_handling_correct | Visible claims do not cover duplicate-resolution semantics. |
| invalid_rows_rejected_with_reason | Visible claims do not cover rejection semantics. |
| summary_counts_correct | Visible claims do not cover aggregate outcome correctness. |
| output_files_present | Visible claims only cover generic README and pyproject artifacts, not business-result outputs. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Keep `HELDOUT_EVALUATION_SUITE.template.json` and evaluator fixtures out of the visible prompt.
3. Create `.agentharness/evaluation/csv-member-import/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or hidden evaluator data in agent-visible context.
5. Check overlap semantically, not lexically.