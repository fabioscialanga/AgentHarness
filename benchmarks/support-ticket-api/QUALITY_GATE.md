# Quality gate for support-ticket-api

## Purpose
This document proves the two gate properties for this task pack:
- semantic disjunction between the visible `verify-run` claims and the held-out evaluation suite
- non-leakage of held-out evaluation material into the agent-visible context

## Agent-visible claims contract
Visible file: `CLAIMS_CONTRACT.template.json`

| Claim id | Type | What it verifies |
| --- | --- | --- |
| claim_scope_forbidden | forbidden_paths | The run did not drift into clearly forbidden paths such as frontend or infra. |
| claim_tests | tests_executed | The declared automated test command was executed and evidenced. |
| claim_readme | artifact_present | README.md exists as an operational artifact. |
| claim_pyproject | artifact_present | pyproject.toml exists as a dependency artifact. |

These claims are intentionally about process, scope, and required artifacts. They do not certify business correctness.

## Held-out evaluation suite
Held-out file: `HELDOUT_EVALUATION_SUITE.template.json`

| Case id | Business property checked by the hidden evaluator |
| --- | --- |
| create_valid_ticket | Valid ticket creation semantics and default status |
| list_filters_work | Query filtering semantics for status, priority, and category |
| closed_ticket_reopen_blocked | Ticket state-machine rule on closed tickets |
| comments_embedded_in_detail | Response composition for ticket detail with comments |
| invalid_email_rejected | Business validation on requester_email |

The held-out suite reads only hidden evaluator outputs under:
- `.agentharness/evaluation/support-ticket-api/summary.txt`
- `.agentharness/evaluation/support-ticket-api/result.json`

## Semantic disjunction proof
| Held-out case | Why it is semantically disjoint from visible claims |
| --- | --- |
| create_valid_ticket | Visible claims never assert ticket-creation semantics; they only assert process traces and artifact presence. |
| list_filters_work | No visible claim certifies query semantics or filter correctness. |
| closed_ticket_reopen_blocked | Visible claims do not cover business state-machine rules. |
| comments_embedded_in_detail | Visible claims do not cover response content composition. |
| invalid_email_rejected | Visible claims do not cover input-validation outcomes. |

## Non-leakage plan
1. Show only `SPEC.md` and `CLAIMS_CONTRACT.template.json` during the run.
2. Do not show `HELDOUT_EVALUATION_SUITE.template.json` to either condition.
3. Create `.agentharness/evaluation/support-ticket-api/` only after the run completes.
4. Do not expose held-out case ids, expected `=pass` markers, or evaluator fixtures in the visible prompt.
5. Check overlap semantically, not lexically.