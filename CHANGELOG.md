# Changelog

All notable user-facing changes to AgentHarness are documented here.

The project follows the structure of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and intends to adopt semantic versioning for published releases.

## Unreleased

No user-facing changes yet.

## 0.1.0 - 2026-07-15

### Added

- Project contracts, validation, generation, and bootstrap flows.
- `agentharness check`, a one-command path that snapshots a workspace, generates run and claims envelopes, reexecutes an allowed pytest command, and writes persistent evidence.
- `agentharness verify-run` for explicit run and claims envelopes.
- Explicit isolation metadata for the `workspace-copy` executor.
- Deterministic held-out evaluation and benchmark tooling.
- Provider/model pinning, progressive results, and provider-outage abort handling for Stage B diagnostics.
- Community CI across Python 3.11, 3.12, and 3.13, with the frozen benchmark grading suite kept on Python 3.12.
- Apache-2.0 licensing, contribution guidance, security policy, and GitHub issue templates.

### Changed

- Product positioning now emphasizes independent, auditable verification of coding-agent claims.
- Package metadata now declares supported Python versions and project URLs.
- The PyPI distribution is named `agentharness-verifier`; the import package and CLI remain `agentharness`.

### Security

- External and absolute symlinks are rejected when creating a direct-check workspace snapshot.
- Documentation explicitly states that `workspace-copy` is not a network or host-filesystem security sandbox.
