# AGENTS.md

## Project identity
Project: CivicTrack
Type: open source civic issue tracking API
Primary goal: build a simple, reliable, self-hostable API for civic reporting workflows.

## Core rules
- Prefer simple and explicit code over abstractions that hide behavior.
- Keep business rules out of HTTP route handlers.
- Do not modify authentication, upload handling, audit logging, or dependency set without human review.
- Never hardcode secrets, credentials, or tokens.
- Every bug fix must leave a regression test when technically feasible.
- If a task is ambiguous, constrain the change instead of widening scope.

## Architecture rules
- API layer handles transport only.
- Domain layer owns workflows and state transitions.
- Validation logic stays centralized and testable.
- Persistence code must not absorb business rules that belong in domain services.
- Audit events should be generated for meaningful state changes.

## Quality gates
Before considering a task done:
- run format/lint/type checks when configured
- run relevant unit tests
- run integration smoke tests when API or persistence behavior changes
- verify no secrets were introduced
- summarize files changed, tests run, and residual risks

## Security rules
- Validate all user-controlled inputs.
- Restrict uploaded file types and size.
- Avoid logging raw personal contact data unless explicitly required and reviewed.
- Treat email and webhook integrations as optional and failure-prone.
- Add safe error handling for external calls.

## Risk boundaries
Human review required for:
- auth or permission changes
- audit model changes
- upload handling changes
- dependency additions or removals
- CI pipeline changes

## Working style
- Make the smallest viable change.
- Prefer readability over cleverness.
- If you touch behavior, touch tests.
- If you fix a bug, protect it with a regression test.
