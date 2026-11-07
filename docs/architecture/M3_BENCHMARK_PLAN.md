# M3 Checkpoint 1 — Piano di benchmark

**Stato:** piano e label pre-registrate; nessun benchmark M3 è stato eseguito e nessun test viene avviato automaticamente. Le fixture saranno repository sintetici locali con commit/diff e artifact `check`/`verify-run` già preparati da esecuzioni **esplicitamente richieste** durante la costruzione del dataset. Le etichette sono definite da due revisori indipendenti prima di valutare il motore; i disaccordi sono adjudicati e conservati nel ledger.

## Dataset iniziale: 36 scenari

Legenda: `S` = rischio concreto da segnalare, `N` = nessun rischio secondo la regola, `A` = ambiguo/astensione. Evidenza `C` = covered, `U` = uncovered, `F` = failed, `?` = unknown, `—` = non applicabile. «Corrente» significa stesso commit, diff, scope e ambiente ammissibile del contratto; «vecchio» significa binding o tempo non più validi. L'azione attesa è: `S/U` suggerire verifica; `S/F` segnalare fallimento con artifact; `S/C` mostrare stato solo su richiesta; `S/?` chiedere nuova prova o chiarimento; `N` silenzio; `A` astenersi senza inventare un risultato.

| ID | Categoria | Fixture / variazione | Rischio | Evidenza | Ragione attesa |
| --- | --- | --- | :---: | :---: | --- |
| D01 | DEP | Aggiunta dipendenza runtime PEP 621, nessun artifact | S | U | Cambio semantico senza verifica. |
| D02 | DEP | Bump del vincolo runtime; `check` corrente e rieseguito con successo | S | C | Comando pertinente e binding valido. |
| D03 | DEP | Stesso bump; report verde dal commit precedente | S | ? | Stato diverso, report obsoleto. |
| D04 | DEP | Bump; riesecuzione corrente con exit code non zero | S | F | Fallimento attestato. |
| D05 | DEP | Solo riordino delle voci di dipendenza | N | — | Lista semanticamente equivalente. |
| D06 | DEP | Solo commenti/spaziatura in `pyproject.toml` | N | — | Nessuna variazione di vincolo. |
| D07 | DEP | Cambio di `[build-system].requires`, nessun artifact | S | U | Rischio build. |
| D08 | DEP | Cambio optional dependency; test verde di modulo estraneo | S | ? | Comando non pertinente. |
| D09 | DEP | TOML malformato durante la modifica | A | ? | Parsing non affidabile. |
| D10 | DEP | Nuovo `pyproject.toml` non tracciato con dipendenze | S | U | File non tracciato rilevante, nessuna evidenza. |
| D11 | DEP | Cambio già committato, base esplicita e CI sul target esatto | S | C | Provenienza completa dell'evidenza esterna, se ammessa dalla policy. |
| D12 | DEP | Cambio già committato senza base di confronto | A | ? | Non inferire «nessun rischio» da HEAD pulito. |
| C01 | CIR | Trigger workflow di release ampliato, nessun artifact | S | U | Nuovo percorso di pubblicazione. |
| C02 | CIR | Step CI cambiato; job corrente riuscito con commit e log verificabili | S | C | Controllo pertinente sul target esatto. |
| C03 | CIR | Solo commenti YAML | N | — | Nessun cambio materiale. |
| C04 | CIR | Solo nome descrittivo del job cambiato | N | — | Comportamento invariato. |
| C05 | CIR | Step di test rimosso dal workflow | S | U | Riduzione di copertura, nessuna prova sostitutiva. |
| C06 | CIR | Workflow cambiato; job corrente fallito | S | F | Fallimento con log/exit attestati. |
| C07 | CIR | Workflow cambiato; job verde sul commit precedente | S | ? | Verde obsoleto. |
| C08 | CIR | YAML invalido o espressione non interpretabile | A | ? | Astensione del parser. |
| C09 | CIR | Deploy spostato da tag a ogni push | S | U | Trigger di release ampliato. |
| C10 | CIR | Action aggiornata a digest equivalente, solo commento di versione | N | — | Esecuzione identica. |
| C11 | CIR | Nuovo workflow non tracciato che pubblica artifact | S | U | File nuovo rilevante. |
| C12 | CIR | Workflow rinominato con contenuto identico | N | — | Rename senza cambio semantico. |
| S01 | SEC | `SECURITY.md` eliminato | S | U | Policy di segnalazione rimossa. |
| S02 | SEC | Correzione editoriale in `SECURITY.md` | N | — | Nessun indebolimento. |
| S03 | SEC | `.github/CODEOWNERS` eliminato | S | U | Review ownership rimossa. |
| S04 | SEC | Workflow PR aggiunge `pull_request_target` | S | U | Contesto privilegiato nuovo. |
| S05 | SEC | Workflow PR passa a `permissions: write-all`; report generico «tests pass» | S | ? | Claim non pertinente/non verificata. |
| S06 | SEC | Workflow PR amplia `contents: read` a `write`; controllo policy corrente fallisce | S | F | Fallimento di controllo pertinente e rieseguito. |
| S07 | SEC | Permessi workflow ridotti da write a read | N | — | Restrizione, non indebolimento. |
| S08 | SEC | CODEOWNERS spostato con ownership equivalente | N | — | Stessa policy effettiva. |
| S09 | SEC | `permissions` generato da espressione non interpretabile | A | ? | Semantica incerta. |
| S10 | SEC | `pull_request_target` aggiunto; scanner verde sul diff precedente | S | ? | Artifact obsoleto. |
| S11 | SEC | Commento `security` aggiunto a workflow | N | — | Stringa non eseguibile. |
| S12 | SEC | `SECURITY.md` cancellato e ricreato identico nello stesso stato finale | N | — | Nessun cambiamento netto. |

