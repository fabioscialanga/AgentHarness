# Codex adapter (experimental M2)

The adapter adds one project-local `Stop` hook to `.codex/hooks.json`. Installation is explicit, followed by a separate trust review in Codex. It uses the AgentHarness installation in the Python interpreter that runs `install`.

```sh
agentharness install --host codex --project .
```

The CLI asks for confirmation before changing the file. For user-authorized automation, pass `--yes`. Existing hooks from other tools are preserved. Malformed JSON or a structure that cannot be safely preserved causes installation to stop without replacing the file.

Open Codex in the project. Trust the directory if prompted, then use `/hooks` to review and trust `AgentHarness Stop adapter`. AgentHarness does not change Codex trust. New or modified hook definitions may need another review. See the [official Codex hooks documentation](https://learn.chatgpt.com/docs/hooks).

```sh
agentharness enable --project .
agentharness status --project . --json
agentharness disable --project .
agentharness uninstall --host codex --project .
```

`enable` allows a short suggestion after a `Stop` turn when Git finds a significant tracked change. `disable` suppresses the suggestion, although Codex may still start the hook process. `uninstall` removes only the AgentHarness definition; it retains M1 configuration, fingerprints, evidence, and other tools' hooks. Use `uninstall` to eliminate the hook process cost. No tests or scans run automatically.

Limits: the prototype watches tracked differences from `HEAD` in `pyproject.toml`, `SECURITY.md`, and `.github/workflows/`. It does not detect untracked files or already committed changes. M1 `status --json` can still report `host_adapter_installed: false`; that field does not inventory installed hooks. If the Python interpreter used during installation moves, uninstall and reinstall the adapter. Claude Code integration and a real Codex session on Linux have not been verified. Full Autopilot is outside M2.
