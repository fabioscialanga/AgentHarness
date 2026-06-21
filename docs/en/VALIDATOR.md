# AgentHarness Validator

## Purpose

The validator is the first executable part of AgentHarness.

Its job is to check whether an AgentHarness-style project definition is internally consistent before deeper automation is added.

## What it validates

The current validator checks:
- presence of required repository files such as `PROJECT.md`, `README.md`, and `AGENTS.md`
- required top-level fields in `project.yaml`
- shape of `stack`, `testing`, `quality`, `security`, and `agent_policy`
- `project_slug` format
- enabled workflows against expected workflow files
- declared deliverables against actual files and directories
- `.framework/required-checks.json` against checks declared in `project.yaml`
- `.framework/risk-matrix.yaml` for required risk levels

## Command-line usage

From the repository root:

- `PYTHONPATH=src python3 -m agentharness validate examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness validate examples/civictrack --json`

After `pip install -e .`, you can also run:

- `agentharness validate examples/civictrack`
- `agentharness validate examples/civictrack --json`

## Exit codes

- `0` = validation passed
- `1` = validation failed
- `2` = CLI usage error

## Generator companion

The validator is now paired with a generator command:

- `PYTHONPATH=src python3 -m agentharness generate examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness generate examples/civictrack --json`

The generator rebuilds core `.framework` files from `project.yaml`:
- `required-checks.json`
- `risk-matrix.yaml`
- `generation-report.json`

This means AgentHarness can now both validate project intent and regenerate some of the machine-facing artifacts that depend on it.

## Why this matters

This validator-plus-generator combination turns AgentHarness from a documentation-only concept into a framework with real executable control points.

It is still intentionally narrow, but it proves a critical idea:
project intent can be checked and partially materialized programmatically before being used to drive agents or automation.

## Current limits

The current tooling does not yet:
- normalize project definitions into a canonical schema output
- generate the full repository scaffold
- enforce policy execution during coding tasks
- integrate with CI automatically
- validate arbitrary custom workflow mappings

Those are reasonable next steps after the core validation and generation contracts are stable.
