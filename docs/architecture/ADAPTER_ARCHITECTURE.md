# M2 — contratto adapter proposto

```text
Host Stop JSON ──> adapter Claude/Codex ──> evento turn_finished
                                              │
                         stato M1 enabled ────┤
                                              ▼
                                  decisione deterministica
                                              │
                                  risposta UI non bloccante
```

Il comando vendor-neutral del prototipo è `agentharness host-event --host claude|codex --project PATH`. Legge un oggetto JSON di hook da stdin e scrive sempre un oggetto JSON su stdout. `host_adapters.normalize_stop` valida e normalizza il solo `Stop`; `autopilot.decide_stop` decide senza conoscere l'host; `host_prototype.handle_stop` applica lo stato M1 e raccoglie solo i percorsi Git osservabili. Nessun adapter installa hook o chiama un modello.

## Contratto evento v0

| Campo | Significato |
| --- | --- |
| `host` | `claude` o `codex`, fornito dall'invocazione adapter. |
| `kind` | `turn_finished`; derivato da `hook_event_name: Stop`. |
| `repeated_stop` | Copia validata di `stop_hook_active`; se vero non emette nulla. |
| `project` | Directory esplicita passata alla CLI, mai ricavata automaticamente da dati non fidati del payload. |

La decisione v0 considera significative modifiche tracciate rispetto a `HEAD` in `pyproject.toml`, `SECURITY.md` e `.github/workflows/`. Quando ne trova, restituisce un solo `systemMessage` consultivo. Memorizza solo un fingerprint locale in `.agentharness/host-prototype.json`, ignorato da Git, per non ripetere lo stesso avviso. Non legge contenuti del prompt, non lancia test/scansioni e non blocca/continua il turno. Un errore dell'hook produce `{}` e non interrompe l'host. Con `enabled: false`, il percorso termina prima di qualsiasi comando Git o scrittura.

## Confini e rischi

- **Core deterministico:** carica configurazione, classifica il piccolo insieme di percorsi e decide. Nessun provider LLM.
- **Adapter host:** traduce l'evento e il formato di risposta. Configurazioni hook specifiche dell'host saranno pacchettizzate solo dopo test reali e trust review.
- **Autopilot futuro:** aggiungerà policy, deduplicazione robusta, budget, priorità e routing verso il verificatore esistente. Il prototipo non è un gate.
- **Advisor futuro:** opzionale e separato, solo per casi che richiedono giudizio; non può derogare a policy obbligatorie.
- **Sicurezza e UX:** i comandi hook ricevono dati dall'host; payload non stampato nei log. `systemMessage` può essere visibile come warning, quindi il testo resta breve. Il fingerprint usa contenuto dei soli file osservati e non lo persiste. Non installare automaticamente hook di progetto: Codex richiede trust review e Claude ha proprie impostazioni.

Il prototipo non intercetta file non tracciati e non rileva cambiamenti già committati; questi sono limiti intenzionali del singolo evento sperimentale. La decisione non equivale a una verifica: un controllo produce evidenza solo se l'utente o l'host invoca esplicitamente `check`/`verify-run`.
