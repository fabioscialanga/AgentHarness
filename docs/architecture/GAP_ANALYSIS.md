# M0 — gap analysis e proposta M1

Riferimento: [AS_IS_AUDIT.md](AS_IS_AUDIT.md). Questa è una proposta tecnica, non una dichiarazione di funzionalità già implementate.

## Principi e lacune

| Principio | Stato attuale e gap |
| --- | --- |
| Zero Overhead | I comandi attuali sono su richiesta, quindi non c'è daemon. Manca però una modalità Autopilot persistente e leggera; la copia del workspace di `check` è costosa e va invocata solo per decisioni motivate. |
| AI on Demand | Il nucleo di verifica è deterministico. Manca una decisione locale su quando consigliare controlli; M1 non richiede LLM. |
| Reuse First | Esistono verifica, policy di riesecuzione e JSONL riusabili. Manca un contratto adapter host. Le capacità native delle versioni di Claude Code e Codex, così come Spec Kit e Bansat, sono non verificate: prima di implementare hook o slash command servono prove sulle API effettive. |
| Evidence Over Claims | `verify-run` e `check` forniscono evidenze indipendenti. Per Autopilot mancano legame tra evidenza, commit/configurazione e validità temporale; non si può riusare ciecamente una traccia precedente. |

## Decisione architetturale

**Evolvere il package attuale**, con un piccolo modulo autonomo di configurazione/decisione accanto al motore di verifica. Un nuovo core separato duplichererebbe CLI, artefatti e policy senza necessità dimostrata. Conservare `check`, `verify-run` e i report esistenti. Isolare il percorso `status` dalle importazioni pesanti della CLI dove fattibile, misurando prima tempi e regressioni.

| Componente | Scelta | Motivo |
| --- | --- | --- |
| `verify.py`, `checks.py`, `reexecution.py`, `direct_check.py` | Reuse | Nucleo di evidenze già presente. |
| `observability.py` | Refactor mirato | Riutilizzare il formato JSONL; aggiungere eventi Autopilot solo al verificarsi di azioni, senza daemon. |
| `cli.py` | Refactor incrementale | Aggiungere `enable`, `disable`, `status` senza collisioni con i comandi attuali. |
| Configurazione e decisioni locali | Add | Piccolo stato per progetto, schema versionato, default Balanced, nessun segreto. |
| Advisor LLM, hook host, compliance guidance, release gate | Defer | Richiedono specifiche e verifiche ulteriori; non fanno parte del minimo M1. |

## Piano M1 proposto

1. `src/agentharness/config.py`: configurazione per progetto in `.agentharness/config.yaml`; valori convalidati (`enabled`, `mode`, `profile`, policy e budget), scrittura atomica, default espliciti. Definire `mode` solo quando ha una semantica distinta da `enabled`.
2. `src/agentharness/cli.py`: nuovi comandi `enable`, `disable`, `status`, output testuale e JSON; `status` mostra solo dati osservabili, segnala quando costo o controlli non sono misurabili. Nessuna chiamata LLM.
3. `src/agentharness/autopilot.py` e `observability.py`: decisioni deterministiche su diff locale e policy, evento JSONL solo su cambiamento significativo o comando; nessun processo residente. Non eseguire automaticamente test intrusivi.
4. `tests/test_autopilot.py` e test CLI: persistenza, idempotenza, configurazione errata, nessuna chiamata di rete/LLM, stato veritiero, compatibilità dei comandi esistenti. Documentare uso e limiti in `docs/en` e `docs/it`.
5. Adapter host solo dopo una prova riproducibile delle API della versione installata; altrimenti pubblicare un contratto adapter e fermarsi alla CLI vendor neutral.

## Rischi e red team architetturale

- **Duplicazione:** non costruire un nuovo verificatore o un sistema di test parallelo ai comandi esistenti.
- **Costo nascosto:** default senza LLM; budget e contatori solo quando misurabili. Evitare scansioni continue del repository.
- **Coupling:** non codificare convenzioni di un host nella CLI; adapter opzionali.
- **Sicurezza:** un hook non deve eseguire codice non fidato automaticamente; `workspace-copy` non è sandbox (`SECURITY.md`). Redigere log senza segreti.
- **Manutenzione:** schema config versionato e migrazione esplicita; evitare nuove dipendenze pesanti.
- **UX:** `disabled` deve essere idempotente e spegnere ogni automazione; `status` deve distinguere assenza di dati da successo.

Complessità qualitativa: M1 core e CLI **bassa-media**; adapter host **incerta** finché le API non sono verificate; Advisor e lifecycle **alta** e rinviata. Checkpoint: presentare questi risultati prima di refactoring invasivi. M1 richiede approvazione del piano indicata nel handoff.
