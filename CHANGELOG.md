# Changelog

All notable user-facing changes to AgentHarness are documented here.

The project follows the structure of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and intends to adopt semantic versioning for published releases.

## Unreleased

### Added

- `agentharness check`, a one-command path that snapshots a workspace, generates run and claims envelopes, reexecutes an allowed pytest command, and writes persistent evidence.
- Explicit isolation metadata for the `workspace-copy` executor.
- Provider/model pinning, progressive results, and provider-outage abort handling for Stage B diagnostics.
- Community CI, Apache-2.0 licensing, contribution guidance, security policy, and GitHub issue templates.

### Changed

- Product positioning now emphasizes independent, auditable verification of coding-agent claims.
- Package metadata now declares supported Python versions and project URLs.

### Security

- External and absolute symlinks are rejected when creating a direct-check workspace snapshot.
- Documentation explicitly states that `workspace-copy` is not a network or host-filesystem security sandbox.

## 0.1.0 - Initial alpha

- Project contracts, validation, generation, and bootstrap flows.
- Claim-based `verify-run` with controlled pytest reexecution.
- Deterministic held-out evaluation and benchmark tooling.
