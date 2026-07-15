# GitHub Actions integration

AgentHarness can turn a pull-request test claim into a persistent verification artifact. The repository includes a copyable workflow at:

`examples/github-actions/agentharness-check.yml`

## What the workflow does

1. Checks out the pull request.
2. Installs the target project and AgentHarness.
3. Runs `agentharness check` against the checked-out workspace.
4. Reexecutes `python -m pytest -q` in a persistent workspace copy.
5. Uploads the run envelope, claims, stdout, stderr, hashes, and verification report even when verification fails.

## Install it

After the `0.1.0` package is published on PyPI:

```bash
mkdir -p .github/workflows
cp examples/github-actions/agentharness-check.yml .github/workflows/agentharness.yml
```

Before that release, replace the PyPI install line in the copied workflow with a commit-pinned Git install:

```bash
python -m pip install \
  "agentharness @ git+https://github.com/fabioscialanga/AgentHarness.git@3d17631808481671d06740769d5ea30d41198bc0"
```

## Adapt it to the project

The template assumes:

```bash
python -m pip install -e .
python -m pytest -q
```

Change the project installation line if the repository uses another dependency manager. The verification command must remain one of the pytest forms accepted by AgentHarness.

For scope checks, add path rules:

```bash
--allowed-path "src/*" \
--allowed-path "tests/*" \
--forbidden-path "secrets/*"
```

## CI behavior

AgentHarness uses stable exit codes:

- `0`: all blocking claims are supported
- `1`: a blocking claim is unsupported or inconclusive
- `2`: invalid input or invalid verification configuration

The evidence upload step uses `if: always()` so a failed verification still leaves diagnostic artifacts.

## Isolation boundary

The command working directory is a persistent workspace copy. This protects ordinary relative writes from landing in the original checkout, but it is not a security sandbox:

- the original workspace is not OS-write-protected
- network access is not isolated
- absolute host paths are not isolated

Do not use the current executor to run untrusted code on a sensitive runner. See `SECURITY.md`.
