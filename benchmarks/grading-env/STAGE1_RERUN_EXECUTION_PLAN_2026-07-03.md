# Stage 1 rerun execution plan — 2026-07-03

This plan operationalizes `MINI_PREREG_RERUN_2026-07-03.md` after the completed diagnostic run showed a contiguous provider-outage contamination block across `order_index` 21..36.

## Objective

Produce a fresh Stage 1 A/B rerun whose result is usable for treatment interpretation under the contamination gate defined in `MINI_PREREG_RERUN_2026-07-03.md`.

## Non-goal

Do not treat the already completed run at `stage-1-diagnostics-seed-20260701-published-e42d82f` as confirmatory A/B evidence. Keep it as an operational diagnosis artifact only.

## Preconditions before launch

1. Use published repo state from this amendment series or later.
2. Keep the current repaired grader / wheelhouse / fixture stack unchanged unless a new dated amendment is added.
3. Pin provider and model explicitly at launch time.
4. Launch from a clean frozen worktree rather than a dirty active checkout.

## Recommended launch mechanics

1. Materialize a fresh frozen worktree at the published commit to be rerun.
2. Use a new run directory under `benchmarks/runs/`.
3. Persist `cell-order.json` at launch.
4. Keep the existing explicit subprocess timeout enforcement.
5. Keep the existing fresh-cell rematerialization behavior for reruns after invalids.

## Operational anti-contamination procedure

Because the completed run failed via one contiguous provider outage window, the rerun should be monitored operationally rather than left completely unattended.

### Live gate during execution

If a block of 4 consecutive cells becomes `provider_unavailable` / `harness_invalid`, stop the run and classify it immediately as contaminated rather than letting the rest complete and then arguing over it later.

Reason: the completed run showed that a mid-run outage block can create an analyzable-looking file tree while still destroying causal interpretability.

### End-of-run gate

After the run finishes, read `stage1-summary.json` and evaluate the exact contamination gate from `MINI_PREREG_RERUN_2026-07-03.md`:
- total provider-unavailable cells <= 4
- absolute condition difference <= 1
- no contiguous provider-failure block of length >= 4
- final summary present

If any condition fails, classify the rerun as contaminated and do not claim `B > A` or `A > B`.

## Primary reporting rule

If the contamination gate passes, report first:
- mean score over all 24 scheduled cells per condition,
- with invalid/provider-unavailable cells counted as `0.0`.

Then report sensitivity summaries:
- mean over valid completed cells only,
- ceiling counts,
- under-ceiling counts.

## Minimal user-facing interpretation template

### If the gate passes
- "The rerun met the contamination gate. Under the preregistered primary estimand, condition X scored Y vs Z for condition W."

### If the gate fails
- "The rerun completed but failed the contamination gate, so it cannot be used as clean evidence for an A/B claim."

## Immediate recommendation

Do not spend more repo time polishing benchmark claims until the rerun either:
1. passes the contamination gate, or
2. shows that provider instability is persistent enough to require a protocol change.
