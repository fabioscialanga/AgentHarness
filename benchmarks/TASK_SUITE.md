# Benchmark task suite

This file lists the benchmark task packs approved by the frozen preregistration.

## Pack conventions
- Each task lives under `benchmarks/<task-id>/`.
- `SPEC.md` is the visible task brief.
- `CLAIMS_CONTRACT.template.json` is visible to both conditions and is limited to process, scope, test-execution, and required-artifact claims.
- `HELDOUT_EVALUATION_SUITE.template.json` is not shown to the agent during the run.
- `QUALITY_GATE.md` documents semantic disjunction and non-leakage.
- The future harness must render `__RUN_ID__` before invoking `verify-run` or `evaluate`.

## Approved task ids
- `support-ticket-api`
- `inventory-adjustment-api`
- `webhook-ingestion-service`
- `report-export-job`
- `leave-request-api`
- `incident-escalation-api`
- `refund-approval-api`
- `csv-member-import`