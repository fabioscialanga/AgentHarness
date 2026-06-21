# AgentHarness Quickstart

## What AgentHarness is for
AgentHarness helps teams use coding agents with more structure and less chaos.

Instead of starting from a vague prompt, it gives the agent a project contract:
- project intent
- machine-readable project config
- workflows
- policies
- checklists
- generated framework metadata

Today, the repository already provides a working operational core:
- `agentharness validate` checks whether an AgentHarness-style project is internally consistent
- `agentharness generate` regenerates core `.framework` metadata from `project.yaml`
- `agentharness bootstrap` scaffolds a new contract-first project skeleton

## Who it is for
AgentHarness is most useful if you want to:
- make agent-driven work more repeatable
- add review, testing, and security structure around agents
- standardize how engineering tasks are framed
- compare governed agent execution against ad hoc prompting

It is less useful for quick throwaway prototypes where no one wants extra project structure.

## Prerequisites
- Python 3.11+
- git

## Install
Clone the repository and install it in editable mode:

```bash
git clone https://github.com/fabioscialanga/AgentHarness.git
cd AgentHarness
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Verify that the CLI is available:

```bash
agentharness --help
```

## First useful commands
### 1. Validate the worked example
```bash
agentharness validate examples/civictrack --json
```

This checks that the example project contract is internally consistent.

### 2. Regenerate framework metadata
```bash
agentharness generate examples/civictrack --json
```

This rebuilds:
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

### 3. Bootstrap a new project
```bash
agentharness bootstrap ./my-project \
  --project-name "My Project" \
  --project-slug my-project \
  --json
```

This creates a new project skeleton with:
- `PROJECT.md`
- `project.yaml`
- `AGENTS.md`
- `workflows/`
- `checklists/`
- `policies/`
- `tests/`
- `.framework/`

and then validates the result.

## Recommended first path
If you are new to the repo, follow this order:
1. Read `README.md`
2. Run `agentharness validate examples/civictrack --json`
3. Run `agentharness bootstrap ...` on a temporary directory
4. Inspect the generated files
5. Read `docs/en/PROJECT_DOCUMENTATION.md` for the deeper model

## Current limits
AgentHarness is still early.

What exists today:
- working CLI commands for validate, generate, and bootstrap
- one worked example project
- tests covering the core flows

What does not exist yet:
- full execution/runtime integration for coding agents
- CI integration out of the box
- broad template coverage for many project types

## Where to go next
- Framework overview: `README.md`
- Deeper project explanation: `docs/en/PROJECT_DOCUMENTATION.md`
- Validator details: `docs/en/VALIDATOR.md`
- Bootstrap details: `docs/en/BOOTSTRAP.md`
- A/B benchmark pack: `docs/en/AB_BENCHMARK.md`
