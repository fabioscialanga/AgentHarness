# Supervisor v1 dogfood ledger

This ledger records operational use, not a benchmark or an efficacy claim.

## Acceptance gate

Continue developing the supervisor only after all of the following are true:

- 10 supervised job executions have completed across at least 3 distinct real workflows.
- A real preflight failure has prevented the main command from starting.
- Detached start, status, stop, timeout, retry, resume, final verification, and artifact hashing have each been exercised by tests or operational use.
- At least one invalid output is rejected by a real workflow verification command.
- The supervisor is chosen voluntarily over an ad hoc shell/cron/watchdog script for a repeated job.

If the tool is not used voluntarily after the gate period, archive the product pivot instead of expanding the framework.

## 2026-09-01 — SIA maintenance

Environment: existing `hexo-ai/sia` checkout mounted into the Hermes Docker container.

1. `first-dogfood`
   - Initial preflight: `preflight_failed`, exit 127.
   - Main pytest command did not start.
   - Cause: the isolated SIA virtual environment did not exist.
   - `uv sync` exposed an upstream dependency-resolution conflict involving the optional OpenHands extra and Python 3.11 compatibility.
   - SIA was installed without modifying its source using `uv pip install --python .venv/bin/python -e '.[claude,dev]'`.
   - The same run was resumed successfully.
   - Result: 126 passed, 1 skipped; success check passed.

2. `second-dogfood`
   - Foreground execution with final log hashing enabled.
   - Result: 126 passed, 1 skipped; success check passed; stdout/stderr SHA-256 recorded.

3. `third-dogfood`
   - Detached execution after the start-gate race fix.
   - Result: 126 passed, 1 skipped; worker terminated cleanly; one preflight and one attempt; success check passed; stdout SHA-256 recorded.

Current gate progress:

- Supervised executions: 3/10.
- Distinct real workflows: 1/3.
- Real preflight prevention: passed.
- Voluntary repeated use: not yet established.
- Product usefulness verdict: pending.

No provider/model call was made during these maintenance runs. The SIA source checkout already showed mode-bit changes across tracked files; these were not altered or normalized as part of this work.
