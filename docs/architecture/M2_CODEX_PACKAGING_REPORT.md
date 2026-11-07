# M2 — report del packaging controllato Codex

Data: 7 novembre 2026. Branch: `feat/m2-host-prototype`. Prova su Windows, `codex-cli 0.154.0`, Python 3.12.10 e modello host `gpt-5.6-luna`. Repository Git temporaneo `C:\AgentAi\AgentHarness\m2_adapter_probe`; nessun hook globale, nessun bypass del trust, nessun merge.

## Esito funzionale

Il progetto temporaneo conteneva un `pyproject.toml` committato e poi modificato. Comandi:

```text
agentharness enable --project C:\AgentAi\AgentHarness\m2_adapter_probe
agentharness install --host codex --project C:\AgentAi\AgentHarness\m2_adapter_probe --yes --json
codex.cmd -C C:\AgentAi\AgentHarness\m2_adapter_probe -m gpt-5.6-luna --no-alt-screen --sandbox read-only
```

La TUI ha richiesto trust del progetto, poi revisione dell'hook con `/hooks`. Dopo il trust esplicito, un turno `Reply exactly INSTALLED; do not use tools.` ha mostrato `↳ Hook · AgentHarness: modificati pyproject.toml. Valuta un controllo mirato prima del rilascio.` Non sono partiti test o scansioni. Una seconda `install` ha dato `changed: false` e hash SHA-256 del file invariato. Dopo `disable`, un turno TUI non ha prodotto un nuovo suggerimento; il processo hook resta comunque installato e può essere avviato dall'host. `uninstall --yes --json` ha dato `changed: true`; una seconda chiamata `changed: false`. In una nuova TUI, `/hooks` indicava `Stop` con zero hook installati e zero attivi. La directory temporanea è stata rimossa dopo la prova.

## Test e regressioni

I test `test_codex_adapter.py` coprono preservazione di hook estranei, installazione/rimozione ripetute, consenso, JSON malformato e duplicato, modifica di un hook AgentHarness, concorrenza rilevata, errore di `os.replace`, quoting e invocazione del comando con percorsi contenenti spazi, lock e symlink. Il set mirato Windows `test_codex_adapter.py`, `test_host_prototype.py`, `test_foundation.py` ha dato **46 passed in 2,77 s**, exit 0. La regressione core in un clone Git pulito Linux `python:3.12`, dal commit `064430f` con dipendenze installate, sui nove moduli core della CI più `test_host_prototype.py` e `test_codex_adapter.py`, ha dato **134 passed in 26,67 s**, exit 0. Benchmark/Stage 2: **NOT RUN**.

Verifica finale dopo l'aggiunta dei test di ownership e dei casi di configurazione: 49 test mirati passati nel virtualenv Windows. La selezione core e M2 della nuova matrice CI, eseguita in cloni Git puliti Linux con dipendenze installate, ha dato **137 passed** su Python 3.11 (20,21 s), **137 passed** su Python 3.12 (15,59 s) e **137 passed** su Python 3.13 (15,48 s), tutti con exit 0. Questi sono risultati locali; l'esito di GitHub Actions sulla PR va registrato separatamente.

## Misure

Nel virtualenv Windows, 30 invocazioni ciascuna, payload sintetico `{"hook_event_name":"Stop","stop_hook_active":false}`:

| Percorso | p50 | p95 | Massimo | Messaggi |
| --- | ---: | ---: | ---: | ---: |
| Avvio Python (`python -c pass`) | 52,85 ms | 59,55 ms | 73,32 ms | 0 |
| Hook enabled, fingerprint già visto | 231,13 ms | 267,07 ms | 470,34 ms | 0 |
| Hook disabled | 173,16 ms | 220,91 ms | 230,86 ms | 0 |
| Primo fingerprint nuovo, una prova | 264,22 ms | non stimabile | 264,22 ms | 1 |

Sei turni reali `codex exec` con hook installato e trusted, tre enabled e tre disabled, hanno avuto tempi complessivi rispettivamente `[7197,5, 7620,5, 5994,9]` ms (mediana 7197,5) e `[6443,7, 6937,4, 5955,8]` ms (mediana 6443,7). Tutti hanno prodotto 5 token di output del modello secondo l'evento `turn.completed`. Questi tempi comprendono startup Codex, rete e generazione del modello; sei campioni non permettono di attribuire causalmente la differenza di 754 ms all'hook. La TUI ha mostrato il messaggio nel turno enabled; non è stata ottenuta una misura isolata della latenza percepita nella TUI. Il processo AgentHarness non chiama LLM e non esegue verifiche.

## Limiti

I dettagli di concorrenza, rollback, quoting, trust e serializzazione sono in [CODEX_ADAPTER_LIFECYCLE.md](CODEX_ADAPTER_LIFECYCLE.md). Il trust esistente di una vecchia definizione non autorizza una definizione nuova: Codex può richiedere una nuova revisione dopo reinstallazione o cambio dell'interprete. Nessuna prova è stata eseguita su Linux con una sessione Codex reale. Nessun adapter Claude Code è stato installato. Fermarsi qui per revisione indipendente prima di estendere l'Autopilot o effettuare merge.
