# Stage 2 recovery amendment — 2026-07-25

Amendment ID: `stage2-recovery-2026-07-25-outcome-blind-16-task`

## Status and qualification

This is a substantive, outcome-blind amendment. The recovered estimand is `exploratory_amended_16_tasks`; every result is qualified `non_confirmatory_recovered_exploratory`. It cannot support or be presented as a confirmatory public claim. Dataset construction does not authorize analysis.

## No-outcome declaration

The amendment, exclusions, chronological attempt-selection rule, endpoint-validity rule, and authorization gate were fixed without reading, printing, or selecting on real task outcomes. The builder may compute scores only inside sealed artifacts. Its console contract exposes only PASS/FAIL and structural counts.

## Incidents

1. The historical endpoint incorrectly used evaluation payload `ok` as a validity gate. A payload can have `ok=false` solely because one or more terminal cases failed while still constituting a valid six-case endpoint.
2. Three previous diagnostic replays added trace JSONL only to workspaces `b019-s1`, `b020-s1`, and `b020-s2`. Progress, dataset, run, suite, and solution artifacts were not modified.
3. Four legacy suite envelopes have only `schema_version`, `task_id`, and functional case labels, without executable oracle fields. They are not recoverable with the standard evaluator.

## Complete exclusions

- `access-policy-evaluator`
- `dependency-impact-planner`
- `safe-archive-extraction`
- `versioned-document-api`

The amended roster therefore contains exactly 16 tasks, 48 paired blocks, and 96 cells.

## Frozen recovery rules

1. For each retained cell, select the minimum physical attempt number among exact `quarantine/<cell>/attempt-NN-harness_invalid_rerun` directories and the final `private-cells/<cell>` directory. Validate the run ID suffix `_aN`. Ignore `account-tranche-boundary`. Never use passed/failed, score, or any outcome field for selection.
2. Replay only through `agentharness.evaluation.evaluate_run`. Set `write_report=false` and an explicit `trace_path` below the derived recovery output root. Never write to the original run root or workspace.
3. A replay endpoint is valid exactly when: `gating_errors` is empty; there are six results; IDs are unique and equal the six suite IDs; every status is `passed` or `failed`. Payload `ok` is not a validity gate.
4. Preserve treatment/provenance and the selected first attempt's invocation duration. Rebuild the analysis dataset using `stage2_analysis.build_dataset_from_progress`.
5. The builder verifies original progress/dataset seals, complete state, 60 journals, 120 progress rows, manifest/repository bindings where represented, treatment provenance, and absence of pre-existing final analysis results.
6. The builder emits `recovery-progress.private.json`, `recovery-analysis-dataset.sealed.json`, `attempt-lineage.private.json`, `blind-recovery-audit.json`, and `recovery-seal.json`, with `analysis_authorized=false` and complete SHA-256 bindings.
7. The separate finalizer requires `RECOVERY_ANALYSIS_AUTHORIZATION.json` with exact recovery dataset/seal hashes, `analysis_authorized=true`, and scope `exploratory_amended_16_tasks`. It uses the original MME, seeds, and resample counts and forcibly reports non-confirmatory qualification.

## Hash binding

Run-dependent hashes are deliberately builder-compiled, not placeholders to be guessed. `blind-recovery-audit.json` binds the amendment, manifest, original progress/dataset seals, and repository commit. `recovery-seal.json` additionally binds every recovered artifact. Authorization must bind the exact dataset and recovery-seal file hashes.
