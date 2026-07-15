# Security Policy

## Supported versions

AgentHarness is currently alpha software. Security fixes are applied to the latest commit on `main` until the first stable release line is established.

## Reporting a vulnerability

Do not report vulnerabilities in a public GitHub issue.

Use GitHub's private vulnerability reporting for the repository:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include affected version or commit, impact, reproduction steps, and any proposed mitigation.

If private vulnerability reporting is not available, contact the repository owner privately through their GitHub profile before sharing technical details.

Please do not include live credentials, access tokens, private repositories, or personal data in the report.

## Important execution boundary

The current `workspace-copy` executor used by `agentharness check` is not a security sandbox.

It provides a persistent copy as the command working directory, but it does not currently:

- disable network access
- isolate the rest of the host filesystem
- make the original workspace read-only at the operating-system level
- impose container CPU or memory limits

Do not use it to execute untrusted code on a sensitive host. Use an isolated machine or container until a strict executor is available.

## Disclosure process

The maintainer will acknowledge a complete private report, assess severity, prepare a fix and regression test where practical, and coordinate disclosure after affected users have a reasonable opportunity to update.
