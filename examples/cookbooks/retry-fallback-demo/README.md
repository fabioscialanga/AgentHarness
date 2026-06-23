# Retry + fallback demo

This cookbook shows a retry-aware fallback plan with `agentharness run-plan`.

Run:

```bash
agentharness run-plan \
  --plan examples/cookbooks/retry-fallback-demo/plan.json \
  --json
```

What happens:
- the primary target fails twice
- AgentHarness records both attempts under `workspace/.agentharness/resilience/`
- the fallback target succeeds
- a structured JSONL trace is emitted under `workspace/.agentharness/traces/resilience/`
