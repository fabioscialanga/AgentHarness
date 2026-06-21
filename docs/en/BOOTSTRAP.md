# AgentHarness Bootstrap

## Why this exists

One of the strongest ideas in SIA is not only the self-improvement loop itself, but the fact that custom tasks must follow an explicit directory contract.

AgentHarness benefits from the same discipline.

The bootstrap command creates a new repository skeleton that already contains:
- human-readable project intent
- machine-readable project definition
- agent operating rules
- workflows, policies, and checklists
- generated `.framework` metadata

## Command

From the AgentHarness repository root:

- `PYTHONPATH=src python3 -m agentharness bootstrap ./my-project --project-name "My Project" --project-slug my-project`

After `pip install -e .`, you can also run:

- `agentharness bootstrap ./my-project --project-name "My Project" --project-slug my-project`

## Optional flags

- `--project-type`
- `--language`
- `--framework`
- `--database`
- `--package-manager`
- `--license`
- `--json`

## What gets created

The command writes:
- `PROJECT.md`
- `project.yaml`
- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE_SUMMARY.md`
- `docs/DELIVERY_MODEL.md`
- `workflows/*.md`
- `checklists/*.md`
- `policies/*.yaml`
- `tests/unit/README.md`
- `tests/integration/README.md`
- `tests/regression/README.md`
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

After writing the files, AgentHarness immediately generates the `.framework` outputs and validates the project contract.

## Why it matters

This moves AgentHarness closer to being an operational framework rather than just a pattern library.

The repository can now:
- scaffold a new project contract
- generate derived control artifacts
- validate the result

That is a much stronger starting point for future automation.
