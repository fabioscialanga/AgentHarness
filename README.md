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
AgentHarness is a framework for making agent-driven engineering more structured, testable, reviewable, and harder to fake.

The goal is not to build another coding assistant.
The goal is to give coding agents a project contract and a verification layer so they operate with clearer context, rules, checks, review boundaries, and evidence requirements.

In practice, AgentHarness helps turn project intent into:
- a human-readable project brief
- a machine-readable project config
- workflows for common engineering tasks
- policies for autonomy, testing, and security
- generated framework metadata used for verification
- claim-based run evidence that can be accepted or rejected mechanically

If you want the deeper model, read `docs/en/PROJECT_DOCUMENTATION.md` or `docs/it/DOCUMENTAZIONE_PROGETTO.md`.

## What works today
AgentHarness already includes a working Python CLI with five concrete commands:

1. `agentharness validate`
- validates that an AgentHarness-style project is internally consistent

2. `agentharness generate`
- regenerates core `.framework` artifacts from `project.yaml`

3. `agentharness verify`
- verifies a project against its contract, checks semantic consistency in AGENTS.md against project.yaml, and detects drift in checked-in `.framework` artifacts

4. `agentharness verify-run`
- verifies an agent run against explicit claims and only accepts claims that are backed by controlled proof inside the currently supported verification surface
- defaults to strict proof for `tests_executed` and `artifact_present`
- prefers controlled reexecution for allowed pytest wrappers (`pytest`, `python -m pytest`, `uv run pytest`), supports controlled relative working directories inside the workspace, falls back to parsed evidence only when reexecution cannot establish the verdict, and returns `inconclusive` when truth cannot be defended
- rejects malformed run/claim envelopes, out-of-scope filesystem evidence, mismatched run binding, and command evidence parked outside the reserved `.agentharness/evidence/<run_id>/` namespace

5. `agentharness bootstrap`
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

### Verify the example end to end
```bash
agentharness verify examples/civictrack --json
```

### Verify claim-based agent evidence
```bash
agentharness verify-run \
  --run tests/fixtures/run_invite_schema_success.json \
  --claims tests/fixtures/claims_invite_schema.json \
  --json
```

### Catch an agent that declared a fake green test run
```bash
agentharness verify-run \
  --run tests/fixtures/run_invite_lie.json \
  --claims tests/fixtures/claims_invite_lie.json \
  --json
```

The second example is designed to fail. The run record declares a green pytest command, but the allowed command is reexecuted and AgentHarness captures the real non-zero exit code under `.agentharness/evidence/<run_id>/reexecuted/`.

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
- `PROJECT.md`: human-readable project intent
- `project.yaml`: structured machine-readable project config
- `AGENTS.md`: agent operating rules
- `workflows/`: task templates
- `checklists/`: definition of done, review, security, testing
- `policies/`: autonomy, quality, and security rules
- `.framework/`: generated metadata, risk matrices, required checks

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
AgentHarness turns project spec into a contract-first verification harness: it validates project rules, regenerates deterministic governance artifacts, and accepts agent claims only when the currently supported evidence checks can defend them.
