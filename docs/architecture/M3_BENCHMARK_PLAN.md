# M3 Checkpoint 1 — Piano di benchmark

**Stato:** piano e label pre-registrate; il dataset DEP è stato preparato nel Checkpoint 2, senza eseguire il motore M3. Le fixture sono repository sintetici con commit/diff e artifact `check`/`verify-run` preparati da esecuzioni **esplicitamente richieste** durante la costruzione. I byte delle 37 fixture DEP, il ledger e i contratti sono congelati da `benchmarks/m3_dep/MANIFEST.sha256` **prima di scrivere il motore**. Le label D01–D36 restano quelle preregistrate; D37 aggiunge il caso di timestamp futuro entro la tolleranza. La revisione indipendente del dataset resta il prossimo checkpoint.

## Dataset iniziale: 61 scenari, di cui 37 DEP

Legenda: `S` = rischio concreto da segnalare, `N` = nessun rischio secondo la regola, `A` = ambiguo/astensione. Evidenza `C` = covered, `U` = uncovered, `F` = failed, `?` = unknown, `—` = non applicabile. «Corrente» significa stesso commit, diff, scope e ambiente ammissibile del contratto; «vecchio» significa binding o tempo non più validi. L'azione attesa è: `S/U` suggerire verifica; `S/F` segnalare fallimento con artifact; `S/C` mostrare stato solo su richiesta; `S/?` chiedere nuova prova o chiarimento; `N` silenzio; `A` astenersi senza inventare un risultato.

| ID | Categoria | Fixture / variazione | Rischio | Evidenza | Ragione attesa |
| --- | --- | --- | :---: | :---: | --- |
| D01 | DEP | Aggiunta dipendenza runtime PEP 621, nessun artifact | S | U | Cambio semantico senza verifica. |
| D02 | DEP | Bump del vincolo runtime; `check` corrente e rieseguito con successo | S | C | Comando pertinente e binding valido. |
| D03 | DEP | Stesso bump; report verde dal commit precedente | S | ? | Stato diverso, report obsoleto. |
| D04 | DEP | Bump; riesecuzione corrente con exit code non zero | S | F | Fallimento attestato. |
| D05 | DEP | Solo riordino delle voci di dipendenza | N | — | Lista semanticamente equivalente. |
| D06 | DEP | Solo commenti/spaziatura in `pyproject.toml` | N | — | Nessuna variazione di vincolo. |
| D07 | DEP | Aggiunta a `[project.optional-dependencies].dev`, nessun artifact | S | U | Gruppo opzionale PEP 621 cambiato. |
| D08 | DEP | Cambio optional dependency; test verde di modulo estraneo | S | ? | Comando non pertinente. |
| D09 | DEP | TOML malformato durante la modifica | A | ? | Parsing non affidabile. |
| D10 | DEP | Nuovo `pyproject.toml` non tracciato con dipendenze | S | U | File non tracciato rilevante, nessuna evidenza. |
| D11 | DEP | Cambio già committato, base esplicita e `check` sul target esatto | S | C | Binding locale corrente sul commit target. |
| D12 | DEP | Cambio già committato senza base di confronto | A | ? | Non inferire «nessun rischio» da HEAD pulito. |
| D13 | DEP | `My_Pkg` diventa `my-pkg`, stesso vincolo | N | — | Nome normalizzato PEP 503 equivalente. |
| D14 | DEP | Extras `[PDF,cli]` diventano `[cli,pdf]` | N | — | Extras normalizzati e ordinati. |
| D15 | DEP | Clauses `>=1,<2` diventano `<2,>=1` | N | — | Ordine delle clausole irrilevante. |
| D16 | DEP | `==1.0` diventa `==1.0.0` | N | — | Release numerica equivalente nel sottoinsieme. |
| D17 | DEP | Solo `project.description` modificata | N | — | Metadato fuori dalla regola. |
| D18 | DEP | Rimozione di una dipendenza runtime, nessun artifact | S | U | Cambiamento PEP 621 materiale. |
| D19 | DEP | Optional dependency modificata, `check` corrente pertinente positivo | S | C | Gruppo e scope inclusi nel binding. |
| D20 | DEP | Marker PEP 508 modificato (`; python_version ...`) | A | ? | Grammatica fuori sottoinsieme. |
| D21 | DEP | Direct URL/reference `@` modificata | A | ? | Nessuna rete o risoluzione URL. |
| D22 | DEP | Specifier `~=` modificato | A | ? | Operatore fuori sottoinsieme. |
| D23 | DEP | `project.dynamic` dichiara `dependencies` | A | ? | Metadata prodotto dinamicamente. |
| D24 | DEP | Due voci con stesso nome normalizzato e vincoli diversi | A | ? | Duplicato ambiguo. |
| D25 | DEP | Bump valido; `run.json` alterato dopo `verify-run` | S | ? | Hash run non corrisponde al report. |
| D26 | DEP | Bump valido; hash stdout alterato | S | ? | Artifact manipolato, non `covered`. |
| D27 | DEP | Bump valido; solo `evaluated_at` aggiornato su riesecuzione >24h | S | ? | Tempo di esecuzione scaduto. |
| D28 | DEP | Bump valido; diff cambiato un minuto dopo il test | S | ? | Stato mutato anche se età <24h. |
| D29 | DEP | Bump valido; due esiti opposti dello stesso comando/stato/ambiente | S | ? | Contraddizione, non scegliere il verde. |
| D30 | DEP | Bump valido; solo artifact di comando/progetto estraneo | S | U | Nessuna candidata dichiarata. |
| D31 | DEP | Bump valido; report vecchio fallito e `check` corrente positivo | S | C | Il fallimento obsoleto non prevale sul corrente. |
| D32 | DEP | Bump valido; report corrente positivo e seconda candidata manipolata sullo stesso controllo | S | ? | Non scegliere il verde ignorando tampering. |
| D33 | DEP | Bump valido; riesecuzione corrente in timeout | S | ? | Timeout non è fallimento attestato né successo. |
| D34 | DEP | Versione pre-release o epoch modificata | A | ? | Versione fuori dal sottoinsieme. |
| D35 | DEP | Timestamp di riesecuzione futuro di oltre 5 minuti | S | ? | Clock/payload non affidabile. |
| D36 | DEP | Bump valido; `check` richiesto negativo e altro comando non richiesto positivo | S | F | Il controllo richiesto fallito non è cancellato dall'altro. |
| D37 | DEP | Bump valido; riesecuzione terminata 2 minuti dopo il clock di valutazione, entro tolleranza | S | C | Skew futuro ≤5 minuti, senza estendere la scadenza di 24 ore. |
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