Le fixture C02/D11 richiedono un adapter di importazione di evidenza CI **progettato e verificato separatamente**; se non disponibile al momento del primo MVP, il motore deve produrre `?`, non `C`. Il ledger conserva sia la label obiettivo sia la capacità effettivamente abilitata, evitando di contare funzionalità non implementate come regressioni. Il primo MVP esegue la valutazione automatizzata solo sulle fixture DEP supportate; CIR e SEC restano test di progetto per i checkpoint successivi.

## Metodo e metriche

1. **Preparazione:** fissare hash dei repository fixture, base/target, patch canoniche, artifact e label. Ogni scenario ha una variante di controllo senza cambiamento rischioso. Non includere segreti o dati personali. Nessun test viene lanciato dal motore durante la valutazione; gli artifact sono preallestiti e immutabili.
2. **Detection:** sui casi determinati `S/N`, misurare precisione, recall, F1 e falsi avvisi per 100 modifiche innocue. Sui casi `A`, misurare tasso di astensione corretto. Riportare per categoria e totale, senza nascondere gli errori dietro la media.
3. **Evidence matching:** matrice di confusione `C/U/F/?`, accuratezza macro e, come misura critica, **false-covered rate** su evidenze obsolete, non pertinenti, mancanti o falsificate. Obiettivo iniziale da validare: **zero false `covered`** nelle fixture D03, D08, C07, S05, S10 e in varianti mutazionali di commit/diff/hash/timestamp. Un timeout non può diventare `F` o `C`.
4. **Costo:** p50/p95 della latenza dell'hook end-to-end e del solo matcher, invocazioni Git, file/byte letti, messaggi per turno e token aggiunti dall'host se osservabili. Misurare disabled e nessun rischio separatamente. Nessun LLM AgentHarness: atteso 0 chiamate/0 token diretti.
5. **Confronto verticale:** per le fixture DEP, eseguire task appaiati con Codex solo e Codex+AgentHarness, stesso modello/versione, prompt, budget e stato iniziale, ordine randomizzato. Revisori ciechi giudicano: rischio individuato, correttezza dello stato dell'evidenza, falsa dichiarazione di test passati, verifiche richieste dall'utente, tempo e token. Almeno tre repliche per fixture prima di stimare intervalli di confidenza; il piano non presume un vantaggio.
6. **Gate MVP proposto:** nessun falso `covered`, regressioni M1/M2 nulle e nessun comando automatico. Sui casi DEP determinati, precisione ≥0,90 e recall ≥0,80; riportare comunque gli intervalli di confidenza, perché il campione è piccolo. Rispetto a M2 sulla stessa macchina, percorso disabled senza nuove chiamate Git e p95 non oltre +10%; percorso enabled senza rischio con p95 incrementale ≤50 ms. Al massimo un nuovo messaggio per rischio e `state_id`; 0 chiamate LLM AgentHarness. Le soglie saranno confermate o corrette dalla revisione indipendente **prima** del codice. Se DEP non supera il gate, correggere regole o binding; non aggiungere categorie per compensare.

**Risultati M3:** **NOT RUN**. Questo documento definisce soltanto dataset, ground truth e misure da sottoporre a revisione indipendente.
