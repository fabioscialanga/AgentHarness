# AgentHarness

English | Italiano
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

## What this repository is

AgentHarness is a framework concept for turning project intent into controlled agent execution.

The goal is not to build another coding agent.
The goal is to provide the operating layer around agents so teams can use AI-assisted development in a more reliable, testable, and secure way.

In practical terms, AgentHarness starts from project definition artifacts such as:
- a human-readable project brief
- a machine-readable project config
- policy files for autonomy, testing, and security
- workflow templates for common engineering tasks

From there, it aims to bootstrap:
- agent context
- project rules
- workflow constraints
- quality gates
- security checks
- review boundaries

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

## What AgentHarness is

AgentHarness is intended to help teams:
- define project intent clearly
- convert that intent into reusable agent-operating artifacts
- separate prototyping from production discipline
- make testing and security first-class in AI-assisted development
- standardize common workflows such as feature creation, bug fixing, refactoring, and test generation

## What AgentHarness is not

It is not:
- a frontier model
- a replacement for software engineering judgment
- a guarantee that generated code is correct
- just a prompt library
- just a project scaffolder

## Proposed building blocks

- `PROJECT.md` — human-readable project intent
- `project.yaml` — structured machine-readable project config
- `AGENTS.md` — agent operating rules
- `workflows/` — task templates
- `checklists/` — definition of done, review, security, testing
- `policies/` — autonomy, quality, and security rules
- `.framework/` — generated metadata, risk matrices, required checks

## Repository status

This repository is currently in bootstrap phase.

It now includes two concrete layers:
- a generic open source example project showing how AgentHarness-style inputs, policies, and workflows can look in practice
- a first working validator for AgentHarness-style project definitions

## Working validator

AgentHarness now includes a real Python validator that checks:
- required top-level fields in `project.yaml`
- stack, testing, quality, security, and agent policy structure
- enabled workflow files
- declared deliverables against actual repository files
- `.framework` generated outputs such as required checks and risk matrix

Example usage:
- `PYTHONPATH=src python3 -m agentharness validate examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness validate examples/civictrack --json`

## Framework output generator

AgentHarness now also includes a generator for `.framework` outputs.

It derives framework metadata directly from `project.yaml` and writes:
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

Example usage:
- `PYTHONPATH=src python3 -m agentharness generate examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness generate examples/civictrack --json`

This makes the framework more than static documentation: it now both validates and regenerates core project-control artifacts.

## Bootstrap command

Inspired in part by SIA's explicit custom-task packaging model, AgentHarness now also has a bootstrap command for creating a new contract-first project skeleton.

Example usage:
- `PYTHONPATH=src python3 -m agentharness bootstrap ./my-project --project-name "My Project" --project-slug my-project`

The bootstrap command creates:
- `PROJECT.md`
- `project.yaml`
- `README.md`
- `AGENTS.md`
- `docs/`
- `workflows/`
- `checklists/`
- `policies/`
- `tests/`
- `.framework/`

and then generates framework metadata and validates the result.

## Initial roadmap

1. Define the core spec for project inputs
2. Define policy schema for autonomy, testing, and security
3. Build a validator for project definitions
4. Generate base artifacts from the normalized spec
5. Add workflow and verification execution primitives
6. Iterate on examples before building deeper automation

## Example

See `examples/civictrack/` for a generic example repository structure designed for open source demonstration.

## Positioning in one sentence

AgentHarness turns project spec into controlled agent execution.
