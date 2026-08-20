# Changelog

All notable user-facing changes to AgentHarness are documented here.

The project follows the structure of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and intends to adopt semantic versioning for published releases.

## Unreleased

No user-facing changes yet.

## 0.2.0 - 2026-08-18

### Added

- `agentharness review` for independently reexecuting behavioral acceptance checks from a trusted plan and test bundle kept outside the reviewed workspace.
- Durable behavioral review reports with actionable remediations and provenance hashes for the plan, test bundle, and reviewed workspace.
- A repeatable FAIL-to-PASS behavioral review cookbook.

### Changed

- Behavioral checks run sequentially in just-in-time workspace copies so one check cannot create a false pass by contaminating a later staged copy.
- Workspace fingerprints now bind directory structure, entry type, permissions, symlink targets, and file content.
- Review output may target an existing empty directory, matching standard temporary-directory workflows.
- Import and collection failures caused by reviewed source are reported as actionable findings; malformed or missing trusted tests remain fail-closed diagnostics.

### Security

- Review plan identifiers reject dot-path components and oversized values before they are used as artifact paths.
- Original workspace and trusted test-bundle fingerprints are rechecked before and after every behavioral check; mutation invalidates the review.

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