La fixture C02 richiede un adapter di importazione di evidenza CI **progettato e verificato separatamente**; se non disponibile, il motore deve produrre `?`, non `C`. D11 usa solo `check` locale sul commit target. Il ledger conserva sia la label obiettivo sia la capacità effettivamente abilitata, evitando di contare funzionalità non implementate come regressioni. Il primo MVP esegue la valutazione automatizzata solo sulle fixture DEP supportate; CIR e SEC restano test di progetto per i checkpoint successivi. D20–D24 e D34 sono astensioni attese, non false negative della detection supportata.

## Metodo e metriche

1. **Congelamento prima del codice:** questo documento fissa ID, variazione e label. Due revisori indipendenti firmano il ledger; poi un manifest versionato elenca per ogni fixture commit base/target, SHA-256 del patch canonico, SHA-256 di tutti gli artifact, clock di valutazione congelato e label. Il commit del manifest deve precedere ogni commit implementativo M3; dopo il congelamento nessuna fixture o label cambia in base agli output del motore. Eventuali aggiunte vanno in un set holdout separato con nuova revisione. Non includere segreti o dati personali. Nessun test viene lanciato dal motore durante la valutazione.
2. **Detection:** sui casi determinati `S/N`, misurare precisione, recall, F1 e falsi avvisi per 100 modifiche innocue. Sui casi `A`, misurare tasso di astensione corretto. Riportare per categoria e totale, senza nascondere gli errori dietro la media.
3. **Evidence matching:** matrice di confusione `C/U/F/?`, accuratezza macro e, come misura critica, **false-covered rate** su evidenze obsolete, non pertinenti, mancanti o falsificate. Misurare anche la correttezza del motivo `absent/stale/irrelevant/tampered/contradictory/expired/state_changed`. Obiettivo: **zero false `covered`** nelle fixture D03, D08, D25–D29, D32–D35, C07, S05, S10 e nelle mutazioni di commit/diff/hash/timestamp. Un timeout non può diventare `F` o `C`.
4. **Costo:** p50/p95 della latenza dell'hook end-to-end e del solo matcher, invocazioni Git, file/byte letti, messaggi per turno e token aggiunti dall'host se osservabili. Misurare disabled e nessun rischio separatamente. Nessun LLM AgentHarness: atteso 0 chiamate/0 token diretti.
5. **Confronto verticale:** per le fixture DEP supportate, eseguire task appaiati con Codex solo e Codex+AgentHarness, stesso modello/versione, prompt, budget e stato iniziale, ordine randomizzato. Revisori ciechi giudicano: rischio individuato, correttezza dello stato dell'evidenza, falsa dichiarazione di test passati, verifiche richieste dall'utente, tempo e token. Almeno tre repliche per fixture prima di stimare intervalli di confidenza; il piano non presume un vantaggio. La label `covered` valuta **solo la copertura del controllo pertinente**, mai la sicurezza generale della dipendenza.
6. **Gate MVP proposto:** nessun falso `covered`, regressioni M1/M2 nulle e nessun comando automatico. Sui casi DEP determinati, precisione ≥0,90 e recall ≥0,80; riportare comunque gli intervalli di confidenza, perché il campione è piccolo. Rispetto a M2 sulla stessa macchina, percorso disabled senza nuove chiamate Git e p95 non oltre +10%; percorso enabled senza rischio con p95 incrementale ≤50 ms. Al massimo un nuovo messaggio per rischio e `state_id`; 0 chiamate LLM AgentHarness. Le soglie saranno confermate o corrette dalla revisione indipendente **prima** del codice. Se DEP non supera il gate, correggere regole o binding; non aggiungere categorie per compensare.

**Risultati del motore M3:** **NOT RUN**. È stata eseguita soltanto la preparazione esplicita delle fixture e la validazione di integrità del dataset; precisione, recall e overhead del motore restano da misurare dopo la revisione indipendente.
