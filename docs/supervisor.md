# Supervise a long-running job

AgentHarness can run a command in the background, preserve its state and logs, enforce preflight and timeout rules, retry selected exit codes, verify success, and hash declared artifacts.

This is a local process supervisor, not a container or security sandbox. Commands inherit the current environment and can access anything allowed to the current user. Command arguments, paths, exit metadata, and hashes are persisted in `state.json`; do not put secrets in the YAML or command-line arguments. Pass credentials through the inherited environment or the external tool's secret store.

## Job file

```yaml
schema_version: 1
job_id: nightly-research
workspace: /absolute/path/to/workspace

preflight:
  - python3
  - -c
  - import required_package

command:
  - python3
  - run_research.py
  - --output
  - outputs/report.json

timeout_seconds: 3600
retry:
  max_attempts: 2
  backoff_seconds: 10
  retry_on_exit_codes: [1]

success_check:
  - python3
  - -c
  - "import json; json.load(open('outputs/report.json'))"

artifacts:
  - outputs/report.json
  - outputs/*.log
```

Commands must be YAML lists. AgentHarness does not invoke a shell implicitly. If a workflow deliberately needs a shell, make that explicit in the command, for example `bash`, `-lc`, and the script text.

Relative workspace paths are resolved from the job file. Artifact paths and globs must remain inside the workspace. State defaults to:

```text
<workspace>/.agentharness/supervisor/<job-id>/
```

Set `state_dir` in the YAML when state must live outside the workspace.

## Commands

Start detached:

```bash
agentharness supervise job.yaml
```

Run synchronously:

```bash
agentharness supervise job.yaml --foreground
```

Inspect, stop, or resume the current run:

```bash
agentharness status job.yaml --json
agentharness stop job.yaml
agentharness resume job.yaml
```

Resume keeps the same run and existing attempts. It is allowed after a failed preflight, timeout, stop, failed command, or failed verification only while retry budget remains. A successful run is immutable; start a new run instead.

## Terminal states

- `succeeded`: command, optional success check, and artifact checks passed.
- `preflight_failed`: the main command was not started.
- `failed`: command exited unsuccessfully and no allowed retry remains.
- `timed_out`: the process group exceeded its timeout and was terminated.
- `verification_failed`: the command exited successfully but the success check or required artifacts failed.
- `stopped`: the user stopped the worker.

Each preflight, attempt, and success check has separate stdout/stderr files and SHA-256 hashes in `state.json`. Declared artifact files are recorded with size and SHA-256.

## Current v1 boundary

The v1 deliberately does not include a dashboard, distributed workers, provider-specific quota APIs, or notification plugins. Scheduling and notifications can call the stable CLI and inspect `status --json`. These features should be added only after repeated real use demonstrates the need.

Operational use is tracked in [`supervisor-dogfood.md`](supervisor-dogfood.md). The product usefulness verdict remains pending until its explicit gate is met.
