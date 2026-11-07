# M3 Checkpoint 1 — Architettura proposta

**Solo progettazione.** Evolvere il repository esistente: il core resta deterministico, gli adapter traducono eventi host, e `check`/`verify-run` rimangono gli unici percorsi di verifica. Nessuna modifica a `main`, nessun daemon, polling, LLM predefinito, installazione host automatica, test o scansione lanciati da un hook.

## Flusso minimo

```text
Stop host / invocazione CLI esplicita
        │
        ▼
Snapshot Git limitato ──> Detection (DEP, poi CIR/SEC) ──> RiskCandidate
                                                   │
Artifact check/verify-run ──> Evidence matching ──> EvidenceAssessment
                                                   │
                                                   ▼
                                  Decisione deterministica consultiva
                                                   │
                                  Messaggio breve + riferimenti verificabili
```

| Componente | Responsabilità | Non deve fare |
| --- | --- | --- |
| **Raccolta stato** | Su evento `Stop` abilitato o comando esplicito, leggere HEAD, diff staged/unstaged e stato dei file rilevanti con limiti di tempo/dimensione; usare una base commit esplicita per cambi già committati. Produrre `state_id` o `unknown`. | Polling, attraversare l'intero disco, eseguire script del progetto, interpretare il payload come comando. |
| **Detection** | Applicare esclusivamente le regole versionate di [M3_RISK_TAXONOMY.md](M3_RISK_TAXONOMY.md); restituire `RiskCandidate {rule_id, scope, change_id, explanation, confidence/unknown_reason}`. | Leggere o giudicare report di test, chiamare LLM, dichiarare «vulnerabilità confermata». |
| **Evidence matching** | Leggere artifact già presenti in `.agentharness/runs`, verificare hash, stato, scope, comando, esito e tempo secondo [M3_EVIDENCE_CONTRACT.md](M3_EVIDENCE_CONTRACT.md). Restituire `covered/uncovered/failed/unknown` con riferimenti e motivi. | Rieseguire test, promuovere `ok: true` senza binding a `state_id`, usare log non pertinenti. |
| **Decisione** | Combinare rischio ed evidenza. Nessun rischio concreto → silenzio. Rischio `covered` → nessun sollecito ripetitivo, stato consultabile. `uncovered` → suggerire il controllo pertinente. `failed` → indicare il fallimento e l'artifact. `unknown` → chiedere chiarimento o nuova verifica senza affermare un esito. Deduplicare sullo stato osservato. | Bloccare Codex, avviare verificatori, cambiare trust/configurazione host. |
| **Adapter Codex** | Riutilizzare `normalize_stop`, `host-event`, `enable/disable` e l'hook di progetto M2 per mostrare una risposta breve. | Contenere regole di rischio o interpretare gli artifact. Claude Code resta non verificato. |

## Integrazione con i componenti esistenti

- `direct_check.check_workspace` crea `.agentharness/runs/<run_id>/run.json`, `claims.json`, `verify-report.json` e una snapshot persistente. È il punto naturale per acquisire, **solo su richiesta dell'utente**, il binding M3 a commit/diff/stato; non richiede un secondo esecutore.
- `verify.verify_run` valida envelope, hash di `run.json` e `claims.json`, claim ed eventuale riesecuzione controllata. Il matcher M3 legge il suo report; non ne cambia i significati. Un report M2 preesistente senza binding di stato non è automaticamente `covered`.
- `host_prototype.changed_paths` e `autopilot.decide_stop` oggi emettono un suggerimento basato su pochi percorsi tracciati. Nel futuro MVP, la detection DEP sostituirà **solo la decisione consultiva** per `pyproject.toml`; il codice di fingerprinting e fail-open può essere riusato. Non modificare i verificatori esistenti né aggiungere una pipeline concorrente.
- La configurazione M1 resta `enabled: false/true`, `balanced` e `mode: manual`. Il checkpoint documentale non introduce nuove chiavi. Eventuali policy configurabili richiederanno proposta di schema e migrazione separata.

## Caso verticale unico per il primo MVP: dipendenza PEP 621

**Scenario:** un agente modifica il vincolo di una dipendenza in `[project].dependencies` di `pyproject.toml`. AgentHarness identifica la variazione semantica, cerca un `check` esplicitamente eseguito sullo stesso stato e mostra «rischio DEP; evidenza `uncovered`/`unknown`/`failed`/`covered`» con il percorso dell'artifact. Se non c'è evidenza valida, suggerisce il comando approvato dal progetto, senza lanciarlo. Dopo un `check` richiesto dall'utente, lo stato diventa `covered` solo se la riesecuzione e il binding sono validi.

**Perché è un confronto utile con Codex solo:** Codex può riconoscere la modifica e suggerire test, ma il protocollo M3 richiede di distinguere in modo ripetibile tra test realmente eseguito sul diff corrente, test precedente, claim non verificata e fallimento. Il valore misurabile è la riduzione di affermazioni «verificato» prive di evidenza e la maggiore scoperta di test obsoleti, a fronte di latenza, messaggi e token aggiunti. Il benchmark usa gli stessi task e artifact preallestiti per Codex con/senza AgentHarness; non presuppone superiorità dell'adapter.

## Gate prima del codice

1. Revisionare tassonomia, contratto e fixture di [M3_BENCHMARK_PLAN.md](M3_BENCHMARK_PLAN.md); correggere ambiguità prima di scegliere soglie.
2. Definire un binding serializzato v0 e la sua migrazione senza cambiare i risultati `check`/`verify-run`; verificare che il costo di lettura su `Stop` resti misurabile e limitato.
3. Autorizzare separatamente il solo MVP DEP. CIR, SEC, nuovi host e Advisor LLM non entrano implicitamente nel primo codice M3.
