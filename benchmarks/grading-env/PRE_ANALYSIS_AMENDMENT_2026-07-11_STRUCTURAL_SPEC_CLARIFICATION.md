# Pre-analysis amendment - 2026-07-11

Context: before collecting any new benchmark data, we reviewed the Stage 1 diagnostic slice and found that a large share of within-task variance came from all-or-nothing wiring failures rather than from task logic alone. The working estimate from the diagnostic analysis was that wiring failures explained about 58 percent of the pooled within-task variance.

This is a substantive benchmark amendment because it changes task specifications before new data collection.

## Motivation

The prior task specifications were not explicit enough about project structure, packaging, importability, and entrypoint placement in the submitted workspace.

That ambiguity created a benchmark-validity problem:
- some cells failed at application loading or CLI entrypoint discovery
- those failures were structural and all-or-nothing
- those failures inflated the observed within-task standard deviation
- inflated structural variance makes it harder to measure the treatment effect itself

The purpose of this amendment is to reduce specification-induced wiring noise so that the next diagnostic rerun better measures treatment-relevant performance instead of ambiguity about how the project must be laid out.

## Scope of the amendment

This amendment changes only structural requirements in the public task specifications.

Allowed changes made in this amendment:
- repository root must itself be a runnable Python project
- package layout must live either at workspace root or under `src/`
- single-file entry modules must live at the workspace root when applicable
- FastAPI apps or CLI entrypoints must be importable from the submitted workspace without custom `PYTHONPATH` edits, post-submission renames, or nonstandard bootstrap steps
- accepted manifest locations are clarified
- manifests must declare all runtime and test dependencies needed in the grading environment

No changes were made to:
- functional requirements
- business rules
- acceptance criteria
- hidden evaluator logic
- treatment prompts
- any wording that would hint at held-out behavioral checks

## Symmetry and neutrality

The clarification is intentionally symmetric across tasks and does not favor either benchmark arm.

The updated wording standardizes only the structure and packaging contract for:
- `support-ticket-api`
- `inventory-adjustment-api`
- `incident-escalation-api`
- `webhook-ingestion-service`
- `leave-request-api`
- `refund-approval-api`
- `csv-member-import`
- `report-export-job`

No task-specific logic hints were added.

## Planned use of new data

Any new data collected after this amendment will be used first for a masked diagnostic rerun whose purpose is:
- re-estimate pooled within-task standard deviation
- re-estimate the share of variance attributable to wiring versus logic
- confirm that the treatment-delivery channel is functioning

That diagnostic rerun is not to be interpreted as confirmatory evidence about the A versus B contrast.

Only after the updated variance estimate is available should campaign sizing be recomputed using the frozen Stage 2 power-analysis stack.
