# Stage 2 analysis freeze — 2026-07-10

This document freezes the executable Stage 2 analysis stack before any Stage 2 data collection.

## Scope

These scripts are frozen for Stage 2 analysis:
- `src/agentharness/stage2_analysis.py`
- `benchmarks/grading-env/stage2_build_dataset.py`
- `benchmarks/grading-env/stage2_run_analysis.py`
- `benchmarks/grading-env/stage2_generate_synthetic_dataset.py`
- `benchmarks/grading-env/stage2_synthetic_smoke.py`
- `benchmarks/grading-env/stage2_power_curve.py`
- `benchmarks/grading-env/stage2_null_identifiability_curve.py`
- `benchmarks/grading-env/stage1_blind_variance_regime.py`
- `tests/test_stage2_analysis.py`
- `benchmarks/grading-env/stage2-analysis-requirements.txt`
- `benchmarks/grading-env/STAGE2_POWER_CURVE_FREEZE_2026-07-10.json`
- `benchmarks/grading-env/STAGE2_POWER_CURVE_FREEZE_2026-07-10.md`
- `benchmarks/grading-env/STAGE2_NULL_IDENTIFIABILITY_FREEZE_2026-07-10.json`
- `benchmarks/grading-env/STAGE2_NULL_IDENTIFIABILITY_FREEZE_2026-07-10.md`

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
- equal task weighting after invalid handling: each task contributes one paired difference, and tasks are not weighted by how many valid cells remain inside that task-condition after exclusion of infrastructure-invalid rows
- small-cluster t inference over the 8 task-level differences

This choice is frozen because the pinned Python stack available here does not provide a trustworthy Kenward-Roger implementation for the required mixed-model path. The script still fits a REML random-intercept mixed model and records its `B - A` coefficient as a concordance check, but the finite-sample inferential quantities used by the frozen report come from the task-cluster estimator above.

This is a substantive pre-analysis execution freeze, not a post-hoc analytic convenience.

## Frozen decision rule

The frozen top-line decision emits exactly three states from the primary task-cluster confidence interval relative to the MME of `0.10`:
- `improvement_supported` if the primary CI lower bound is strictly greater than `0.10`
- `no_meaningful_effect` if the primary CI upper bound is strictly less than `0.10`
- `inconclusive` otherwise

This rule is frozen before any Stage 2 real data and is the basis for distinguishing an interpretable null from a power-limited non-result.

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

The scripts were validated on synthetic datasets before any Stage 2 real data existed.

Frozen synthetic validation commands:

- `python benchmarks/grading-env/stage2_synthetic_smoke.py`
- `PYTHONPATH=src python -m pytest tests/test_stage2_analysis.py -q`

Frozen calibration checks now include:
- positive control: a known positive true effect is recovered within tolerance
- three-state decision control: synthetic cases must produce `improvement_supported`, `no_meaningful_effect`, and `inconclusive`
- null control: `true_effect = 0.0` must not produce `improvement_supported`
- sub-MME control: `true_effect = 0.05` must not produce `improvement_supported`
- sign control: `true_effect = -0.15` must not produce `improvement_supported`
- false-positive calibration: 100 synthetic null datasets with distinct seeds must keep the observed `improvement_supported` rate at or below 10% in the frozen regression suite
- power-curve calibration: `python benchmarks/grading-env/stage2_power_curve.py` freezes the observed `improvement_supported` rate over the synthetic effect/noise grid before Stage 2 data exist
- null-identifiability calibration: `python benchmarks/grading-env/stage2_null_identifiability_curve.py` freezes the observed `no_meaningful_effect` versus `inconclusive` rate at `true_effect = 0.00` across the same synthetic noise profiles
- post-Stage-1 blind regime-matching script: `python benchmarks/grading-env/stage1_blind_variance_regime.py progress.json --output ...` estimates between-task and within-task-condition dispersion without ever computing an A-vs-B contrast

Frozen power-curve highlights from the checked-in artifact:
- at `true_effect = 0.12`, observed `improvement_supported` rates were `0.595` under `low_noise`, `0.170` under `medium_noise`, and `0.095` under `high_noise`
- at `true_effect = 0.18`, observed `improvement_supported` rates were `1.000` under `low_noise`, `0.995` under `medium_noise`, and `0.885` under `high_noise`
- therefore a later non-positive result must be interpreted against the frozen noise-conditional power profile rather than collapsed into a generic null claim

Frozen null-identifiability highlights from the checked-in artifact:
- at `true_effect = 0.00`, observed `no_meaningful_effect` rates were `1.000` under `low_noise`, `1.000` under `medium_noise`, and `0.985` under `high_noise`
- corresponding `inconclusive` rates were `0.000`, `0.000`, and `0.015`
- therefore the frozen decision rule can, in the synthetic regime family currently encoded, still emit an informative `no_meaningful_effect` verdict even when noise is medium or high
- the remaining uncertainty is empirical regime-matching: after Stage 1 closes, blind variance estimation must determine which frozen synthetic regime is closest to the observed run without reading any A-vs-B contrast

Pass criteria:
- the recovered primary effect matches the known positive synthetic effect within the configured tolerance
- the report is generated end-to-end
- the three-state calibration cases emit the intended verdicts
- the negative/null/sub-MME/sign controls all refuse `improvement_supported`
- the null Monte Carlo calibration remains within the frozen bound above
- the power-curve artifacts are regenerated without consulting any Stage 1 summary or Stage 2 real data

## Environment freeze

Use a Python 3.12 virtual environment with:
- `benchmarks/grading-env/stage2-analysis-requirements.txt`

Suggested setup:

`python -m venv .analysis-venv && . .analysis-venv/bin/activate && pip install -r benchmarks/grading-env/stage2-analysis-requirements.txt && pip install -e .`

## Blindness rule

No Stage 1 summary, invalid-rate summary, treatment contrast, or Stage 2 real data may be used to modify these scripts after this freeze. Any later change requires a dated amendment before Stage 2 launch.
