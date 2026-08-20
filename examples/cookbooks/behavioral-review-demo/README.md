# Independent behavioral review demo

This demo shows the mechanism AgentHarness can now verify: an agent-authored workspace may look plausible while an external, trusted review plan exposes a missing behavior.

The tracked workspace is intentionally buggy. Run from the repository root and use a new temporary artifact directory every time:

```bash
BAD_OUTPUT="$(mktemp -d /tmp/agentharness-review-bad-XXXXXX)"

agentharness review \
  --workspace examples/cookbooks/behavioral-review-demo/workspace \
  --plan examples/cookbooks/behavioral-review-demo/review-plan.json \
  --output-dir "$BAD_OUTPUT"

echo "exit=$?" # expected: 1
```

Expected result: `adds_positive_numbers` passes and `adds_negative_numbers` produces one actionable finding. Exit code is `1`.

Do not edit the tracked defective fixture. Make a temporary copy, apply the smallest correction there, and use another new artifact directory:

```bash
FIXED_WORKSPACE="$(mktemp -d /tmp/agentharness-review-fixed-XXXXXX)"
GOOD_OUTPUT="$(mktemp -d /tmp/agentharness-review-good-XXXXXX)"
cp examples/cookbooks/behavioral-review-demo/workspace/calculator.py "$FIXED_WORKSPACE/calculator.py"

python - "$FIXED_WORKSPACE/calculator.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_text(
    path.read_text().replace("abs(left) + abs(right)", "left + right"),
    encoding="utf-8",
)
PY

agentharness review \
  --workspace "$FIXED_WORKSPACE" \
  --plan examples/cookbooks/behavioral-review-demo/review-plan.json \
  --output-dir "$GOOD_OUTPUT"

echo "exit=$?" # expected: 0
```

Both checks now pass. Inspect `behavioral-review-report.json` in each output directory: the plan and test-bundle hashes stay unchanged, while the workspace hash changes. The reports, rather than terminal narration, are the durable evidence for the transition.

Why the plan is outside the reviewed workspace:

- checks are not derived from the agent's claims;
- the reviewed code cannot supply its own acceptance criteria;
- plan, test bundle, and reviewed workspace hashes are recorded in the report;
- each check runs in a fresh workspace copy;
- workspace pytest configuration and plugins are ignored;
- the exact selected test must produce a structured pass or fail result.

This is controlled verification, not a hostile-code sandbox. Review tests must be trusted. The current runner does not isolate network access or the host filesystem; use a container or dedicated low-privilege runner for untrusted code.

## Cloned-start mechanism evidence

The [`mechanism-evidence/`](mechanism-evidence/) directory preserves a one-pair check in which two byte-identical defective workspaces received asymmetric treatment: A remained unchanged, while B received the actionable AgentHarness finding through one external repair-agent invocation. The declared and actual diff matched, the original finding resolved only in B, and a mixed-sign heldout check failed in A and passed in B.

This demonstrates an operable mechanism chain, not average efficacy or superiority over generic self-repair.
