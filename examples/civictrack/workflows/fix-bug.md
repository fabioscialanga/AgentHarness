# Workflow: fix-bug

## Goal
Fix a bug without introducing silent regressions.

## Required inputs
- observed behavior
- expected behavior
- affected area
- severity

## Steps
1. Reproduce or narrow the bug.
2. Add a regression test when feasible.
3. Apply the smallest safe fix.
4. Run relevant checks.
5. Summarize the cause, fix, and residual risk.

## Required checks
- regression test for the bug
- unit tests for touched module
- lint
- type checks when configured
- security-related checks if validation, logging, auth, or uploads changed

## Stop conditions
- bug cannot be reproduced
- fix requires architecture redesign
- fix crosses into auth, upload, or audit model changes
