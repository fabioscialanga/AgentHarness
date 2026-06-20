# Workflow: refactor-module

## Goal
Improve structure or readability while preserving behavior.

## Rules
- no hidden behavioral change
- no dependency changes unless explicitly approved
- keep refactor bounded to the declared module

## Required checks
- unit tests for affected module
- lint
- type checks when configured
- integration smoke tests if public behavior may be indirectly affected
