# Contributing to AgentHarness

Thank you for helping make coding-agent verification more useful and trustworthy.

## Project focus

AgentHarness exists to turn coding-agent claims into independently reexecuted, auditable evidence.

High-value contributions improve one or more of:

- verification correctness
- evidence quality and provenance
- executor isolation
- the `agentharness check` user journey
- CI and coding-agent integrations
- documentation backed by runnable examples

Please avoid adding broad orchestration or governance features unless they directly strengthen the verification workflow.

## Development setup

AgentHarness requires Python 3.11 or newer.

```bash
git clone https://github.com/fabioscialanga/AgentHarness.git
cd AgentHarness
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the full suite on Python 3.12, which is the frozen offline grading runtime:

```bash
python -m pytest -q
```

On Python 3.11 or 3.13, run the version-independent community core:

```bash
python -m pytest -q --ignore-glob='tests/test_*benchmark_hidden_evaluator.py'
```

The hidden benchmark evaluators are not silently treated as cross-version: CI runs them separately against the frozen Python 3.12 grading environment.

Run the product smoke path:

```bash
agentharness check \
  --workspace tests/fixtures/workspace_success \
  --command "python -m pytest -q" \
  --output-dir /tmp/agentharness-contributor-smoke \
  --json
```

## Before opening a pull request

1. Keep the change focused.
2. Add or update tests for observable behavior.
3. Run `python -m pytest -q`.
4. Update the English and Italian quickstarts when the public CLI changes.
5. Do not weaken verification semantics to make a fixture pass.
6. Separate product failures from provider or environment failures.
7. State security and isolation limits explicitly.

## Pull requests

A useful pull request explains:

- the user problem
- the chosen behavior
- alternatives considered
- verification commands and real output
- compatibility or security implications

Small, complete vertical slices are preferred over large speculative frameworks.

## Reporting bugs and proposing features

Use GitHub Issues and select the closest template. Include a minimal reproduction and redact credentials, tokens, private source code, and personal data.

For vulnerabilities, follow `SECURITY.md` and do not open a public issue.
