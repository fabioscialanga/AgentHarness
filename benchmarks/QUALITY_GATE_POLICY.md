# Benchmark quality-gate policy

This policy applies to every task pack in `benchmarks/`.

## Semantic disjunction rule
- The held-out evaluation suite must measure business outcomes.
- The visible `verify-run` claims contract must measure process, scope, declared test execution, and required artifacts.
- A textual difference is not enough; overlap is semantic, not lexical.
- If a held-out case and a visible claim verify the same substantive property, the task pack fails the gate until one of them is rewritten or removed.

## Non-leakage rule
- Only `SPEC.md` and the visible claims contract may be shown during the run.
- The held-out suite, evaluator fixtures, expected pass markers, and evaluator output paths must stay out of the agent-visible prompt.
- Hidden evaluator outputs under `.agentharness/evaluation/<task-id>/` are created only after the agent run completes.

## Construction checklist
- task spec is self-contained
- claims contract is process-only
- held-out suite is outcome-only
- disjunction is documented in `QUALITY_GATE.md`
- non-leakage plan is documented in `QUALITY_GATE.md`