# AgentHarness

English | Italiano
- English documentation: `docs/en/PROJECT_DOCUMENTATION.md`
- Documentazione italiana: `docs/it/DOCUMENTAZIONE_PROGETTO.md`
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

The first concrete artifact included here is a generic open source example project showing how AgentHarness-style inputs, policies, and workflows can look in practice.

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
