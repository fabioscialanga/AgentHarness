# M3 DEP consultation / Consultazione DEP M3

## English

`agentharness dep-assess` is an explicit, read-only consultation of PEP 621 dependency changes in the **working tree**. It reuses M3 detection and evidence matching. It does not run tests, scans, an LLM, or any artifact command. It does not enable AgentHarness or install a host hook. It works independently of project `enable`/`disable`; Codex Stop remains unchanged.

```text
agentharness dep-assess --project <git-root> --json
agentharness dep-assess --project <git-root> --control DEP-PEP621-PYTEST-V0 --json
agentharness dep-assess --project <git-root> --control-run <run-id>
```

The first form reports detection. If it finds a risk, evidence is `unknown:control_not_selected`; it never creates an approved control. `--control` selects **only** the existing fixed mapping for this invocation. It does not persist approval or execute the mapped command. With no evidence, the result is `uncovered`. An unsupported mapping is `unknown:control_mapping_unapproved`. Alternatively, `--control-run` selects a `local-capture` binding from a prior *explicit* `check --approve-dep-control`; the run id must be a safe single path component. These two options are mutually exclusive.

To create a binding, the user must separately request the existing command:

```text
agentharness check --workspace <git-root> --command "python -m pytest -q tests/test_dep.py" --approve-dep-control --run-id dep-check
agentharness dep-assess --project <git-root> --control-run dep-check --json
```

The second line reads evidence only. A selected binding is checked for schema, provenance, fixed mapping and scope before matching; the matcher still verifies state, interpreter, artifact hashes, freshness, and contradictory results. Selection does not make an artifact trusted by itself.

JSON schema `m3.dep-assess.v0` has top-level `schema_version`, `project`, `detection`, and `evidence`. `detection.status` is `risk`, `no_change`, or `abstain`; it also gives `reason`, `rule_id`, `description`, `scope`, and `state_id` when available. `evidence` is `null` when no risk was detected. For a risk, `evidence.status` is `covered`, `uncovered`, `failed`, or `unknown`, with `reason`, `control_mapping_id`, `control_run`, `control_binding`, `run_ids`, and project-relative `artifact_refs`. Artifact references identify **candidates**, not proof that a run is trustworthy. `covered` means only that the approved DEP check covers this risk under the v0 contract; it does **not** say the dependency or code is safe. A successful consultation exits 0 even for `abstain` or `unknown`; invalid project/CLI input exits 2.

The CLI has no committed-range selector. A clean HEAD can therefore produce `abstain:committed_base_unspecified`. M3 v0 recognizes only the fixed `DEP-PEP621-PYTEST-V0` mapping and the supported PEP 508 subset. The 24-hour evidence policy, input budgets, and state consistency checks remain unchanged.

## Italiano

`agentharness dep-assess` consulta esplicitamente e in sola lettura le modifiche alle dipendenze PEP 621 nel **working tree**. Riutilizza detection e matching M3. Non esegue test, scansioni, LLM o comandi contenuti negli artifact; non abilita il progetto né installa hook. Funziona indipendentemente da `enable`/`disable`. L'hook Codex Stop resta invariato.

```text
agentharness dep-assess --project <radice-git> --json
agentharness dep-assess --project <radice-git> --control DEP-PEP621-PYTEST-V0 --json
agentharness dep-assess --project <radice-git> --control-run <run-id>
```

Senza controllo selezionato, un rischio produce `unknown:control_not_selected`. `--control` seleziona **solo** il mapping fisso già approvato per questa consultazione: non salva l'approvazione e non lancia il comando. Se mancano evidenze, l'esito è `uncovered`. Un mapping diverso dà `unknown:control_mapping_unapproved`. `--control-run` seleziona invece un binding `local-capture` creato da un precedente `check --approve-dep-control` richiesto esplicitamente dall'utente. Le due opzioni sono alternative.

```text
agentharness check --workspace <radice-git> --command "python -m pytest -q tests/test_dep.py" --approve-dep-control --run-id dep-check
agentharness dep-assess --project <radice-git> --control-run dep-check --json
```

La seconda riga legge soltanto gli artifact. Il binding selezionato deve avere schema, provenienza, mapping e scope corretti; il matcher verifica inoltre stato Git, interprete, hash, freschezza e risultati contraddittori. Se la detection è `no_change` o `abstain`, `evidence` è `null`. Quando c'è un rischio, `evidence.status` è `covered`, `uncovered`, `failed` o `unknown`, con motivazione e riferimenti relativi al progetto. `covered` indica soltanto copertura del controllo DEP pertinente, **non** sicurezza generale della dipendenza o del codice. La consultazione valida termina con codice 0 anche per `unknown` e `abstain`; input non valido termina con 2.

Il comando non seleziona range di commit: su HEAD pulito può restituire `abstain:committed_base_unspecified`. Restano invariati mapping v0, subset PEP 508, policy delle 24 ore, limiti di lettura e verifiche dello stato. `check`, `verify-run` e `status` conservano il significato precedente.
