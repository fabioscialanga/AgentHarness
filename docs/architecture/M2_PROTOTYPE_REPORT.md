# M2 — rapporto del prototipo e roadmap proposta

Data: 7 novembre 2026. Branch: `feat/m2-host-prototype`, basato sul merge M1 `9a892a5`. Il prototipo non installa hook host e non viene eseguito in modo automatico in una sessione Claude Code o Codex. Va sottoposto a revisione architetturale prima di estendere l'Autopilot.

## Cosa è stato realizzato

Un solo evento vendor-neutral `turn_finished`, normalizzato da input `Stop` Claude/Codex. Con `enabled: false`, restituisce `{}` prima di invocare Git. Con `enabled: true`, una modifica tracciata in `pyproject.toml`, `SECURITY.md` o `.github/workflows/` produce al massimo un breve `systemMessage` per fingerprint. Il messaggio suggerisce una verifica mirata, senza avviarla. Lo stato locale di deduplicazione è ignorato da Git. Non ci sono daemon, polling, chiamate LLM, adapter installati o modifiche ai verificatori.

Per prova manuale isolata: `echo '{"hook_event_name":"Stop","stop_hook_active":false}' | agentharness host-event --host codex --project PATH`. Una futura installazione hook dovrà usare la configurazione e la trust review specifiche dell'host. L'attivazione M1 resta distinta dall'installazione degli hook.

## Evidenze e misure

Comando test: `.venv/Scripts/python.exe -m pytest -q tests/test_host_prototype.py tests/test_foundation.py` su Windows Python 3.12: **18 passed**, exit code 0, 0,74 s. I test verificano disabilitazione, nessuna discovery quando disabilitato, singolo suggerimento per modifica significativa, deduplicazione, silenzio sui file ordinari e risposta innocua a payload invalido.

Regressione core in clone Linux Python 3.12 isolato, con sole dipendenze runtime: `python -m pytest -q` sui moduli `test_claim_verify`, `test_direct_check`, `test_foundation`, `test_host_prototype`, `test_level2_reliability`, `test_release_check`, `test_repair_safety`, `test_runtime_features`, `test_validation`: **106 passed**, exit code 0, 18,42 s. I benchmark/Stage 2 non sono stati ripetuti in M2 perché il prototipo non modifica i loro percorsi; il risultato della CI M1 resta distinto.

Microbenchmark locale, Windows Python 3.12, repository temporaneo, `handle_stop` chiamato direttamente:

| Scenario | Ripetizioni | Mediana | Massimo | Messaggi |
| --- | ---: | ---: | ---: | ---: |
| Disabilitato | 100 | 0,155 ms | 1,317 ms | 0 |
| Abilitato, nessuna modifica significativa | 30 | 53,222 ms | 97,946 ms | 0 |
| Abilitato, stessa modifica già segnalata | 30 | 53,774 ms | 86,632 ms | 0 |
| Disabilitato dopo una modifica | 30 | 0,542 ms | 1,171 ms | 0 |

Primo evento significativo: un `systemMessage` di 85 caratteri circa; nessun comando di verifica eseguito. Venti avvii separati di `python -m agentharness host-event --host codex` con stato disabilitato: mediana 131,27 ms, intervallo 118,53–160,11 ms, zero messaggi. Queste misure includono la variabilità del processo Windows e non prevedono la latenza di Claude/Codex. Il prototipo invoca Git una volta per `Stop` abilitato, zero volte se disabilitato. Chiamate LLM del prototipo: **0**. Token inviati direttamente a un modello dal prototipo: **0**; eventuale esposizione del `systemMessage` nel contesto di una sessione host reale è **non misurata**.

Limiti: Claude Code non installato nell'ambiente locale; Codex CLI 0.154.0 presente, ma nessun hook reale attivato. Il comportamento end-to-end degli host resta non verificato. Il fingerprint è sperimentale; file non tracciati, commit già effettuati e cambiamenti fuori dai tre percorsi non generano segnali. Un warning UI non dimostra che una verifica sia stata eseguita.

## Roadmap M2 e criteri di accettazione

1. **Verifica adapter host:** in ambienti temporanei con versioni esplicitamente registrate, installare un hook `Stop` per host, passare payload reali e verificare che gli output seguano il contratto. Misurare latenza p50/p95, chiamate host e token eventualmente aggiunti. Criterio: enable/disable/status veritieri; dopo `disable`, zero messaggi e zero invocazioni Git dell'handler; nessun turno bloccato.
2. **Packaging opt-in:** offrire installazione/rimozione reversibile di hook e una skill di comando dove supportata, con trust review e senza assumere slash command identici. Criterio: installazione esplicita, uninstall pulito e nessuna modifica a configurazioni host preesistenti senza gestione dei conflitti.
3. **Decisioni Autopilot:** aggiungere classificazione incrementale dei cambiamenti e policy configurabili, con deduplicazione legata a commit/configurazione e limiti di costo. Criterio: niente LLM sul percorso ordinario, overhead misurato e soglia concordata, nessun test/scansione non autorizzato.
4. **Advisor opzionale:** progettare provider simulato e budget prima di qualunque chiamata reale. Criterio: fallback deterministico, costo contabilizzato quando disponibile e separazione rigorosa tra suggerimento ed evidenza di verifica.

Checkpoint: fermarsi qui per revisione architetturale. Non installare automaticamente gli adapter, non implementare l'Autopilot completo e non effettuare merge M2.
