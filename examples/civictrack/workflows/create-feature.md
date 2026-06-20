# Workflow: create-feature

## Goal
Add a new feature with minimal scope expansion and explicit verification.

## Required inputs
- feature description
- impacted modules
- expected behavior
- risk level

## Steps
1. Read PROJECT.md, AGENTS.md, and ARCHITECTURE_SUMMARY.md.
2. Confirm the task fits allowed autonomy.
3. Identify the smallest set of files to touch.
4. Implement the feature without hiding domain logic in transport or persistence layers.
5. Add or update tests.
6. Run required checks.
7. Produce a short execution summary.

## Required checks
- format
- lint
- type checks when configured
- unit tests for affected modules
- integration smoke tests if API or persistence changed

## Stop conditions
- ambiguous requirements
- auth changes
- upload safety changes
- audit behavior changes
- dependency changes
