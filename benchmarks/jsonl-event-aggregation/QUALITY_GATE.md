# Quality gate for jsonl-event-aggregation

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

Claims are process-only: forbidden scope, test execution, README presence, and manifest presence. They do not certify functional correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| jsonl_grouped_counts | Grouped counts, unique actors, and totals are correct. |
| jsonl_utc_date_normalization | Offset timestamps are grouped by UTC date. |
| jsonl_invalid_and_duplicate_handling | Invalid and duplicate records use the frozen precedence and first-valid semantics. |
| jsonl_summary_consistency | Summary values reconcile with accepted groups and rejections. |
| jsonl_deterministic_outputs | Required artifacts are byte-stable and missing input fails cleanly. |

The sixth case validates only the stable result envelope. The campaign endpoint remains the frozen six-case score.

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| jsonl_grouped_counts | Process claims do not certify this business behavior. |
| jsonl_utc_date_normalization | Process claims do not certify this business behavior. |
| jsonl_invalid_and_duplicate_handling | Process claims do not certify this business behavior. |
| jsonl_summary_consistency | Process claims do not certify this business behavior. |
| jsonl_deterministic_outputs | Process claims do not certify this business behavior. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during an agent run.
2. Keep this file, the held-out suite, evaluator code, fixtures, references, mutants, and expected outputs outside the visible workspace.
3. Create `.agentharness/evaluation/jsonl-event-aggregation/` only after the agent run completes.
4. Reject visible bundles containing held-out case ids, pass/fail markers, fixture literals, prior run artifacts, or sibling solutions.
5. Validate semantic rather than merely lexical disjunction.
