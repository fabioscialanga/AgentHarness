# Evaluation demo

This cookbook shows deterministic evaluation with `agentharness evaluate`.

Run:

```bash
agentharness evaluate \
  --run examples/cookbooks/evaluation-demo/run.json \
  --suite examples/cookbooks/evaluation-demo/suite.json \
  --json
```

What it checks:
- `workspace/answer.txt` contains required summary text
- `workspace/result.json` matches a small JSON schema

The command emits a JSON verdict and also writes a structured trace under `workspace/.agentharness/traces/evaluation/` unless you override `--trace-jsonl`.
