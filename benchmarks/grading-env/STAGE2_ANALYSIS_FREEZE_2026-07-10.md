# Stage 2 analysis freeze — 2026-07-10

This document freezes the executable Stage 2 analysis stack before any Stage 2 data collection.

## Scope

These scripts are frozen for Stage 2 analysis:
- `src/agentharness/stage2_analysis.py`
- `benchmarks/grading-env/stage2_build_dataset.py`
- `benchmarks/grading-env/stage2_run_analysis.py`
- `benchmarks/grading-env/stage2_generate_synthetic_dataset.py`
- `benchmarks/grading-env/stage2_synthetic_smoke.py`
- `tests/test_stage2_analysis.py`
- `benchmarks/grading-env/stage2-analysis-requirements.txt`

## Frozen analysis outputs

Running `stage2_run_analysis.py` on a prepared dataset must emit:
- `dataset-summary.json`
- `primary-analysis.json`
- `cluster-bootstrap.json`
- `wild-cluster-bootstrap.json`
- `leave-one-task-out.json`
- `sensitivity-invalids.json`
- `manipulation-checks.json`
- `final-report.json`

## Frozen dataset contract

Each row in the Stage 2 analysis dataset must contain at least:
- `task_id`
- `condition`
- `replicate_id`
- `score`
- `benchmark_execution_status`
- `benchmark_outcome_status`
- `benchmark_classification_reason`
- `solution_hash_changed_between_attempt_and_repair`
- `verify_run_ok`

`stage2_build_dataset.py` constructs this dataset from the run-level `progress.json` without consulting any Stage 1 summary file.

## Frozen inferential stack

### Primary analytic policy

Primary analysis excludes infrastructure-invalid rows from the inferential dataset:
- `provider_unavailable`
- `harness_invalid`

True task failures remain in the dataset with their observed score, including zero when present.

### Primary effect estimator

The executable primary estimator is:
- task-level paired mean difference in score (`B - A`)
- one difference per task after averaging over replicates within condition
- small-cluster t inference over the 8 task-level differences

This choice is frozen because the pinned Python stack available here does not provide a trustworthy Kenward-Roger implementation for the required mixed-model path. The script still fits a REML random-intercept mixed model and records its `B - A` coefficient as a concordance check, but the finite-sample inferential quantities used by the frozen report come from the task-cluster estimator above.

This is a substantive pre-analysis execution freeze, not a post-hoc analytic convenience.

### Frozen robustness analyses

- cluster bootstrap over task-level paired differences
  - seed: `20260703`
  - resamples: `10000`
- wild cluster bootstrap over task-level paired differences
  - seed: `20260704`
  - resamples: `10000`
- leave-one-task-out over tasks
- invalid sensitivity with infrastructure-invalid rows counted as zero instead of excluded

### Frozen manipulation checks

Manipulation checks are reported, not used as benefit endpoints:
- hash-change rate between attempt and repair in `A-baseline`
- hash-change rate between attempt and repair in `B-agentharness`
- feedback-delivered rate in `B-agentharness`

## Synthetic validation freeze

The scripts were validated on a synthetic dataset with a known built-in treatment effect before any Stage 2 real data existed.

Frozen synthetic validation command:

`python benchmarks/grading-env/stage2_synthetic_smoke.py`

Pass criterion:
- the recovered primary effect must be within the configured tolerance of the known synthetic effect
- the report must be generated end-to-end

## Environment freeze

Use a Python 3.12 virtual environment with:
- `benchmarks/grading-env/stage2-analysis-requirements.txt`

Suggested setup:

`python -m venv .analysis-venv && . .analysis-venv/bin/activate && pip install -r benchmarks/grading-env/stage2-analysis-requirements.txt && pip install -e .`

## Blindness rule

No Stage 1 summary, invalid-rate summary, treatment contrast, or Stage 2 real data may be used to modify these scripts after this freeze. Any later change requires a dated amendment before Stage 2 launch.
