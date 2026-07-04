# Mini-preregistration for fresh Stage 1 rerun — 2026-07-03

Context: the completed Stage 1 diagnostic run at `stage-1-diagnostics-seed-20260701-published-e42d82f` produced valid benchmark results but also substantial asymmetric provider contamination.

Observed contamination from the completed run:
- 48 scheduled cells total
- 16 invalid cells total
- all 16 invalid cells were also classified as `provider_unavailable`
- contamination was asymmetric by condition:
  - `A-baseline`: 10 provider-unavailable / invalid cells
  - `B-agentharness`: 6 provider-unavailable / invalid cells
- the contaminated cells clustered contiguously in execution order (`order_index` 21 through 36), consistent with a provider-availability window rather than a task-specific benchmark failure

Because of that asymmetry, the completed run may be used for operational diagnosis only and not as clean causal evidence that condition B outperforms condition A.

## 1. Goal of the rerun

Run a fresh Stage 1 A/B diagnostic on the published benchmark stack to estimate whether `B-agentharness` outperforms `A-baseline` on benchmark score under materially cleaner and more balanced provider availability.

## 2. Frozen execution state

Unless a later dated amendment explicitly changes this, the rerun should use:
- published repo state from the amendment series current as of 2026-07-03, with `origin/main` at or after commit `e42d82feb66be9b3af05528710e4cb667161ab6c`
- the same Stage 1 task set currently encoded in `benchmarks/grading-env/run_stage1_diagnostics.py`
- the same condition labels:
  - `A-baseline`
  - `B-agentharness`
- the same replicate labels:
  - `r1`
  - `r2`
  - `r3`
- provider/model pinned explicitly at launch time

## 3. Scheduled cells

The rerun target remains 48 cells total:
- 8 tasks
- 2 conditions
- 3 replicates

The analysis unit is the cell.

## 4. Operational contamination gate

The rerun is analyzable for A/B effect claims only if all of the following hold:

1. `provider_unavailable_count` across the full run is at most 4 total cells.
2. The absolute difference in `provider_unavailable_count` between conditions is at most 1 cell.
3. No long contiguous provider-failure block appears that spans 4 or more consecutive `order_index` values.
4. The final run completes with real `stage1-summary.json` output.

If any of these four conditions fails, the rerun is classified as operationally contaminated and must not be used to claim `B > A` or `A > B`.

## 5. Primary estimand

If the operational contamination gate passes, the primary estimand is:
- mean benchmark score over all 24 scheduled cells per condition,
- counting any remaining `harness_invalid` / `provider_unavailable` cell as score `0.0`.

Reason: this preserves condition-level accountability over the full scheduled run while tolerating only low, balanced residual operational noise.

## 6. Sensitivity analysis

If the operational contamination gate passes, also report:
- mean score on valid completed cells only,
- ceiling count (`score >= 1.0`) per condition,
- under-ceiling count (`score < 1.0`) per condition.

If the primary and sensitivity readouts materially disagree, prefer the more conservative interpretation and avoid strong treatment claims.

## 7. Interpretation rule

For this rerun, a directional claim that `B-agentharness` beats `A-baseline` requires both:
1. the contamination gate to pass, and
2. `B-agentharness` to exceed `A-baseline` on the primary estimand.

Otherwise, the correct conclusion is either:
- no clean evidence of advantage, or
- operationally contaminated rerun.

## 8. What this amendment does not change

This mini-preregistration does not change:
- the repaired hidden graders,
- the refreshed offline grading wheelhouse,
- the published representative benchmark fixtures,
- the fresh-cell rerun behavior already enforced in the launcher,
- the explicit subprocess timeout enforcement already present in `run_stage1_diagnostics.py`.

## 9. Immediate next-step recommendation

Before relaunch, prefer an execution plan that reduces outage-window asymmetry at the scheduler level (for example, avoid treating a single long provider outage block as analyzable benchmark evidence). This note records the decision rule even if the launch mechanics stay otherwise unchanged.
