# Adapter Codex (M2 sperimentale)

L'adapter aggiunge un solo hook `Stop` di progetto in `.codex/hooks.json`. Richiede un'installazione esplicita e la successiva autorizzazione nell'interfaccia Codex. Usa l'AgentHarness installato nello stesso interprete Python con cui esegui `install`.

```sh
agentharness install --host codex --project .
```

La CLI chiede conferma prima di modificare il file. Per uno script già autorizzato dall'utente, passa `--yes`. Se `.codex/hooks.json` contiene hook di altri strumenti, AgentHarness li conserva. Se il JSON è malformato o non può essere preservato in sicurezza, l'installazione si ferma senza sostituirlo.

Apri Codex nel progetto. Se richiesto, autorizza la directory; poi usa `/hooks` per leggere e autorizzare la definizione `AgentHarness Stop adapter`. AgentHarness non modifica il trust di Codex. Una definizione nuova o modificata può richiedere una nuova autorizzazione. [Documentazione ufficiale degli hook Codex](https://learn.chatgpt.com/docs/hooks).

```sh
agentharness enable --project .
agentharness status --project . --json
agentharness disable --project .
agentharness uninstall --host codex --project .
```

`enable` permette un breve suggerimento dopo un turno `Stop` se Git rileva una modifica tracciata e significativa. `disable` sopprime il suggerimento, ma Codex può ancora avviare il processo hook. `uninstall` rimuove solo la definizione AgentHarness; non cancella configurazione M1, fingerprint, evidenze o hook di altri strumenti. Per eliminare il costo del processo hook, usa `uninstall`. Nessun test o scansione viene avviato automaticamente.

Limiti: il prototipo osserva modifiche tracciate rispetto a `HEAD` in `pyproject.toml`, `SECURITY.md` e `.github/workflows/`; non osserva file non tracciati né commit già effettuati. `status --json` M1 può ancora riportare `host_adapter_installed: false`: quel campo non inventaria gli hook installati. Se l'interprete Python usato all'installazione viene spostato, rimuovi e reinstalla l'adapter. L'integrazione Claude Code e una sessione Codex reale su Linux non sono state verificate. L'Autopilot completo non fa parte di M2.
