# Releasing AgentHarness

AgentHarness publishes with PyPI Trusted Publishing. No long-lived PyPI token belongs in GitHub secrets.

## One-time PyPI setup

Create a pending publisher at PyPI with these exact values:

- PyPI project name: `agentharness-verifier`
- GitHub owner: `fabioscialanga`
- GitHub repository: `AgentHarness`
- Workflow filename: `release.yml`
- Environment name: `pypi`

Also create the `pypi` environment in the GitHub repository settings. Optional environment reviewers can protect production publication.

## Release gate

Before tagging:

```bash
python scripts/check_release.py --tag v0.1.0
python -m pytest -q
python -m build
python -m twine check dist/*
```

Run the `Release` workflow manually with `release_tag=v0.1.0`. A manual run validates and uploads the distributions as a workflow artifact but does not publish them.

## Publish

Only after the dry run and normal CI are green:

```bash
git tag -a v0.1.0 -m "AgentHarness 0.1.0"
git push origin v0.1.0
```

The tag-triggered workflow:

1. validates tag, package version, and dated changelog entry
2. builds wheel and source distribution
3. runs `twine check`
4. uploads the distributions and creates build-provenance attestations
5. publishes to PyPI through OIDC Trusted Publishing
6. creates the GitHub Release only after PyPI publication succeeds

## Verify the public release

```bash
python3 -m venv /tmp/agentharness-release-check
/tmp/agentharness-release-check/bin/python -m pip install agentharness-verifier==0.1.0
/tmp/agentharness-release-check/bin/agentharness --help
```

Then run `agentharness check` against a small external workspace and confirm that `verify-report.json` exists.

Do not move a version out of the changelog or reuse a published version. PyPI releases are immutable.
