# AgentHarness

English | Italiano
- English quickstart: `docs/en/QUICKSTART.md`
- Quickstart italiano: `docs/it/QUICKSTART.md`
- English documentation: `docs/en/PROJECT_DOCUMENTATION.md`
- Documentazione italiana: `docs/it/DOCUMENTAZIONE_PROGETTO.md`
- Validator docs (English): `docs/en/VALIDATOR.md`
- Documentazione validatore (Italiano): `docs/it/VALIDATORE.md`
- Bootstrap docs (English): `docs/en/BOOTSTRAP.md`
- Documentazione bootstrap (Italiano): `docs/it/BOOTSTRAP.md`
- A/B benchmark docs (English): `docs/en/AB_BENCHMARK.md`
- Documentazione benchmark A/B (Italiano): `docs/it/BENCHMARK_AB.md`
- CivicTrack example (English): `docs/en/EXAMPLE_CIVICTRACK.md`
- Esempio CivicTrack (Italiano): `docs/it/ESEMPIO_CIVICTRACK.md`

## What AgentHarness is for
AgentHarness is a framework for making agent-driven engineering more structured, testable, and reviewable.

The goal is not to build another coding assistant.
The goal is to give coding agents a project contract so they operate with clearer context, rules, checks, and review boundaries.

In practice, AgentHarness helps turn project intent into:
- a human-readable project brief
- a machine-readable project config
- workflows for common engineering tasks
- policies for autonomy, testing, and security
- generated framework metadata used for verification

If you want the deeper model, read `docs/en/PROJECT_DOCUMENTATION.md` or `docs/it/DOCUMENTAZIONE_PROGETTO.md`.

## What works today
AgentHarness already includes a working Python CLI with three concrete commands:

1. `agentharness validate`
- validates that an AgentHarness-style project is internally consistent

2. `agentharness generate`
- regenerates core `.framework` artifacts from `project.yaml`

3. `agentharness bootstrap`
- creates a new contract-first project skeleton and validates it

The repository also includes:
- a worked example project in `examples/civictrack/`
- automated tests for the core flows
- an A/B benchmark pack for comparing framework vs no-framework execution

## Install
Requirements:
- Python 3.11+
- git

Install locally:

```bash
git clone https://github.com/fabioscialanga/AgentHarness.git
cd AgentHarness
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Check that the CLI is installed:

```bash
agentharness --help
```

## Quick start
### Validate the example project
```bash
agentharness validate examples/civictrack --json
```

### Regenerate framework metadata
```bash
agentharness generate examples/civictrack --json
```

### Bootstrap a new project
```bash
agentharness bootstrap ./my-project \
  --project-name "My Project" \
  --project-slug my-project \
  --json
```

For a more guided first run, start with:
- `docs/en/QUICKSTART.md`
- `docs/it/QUICKSTART.md`

## Core idea
A raw model is not enough.
Reliable agentic engineering needs a harness around the model:
- context
- tools
- rules
- verification
- safety boundaries
- observability

AgentHarness focuses on that harness.

## Main repository building blocks
- `PROJECT.md` — human-readable project intent
- `project.yaml` — structured machine-readable project config
- `AGENTS.md` — agent operating rules
- `workflows/` — task templates
- `checklists/` — definition of done, review, security, testing
- `policies/` — autonomy, quality, and security rules
- `.framework/` — generated metadata, risk matrices, required checks

## Repository status
This repository is still early, but it is no longer documentation-only.

What exists today:
- a working validator
- a framework metadata generator
- a bootstrap command
- one worked example repository
- automated tests for the core flows

What does not exist yet:
- full coding-agent runtime integration
- automatic CI integration out of the box
- broad project-template coverage across many project types

## Example
See `examples/civictrack/` for a generic worked example repository showing how AgentHarness inputs, workflows, policies, and generated artifacts fit together.

## A/B benchmark
If you want to test whether the framework adds real value, use the benchmark pack:
- `benchmarks/support-ticket-api/SPEC.md`
- `benchmarks/support-ticket-api/RUN_PROTOCOL.md`
- `benchmarks/support-ticket-api/SCORECARD.md`

## Positioning in one sentence
AgentHarness turns project spec into controlled agent execution.
