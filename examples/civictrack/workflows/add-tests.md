# Workflow: add-tests

## Goal
Increase coverage for existing behavior without changing production logic unless clearly required.

## Rules
- prefer meaningful cases over raw quantity
- include unhappy-path coverage where relevant
- avoid brittle implementation-coupled assertions

## Required checks
- test suite for new tests
- lint if test style tools are configured
