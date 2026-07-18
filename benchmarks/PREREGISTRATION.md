# Benchmark pre-registration

Status: approved before benchmark execution, with task construction still gated by section 5.
Stato: approvato prima dell'esecuzione del benchmark, con costruzione dei task ancora vincolata dal gate della sezione 5.

## Quick approval summary

This pre-registration now fixes:
- primary treatment: B-loop-closed with symmetric repair
- primary endpoint: held-out task evaluation score, continuous from 0 to 1
- `verify-run` role: manipulation check, not primary evidence of benefit
- chosen suite size: 8 tasks
- replicates: 6 paired A/B replicates per task
- minimal meaningful effect: 0.10 absolute on the task evaluation score
- explicit limitation: A vs B estimates the effect of the full AgentHarness package, not a pure isolated framework effect

Pre-run quality gate:
- benchmark execution cannot start until all 8 tasks meet the same quality bar: written spec, allowed and forbidden scope, independent held-out evaluation suite, `verify-run` claims contract, and comparable budget class
- if task 7 or task 8 fail that quality bar, execution is blocked and the plan must be amended before the first run
- benchmark execution cannot start until disjunction is demonstrated between the held-out evaluation suite and the visible claims contract
- benchmark execution cannot start until non-leakage of held-out material into the agent-visible context is demonstrated

This pre-registration is now approved. Benchmark execution remains blocked until the section-5 quality gate is satisfied.

## Italiano

### 1. Scopo
Questo documento congela il design del benchmark prima di qualunque esecuzione.

Obiettivo:
- verificare, o smentire, se AgentHarness migliora l'esecuzione di un coding agent in modo riproducibile e statisticamente difendibile
- ammettere esplicitamente un risultato nullo

Questo benchmark non serve a proclamare una vittoria. Serve a misurare un segnale reale, oppure a mostrare onestamente che non c'è.

### 2. Claim supportata
La claim che questa suite può supportare è limitata:
- può mostrare un segnale, oppure nessun segnale, per i task, il modello, i tool e il budget testati
- non può dimostrare una legge universale su tutti i coding agent o tutti i task software

### 3. Trattamento proposto
Scelta proposta: B-loop-chiuso con repair simmetrico.

Definizione delle condizioni:

| Condizione | Definizione |
| --- | --- |
| A, baseline | l'agente riceve task spec, ambiente, tool consentiti, budget e lo stesso output contract finale, cioè `run.json` più `claims.json` |
| B, AgentHarness | l'agente riceve la stessa task spec più il contesto AgentHarness, e deve produrre `run.json` più `claims.json` |

Regola del repair pass:
- entrambe le condizioni ricevono esattamente un repair pass limitato
- entrambe le condizioni restano dentro lo stesso budget wall-clock totale
- nessuna condizione vede la task evaluation suite durante il run

Guida del repair pass:
- A riceve un'istruzione generica e framework-neutral di auto-revisione rispetto alla task spec
- A non riceve mai feedback dei claim di `verify-run`, file framework, né task evaluation suite
- B riceve il feedback strutturato dei claim di `verify-run`
- B non riceve mai la task evaluation suite

Motivazione della scelta:
- il numero di tentativi diventa simmetrico
- la differenza sistematica resta nella qualità del segnale di repair e nel contesto framework
- il contrasto diventa: repair guidato dalla verifica più contesto framework contro repair generico senza framework

### 4. Confondente esplicito
Il confondente principale va dichiarato senza giri:
- B aggiunge più contesto strutturato
- B aggiunge anche una guida di repair basata sulla verifica

Lo step di repair è ora simmetrico nel conteggio: entrambe le condizioni ricevono esattamente un repair pass limitato. La differenza residua è la qualità della guida di quel pass, che fa parte del pacchetto framework e qui non viene isolata di proposito.

Quindi il confronto A vs B misura l'effetto del pacchetto AgentHarness nel suo insieme.
Non misura in modo pulito:
- solo l'effetto del contesto extra
- solo l'effetto della guida di `verify-run`

Cosa diremo nel report:
- il risultato è una stima di package effect
- non attribuiremo tutto il guadagno solo alla verifica, né solo al contesto

Mitigazioni:
- stesso task
- stesso modello
- stessi tool
- stesso budget
- stessa policy di intervento
- stesso schema minimo di output per entrambe le condizioni
- stesso numero di tentativi totali

Estensione futura possibile, ma non inclusa in questa pre-registrazione salvo approvazione preventiva:
- aggiungere una terza condizione B-contesto per separare meglio effetti di contesto ed effetti di guidance della verifica

### 5. Suite di task fissata
Poiché la precisione dell'inferenza A vs B è governata soprattutto dal numero di task e non dalle sole repliche, la suite viene fissata a 8 task.

Decisione congelata:
- task target: 8
- 4 task non sono accettabili come base di una claim headline
- 6 task restano un piano di ripiego metodologicamente difendibile solo tramite emendamento formale prima del primo run, non come cambio informale a metà costruzione

Task families già confermate o candidate:
1. support-ticket API, già esistente
2. inventory-adjustment API con business rules transazionali
3. webhook ingestion service con schema validation e idempotenza
4. export o report job con output file deterministico e negative-path validation
5. da definire prima del primo run, sotto il quality gate
6. da definire prima del primo run, sotto il quality gate
7. da definire prima del primo run, sotto il quality gate
8. da definire prima del primo run, sotto il quality gate

Requisiti per ogni task:
- spec scritta
- scope consentito e scope vietato
- evaluation suite indipendente e tenuta da parte
- claims contract per `verify-run`
- difficoltà compatibile con lo stesso ordine di budget
- disgiunzione dimostrata tra evaluation suite e claims contract
- non leakage dimostrato del materiale tenuto da parte nel contesto visibile all'agente

Regola di disgiunzione, vincolante:
- i controlli della evaluation suite devono essere disgiunti dai claim che l'agente vede in `verify-run`
- nessuna asserzione può comparire sia nei claim mostrati all'agente sia nella evaluation suite
- se un controllo verifica la stessa proprietà di un claim visibile, va riscritto o rimosso
- senza questa disgiunzione l'endpoint primario non è realmente indipendente da ciò che B ottimizza

Quality gate prima dell'avvio:
- tutti e 8 i task devono soddisfare i requisiti sopra allo stesso livello di qualità
- un task aggiunto in modo raffazzonato è considerato peggiore di una suite più piccola ma solida
- se task 7 o task 8 non raggiungono lo standard, il benchmark non parte finché la pre-registrazione non viene emendata formalmente
- il benchmark non parte finché non è dimostrata, task per task, la disgiunzione tra evaluation suite e claims contract
- il benchmark non parte finché non è dimostrato il non leakage del materiale held-out nel contesto visibile all'agente

Nota protocollare sulla contaminazione da leakage:
- la copia dei file held-out nella cartella `inputs/` è stata introdotta nel commit `9813169`
- di conseguenza, ogni cella prodotta da `prepare_fresh_cell` dal commit `9813169` in poi ha potuto esporre i criteri held-out all'agente durante il run
- i risultati di smoke prodotti sotto quel regime, inclusi i workspace webhook e csv delle run di smoke, non sono validi come misura del base rate dell'agente
- quei run non devono essere riusati come dati di base rate, dati di campagna o dati diagnostici pre-campagna
- la raccolta dati valida riparte solo da celle materializzate dopo la chiusura verificata della falla di non leakage

### 6. Numerosità fissata
Repliche per task:
- 6 repliche appaiate A/B per task

Piano fissato:
- 8 task x 6 repliche = 48 confronti appaiati, 96 run totali

Regola ferrea:
- né il numero di task né il numero di repliche si cambiano dopo l'avvio del primo run benchmark

### 7. Controlli di riproducibilità
Da fissare e loggare per ogni run:
- provider e nome esatto del modello
- runtime agente e sua versione, quando disponibile
- temperatura e controlli di stocasticità, se esposti
- seed reale, se disponibile, altrimenti indice di replica appaiato
- tool access e network policy
- budget wall-clock
- massimo numero di repair pass
- template workspace e file iniziali
- hash versione task
- commit SHA di AgentHarness
- hash versione script benchmark
- Python 3.12 come target del grading congelato
- `benchmarks/grading-env/constraints-py312.txt`
- `benchmarks/grading-env/wheelhouse-manifest.json` con hash delle wheel
- `benchmarks/grading-env/wheelhouse/` come unica sorgente offline per install con `--no-index`
- warning noto e congelato: l'attuale combinazione Starlette e httpx emette un deprecation warning verso `httpx2` durante `TestClient`, senza invalidare il grading

### 8. Metriche
#### 8.1 Endpoint primario
Endpoint primario: task evaluation score, continuo tra 0 e 1, calcolato per run dalla task evaluation suite indipendente e tenuta da parte.

La task evaluation suite:
- è indipendente da `verify-run`
- non viene mai mostrata a nessuna delle due condizioni durante il run
- verifica correttezza task-specific, regole di business, schema esatto e negative path
- deve essere disgiunta dai claim visibili in `verify-run`

Lo score è la proporzione di controlli di accettazione indipendenti superati.

Motivazione:
- è l'unico esito che B non ottimizza direttamente, quindi non è circolare
- uno score continuo porta informazione graduata e riduce effetti di ceiling e floor rispetto a un solo binario
- questa indipendenza vale solo se non c'è sovrapposizione assertiva tra evaluation suite e claims visibili

Secondario binario chiave, derivato dalla stessa suite:
- task evaluation pass, vero solo se tutti i controlli critici di accettazione passano

#### 8.2 Metriche oggettive secondarie
Metriche secondarie per run:
- task evaluation pass
- numero di controlli indipendenti superati nella evaluation suite
- numero di controlli indipendenti falliti nella evaluation suite
- tempo totale
- numero di repair pass consumati
- completezza artifact grezzi richiesti
- numero di file cambiati fuori scope, se misurato deterministicamente

Manipulation check, non esiti di beneficio:
- pass complessivo di `verify-run`
- quota di claim supported
- conteggio claim unsupported
- conteggio claim inconclusive
- conteggio claim invalid

Queste metriche di `verify-run` nella condizione B sono parzialmente circolari per disegno, perché B itera per soddisfare il loop di verifica. Vengono riportate solo per mostrare che B ha effettivamente ingaggiato il loop, non come prova primaria di beneficio.

Fonti di verità:
- report JSON della task evaluation suite
- report JSON di `verify-run`, ma solo come manipulation check
- controlli deterministici sul filesystem dei raw artifact
- metadata del benchmark

Verifica di indipendenza da documentare per ogni task:
- mappa esplicita dei claim visibili in `verify-run`
- mappa esplicita dei controlli della evaluation suite tenuta da parte
- dimostrazione di disgiunzione, cioè assenza di asserzioni duplicate o semanticamente equivalenti
- dimostrazione di non leakage del materiale held-out nel contesto passato all'agente

#### 8.3 Metriche soggettive residue
Le metriche soggettive non sono primarie.

Uso limitato a:
- reviewability del codice
- chiarezza operativa del README

Protocollo:
- 2 valutatori in cieco
- artifact anonimizzati
- scala 1 a 5
- media dei due voti
- accordo tra valutatori riportato in modo descrittivo

Se il cieco non è credibile, questi risultati restano solo esplorativi.

### 9. Effetto minimo rilevante
Effetto minimo rilevante, MME:
- valore fissato: 0.10 assoluto sul task evaluation score

Interpretazione:
- il benchmark non chiede solo se B è migliore di A
- chiede se B è migliore di A abbastanza da contare davvero

### 10. Ipotesi
Ipotesi primaria, direzionale:
- la condizione B produce un task evaluation score più alto della condizione A di almeno l'effetto minimo rilevante, sulla suite indipendente tenuta da parte

Ipotesi nulla:
- nessuna differenza, oppure una differenza più piccola dell'effetto minimo rilevante, oppure una differenza compatibile con il rumore sotto questo design

Le ipotesi secondarie su supported-claim rate e riduzione dei claim blocking vengono riclassificate come manipulation check per la condizione B, non come prova di beneficio.

### 11. Piano statistico
Unità di analisi:
- il singolo run è un'osservazione
- i run sono annidati nei task
- i task sono i cluster e governano la precisione dell'inferenza A vs B

Analisi primaria sull'endpoint primario:
- modello a effetti misti con condizione come effetto fisso e intercetta random per task
- per il task evaluation score continuo usare un modello lineare a effetti misti
- per il modello lineare a effetti misti usare REML e una correzione dei gradi di libertà tipo Satterthwaite o Kenward-Roger
- per il secondario binario task evaluation pass usare un modello lineare generalizzato a effetti misti, logistico
- riportare l'effetto aggiustato B meno A con intervallo di confidenza al 95 percento

Analisi di robustezza:
- cluster bootstrap che ricampiona i task con le loro repliche
- con pochi cluster considerare la variante wild e riportarla esplicitamente come approssimata
- riportare la differenza media B meno A con intervallo di confidenza al 95 percento
- la precisione dell'inferenza è guidata dal numero di task, non dal numero di repliche

Il Wilcoxon signed-rank a livello task viene rimosso come test primario, perché con il numero di task inizialmente previsto non può sostenere una significatività headline. Può apparire solo come sensitivity check chiaramente etichettato e sottodimensionato, mai come base del risultato principale.

Metriche secondarie oggettive:
- modelli a effetti misti oppure, dove un semplice riassunto appaiato è valido, Wilcoxon signed-rank
- Mann-Whitney U per confronti non appaiati
- bootstrap CI 95 percento per ogni effect size riportato
- Holm per controllare la molteplicità nella famiglia secondaria
- l'unico endpoint primario non prende correzione di molteplicità

Dati mancanti e fallimenti:
- tutti i run si includono
- un run crashato o in timeout vale 0 sul task evaluation score e conta come fallimento sul pass binario
- artifact richiesti mancanti contano come fallimento sui criteri relativi
- se la soluzione non si installa, non si importa o non si avvia dentro l'ambiente isolato costruito dalla propria manifest dichiarata, il run resta incluso come real_failure con score 0 sul task evaluation score
- import failure o runtime failure dopo la build dell'ambiente isolato non sono invalidazione di default: restano real_failure salvo evidenza che il guasto appartenga al grader
- niente esclusioni post hoc, salvo hard invalidation dell'harness o del grader, con motivo loggato, quando il guasto è attribuibile all'infrastruttura di valutazione e non alla soluzione

Limite onesto da dichiarare fin d'ora:
- con 8 task l'inferenza a livello di cluster resta comunque modesta e va interpretata con cautela
- il benchmark può produrre evidenza utile, non una legge universale
- le prime celle possono essere usate solo come controllo interno del base rate e del rischio di ceiling, senza modificare N, MME o il piano inferenziale

### 12. Regola di decisione
AgentHarness viene descritto come supportato da evidenza di beneficio solo se tutte queste condizioni tengono sul task evaluation score indipendente tenuto da parte:
1. la stima a effetti misti favorisce B rispetto ad A
2. la stima cluster-bootstrap favorisce B rispetto ad A
3. l'intervallo di confidenza al 95 percento per l'effetto B meno A sta interamente sopra zero
4. l'estremo inferiore dell'intervallo è pari o superiore all'effetto minimo rilevante
5. il risultato non è trainato da un singolo task, verificato con leave-one-task-out
6. il guadagno non è spiegato da un costo temporale grossolanamente impraticabile
7. il report continua a dichiarare in modo chiaro il confondente di package effect

Se queste condizioni non tengono, il risultato headline deve essere uno tra:
- nessun effetto rilevato
- evidenza mista
- miglioramento con confondimento non risolto

Le metriche di manipulation check derivate da `verify-run` non sono mai sufficienti per sostenere una claim di beneficio.

### 13. Raw artifacts obbligatori
Ogni run deve salvare almeno:
- `prompt.txt`
- snapshot task spec
- snapshot contesto baseline o framework
- transcript o raw output log agente
- `stdout.log`
- `stderr.log`
- snapshot workspace oppure manifest file cambiati
- `run.json`
- `claims.json`
- `verify-run-report.json`
- `evaluation-report.json`
- `metadata.json`
- log del repair pass, se presente

Directory shape proposta:
- `benchmarks/runs/<task_id>/<condition>/<replicate_id>/`

### 14. Design dell'harness di misura
Importante: questa sezione descrive solo il design, non autorizza ancora implementazione o run.

Responsabilità dell'harness:
1. creare un workspace pulito per una singola cella task-condizione-replica
2. comporre prompt e pacchetto contesto corretto
3. lanciare il coding agent con impostazioni fissate
4. catturare output grezzi e metadata
5. invocare `agentharness verify-run`
6. invocare la task evaluation suite indipendente e tenuta da parte
7. produrre un summary JSON derivato solo da artifact e report reali

Comandi previsti, a livello di design:
- comando per eseguire una singola cella
- comando per eseguire l'intera matrice, solo dopo approvazione
- comando per anonimizzare artifact per review in cieco
- comando per aggregare i grezzi in tabelle e statistiche

Come `verify-run` entra nel design:
- verifica envelope run e claim
- controlla scope, artifact richiesti e test claims
- riesegue wrapper pytest supportati quando possibile
- produce conteggi machine-readable di supported, unsupported, inconclusive e invalid
- serve come manipulation check per confermare che B abbia davvero ingaggiato il loop di verifica
- non è l'endpoint primario del beneficio

Come entra la evaluation suite:
- è l'outcome indipendente tenuto da parte
- controlla correttezza task-specific non abbastanza catturata genericamente da `verify-run`
- produce un report JSON rigenerabile dai raw artifact
- è la fonte primaria per la claim di beneficio

Prerequisito operativo del grader held-out, da soddisfare prima del primo run senza cambiare endpoint o parametri congelati:
- per ogni soluzione, il grader costruisce un ambiente isolato a partire dalla manifest dichiarata dalla soluzione stessa
- il grading held-out gira fuori processo dentro quell'ambiente isolato, non nel processo del grader con il suo ambiente ambientale
- la manifest dichiarata è obbligatoria, ma il grader non applica una allowlist hardcoded o un minimo hardcoded di dipendenze per task
- il wheelhouse offline congelato è l'unica fonte di verità per l'ammissione delle dipendenze: se una dipendenza installa offline viene ammessa, se non installa il run resta `real_failure`
- la tassonomia degli esiti distingue almeno: valid, real_failure, harness_invalid
- valid significa che il grading è partito correttamente nell'ambiente isolato e ha prodotto osservazioni task-specific
- real_failure significa che la soluzione, valutata dalla propria manifest dichiarata, non installa, non importa, non parte, oppure fallisce i check held-out
- harness_invalid è riservato a bug o guasti del grader, del protocollo worker, o dell'infrastruttura di valutazione non imputabili alla soluzione
- un semplice import failure non è harness_invalid per scorciatoia: dopo build isolata resta normalmente real_failure

### 15. Decisioni congelate e prerequisiti pre-run
Decisioni congelate:
1. Trattamento:
   - B-loop-chiuso con repair simmetrico per A

2. Numerosità:
   - 8 task x 6 repliche = 96 run totali

3. Endpoint primario:
   - task evaluation score indipendente
   - `verify-run` classificato come manipulation check, non come prova primaria di beneficio

4. MME:
   - 0.10

Prerequisiti pre-run ancora obbligatori:
5. Task suite:
   - per ogni nuovo task definire la sua evaluation suite indipendente prima del primo run
   - tutti gli 8 task devono superare il quality gate dichiarato nella sezione 5
   - per ogni task deve essere documentata la disgiunzione tra evaluation suite e claims contract
   - per ogni task deve essere documentato il non leakage del materiale held-out

6. Residuo soggettivo:
   - se incluso nella fase uno, resta secondario ed esplorativo

7. Ambiente di grading held-out:
   - freeze operativo completo
   - ricostruibile dai soli artefatti versionati in `benchmarks/grading-env/`
   - gate root offline verde
   - gate a livello di soluzione verde per reference API, reference CLI e variante in-spec con `EmailStr`

### 16. Freeze rule
Nessun benchmark run parte prima che sia soddisfatto il quality gate della sezione 5.
Con questa approvazione si congelano:
- trattamento
- numero di task fissato a 8 e regole di costruzione dei task
- N
- metriche
- MME
- regola di decisione

Le istanze concrete dei task vengono aggiunte sotto il quality gate della sezione 5 prima del primo run.
Qualunque riduzione a 6 o modifica del numero richiede emendamento formale.

Se gli 8 task non raggiungono il quality gate prima del primo run, il benchmark resta bloccato e richiede un emendamento formale della pre-registrazione.
Lo stesso vale se non è dimostrata la disgiunzione tra evaluation suite e claims contract, oppure se c'è leakage del materiale held-out.

## English

### 1. Purpose
This document freezes the benchmark design before execution.
The goal is to test, or falsify, whether AgentHarness improves coding-agent execution in a reproducible and statistically defensible way.
A null result is explicitly acceptable.

### 2. Supported claim
This benchmark can support only a limited claim:
- it may show a signal, or no signal, for the tested tasks, model, tools, and budget
- it cannot prove a universal law across all coding agents or software tasks

### 3. Proposed treatment
Proposed choice: B-loop-closed with symmetric repair.

| Condition | Definition |
| --- | --- |
| A, baseline | the agent gets task spec, environment, allowed tools, budget, and the same final output contract, namely `run.json` plus `claims.json` |
| B, AgentHarness | the agent gets the same task spec plus AgentHarness context, and must produce `run.json` plus `claims.json` |

Repair-pass rule:
- both conditions receive exactly one bounded repair pass
- both conditions stay inside the same total wall-clock budget
- neither condition ever sees the held-out task evaluation suite during the run

Repair guidance:
- A receives a generic, framework-neutral self-review instruction against the task spec
- A never receives `verify-run` claim feedback, framework files, or the task evaluation suite
- B receives structured `verify-run` claim feedback
- B never receives the task evaluation suite

This keeps the number of attempts symmetric and makes the contrast: verification-guided repair plus framework context versus generic repair without framework.

### 4. Explicit confounder
The main confounder must be stated plainly:
- B adds more structured context
- B also adds verification-guided repair

The repair step is now symmetric in count: both conditions receive exactly one bounded repair pass. The remaining difference is the guidance quality of that pass, which is part of the framework package and is intentionally not isolated here.

Therefore A vs B estimates the effect of the full AgentHarness package.
It does not cleanly isolate:
- extra-context effects alone
- verification-guidance effects alone

The report must state this as a package-effect estimate.

Possible future extension, not included unless approved before any run:
- add a B-context arm to separate context effects from verification-guidance effects

### 5. Fixed task suite
Because A versus B inference precision is governed mainly by the number of tasks, not just by replicates, the suite size is fixed at 8 tasks.

Frozen decision:
- target task count: 8
- 4 tasks are not acceptable as the basis for a headline claim
- 6 tasks remain a defensible fallback only through a formal amendment before the first run, not as an informal mid-build change

Confirmed or candidate task families:
1. support-ticket API
2. inventory-adjustment API
3. webhook ingestion service
4. export or report job
5. to be defined before the first run, under the quality gate
6. to be defined before the first run, under the quality gate
7. to be defined before the first run, under the quality gate
8. to be defined before the first run, under the quality gate

Each task must define:
- written spec
- allowed and forbidden scope
- independent held-out evaluation suite
- `verify-run` claims contract
- comparable budget class
- demonstrated disjunction between the evaluation suite and the visible claims contract
- demonstrated non-leakage of held-out material into the agent-visible context

Binding disjunction rule:
- evaluation-suite checks must be disjoint from the claims the agent sees in `verify-run`
- no assertion may appear both in the visible claims contract and in the evaluation suite
- if an evaluation check tests the same property as a visible claim, it must be rewritten or removed
- without this disjunction the primary endpoint is not truly independent of what condition B optimizes against

Quality gate before launch:
- all 8 tasks must satisfy the requirements above at the same quality level
- a rushed eighth task is considered worse than a smaller but solid suite
- if task 7 or task 8 fail that bar, benchmark execution is blocked until the pre-registration is formally amended
- benchmark execution is blocked until disjunction is demonstrated, task by task, between the evaluation suite and the claims contract
- benchmark execution is blocked until non-leakage of held-out material into the agent-visible context is demonstrated

### 6. Fixed sample size
Replicates per task:
- 6 paired A/B replicates per task

Frozen plan:
- 8 tasks x 6 replicates = 48 paired comparisons, 96 total runs

Hard rule:
- neither task count nor replicate count changes after the first benchmark run starts

### 7. Reproducibility controls
Per run, fix and log at least:
- exact model provider and model name
- agent runtime and version when available
- temperature and stochasticity controls when exposed
- true seed when available, otherwise paired replicate index
- tool access and network policy
- wall-clock budget
- maximum repair-pass count
- initial workspace template and files
- task-version hash
- AgentHarness commit SHA
- benchmark-script version hash
- Python 3.12 as the frozen grading target
- `benchmarks/grading-env/constraints-py312.txt`
- `benchmarks/grading-env/wheelhouse-manifest.json` with wheel hashes
- `benchmarks/grading-env/wheelhouse/` as the only offline source for `--no-index` installs
- known frozen warning: the current Starlette and httpx combination emits an `httpx2` deprecation warning during `TestClient` usage without invalidating grading

### 8. Metrics
#### 8.1 Primary endpoint
Primary endpoint: task evaluation score, continuous from 0 to 1, computed per run by the independent held-out task evaluation suite.

The task evaluation suite:
- is independent of `verify-run`
- is never shown to either condition during the run
- checks task-specific correctness, business rules, exact schema, and negative paths
- must be disjoint from the visible `verify-run` claims

The score is the proportion of independent acceptance checks passed.

Rationale:
- this is the only outcome B does not directly optimize against, so it is not circular
- a continuous score carries graded information and reduces ceiling and floor effects relative to a single binary
- this independence holds only if there is no assertion overlap between the evaluation suite and the visible claims

Key binary secondary derived from the same suite:
- task evaluation pass, true only if all critical acceptance checks pass

#### 8.2 Secondary objective metrics
Secondary metrics per run:
- task evaluation pass
- number of independent evaluation checks passed
- number of independent evaluation checks failed
- elapsed time
- repair-pass count
- required raw-artifact completeness
- out-of-scope changed-file count, when measured deterministically

Manipulation checks, not benefit outcomes:
- overall `verify-run` pass
- supported-claim rate
- unsupported claim count
- inconclusive claim count
- invalid claim count

These `verify-run` metrics are partially circular for condition B by design, because B iterates to satisfy the verification loop. They are reported only to confirm that B genuinely engaged the loop, not as primary evidence of benefit.

Truth sources:
- task evaluation suite JSON report
- `verify-run` JSON report, but only as a manipulation check
- deterministic raw-artifact filesystem checks
- benchmark metadata

Independence evidence that must be documented for every task:
- explicit map of visible `verify-run` claims
- explicit map of held-out evaluation-suite checks
- demonstration of disjunction, meaning no duplicated or semantically equivalent assertions
- demonstration of non-leakage of held-out material into the context shown to the agent

#### 8.3 Residual subjective metrics
Subjective metrics are never primary.

Limited use:
- code reviewability
- README operational clarity

Protocol:
- 2 blinded raters
- anonymized artifacts
- 1 to 5 scale
- mean of the two ratings
- inter-rater agreement reported descriptively

If blinding is not credible, these results remain exploratory only.

### 9. Minimal meaningful effect
Minimal meaningful effect, MME:
- fixed value: 0.10 absolute on the task evaluation score

Interpretation:
- the benchmark asks not only whether B is better than A
- it asks whether B is better than A enough to matter

### 10. Hypotheses
Primary directional hypothesis:
- condition B yields a higher task evaluation score than condition A by at least the minimal meaningful effect, on the held-out independent suite

Null hypothesis:
- no difference, or a difference smaller than the minimal meaningful effect, or a difference compatible with noise under this design

The former secondary hypotheses about supported-claim rate and blocking-claim reduction are reclassified as manipulation checks for condition B, not as evidence of benefit.

### 11. Statistical plan
Unit of analysis:
- one run is one observation
- runs are nested within tasks
- tasks are the clusters and govern A versus B inference precision

Primary analysis on the primary endpoint:
- mixed-effects model with condition as a fixed effect and random intercept for task
- for the continuous task evaluation score, use a linear mixed model
- for the linear mixed model, use REML and a degrees-of-freedom correction such as Satterthwaite or Kenward-Roger
- for the binary secondary task evaluation pass, use a logistic generalized linear mixed model
- report the adjusted B minus A effect with a 95 percent confidence interval

Robustness analysis:
- cluster bootstrap that resamples tasks with their replicates
- with few clusters, consider the wild variant and report it explicitly as approximate
- report the mean B minus A difference with a 95 percent confidence interval
- inference precision is driven by the number of tasks, not the number of replicates

Task-level Wilcoxon signed-rank is removed as a primary test. It may appear only as a clearly labeled, underpowered sensitivity check, never as the basis of the headline result.

Secondary objective metrics:
- mixed-effects models or, where a simple paired summary is valid, Wilcoxon signed-rank
- Mann-Whitney U for unpaired comparisons
- bootstrap 95 percent confidence interval for every reported effect size
- Holm correction for the secondary family
- no multiplicity correction for the single primary endpoint

Missing data and failures:
- all runs are included
- a crashed or timed-out run gets 0 on the task evaluation score and counts as a failure on the binary pass
- missing required artifacts count as failures under the relevant criteria
- no post-hoc exclusion except pre-registered hard invalidation of the harness before agent start, with logged reason

Honest limitation to record now:
- with 8 tasks, cluster-level inference remains modest and should be interpreted cautiously
- the benchmark can produce useful evidence, not a universal law
- the earliest cells may be used only as an internal check on base rate and ceiling risk, without changing N, MME, or the inferential plan

### 12. Decision rule
AgentHarness is described as supported by evidence of benefit only if all of the following hold on the held-out independent task evaluation score:
1. the mixed-effects estimate favors B over A
2. the cluster-bootstrap estimate favors B over A
3. the 95 percent confidence interval for the B minus A effect lies entirely above zero
4. the lower bound of that interval is at or above the minimal meaningful effect
5. the result is not driven by a single task, checked by leave-one-task-out
6. the gain is not explained by grossly impractical time cost
7. the report continues to state the package-effect confounder plainly

If these conditions do not hold, the headline result must be one of:
- no effect detected
- mixed evidence
- improvement with unresolved confounding

Manipulation-check metrics derived from `verify-run` are never sufficient for a benefit claim.

### 13. Required raw artifacts
Per run, retain at least:
- `prompt.txt`
- task-spec snapshot
- baseline or framework context snapshot
- transcript or raw output log
- `stdout.log`
- `stderr.log`
- workspace snapshot or changed-files manifest
- `run.json`
- `claims.json`
- `verify-run-report.json`
- `evaluation-report.json`
- `metadata.json`
- repair-pass log, if any

Suggested layout:
- `benchmarks/runs/<task_id>/<condition>/<replicate_id>/`

### 14. Measurement harness design
Design only, no implementation or run approval yet.

The harness should:
1. create a clean workspace for one task-condition-replicate cell
2. render the correct prompt and context package
3. launch the coding agent with fixed settings
4. capture raw outputs and metadata
5. invoke `agentharness verify-run`
6. invoke the independent held-out task evaluation suite
7. produce a normalized summary JSON derived only from real artifacts and reports

Planned command categories:
- command for one cell
- command for the full matrix, only after approval
- command to anonymize artifacts for blinded review
- command to aggregate raw outputs into tables and statistics

Role of `verify-run` in the design:
- checks run and claim envelopes
- checks scope, required artifacts, and test claims
- reexecutes supported pytest wrappers when possible
- emits machine-readable supported, unsupported, inconclusive, and invalid counts
- serves as a manipulation check that B genuinely engaged the verification loop
- is not the primary benefit endpoint

Role of the evaluation suite:
- it is the held-out independent outcome
- it checks task-specific correctness that `verify-run` does not capture generically enough
- it produces a JSON report reproducible from raw artifacts
- it is the primary source for the benefit claim

### 15. Frozen decisions and pre-run prerequisites
Frozen decisions:
1. Treatment:
   - B-loop-closed with symmetric repair for A

2. Sample size:
   - 8 tasks x 6 replicates = 96 total runs

3. Primary endpoint:
   - independent task evaluation score
   - `verify-run` classified as a manipulation check, not as primary benefit evidence

4. MME:
   - 0.10

Mandatory pre-run prerequisites:
5. Task suite:
   - every new task must define its independent evaluation suite before the first run
   - all 8 tasks must pass the quality gate declared in section 5
   - every task must document disjunction between the evaluation suite and the claims contract
   - every task must document non-leakage of held-out material

6. Residual subjective metrics:
   - if included in phase one, they remain exploratory secondary outputs

7. Held-out grading environment:
   - operational freeze complete
   - rebuildable from the versioned artifacts in `benchmarks/grading-env/` alone
   - root offline gate green
   - solution-level gate green for API reference, CLI reference, and an in-spec `EmailStr` variant

### 16. Freeze rule
No benchmark run starts until the section-5 quality gate is satisfied.
With this approval, the following are frozen:
- treatment
- task count fixed at 8 and the rules for constructing tasks
- sample size
- metrics
- MME
- decision rule

Concrete task instances are added under the section-5 quality gate before the first run.
Any reduction to 6 tasks or other change in task count requires a formal amendment.

If the 8-task quality gate is not met before the first run, benchmark execution stays blocked and requires a formal pre-registration amendment.
The same block applies if disjunction between evaluation suite and claims contract is not demonstrated, or if held-out material leaks into the agent-visible context.

### 17. Operational appendix

This section freezes the concrete operational parameters, system facts, and held-out functional checks that must remain unchanged before the first benchmark run.

#### 17.1 Frozen system facts
- repository path: `/home/fabio/AgentHarness`
- frozen branch: `main`
- frozen benchmark code commit SHA: `04db03d`
- appendix first recorded in the repository at commit: `10ea1a1`
- agent model: `gpt-5.4`
- agent provider: `openai-codex`
- frozen grading constraints path: `/home/fabio/AgentHarness/benchmarks/grading-env/constraints-py312.txt`
- frozen wheelhouse manifest path: `/home/fabio/AgentHarness/benchmarks/grading-env/wheelhouse-manifest.json`
- frozen offline wheelhouse path: `/home/fabio/AgentHarness/benchmarks/grading-env/wheelhouse`

#### 17.2 Frozen per-cell budget and time limits
- maximum turns per cell: `40`
- maximum input tokens per cell: `200000`
- maximum output tokens per cell: `60000`
- maximum total tokens per cell: `300000`
- agent invocation timeout per cell: `1800` seconds
- local test timeout per cell: `180` seconds
- budget and timeout are identical for condition A, condition B, and all replicates

#### 17.3 Frozen randomization and bootstrap settings
- randomization method: pseudorandom permutation of cell order using a seeded generator, with the seed recorded per stage
- Stage 1 seed: `20260701`
- Stage 2 seed: `20260702`
- bootstrap 1: cluster bootstrap
  - purpose: confidence interval for the effect
  - resampling unit: task
  - seed: `20260703`
  - resamples: `10000`
- bootstrap 2: wild cluster bootstrap
  - purpose: confidence interval for the effect
  - resampling unit: task
  - seed: `20260704`
  - resamples: `10000`

#### 17.4 Held-out functional checks by task
Only functional checks are part of this table. The structural envelope check `evaluation_result_schema` is excluded from every task below and is not part of the primary endpoint.

| Task | Held-out functional checks only |
| --- | --- |
| `support-ticket-api` | `create_valid_ticket`, `list_filters_work`, `closed_ticket_reopen_blocked`, `comments_embedded_in_detail`, `invalid_email_rejected` |
| `inventory-adjustment-api` | `reserve_within_available`, `over_reserve_rejected`, `damage_cannot_go_negative`, `recount_sets_exact_quantity`, `release_cannot_exceed_reserved` |
| `webhook-ingestion-service` | `valid_signed_event_stored`, `invalid_signature_rejected`, `duplicate_delivery_idempotent`, `type_normalized_correctly`, `missing_fields_rejected` |
| `report-export-job` | `csv_rows_sorted_complete`, `net_totals_correct`, `date_filter_applied`, `summary_totals_match`, `invalid_date_rejected` |
| `leave-request-api` | `valid_request_created`, `overlap_rejected`, `personal_leave_limit_enforced`, `approval_sets_reviewed_at`, `terminal_state_blocks_second_review` |
| `incident-escalation-api` | `sev1_escalates_on_time`, `ack_stops_escalation`, `resolved_stops_escalation`, `sev3_not_auto_escalated`, `invalid_as_of_rejected` |
| `refund-approval-api` | `small_refund_auto_approved`, `medium_refund_needs_manager`, `large_refund_needs_finance`, `invalid_amount_rejected`, `terminal_state_blocks_reapproval` |
| `csv-member-import` | `valid_rows_normalized`, `duplicate_handling_correct`, `invalid_rows_rejected_with_reason`, `summary_counts_correct`, `output_files_present` |

Source of the held-out functional checks above: the versioned evaluator definitions in each task's `HELDOUT_EVALUATION_SUITE.template.json`, with the non-functional envelope check removed.

#### 17.5 Frozen non-leakage audit result
- non-leakage audit result: `PASS`
- basis of the PASS:
  - `benchmarks/QUALITY_GATE_POLICY.md` requires that only `SPEC.md` and the visible claims contract may be shown during the run
  - `src/agentharness/benchmark_cells.py` copies only `SPEC.md` and `CLAIMS_CONTRACT.template.json` into the agent-visible `inputs/` directory
  - `src/agentharness/benchmark_cells.py` does not copy `QUALITY_GATE.md`, `RUN_PROTOCOL.md`, `SCORECARD.md`, or held-out evaluator outputs into the agent-visible inputs
  - prompt construction in `src/agentharness/benchmark_cells.py` uses only materialized cell-local input/output paths and explicitly instructs the agent not to inspect any held-out evaluation suite
  - regression tests in `tests/test_benchmark_cells.py` enforce the allowed-inputs and cell-local-path non-leakage constraints

#### 17.6 Pre-analysis amendment (2026-07-02, before inspecting any Stage 1 outputs)
An initial Stage 1 launch was started and then aborted before inspecting any summary statistics, invalid-rate aggregates, ceiling counts, or treatment-contrast results. The aborted run is discarded unread and is not part of the benchmark evidence base. This amendment records three execution-level corrections discovered by code inspection before any Stage 1 analysis.

- correction 1: token budgets in section 17.2 remain frozen as nominal safety ceilings, but on the `openai-codex` / `gpt-5.4` backend they are not hard-enforced by the Stage 1 runner path actually used for execution
  - frozen nominal ceilings remain: input `200000`, output `60000`, total `300000`
  - interpretation after this amendment: these token values are documented operating ceilings, not an enforced exclusion rule in the current backend path
  - hard-enforced per-cell controls for the relaunched Stage 1 are: maximum turns `40`, agent wall-clock timeout `1800` seconds, and local pytest timeout `180` seconds
- correction 2: the single allowed rerun for a `harness_invalid` or held-out-`invalid` cell must be executed on a freshly rematerialized cell
  - operational rule after this amendment: before the one allowed rerun, the harness must call fresh cell materialization again so that `workspace/`, `inputs/`, `outputs/`, `run.json`, `claims.json`, `provenance.json`, and `metadata.json` are recreated from scratch
  - if the rerun remains invalid, the cell is excluded from the primary analysis and reported explicitly under the preregistered invalid-cell rule
- correction 3: the relaunched Stage 1 runner must enforce the declared time limits directly in the launcher wrapper
  - agent invocation timeout per cell: enforced at `1800` seconds
  - local pytest timeout per cell: enforced at `180` seconds
  - these enforcement checks are verified in code before the benchmark is relaunched

#### 17.7 Pre-analysis amendment (2026-07-02, before inspecting any Stage 1 outputs)
A second Stage 1 launch exposed a harness-side execution-path discrepancy before any analyzable cell results were produced. The first randomized cell (`refund-approval-api`, `A-baseline`, `r2`) repeatedly left the materialized workspace empty while the child Hermes CLI wrote solution files under `/home/fabio`. This run is discarded unread and is not part of the benchmark evidence base.

- correction 4: Hermes CLI execution in this environment must not rely on subprocess cwd semantics for benchmark-cell file placement
  - empirical finding before analysis: invoking `hermes chat` from a subprocess with `cwd=<cell workspace>` still caused file-tool writes to land in the default Hermes session directory (`/home/fabio`) rather than in the per-cell workspace
  - operational rule after this amendment: Stage 1 benchmark prompts must provide explicit absolute cell-local paths for the workspace, visible inputs, and repair-feedback files, and must instruct the agent to use those exact absolute paths for all file operations instead of relying on the default current working directory
  - non-leakage interpretation after this amendment: prompt-visible paths remain confined to the materialized cell (`workspace/`, `inputs/`, `outputs/`) and do not expose benchmark task-pack directories or held-out evaluator assets
- correction 5: the analyzable benchmark-code freeze is updated to the first commit that includes the verified absolute-path workspace fix and its regression-test updates
  - the prior benchmark-code freeze commit `04db03d` remains the basis for discarded unread smoke/diagnostic launches only
  - the replacement benchmark-code commit is the commit referenced by the post-amendment relaunch and by the run-level provenance artifacts of the analyzable Stage 1 campaign

#### 17.8 Post-diagnostic amendment (2026-07-03, before any treatment-effect interpretation of the completed Stage 1 run)
The completed Stage 1 diagnostic campaign on the post-amendment freeze is not analyzable for A-vs-B treatment effect because benchmark-cell execution was materially contaminated by provider-availability failures. This amendment records that diagnosis before any treatment-effect claim is made from the run.

- correction 6: provider-side quota / rate-limit failures must be reported separately from generic harness-invalid cells and separately from ordinary task failures
  - empirical finding after run completion: a large subset of Stage 1 cells terminated with empty workspaces because the Hermes CLI invocation failed upstream with provider-side availability errors, including `HTTP 429: The usage limit has been reached`
  - these cells do not constitute evidence about task-solving ability and must not be pooled with ordinary failed solutions when interpreting condition means or ceilings
  - Stage 1 summaries must report provider-unavailable counts explicitly, alongside but distinct from generic harness-invalid counts
- correction 7: the completed Stage 1 diagnostic campaign on freeze `e8e8504` is classified as non-analyzable for treatment contrast
  - observed contamination count: `31/48` cells were invalid due to provider-unavailable failures, with asymmetric realized exposure across conditions
  - consequence: the completed run may be used only for diagnostic inspection of failure modes and harness instrumentation, not for comparative A-vs-B inference
  - operational requirement before any renewed Stage 1 claim: rerun only under a provider/profile path with sufficient confirmed execution headroom, or under an explicit preflight/abort rule that stops the campaign if provider-unavailable failures recur

#### 17.9 Pre-relaunch amendment (2026-07-07, before any renewed Stage 1 launch)
Two execution-path corrections are required before any clean Stage 1 relaunch.

- correction 8: persistent provider-side availability failures must terminate as analyzable invalids, not as apparent task misses
  - the benchmark runner must retry provider-side invocation failures with bounded backoff using explicit markers such as `HTTP 429`, `usage limit has been reached`, `rate limit`, `temporarily unavailable`, and `quota`
  - if every invocation attempt still ends in those provider-side markers and leaves the workspace empty, the cell must be recorded as `benchmark_execution_status = harness_invalid`, `benchmark_outcome_status = invalid`, with a `benchmark_classification_reason` prefixed by `provider_unavailable:`
  - these cells remain excluded from the primary analysis and must be counted separately in reliability summaries as provider-unavailable, not as agent failures
  - the Stage 1 launcher must also enforce a fixed delay between cells to reduce contiguous provider-throttling blocks
- correction 9: FastAPI app discovery in hidden evaluation must be based on a real importable app object, not on a literal source-string pattern
  - discovery must not depend on finding the text `FastAPI(` in source files
  - acceptable benchmark solutions include equivalent constructions such as aliased imports and supported zero-argument app factories, provided they materialize a real `FastAPI` application object in the workspace
  - hidden evaluation must continue to reject workspaces that do not expose any importable `FastAPI` app object


#### 17.10 Pre-relaunch amendment (2026-07-10, before any renewed analyzable Stage 1 launch)
A fresh unread Stage 1 relaunch attempt was aborted immediately after the first observed invocation because the runner surfaced a new infrastructure-classification defect before any summary, invalid-rate review, or treatment-contrast inspection was performed. The aborted run is archived unread and is not analyzable.

- correction 10: Codex SSE stream-stall failures must be treated as provider-unavailable retry markers and, if persistent, as provider-unavailable invalids
  - empirical finding before analysis: the first observed invocation of the unread aborted relaunch failed with the message `Codex stream produced no SSE events for 12s after first byte`, leaving the workspace empty
  - this failure mode is provider-side availability degradation, not evidence about task-solving ability and not evidence of an empty-workspace task miss
  - the benchmark runner must therefore include the message fragment `produced no SSE events` in both the bounded-backoff retry markers and the provider-unavailable classification markers
  - if all invocation attempts end in that marker and the workspace remains empty, the cell must be recorded as `benchmark_execution_status = harness_invalid`, `benchmark_outcome_status = invalid`, with `benchmark_classification_reason` prefixed by `provider_unavailable:`
- declaration on correction 9 status: the FastAPI app-discovery fix recorded in correction 9 is a substantive pre-analysis benchmark-validity amendment, not a mere infrastructure refactor
  - reason: it changes which benchmark solutions are recognized as valid hidden-evaluation candidates under the preregistered task semantics
  - analyzable Stage 1 and Stage 2 runs must therefore use a commit that includes both the correction-9 discovery fix and the correction-10 SSE-stall provider classification fix

#### 17.11 Stage 2 analysis-stack freeze (2026-07-10, before any Stage 2 data collection)
The Stage 2 inferential scripts now exist, were tested on synthetic data with a known built-in effect, and are frozen before any Stage 2 real data collection. No Stage 1 summary outputs or treatment contrasts were used to shape these scripts.

- correction 11: the executable Stage 2 analysis stack is frozen in versioned code and a dated freeze note before Stage 2 launch
  - frozen files include `src/agentharness/stage2_analysis.py`, `benchmarks/grading-env/stage2_build_dataset.py`, `benchmarks/grading-env/stage2_run_analysis.py`, `benchmarks/grading-env/stage2_generate_synthetic_dataset.py`, `benchmarks/grading-env/stage2_synthetic_smoke.py`, `tests/test_stage2_analysis.py`, and `benchmarks/grading-env/STAGE2_ANALYSIS_FREEZE_2026-07-10.md`
  - the scripts were validated end-to-end on a synthetic dataset whose true `B - A` effect is known by construction, and the recovered effect had to match that truth within a fixed tolerance before freeze
  - the frozen robustness set includes cluster bootstrap, wild cluster bootstrap, leave-one-task-out, invalid-policy sensitivity, and the manipulation check based on attempt-versus-repair solution-hash change in both arms
- correction 12: because the pinned Python stack available here does not provide a dependable Kenward-Roger implementation for the planned random-intercept model, the executable finite-sample primary inference is frozen as task-level paired mean differences with small-cluster t inference over tasks
  - the REML random-intercept mixed-model coefficient is still emitted as a concordance estimate in the report
  - the primary inferential quantities used for the frozen report come from the task-cluster estimator, not from an unavailable or guessed Kenward-Roger routine
  - this is declared now, before Stage 2 data exist, as a substantive analytic-execution amendment rather than a silent implementation substitution

#### 17.12 Stage 2 calibration extension to the freeze (2026-07-10, before any Stage 2 data collection)
The Stage 2 freeze is extended to verify that the analysis code can say "no" under synthetic datasets where improvement should not be declared.

- correction 13: the frozen regression suite now includes explicit calibration controls in addition to the positive-control recovery test
  - `true_effect = 0.0` must not return `improvement_supported`
  - `true_effect = 0.05`, below the frozen MME of `0.10`, must not return `improvement_supported`
  - `true_effect = -0.15` must not return `improvement_supported`
- correction 14: the frozen suite now includes a null Monte Carlo false-positive check over 100 synthetic datasets with distinct seeds
  - the observed rate of `improvement_supported` under the null must remain at or below 10% in the frozen regression suite
  - the purpose is calibration against optimistic analysis behavior before any Stage 2 real data are seen
- correction 15: the task-cluster estimator is now explicitly frozen as equal-weight-per-task after invalid handling
  - within each task and condition, valid cells are averaged first
  - after that, each task contributes exactly one paired `B - A` difference
  - tasks are not weighted by how many valid cells remain after infrastructure-invalid exclusions

This extension was implemented and tested before any Stage 2 data collection and without reading Stage 1 summary outputs or treatment contrasts.

#### 17.13 Stage 2 decision-rule and power-curve extension (2026-07-10, before any Stage 2 data collection)
The Stage 2 freeze is extended again so that a final non-positive result cannot be over-interpreted as evidence of no meaningful effect unless the frozen decision rule actually supports that conclusion.

- correction 16: the frozen top-line decision now emits exactly three states from the primary task-cluster confidence interval relative to the MME of `0.10`
  - `improvement_supported` if the primary CI lower bound is strictly greater than `0.10`
  - `no_meaningful_effect` if the primary CI upper bound is strictly less than `0.10`
  - `inconclusive` otherwise
- correction 17: the frozen regression suite now includes synthetic cases that explicitly produce each of the three decision states
  - positive-effect control for `improvement_supported`
  - null / negative controls for `no_meaningful_effect`
  - above-MME but noisy control for `inconclusive`
- correction 18: a synthetic power-curve freeze has now been generated and versioned before any Stage 2 real data collection
  - effects grid: `0.05, 0.10, 0.12, 0.15, 0.18, 0.25`
  - noise grid: low / medium / high synthetic noise profiles
  - replications: 200 synthetic datasets per effect × noise cell
  - frozen output artifacts: `STAGE2_POWER_CURVE_FREEZE_2026-07-10.json` and `.md`
  - reported quantity: observed rate of `improvement_supported`, plus complementary `no_meaningful_effect` and `inconclusive` rates
  - frozen examples: for `true_effect = 0.12`, observed `improvement_supported` rates are `0.595` (low noise), `0.170` (medium noise), and `0.095` (high noise)
- correction 19: the Stage 2 interpretation rule is now pre-bound to this three-state logic
  - a final CI entirely below the MME supports `no_meaningful_effect`
  - a final CI straddling the MME is `inconclusive`, not a null claim

This extension was implemented and tested before any Stage 2 data collection and without reading Stage 1 summary outputs or treatment contrasts.

#### 17.14 Stage 2 null-identifiability and blind noise-regime extension (2026-07-10, before any Stage 2 data collection)
The Stage 2 freeze is extended once more to separate two questions that had previously been conflated: (a) power to declare a meaningful improvement, and (b) power to declare the absence of a meaningful improvement.

- correction 20: a null-identifiability freeze has now been generated at `true_effect = 0.00` across the frozen low / medium / high synthetic noise profiles
  - artifact files: `STAGE2_NULL_IDENTIFIABILITY_FREEZE_2026-07-10.json` and `.md`
  - replications: 200 synthetic datasets per noise profile
  - reported quantities: rates of `no_meaningful_effect`, `inconclusive`, and `improvement_supported`
  - frozen result: `no_meaningful_effect` occurred at rates `1.000` (low noise), `1.000` (medium noise), and `0.985` (high noise)
- correction 21: the key remaining uncertainty is therefore not whether the frozen decision rule can ever emit `no_meaningful_effect`, but whether the live Stage 1 dispersion regime is closest to the low / medium / high synthetic family used by the frozen calibration artifacts
- correction 22: a post-Stage-1 blind regime-matching script now exists and is frozen before any Stage 2 data collection
  - script: `benchmarks/grading-env/stage1_blind_variance_regime.py`
  - inputs: `progress.json` from a completed Stage 1 run
  - output: a blind report containing between-task score dispersion, within-task-condition replicate dispersion, and nearest frozen synthetic noise profile
  - explicit guardrail: it estimates dispersion only and does not compute or report any A-vs-B contrast
- correction 23: campaign decisions remain deferred until that blind regime report exists on the completed Stage 1 run
  - if the observed blind dispersion is compatible with a frozen regime where practical-effect detection is too weak for the intended claim, the campaign must be reconsidered before any contrast reading or Stage 2 launch
  - the MME remains unchanged; no threshold-lowering amendment is introduced here

This extension was implemented before any Stage 2 data collection and without reading Stage 1 summary outputs or treatment contrasts.

#### 17.15 Treatment-delivery amendment (2026-07-11, after blind regime matching and before any treatment-contrast reading from the current Stage 1 run)
A manipulation check on the completed Stage 1 run found that the intended pre-repair `verify-run` feedback artifact was not delivered to the AgentHarness repair pass in condition B. This amendment records that delivery failure, freezes the corrective gate, and forbids treatment-effect interpretation of the current run.

- correction 24: the Stage 1 run completed on launcher commit `e5600bd` is not interpretable as an A-vs-B treatment-effect run
  - empirical finding: across the completed Stage 1 artifacts, the expected file `outputs/pre-repair-verify-run-report.json` was absent in all `24/24` condition-B cells
  - consequence: the intended B-arm treatment was not observably delivered, so the current run cannot support any estimate of treatment effect and may be used only for harness diagnosis
- correction 25: treatment delivery is now a symmetric harness gate on both arms
  - in condition B, treatment delivery requires a written, non-empty, parseable pre-repair `verify-run` report that contains explicit `feedback`
  - in condition A, treatment delivery requires that the repair-pass treatment prompt itself be materialized and delivered rather than silently skipped by the harness
  - if the required treatment artifact for either arm is missing, empty, malformed, or otherwise not delivered, the cell must short-circuit before repair and be recorded as `benchmark_execution_status = harness_invalid` with `benchmark_classification_reason = treatment_not_delivered`
  - these cells are experiment-invalid infrastructure exclusions, not task-solving failures, and must be counted explicitly in run summaries
- correction 26: `run_verify_run` and the `verify-run` command must verify real report persistence, not only stdout
  - passing `--report-path` must cause the report to be written at that exact path in the real runtime context
  - the wrapper must surface whether the report exists, is non-empty, is parseable JSON, and contains explicit `feedback`, so the arm-level gate can reject silent treatment loss automatically
- declaration on current Stage 1 campaign status: no A-vs-B contrast from the current Stage 1 run may be read or interpreted as a treatment effect until the treatment-delivery channel is repaired and Stage 1 is rerun on the corrected benchmark code

#### 17.16 Pre-rerun code-lineage amendment (2026-07-15, before the masked noise remeasurement)
Before collecting the masked post-clarification noise data, the complete code lineage from structural-spec freeze `4a5ba8f` through public-release head `678d986` was reviewed and recorded. The starting commit remains the substantive structural-spec clarification already declared in the dated 2026-07-11 amendment. The later commits are packaging, release, CI, community-readiness, product-front-door, reliability, and invocation-adaptation work. This lineage review does not authorize treatment-effect interpretation of the diagnostic rerun.

Commits in the reviewed range:
- `4a5ba8f6751278c9fc7b207ea323e2b4cc7d5cbd` (`Clarify benchmark structural spec contracts`): the already-declared substantive clarification of task packaging, importability, layout, and entrypoint contracts; it changes no functional requirement, hidden evaluator, treatment prompt, or score calculation
- `fbf0de67732851971f609a3972884ef24b4c16bb` (`Harden Stage B reliability runs`): operational reliability and invocation adaptation; in `benchmark_cells.py`, the invoker change only exposes `provider`, `model`, and `max_turns` as explicit invocation parameters and forwards them to the Hermes CLI
- `6b8810fa512f7a94c3d9ebe90c02790e08206262` (`Add one-command workspace verification`): product-front-door and package usability work
- `9617df85f1011b7248a971ea0d72c1d0d47fccdf` (`Prepare AgentHarness for community adoption`): open-source packaging, metadata, CI, licensing, and contributor-readiness work
- `3d17631808481671d06740769d5ea30d41198bc0` (`Fix clean-install verification and CI compatibility`): clean-install and invocation adaptation; the `reexecution.py` change selects the currently running Python interpreter for allowed `python -m pytest` reexecution when pytest is available in that interpreter
- `24192214dfc6d9682dbf29f9b38352d5f3c577d1` (`Prepare verified 0.1.0 release workflow`): release validation, build, documentation, and Trusted Publishing workflow
- `94c61f62968167a93b2b9259f8844051a7e49c60` (`Rename PyPI distribution to agentharness-verifier`): distribution-name and release-documentation adaptation
- `678d98645088886230bb3e013b2c30248b0f4554` (`Fix renamed wheel in clean-install CI`): clean-install CI filename correction

Methodological declaration for this range:
- the `benchmark_cells.py` invocation change exposes only provider, model, and maximum turns as invoker parameters; it does not alter task materialization, treatment content, treatment-delivery criteria, held-out grading logic, or score computation
- the `reexecution.py` change selects the current interpreter for pytest reexecution; it does not alter the allowed test semantics, verdict rules, benchmark treatment, hidden grading logic, or score computation
- no commit in this range modifies the hidden task evaluators or the calculation of the held-out task score
- packaging, release, CI, and invocation adaptations in this range are operational prerequisites only; they do not change the estimand or authorize reading an A-versus-B contrast from the masked noise-remeasurement run
- the next run is restricted to treatment-delivery integrity checks, invalid classification, masked dispersion estimation, and blind wiring-versus-logic diagnosis

#### 17.17 Post-contrast repair-safety amendment (2026-07-16, before any safety pilot or renewed efficacy campaign)
A post-contrast causal-forensic audit of the masked noise-remeasurement run identified three condition-B cells in which cumulative repair changes directly damaged solutions that had passed canonical pre-repair pytest. This amendment is necessarily post-contrast. It does not alter, exclude, or replace the preregistered result from the 2026-07-15 run. The official estimate and confidence interval remain unchanged, and the post-hoc exclusion sensitivity remains diagnostic only.

- correction 27: canonical pytest reexecution must preserve the benchmark runner's interpreter, working directory, and allowlisted environment
  - `run.json` must record the absolute `.stageb-test-venv` Python command rather than the generic text `pytest -q`
  - the reexecution policy may preserve that absolute interpreter only when it belongs to an approved virtualenv path inside the declared workspace
  - command-level `PYTHONPATH` must remain inside the workspace
  - command-level `AGENTHARNESS_GRADING_ENV_DIR` must equal the versioned repository grading environment
  - a declared-versus-reexecuted exit-code mismatch must be labeled `environment_mismatch` in diagnostics, but no caller-controlled run field may downgrade a reexecuted failure from `unsupported`
- correction 28: all repair retries are cumulative and must be audited as one intervention
  - every cell must retain a pre-repair workspace snapshot outside the agent-editable workspace
  - every cell must emit `repair-cumulative.diff`, including introduced or retargeted symlinks
  - provenance must retain both the raw post-repair solution hash and the final accepted or restored solution hash
- correction 29: the repair pass in both conditions is subject to the same deterministic safety gate
  - post-repair canonical pytest must not regress from green to non-green
  - when both pre- and post-repair pytest are non-green, observable failure/error counts must not increase, passing counts must not decrease, and the pytest exit class must not worsen
  - a manifest that installed before repair must still install offline under the frozen constraints and wheelhouse after repair
  - a repair after green canonical pytest may not change dependency manifests, abandon a declared dependency used by the working implementation, create a local package that shadows a declared third-party dependency, or introduce a workspace symlink
  - the protected `.stageb-test-venv` is fingerprinted; modification forces rollback without executing post-repair tests in the altered environment
- correction 30: an unsafe repair is rolled back before final grading
  - rollback deletes runtime virtualenvs, restores the pre-repair solution snapshot, rebuilds the canonical test environment, and reruns canonical pytest
  - a rollback that does not restore the pre-repair pytest exit state is `harness_invalid`
  - an exception or timeout anywhere in the post-repair safety gate must attempt rollback before the cell exits and must be recorded as `harness_invalid`, never left as an accepted mutated workspace
  - the safety decision, reasons, cumulative diff, rollback status, and rollback validation are mandatory raw artifacts
- correction 31: the repair prompt receives the same safety constraints in both arms
  - both arms are told that canonical pytest is authoritative, all retries are cumulative, speculative infrastructure workarounds are disallowed, and local dependency shadow packages are forbidden
  - when canonical pytest is green, both arms are told not to change dependency versions, replace the persistence layer, or rewrite working architecture
  - condition B is additionally told that `environment_mismatch` is inconclusive feedback and must not be repaired by changing the solution to fit a different environment

Consequences for estimand and data lineage:
- this is a substantive treatment amendment because it changes the executable repair policy and can prevent or reverse harmful repair mutations
- data collected before correction 27 through correction 31 must not be pooled with data collected after these corrections as if they came from one unchanged treatment
- no prior cell is rescored, deleted, or reclassified by this amendment
- the implementation commit frozen for corrections 27 through 31 is `0504b34a01a01dfea5ca8aeecd7b1b4c7e13cc6e`
- the exact implementation SHA must be recorded in the safety-pilot launcher and every pilot provenance record

Frozen safety-pilot protocol, not an efficacy campaign:
- tasks: `inventory-adjustment-api`, `leave-request-api`, and `refund-approval-api`, selected before launch because they instantiate the three audited harmful-repair mechanisms
- cells: one fresh replicate per task and condition, for 6 cells total
- repair policy: exactly the amended symmetric repair policy above
- provider, model, maximum turns, timeouts, grading constraints, and wheelhouse must be recorded before launch
- no hidden evaluator is run during the pilot
- no held-out task score is read or produced
- no A-versus-B endpoint or contrast is computed
- pilot outputs are restricted to treatment delivery, canonical reexecution parity, cumulative repair provenance, safety-gate decision, rollback behavior, and invalid classification

Pilot GO gate, all conditions required:
1. all 6 cells materialize their required arm-specific treatment artifacts
2. all canonical commands are reexecuted with the recorded workspace interpreter, cwd, `PYTHONPATH`, and frozen grading environment
3. declared and reexecuted pytest exit codes agree in every cell
4. every repair emits a non-missing safety report and cumulative diff, including an explicitly empty diff when no files changed
5. every triggered rollback restores the pre-repair pytest exit state
6. no safety-gate infrastructure error, rollback error, treatment-not-delivered error, or unclassified invalid occurs

Pilot STOP rule:
- failure of any GO condition stops the protocol after the affected cell's artifacts are persisted
- no additional pilot cell, efficacy campaign, power recalculation, or public claim is authorized until the failure is diagnosed and a new dated amendment is recorded

This amendment freezes the safety protocol before the pilot. It does not authorize the pilot to schedule a renewed efficacy campaign and does not choose the size or shape of any later campaign.

#### 17.18 Safety-pilot STOP-1 amendment (2026-07-16, after pilot 1 stopped and before any replacement pilot data)

Pilot 1 was launched from `7ab10965650dbc5b7446d5941992ffa09921dc04` under the frozen section 17.17 protocol. Its run root is `/home/fabio/AgentHarness-benchmark-runs/repair-safety-pilot-20260716T073240Z`. The preregistered STOP rule fired after the first randomized cell, `leave-request-api/B-agentharness/r1`, and the remaining five cells were not started. No hidden evaluator was invoked, no held-out score was produced, and no A-versus-B contrast was computed.

Observed integrity facts from the stopped cell:
- both agent invocations returned exit code 0 and materialized non-empty workspace and treatment artifacts, although the Hermes CLI did not print a parseable `session_id` in the captured stdout
- the B verify-run report existed, was non-empty valid JSON, and was referenced by the repair prompt
- the symmetric repair safety gate completed without infrastructure error, emitted a cumulative diff, required no rollback, preserved manifest installability, and improved canonical pytest from exit 1 to exit 0
- verify-run did not reexecute the canonical test command because the claims contract required the literal command `pytest -q`, while `run.json` correctly recorded the canonical absolute command `<workspace>/.stageb-test-venv/bin/python -m pytest -q`
- the pilot launcher also incorrectly resolved the expected `.stageb-test-venv/bin/python` symlink before comparing it with the intentionally unrevolved recorded command, and required a parseable `session_id` even though section 17.17 did not preregister that field as a GO condition

Diagnosis and correction 32:
- required-command resolution may treat only semantically identical pytest wrapper forms as equivalent
- accepted equivalent prefixes are `pytest`, `python -m pytest`, an absolute Python interpreter followed by `-m pytest`, and the same forms under `uv run`
- every pytest argument after the normalized prefix must remain exactly identical and in the same order; this amendment does not permit fuzzy matching, argument deletion, command substitution, or equivalence for non-pytest commands
- the frozen implementation commit for correction 32 is `dd114e77c2a1edcbe461dd62891ffb3e9096061f`
- a diagnostic re-verification of the already collected stopped-cell artifacts, without a provider call or hidden evaluator, confirmed that correction 32 resolves the command, performs controlled reexecution, and emits a `truth_source = reexecuted` audit

Replacement pilot rules:
- pilot 1 remains a stopped, non-GO pilot and its cell must not be counted as replacement-pilot data
- the replacement pilot must start from six entirely fresh cells and a new run root; no workspace, result, or GO status from pilot 1 may be reused
- tasks, conditions, replicate count, provider, model, maximum turns, timeouts, treatment, randomization method, hidden-evaluator prohibition, held-out-score prohibition, contrast prohibition, GO gate, and STOP rule remain those frozen in section 17.17
- the replacement launcher must compare the recorded canonical interpreter path without resolving its virtualenv symlink
- invocation evidence is sufficient when the Hermes attempt exits 0 and has non-empty captured stdout or stderr, consistent with the versioned benchmark runner; a parseable `session_id` remains useful provenance but is not an additional GO requirement
- B feedback delivery is established by a valid non-empty `feedback.items` list, not by a nonexistent top-level `claims` field
- the replacement launch SHA, origin/main SHA, launcher path, launcher SHA-256, and exact six-cell randomized order must be persisted before its first provider call

This dated amendment authorizes one replacement safety pilot under these frozen corrections only. It still does not authorize a hidden evaluation, efficacy campaign, power recalculation, A-versus-B contrast, or public efficacy claim.

#### 17.19 Replacement safety-pilot execution record (2026-07-16, post-pilot)

The replacement pilot authorized by section 17.18 completed from launch and origin/main SHA `d5d27108c9415e7051a56c2c893b41cec4985cfd`. Its immutable launch metadata, exact randomized order, raw cell artifacts, result records, and independent audit are stored under `/home/fabio/AgentHarness-benchmark-runs/repair-safety-pilot-v2-20260716T075933Z`.

Operational result:
- all 6 frozen fresh cells completed and passed the cell-level GO audit
- all 6 invocations had exit code 0 with captured invocation evidence
- all required treatment artifacts were present and non-empty; both B prompts referenced valid structured verify-run reports with feedback
- all applicable B canonical commands completed controlled reexecution with the recorded workspace interpreter, cwd, `PYTHONPATH`, and grading environment, and declared versus reexecuted pytest exits agreed
- all 6 cells emitted a repair-safety report and cumulative diff
- no safety-gate infrastructure error, treatment-delivery error, rollback error, unclassified invalid, or forbidden hidden-evaluation artifact was observed
- no rollback was required in these six live cells; therefore live rollback recovery was not exercised by this pilot, while the deterministic regression and exception paths remain covered by the versioned automated test suite
- no hidden evaluator was invoked, no held-out score was produced or read, and no A-versus-B endpoint or contrast was computed
- the independently recomputed launcher SHA-256 matched the preregistered metadata value `464894b6e89da2f50a799e466684803c78ff8e39c68a38e660effc3c61cb7220`
- the independent audit is `pilot-independent-audit.json` in the replacement run root and records `pilot_go = true`

Interpretation boundary:
- this is a GO for the amended treatment-delivery, canonical-reexecution, and repair-safety channel under the six-cell pilot protocol
- it is not evidence that condition B improves task quality, does not estimate any treatment effect, and does not alter or supersede the official 2026-07-15 result
- this execution record does not itself authorize a renewed efficacy campaign, choose a campaign design, recalculate power, or support a public efficacy claim

#### 17.20 Model-transition safety-pilot amendment (2026-07-16, before any GPT-5.6 safety-pilot data)

The replacement pilot recorded in section 17.19 explicitly overrode the Hermes default and ran on `openai-codex/gpt-5.4`, matching the earlier campaign provider/model pin. The live Hermes default is now `openai-codex/gpt-5.6-sol`. The section 17.19 GO remains valid evidence for GPT-5.4 only and must not be represented as live delivery evidence for GPT-5.6 Sol.

Before any efficacy campaign using GPT-5.6 Sol, one model-transition safety pilot is authorized under these frozen rules:
- use exactly six entirely fresh cells: `inventory-adjustment-api`, `leave-request-api`, and `refund-approval-api`, one replicate in each of `A-baseline` and `B-agentharness`
- pin provider `openai-codex`, model `gpt-5.6-sol`, maximum turns 40, agent timeout 1800 seconds, pytest timeout 180 seconds, and inter-cell delay 30 seconds before the first provider call
- use the same amended treatment, correction 32, repair-safety gate, hidden-evaluator prohibition, held-out-score prohibition, contrast prohibition, GO conditions, and immediate STOP rule frozen in sections 17.17 and 17.18
- create a new run root and fresh workspaces; no workspace, result, or GO status from the GPT-5.4 pilots may be reused
- persist launch SHA, matching origin/main SHA, launcher path and SHA-256, model pin, randomization seed and method, and exact six-cell order before the first provider call
- do not invoke a hidden evaluator, produce or read a held-out task score, calculate an A-versus-B endpoint, or interpret arm differences

Interpretation rule:
- six of six GO permits the treatment-delivery and repair-safety channel to be treated as operationally validated for GPT-5.6 Sol
- any failed GO condition triggers STOP after the affected cell and requires a new dated diagnosis before any additional cell or campaign
- even a complete GO is not efficacy evidence and does not authorize a public treatment-effect claim

#### 17.21 GPT-5.6 stream-watchdog STOP amendment (2026-07-16, after the first GPT-5.6 cell stopped and before any replacement data)

The section 17.20 pilot launched from `e3f9adc53ab7b4ca61eda387f6d2287abd103689` and stopped after its first randomized cell, `leave-request-api/A-baseline/r1`. The remaining five cells were not started. The stopped run root is `/home/fabio/AgentHarness-benchmark-runs/repair-safety-pilot-gpt56-20260716T101623Z`. No hidden evaluator was invoked, no held-out score was produced or read, and no A-versus-B contrast was computed.

Diagnosis:
- all three initial Hermes retries opened a session but exited 1 with `Codex stream produced no SSE events for 12s after first byte`
- the empty initial workspace consequently produced canonical pytest exit 5 and a missing-manifest result
- the bounded repair invocation later exited 0 and produced a runnable workspace; the deterministic repair-safety gate itself completed safely, with post-repair pytest exit 0 and no rollback requirement
- the cell nevertheless correctly failed GO because the initial provider invocation was not valid; the later repair must not be used to retroactively validate the failed initial treatment
- the installed Hermes 0.16.0 runtime defines `HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS` as the supported Codex SSE-idle watchdog control; its default is 12 seconds below approximately 10,000 estimated context tokens and 60 seconds above that range

Frozen operational correction 33:
- set `HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS=60` in the GPT-5.6 benchmark launcher process before importing or invoking Hermes components
- do not change the user's global Hermes configuration; the override is scoped to the launcher and inherited by its Hermes child processes only
- retain the separate 120-second no-byte TTFB watchdog, 1800-second agent timeout, 180-second pytest timeout, and all existing retry limits
- persist the exact SSE-idle threshold in launch metadata
- before a replacement pilot, run one non-benchmark preflight on GPT-5.6 Sol under the 60-second override that requires a bounded tool-using response; the preflight is availability validation only and is not a benchmark cell

Replacement rule:
- the stopped cell remains invalid and must not be reused
- after a successful preflight, start all six cells from entirely fresh workspaces and a new run root
- preserve every other section 17.20 parameter, prohibition, GO condition, and STOP rule
- another invocation or stream-watchdog failure stops the replacement immediately and does not authorize further automatic reruns

#### 17.22 GPT-5.6 Sol model-transition pilot execution record (2026-07-16, post-pilot)

The section 17.21 non-benchmark tool-using preflight succeeded under `HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS=60`. The fresh replacement pilot then completed from launch and origin/main SHA `06ffc5f3296a76eaa83f4572cd82515c1b8f6a20`. Its run root is `/home/fabio/AgentHarness-benchmark-runs/repair-safety-pilot-gpt56-sse60-20260716T103803Z`.

Operational result:
- provider/model was pinned to `openai-codex/gpt-5.6-sol` and the launcher-scoped Codex SSE-idle threshold was pinned to 60 seconds
- all 6 fresh frozen cells completed and passed the cell-level GO audit
- all 6 cells had valid invocation evidence and all required treatment-delivery checks passed
- all required canonical reexecution parity checks passed
- all 6 cells emitted a repair-safety report and cumulative diff
- no safety infrastructure error, treatment-delivery error, rollback error, unclassified invalid, stream-watchdog failure, or forbidden hidden-evaluation artifact was observed
- no rollback was required in these six cells; live rollback recovery was therefore not exercised by this pilot and remains supported by the versioned automated regression suite rather than new live evidence
- no hidden evaluator was invoked, no held-out score was produced or read, and no A-versus-B endpoint or contrast was computed
- the independent audit `pilot-independent-audit.json` records `pilot_go = true`
- the independently recomputed launcher SHA-256 matches the launch metadata value `4a63fa5ae4daf7e1b5f0d547395150a963da4b18e903c06a9c66eda9ffa7ad50`

Interpretation boundary:
- the amended treatment-delivery, canonical-reexecution, and repair-safety channel is operationally validated for GPT-5.6 Sol under this six-cell pilot and launcher-scoped 60-second SSE-idle threshold
- this GO does not estimate efficacy, does not compare the arms, does not alter the official 2026-07-15 result, and does not by itself choose or authorize a renewed efficacy campaign

### 17.23 Substantive amendment: cluster-aware GPT-5.6 campaign sizing and task-expansion gate (2026-07-16)

Timing and data boundary:
- this amendment is recorded before any renewed GPT-5.6 efficacy cell or hidden held-out score is collected
- all execution after amendment 17.22 has been synthetic validation or code/test work; no new real A-vs-B contrast has been produced or inspected
- commit `28e518cce2951119913d5800c8720d126dd832d3` introduced the exact six-case endpoint gate, strict MME numerical boundary, campaign-shape validator, and formal robustness/public-claim classification
- commit `653f7956fc63644b66314a4a2a1445facf78fd9a` withdraws the underpowered 8-task-by-20-replicate wrapper before use and freezes the corrected cluster-aware sizing artifacts

Endpoint and inferential freeze:
- a valid held-out endpoint contains exactly six terminal cases, each with status `passed` or `failed`; the score is passed cases divided by six
- any evaluator failure, non-list result, case-count mismatch, or nonterminal case status makes the cell `harness_invalid` with score zero only in the prespecified invalid-as-zero sensitivity
- the primary estimator remains the equally task-weighted paired task-level mean difference `B - A` with small-cluster t inference
- MME remains `0.10`
- `improvement_supported` requires the primary 95% CI lower bound to be strictly above `0.10`
- `no_meaningful_effect` requires the primary 95% CI upper bound to be strictly below `0.10`
- values numerically within `1e-12` of the MME boundary are treated as equal to the boundary and therefore do not satisfy either strict inequality
- all remaining cases are `inconclusive`

Public-claim gate:
- the primary headline is not rewritten by robustness checks
- `robust_improvement_supported` additionally requires both cluster-bootstrap CIs above zero, every leave-one-task-out point estimate above zero, and the invalid-as-zero sensitivity effect above zero
- if the primary headline is `improvement_supported` but one or more robustness requirements fail, the only allowed classification is `primary_supported_robustness_qualified`; no broad robust-improvement claim is allowed

Corrected sizing model:
- executable source: `benchmarks/grading-env/stage2_cluster_sizing.py`
- frozen outputs: `STAGE2_CLUSTER_SIZING_FREEZE_2026-07-16.json` and `.md`
- simulations per design cell: `50,000`
- seed base: `2026071605`
- observed within-task-condition SD used for planning: `0.224`
- task-specific treatment effects are simulated separately with heterogeneity SD sensitivity values `0.08`, `0.10`, and `0.14`
- this separation is mandatory because increasing replications cannot remove treatment-effect heterogeneity across task clusters

Design decision:
- the 8-task-by-20-replicate design is withdrawn before launch; under the central cluster-aware model its estimated power at true effect `0.18` is materially below `0.80`
- the provisional candidate is `24 tasks x 14 replicates x 2 conditions = 672 cells`
- at effect `0.18`, frozen power is `0.899` for heterogeneity SD `0.08`, `0.815` for `0.10`, and `0.630` for `0.14`
- at effect `0.12`, frozen power is only `0.125`, `0.108`, and `0.084` respectively; therefore this campaign cannot support a claim that it is adequately powered for a `0.12` effect
- the target for planning is explicitly effect `0.18`, not `0.12`

Task-expansion gate:
- the current eight task IDs remain frozen: `csv-member-import`, `incident-escalation-api`, `inventory-adjustment-api`, `leave-request-api`, `refund-approval-api`, `report-export-job`, `support-ticket-api`, and `webhook-ingestion-service`
- sixteen additional tasks must be created and validated before a confirmatory launcher may exist
- every new task must use the same neutral structural specification policy: packaging, import path, runnable entrypoint, file placement, and public input/output schema may be clarified; no hint may disclose held-out behavior, corner cases, expected implementation logic, or evaluator assertions
- each new task must have exactly six held-out terminal cases and must pass evaluator-schema, reference-positive, reference-negative, determinism, packaging, and forbidden-artifact checks
- no new task may be selected, dropped, or rewritten based on an A-vs-B result
- new-task acceptance records must be produced without computing an efficacy contrast
- after all sixteen tasks pass, a separate dated amendment must freeze their IDs, hashes, exact randomized order, launch commit, and launcher hash before any confirmatory cell starts

Operational budget gate:
- nominal campaign budget is `672` cells and `1,344` agent invocations before CLI-level retries
- the hard theoretical ceiling with three CLI attempts for each agent invocation is `4,032` provider calls; this is a ceiling, not an expected budget
- the completed six-cell GPT-5.6 safety pilot took `54.074` wall-clock minutes; direct serial extrapolation is approximately `100.94` hours for 672 cells
- no confirmatory launch is authorized until the user explicitly approves provider quota, concurrency, maximum wall-clock budget, checkpoint frequency, and abort thresholds

Blinding and execution discipline:
- no interim task mean, arm mean, effect, confidence interval, rank, or A-vs-B contrast may be computed or displayed
- progress output before completion is limited to cell counts, execution-status categories, treatment-delivery/safety gate status, retry counts, elapsed time, and quota state
- any treatment-delivery failure, endpoint-contract failure, forbidden artifact, failed rollback, cross-cell contamination, or launcher/hash mismatch triggers STOP before the next cell
- infrastructure invalids follow the symmetric frozen policy; valid task failures remain observed outcomes and are not converted into infrastructure invalids

Authorization state:
- task expansion and non-efficacy validation are authorized by this amendment
- the 672-cell confirmatory campaign is not yet authorized
- no hidden efficacy run may begin from this amendment alone

### 17.24 Task-expansion batch 1 identity and acceptance freeze (2026-07-16)

Scope:
- this batch is development and evaluator validation only; no A/B agent cell, held-out efficacy score, task-level contrast, or campaign launcher is authorized
- batch size is four tasks, balanced as two HTTP APIs and two deterministic CLI/batch utilities

Frozen task IDs and public problem families:
- `appointment-booking-api`: appointment-slot publication, booking, conflict prevention, cancellation, and availability
- `shipment-event-api`: shipment creation, ordered event ingestion, idempotency, current-state projection, and event history
- `jsonl-event-aggregation`: deterministic JSONL ingestion, normalization, duplicate handling, rejection reporting, and aggregate output
- `invoice-payment-reconciliation`: deterministic invoice/payment reconciliation with matched, unmatched, rejected, and summary outputs

Acceptance contract for every task:
- exactly five functional held-out checks plus one stable result-envelope schema case
- visible specifications may pin packaging, module/entrypoint location, CLI flags, route names, public fields, output filenames, and high-level business rules
- visible specifications must not include hidden literal fixtures, boundary examples chosen only for grading, evaluator check IDs, expected hidden outputs, or implementation instructions that reveal how to satisfy the evaluator
- evaluator must reach and pass all five functional checks on an independent reference-positive implementation
- evaluator must run to a coherent real-failure result and fail at least two functional checks on an intentionally deficient reference-negative implementation
- repeated evaluation of the same immutable reference workspace must produce identical functional pass/fail sets and score
- task package and entrypoint must be reachable in a clean copied workspace under the frozen grading environment
- no task workspace or visible task bundle may contain hidden evaluator source, held-out fixture payloads, prior run artifacts, or sibling-task solutions
- each evaluator must preserve the frozen execution-status taxonomy and six-case endpoint contract

Batch GO rule:
- GO requires all four tasks to pass every acceptance item above
- any failed task remains excluded from the 24-task target and cannot be replaced, rewritten, or accepted using A/B performance evidence
- fixes based only on structural gate failures or reference-fixture diagnostics are allowed before batch acceptance and must be documented in the acceptance report
- after GO, a dated post-build amendment must record task hashes and acceptance-report hash; it still does not authorize efficacy collection

### 17.25 Stage 2 task-expansion batch 1 accepted under non-efficacy gates (2026-07-16)

Artifact commit:
- `1c2cff8249d80e416de1025904cc7aea69793ffc`
- pushed to `origin/main` before this post-build amendment

Accepted task identities:
- `appointment-booking-api`
- `shipment-event-api`
- `jsonl-event-aggregation`
- `invoice-payment-reconciliation`

Acceptance evidence:
- machine-readable report: `benchmarks/grading-env/task-expansion-batch1/TASK_EXPANSION_BATCH1_ACCEPTANCE.json`
- report SHA-256: `bdce1dc6705aa77a388e609ff74d104697346c1caf11facd1a9e4c16ae297673`
- human-readable report: `benchmarks/grading-env/task-expansion-batch1/TASK_EXPANSION_BATCH1_ACCEPTANCE.md`
- Markdown report SHA-256: `edbd6fdf5644f1f76558a9f6f3e1eca987ae27293b825676a1fadd150bcb5f07`
- the JSON report freezes 37 artifact hashes, including all four task packs, both evaluator modules, all hidden reference implementations, the mutation-sensitivity matrix, the audit program, and the batch test module
- the task-pack generator reproduced all 16 visible pack files byte-identically

Gate results:
- all four independent reference-positive implementations passed all five functional checks
- all 20 targeted mutants matched their exact preregistered failed-check and passed-check sets
- 12 clean-room evaluations across three hash seeds per task produced identical classifications
- API persistence was tested by creating in a child process that terminated before the evaluator worker performed the read; write-ack/rollback mutants were rejected by that cross-process probe
- malformed or timezone-naive timestamp probes returned controlled 4xx responses and left persisted state unchanged
- all six pairwise comparisons among the four new tasks and all 20 nearest-existing-task comparisons have explicit shared-shell and substantive-difference records
- batch validation result: `4 passed, 32 subtests passed in 356.99s`
- pre-existing repository suite result, excluding only the already-certified batch matrix: `170 passed, 15 skipped in 456.69s`
- final independent blind gate review: GO with no blocking findings

Interpretation and authorization boundary:
- this amendment accepts only construction, non-leakage, determinism, persistence, mutation adequacy, and evaluator reachability for these four task packs
- efficacy cells collected during this batch: `0`
- no A/B contrast was read or used to build, repair, or accept any task
- these four tasks may count toward the 24-task expansion target
- this amendment does not authorize a task-solving pilot, an A/B run, the 672-cell confirmatory campaign, or any efficacy claim
- the next task-expansion batch requires its own pre-build identity freeze and the same non-efficacy acceptance gates before it can count toward the target

### 17.26 Stage 2 task-expansion batch 2 pre-build identity and construct freeze (2026-07-16)

Purpose:
- add the next four task clusters toward the frozen 24-task target
- increase construct diversity without using agent performance, hidden efficacy scores, or any A/B contrast to select or refine tasks
- preserve the exact five-functional-check plus one result-schema contract used by batch 1

Frozen task identities and interfaces:
1. `dependency-impact-planner`: deterministic CLI over a component dependency graph
2. `access-policy-evaluator`: deterministic CLI over a policy document and request JSONL stream
3. `versioned-document-api`: FastAPI plus SQLite/SQLAlchemy document service with optimistic concurrency
4. `safe-archive-extraction`: deterministic ZIP extraction CLI with filesystem-safety constraints

Frozen functional constructs:

`dependency-impact-planner`:
- graph validation for unique identifiers, existing references, and self-loop rejection
- reverse transitive impact closure from an explicit changed-component set
- precedence-respecting parallel execution levels
- deterministic ordering and byte-stable output
- cycle detection with atomic failure and no partial plan artifact

`access-policy-evaluator`:
- documented action/resource wildcard matching
- composition of direct-subject and declared-group rules
- explicit-deny precedence with default deny
- RFC 3339 temporal validity using only request-provided `as_of`
- deterministic auditable decisions plus isolated rejection of malformed request lines

`versioned-document-api`:
- durable creation/read with revision 1 and strong version ETag
- compare-and-swap updates through `If-Match`, with stale writes rejected atomically
- RFC 7396 JSON Merge Patch semantics for object-root documents
- immutable contiguous revision history with no revisions for reads or failed writes
- restoration of a historical revision as a new revision without rewriting prior history

`safe-archive-extraction`:
- correct extraction of regular files/directories with ordered size and SHA-256 manifest
- atomic rejection of absolute, parent-traversal, drive-prefixed, backslash-ambiguous, or escaping paths
- rejection of symlinks and non-regular special entries from ZIP metadata
- preflight collision detection after frozen path normalization, including file/directory conflicts
- atomic `max-entries` and uncompressed `max-bytes` enforcement plus corrupt-archive handling

Pre-build diversity findings:
- the graph planner adds transitive closure, topological layering, and cycle semantics absent from the existing 12 tasks
- the policy evaluator is a stateless rule-composition interpreter, not an approval workflow or mutable CRUD service
- the document API measures optimistic concurrency, structural merge, and immutable version history rather than a domain state machine or webhook deduplication
- the archive extractor measures adversarial binary/filesystem safety rather than retention, import, migration, or report generation
- pairwise overlap among these four tasks must be audited again after implementation; shared CLI/API shells do not count as substantive construct diversity

Batch 2 acceptance gates:
- all batch 1 non-leakage, visible-allowlist, claims-separation, reference-positive, exact mutation-sensitivity, clean-room determinism, reachability, forbidden-artifact, hash-freeze, and independent blind-review gates apply unchanged
- persistence for `versioned-document-api` must be demonstrated across process termination using a write-ack/rollback negative control
- ZIP safety fixtures must remain small and portable; no resource-exhaustion payload may be materialized
- every functional mutant must match an exact preregistered failed-check and passed-check set
- all six pairwise comparisons within batch 2 and each check's nearest existing construct must have explicit substantive distinctions
- GO requires all four tasks to pass every gate; partial acceptance is forbidden

Authorization boundary:
- efficacy cells collected before this freeze: `0`
- no task-solving agent run, A/B pilot, confirmatory cell, or hidden efficacy contrast is authorized by this amendment
- only task-pack construction and non-efficacy validation are authorized
- a dated post-build amendment with exact artifact SHA and report hashes is required before these tasks count toward the 24-task target

### 17.27 Stage 2 task-expansion batch 2 accepted under non-efficacy gates (2026-07-16)

Artifact commit:
- `338e7248745c3a06f1ef6e6cf40c656b340fc72a`
- pushed to `origin/main` before this post-build amendment

Accepted task identities:
- `dependency-impact-planner`
- `access-policy-evaluator`
- `versioned-document-api`
- `safe-archive-extraction`

Acceptance evidence:
- machine-readable report: `benchmarks/grading-env/task-expansion-batch2/TASK_EXPANSION_BATCH2_ACCEPTANCE.json`
- report SHA-256: `6a22b9864e60b111fa4a58f2bdd454bdfb8f02d959c2e3c18a0491e2e576b5de`
- human-readable report: `benchmarks/grading-env/task-expansion-batch2/TASK_EXPANSION_BATCH2_ACCEPTANCE.md`
- Markdown report SHA-256: `4bf1e006aaac590167f5ea9af7b9e20e5d62e6d43a17792cfbe4ebbc5598f8cc`
- the JSON report freezes 37 artifact hashes, including all four visible task packs, evaluator modules, hidden reference implementations, mutation-sensitivity matrix, audit program, and test module
- the task-pack generator reproduced all 16 visible pack files byte-identically

Gate results:
- all four independent reference-positive implementations passed all five functional checks
- all 20 targeted mutants matched their exact preregistered failed-check and passed-check sets
- 12 clean-room evaluations across three hash seeds per task produced identical classifications
- `versioned-document-api` persistence was verified across process termination, including a strong POST ETag, SQL compare-and-swap with one winner under concurrent same-ETag writers, failed-write snapshot preservation, immutable history, and restore preconditions
- `safe-archive-extraction` was verified for path containment, special-entry rejection, normalized collision detection, limits, corruption, exact manifest schema, and complete preservation of pre-existing output state on failure
- diversity evidence contains all 48 comparisons between the four new tasks and the 12 prior tasks, all 20 nearest-existing-task check comparisons, and all 6 pairwise comparisons within batch 2
- batch validation result: `5 passed, 32 subtests passed in 375.55s`
- pre-existing repository suite result, excluding the separately certified batch matrices: `170 passed, 15 skipped in 506.17s`
- final independent blind blocker review: GO with no blocking findings and no files modified by the reviewer

Interpretation and authorization boundary:
- this amendment accepts only construction, non-leakage, construct diversity, determinism, persistence, atomicity, mutation adequacy, and evaluator reachability for these four task packs
- efficacy cells collected during this batch: `0`
- no A/B contrast was read or used to select, build, repair, or accept any task
- these four tasks may count toward the 24-task expansion target; together with the original eight tasks and accepted batch 1, sixteen task identities are now accepted and eight additional tasks remain
- this amendment does not authorize a task-solving pilot, an A/B run, the 672-cell confirmatory campaign, or any efficacy claim
- the next task-expansion batch requires its own pre-build identity freeze and the same non-efficacy acceptance gates before it can count toward the target

### 17.28 Stage 2 task-expansion batch 3 pre-build identity and construct freeze (2026-07-16)

This amendment is registered before any reference implementation, hidden evaluator, mutant implementation, task-solving pilot, A/B cell, or efficacy output for batch 3.

Frozen base:
- `origin/main` and local HEAD at authoring: `6178b855d806687bd09624c43815f2688f82008d`
- accepted task identities before this batch: 16
- efficacy cells collected while selecting or reviewing this batch: 0
- no prior A/B score, contrast, or task-arm result was inspected or used

Frozen machine-readable contract:
- generator: `benchmarks/grading-env/build_task_expansion_batch3_prebuild.py`
- generator SHA-256: `738108592c86892f7c0f6e8318fbe291e86773db2cf787078c1ed5e92800784d`
- JSON freeze: `benchmarks/grading-env/task-expansion-batch3/BATCH3_PREBUILD_FREEZE.json`
- JSON SHA-256: `63f7404b1e62967e42c7f258ef3031b18a1699276e440bcd0bf30431c18b4713`
- human-readable freeze: `benchmarks/grading-env/task-expansion-batch3/BATCH3_PREBUILD_FREEZE.md`
- Markdown SHA-256: `d8f150095fa5ba9804e153dd56ae15f376ab7563d535338a9626cde55592748f`
- the JSON is the normative source for exact public interfaces, functional promises, planned probes, mutant defects, expected failed/passed sets, and overlap records

Frozen batch 3 identities and functional check IDs:

1. `signed-artifact-verifier`
   - deterministic CLI for canonical HMAC-signed manifests, key/manifest validity windows, exact regular-file inventory, and byte integrity
   - `signed_manifest_authenticity`
   - `signed_inventory_completeness`
   - `signed_content_integrity`
   - `signed_trust_time_boundaries`
   - `signed_manifest_atomic_report`

2. `pii-redaction-pipeline`
   - deterministic CLI for recursive selector resolution, privacy actions, keyed pseudonymization, non-selected structure preservation, and one atomic output bundle
   - `pii_selector_resolution`
   - `pii_redaction_actions`
   - `pii_structure_preservation`
   - `pii_rule_validation_precedence`
   - `pii_atomic_audit`

3. `lease-coordination-api`
   - FastAPI plus SQLite service for expiring exclusive ownership, durable monotonic fencing tokens, renew/release, and simultaneous contention
   - `lease_acquire_fencing`
   - `lease_concurrent_contention`
   - `lease_renew_boundaries`
   - `lease_release_reacquire_stale_holder`
   - `lease_state_and_failure_atomicity`

4. `double-entry-ledger-api`
   - FastAPI plus SQLite service for immutable exact-decimal balanced postings, canonical idempotency, derived balances/journals, and compensating reversal
   - `ledger_account_identity`
   - `ledger_balanced_atomic_posting`
   - `ledger_idempotency_conflict`
   - `ledger_balances_and_journal`
   - `ledger_compensating_reversal`

Frozen structural decisions:
- the two CLI tasks commit exactly one output artifact; `pii-redaction-pipeline` uses one JSON bundle containing both `redacted` and `audit`
- all public entrypoints, routes, exact field sets, selector/path rules, canonicalization rules, temporal boundaries, decimal grammar, replay semantics, success statuses, and controlled conflict statuses are frozen in the normative JSON before implementation
- all visible specifications must remain neutral to hidden fixture values and may expose only the frozen behavioral contract
- hidden evaluator implementation details, check IDs, probes, mutant switches, references, and this ledger are forbidden from visible task bundles

Frozen sensitivity contract:
- exactly 5 functional checks per task and one terminal task-shape check
- exactly 1 deterministic mutant per functional check, 20 mutants total
- each mutant has a preregistered singleton `expected_mutant_failed_checks` set
- each mutant has the complementary four-check `expected_mutant_passed_checks` set
- acceptance requires the exact failure set, not merely detection by at least one check
- full pre/post state or output snapshots must be equal after every controlled failure
- persistence claims require cross-process observation
- concurrency claims require simultaneous contenders, one durable winner, no partial rows, and no raw SQLite busy/lock response

Frozen diversity evidence:
- 64 unique pair-specific comparisons between the 4 new identities and all 16 accepted identities
- every comparison records the actual shared surface, the different functional unit, and why success on the prior task does not imply success on the new task
- 20 unique nearest-existing comparisons, one for each functional check
- 6 unique pairwise comparisons within batch 3
- all records are contained in the normative JSON and are frozen before build

Preventive review gate:
- first independent review: `NO-GO`; it identified generic overlap text, incomplete public boundaries, two-file PII atomicity, and insufficiently isolated planned mutants
- second independent review: `NO-GO`; it identified the PII audit schema contradiction, an overbroad account mutant, ambiguous decimal canonicalization, and remaining interface ambiguity
- third independent read-only review: `GO` with zero substantive blockers
- review inspected the 16 accepted visible specifications but no run directory, efficacy cell, A/B output, or contrast

Build authorization after publication of this amendment:
- batch 3 reference implementations, hidden evaluators, deterministic mutants, visible neutral specs, generator and structural tests may be built
- no task-solving pilot, efficacy cell, A/B comparison, campaign sizing update, or confirmatory launch is authorized
- post-build acceptance requires generator byte identity, 4/4 reference positives, exact 20/20 mutation sensitivity, clean-room agreement, full forbidden-artifact gate, complete 64/20/6 diversity evidence, legacy compatibility, independent blind GO, artifact hashes, and a dated post-build amendment

### 17.29 Batch 3 clerical check-ID alignment to the normative freeze (2026-07-16)

This amendment records a clerical correction before hidden evaluator implementation, mutation execution, task-solving pilots, or efficacy cells.

Authority and scope:
- §17.28 already declares `benchmarks/grading-env/task-expansion-batch3/BATCH3_PREBUILD_FREEZE.json` the normative source
- its SHA-256 remains `63f7404b1e62967e42c7f258ef3031b18a1699276e440bcd0bf30431c18b4713`
- task identities, public interfaces, functional contracts, planned probes, mutant defects, failed/passed sets, and diversity records are unchanged
- only seven human-readable labels listed in §17.28 are aligned to the already-frozen JSON keys

Normative labels:
- `signed_inventory_completeness` in the §17.28 summary means `signed_manifest_inventory`
- `signed_content_integrity` means `signed_manifest_content_integrity`
- `signed_trust_time_boundaries` means `signed_manifest_trust_window`
- `pii_rule_validation_precedence` means `pii_rule_precedence`
- `lease_renew_boundaries` means `lease_renewal`
- `lease_release_reacquire_stale_holder` means `lease_release_reacquire`
- `ledger_balanced_atomic_posting` means `ledger_balanced_posting`

Timing and boundary:
- visible task-pack and reference scaffolding had begun when the mismatch was detected by an exact matrix-versus-freeze assertion
- no hidden evaluator had been implemented and no mutant sensitivity run had started
- efficacy cells remain 0 and no A/B output or contrast was read
- all subsequent evaluator, mutant, report, and amendment records must use the normative JSON labels exactly

### 17.30 Stage 2 task-expansion batch 3 post-build acceptance and external review record (2026-07-17)

This amendment is registered after completing the batch 3 structural build and non-efficacy acceptance gates. It does not authorize a task-solving pilot, an A/B run, a confirmatory launch, campaign-shape selection, or any efficacy claim.

Immutable artifact under review:
- artifact commit: `a6986df598c39fbaeb9e8b68e49cfa414629cd62`
- local HEAD and `origin/main` matched that commit before the external review
- the working tree was clean during the external review
- the normative pre-build JSON freeze remained byte-identical with SHA-256 `63f7404b1e62967e42c7f258ef3031b18a1699276e440bcd0bf30431c18b4713`
- the frozen mutation-sensitivity contract was not changed to accommodate implementation outcomes

Canonical local acceptance evidence:
- report: `benchmarks/grading-env/task-expansion-batch3/BATCH3_ACCEPTANCE_REPORT.json`
- report SHA-256: `de65a2550017990a9f2d634570793e0ed7648a09566edbf9e4676a4cb55520e0`
- report mode: `full`
- overall decision: `GO`
- static, packaging, dynamic and legacy-compatibility gates: all `true`
- reference positives: 4/4 task references, each with five functional checks plus the terminal envelope check passing
- mutation sensitivity: exact 20/20 singleton failure sets, with the complementary four checks passing for every mutant
- clean-room agreement: three independent copies per task, all agreeing
- diversity evidence: complete 64 prior-task comparisons, 20 nearest-check comparisons and 6 within-batch pairwise comparisons
- hidden reference hygiene: no tracked runtime or packaging residue
- efficacy cells collected or inspected: 0

Review-driven hardening before final acceptance:
- the PII action oracle was expanded so `redact`, `remove` and HMAC pseudonymization directly exercise strings, numbers, booleans, nulls, objects and arrays
- lease and ledger controlled-failure checks were expanded from selected public-resource comparisons to stable logical snapshots of every user SQLite table, its columns and every row, while retaining public-state and restart checks
- the affected reference positives passed 3/3 and the affected mutants retained exact 15/15 singleton isolation before the final full audit
- these fixes changed evaluator coverage only; task identities, public interfaces, frozen check IDs, planned mutant defects and expected failure/pass sets remained unchanged

External Claude Code review:
- review artifact: `benchmarks/grading-env/task-expansion-batch3/BATCH3_CLAUDE_REVIEW.json`
- review artifact SHA-256: `93d37bc58f8fc86d9d943cc446f7ba59743809194d2ebb561756f6ff74594695`
- reviewer: Claude Code `2.1.199`, model `claude-sonnet-5`
- mode: focused read-only review of immutable commit `a6986df598c39fbaeb9e8b68e49cfa414629cd62`
- verdict: `ok`
- blockers: 0
- the reviewer independently confirmed that both previous blockers were substantively closed, the canonical report hash matched, the freeze and sensitivity matrix were unchanged, and no files were modified during review
- limitation: Claude did not rerun the auditor, generators, tests or concurrent reference behavior; those execution claims remain grounded in the locally observed canonical full audit rather than in the external static review

Acceptance boundary:
- batch 3 adds four structurally accepted task identities, increasing the accepted identity pool from 16 to 20 for future preregistered design work
- no campaign shape is selected by this amendment
- no task-solving pilot, A/B contrast, efficacy result, sizing update or confirmatory run is authorized
- any later measurement or campaign decision still requires its own explicit preregistered authorization and must preserve blindness to the treatment contrast until the corresponding gate permits interpretation

### 17.31 Substantive amendment: GPT-5.6 AgentHarness efficacy campaign authorization (2026-07-17, before any campaign cell)

Authorization and timing:
- the user explicitly authorized proceeding to an efficacy result on 2026-07-17 after restating that the project goal is to demonstrate with credible evidence that AgentHarness is useful and works
- at the time of this amendment, the 20-task structural pool had passed its frozen non-efficacy acceptance gates, but no new Stage 2 efficacy cell under this design had been launched and no contrast from this design existed
- this amendment is substantive: it selects and authorizes a campaign shape, changes the GPT-5.6 treatment implementation to a cleaner causal contrast, freezes a new quota-aware resumable launcher, and permits the contrast to be read only after complete paired data sealing
- this amendment supersedes the non-authorization boundary in §17.30 and the provisional 24-task-by-14-replicate candidate in §17.23; it does not alter or pool any previous efficacy run

Normative executable freeze:
- manifest: `benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-17.json`
- manifest payload SHA-256: `cd2e4fcb5c10bbe280dd2b0b98620eeb750361613eee59e26c8ff99793797d8a`
- the manifest freezes 75 runner, finalizer, analysis, task-specification, claims-contract, held-out-suite and hidden-evaluator file hashes
- campaign runner: `benchmarks/grading-env/run_stage2_efficacy_campaign.py`
- finalizer: `benchmarks/grading-env/finalize_stage2_efficacy.py`
- any frozen-file hash mismatch, dirty repository, or mismatch between local HEAD and `origin/main` blocks launch or resume

Campaign shape and randomization:
- all 20 structurally accepted task identities are included; no task is selected or excluded using an A-vs-B outcome
- conditions: `A-baseline` and `B-agentharness`
- three fresh replicates per task and condition
- total: 60 task-replicate paired blocks, 120 cells, and 240 nominal agent invocations before infrastructure reruns
- randomization seed: `20260717`
- block order and within-block condition order are frozen byte-for-byte in the normative manifest
- blocks are committed atomically only after both conditions complete; no partial block enters the analysis dataset

Causal treatment definition:
- the initial prompt is byte-identical across conditions and contains no condition label or arm-specific implementation guidance
- both conditions receive the same task specification, claims-contract path, workspace rules, provider/model budget, canonical-pytest authority, cumulative-repair policy and deterministic repair-safety gate
- condition A receives a framework-neutral repair prompt based on the task specification and canonical pytest result
- condition B receives the AgentHarness intervention: a persisted pre-repair `verify-run` report with structured feedback, and a repair prompt that explicitly directs the agent to that report
- a repair prompt being written is insufficient: the repair invocation must exit zero and produce captured invocation evidence before the cell may be scored
- the repair prompt, and for B the structured feedback report, are SHA-256 bound before invocation, made read-only, rehashed after invocation, and the cell is invalid unless each pre/post hash is identical
- every valid B cell must record `treatment_delivered = true` and `feedback_delivered = true`; every valid A cell must record `treatment_delivered = true` and `feedback_delivered = false`
- `feedback_delivered` is derived only from the persisted pre-repair treatment artifact and successful repair invocation; the final verify-run result cannot be used as a fallback proxy

Provider, runtime and quota freeze:
- provider/model: `openai-codex/gpt-5.6-sol`
- maximum turns: 40 per agent invocation
- Hermes Codex SSE-idle watchdog: launcher-scoped 60 seconds, with no global configuration change
- toolsets: `terminal,file`; provider fallback and credential rotation are forbidden
- purchased-credit use and authentication reset are forbidden
- quota telemetry is checked before every physical agent invocation and records only safe usage-window fields
- execution pauses fail-closed if quota telemetry is unavailable, weekly usage reaches 85%, session usage reaches 80%, or purchased-credit risk is detected
- pausing for quota is operational only and cannot reveal or alter efficacy outcomes; resume requires the same manifest and repository commit

Infrastructure retry and crash policy:
- a quota or provider-unavailable attempt is preserved in quarantine and does not become an efficacy row
- no cell may exceed three frozen provider attempts without manual adjudication and a new dated amendment
- every `harness_invalid` cell receives at most one symmetric fresh rerun; a second harness-invalid result remains an observed infrastructure-invalid row under the frozen invalid policy
- interrupted cells with an atomic result commit are recovered without rerun; genuinely incomplete cells are quarantined before a fresh attempt
- no workspace, score or repair artifact is reused across fresh attempts

Primary estimand and decision rule:
- endpoint: exact six-case terminal held-out score, passed cases divided by six
- estimator: within each task and condition average valid replicates, then take the equal-weight mean of the 20 paired task differences `B - A`
- primary interval: two-sided 95% Student-t interval with 19 degrees of freedom
- MME remains `0.10`
- `improvement_supported` only if the primary CI lower bound is strictly greater than `0.10`
- `no_meaningful_effect` only if the primary CI upper bound is strictly less than `0.10`
- every other result is `inconclusive`
- infrastructure invalids are excluded from the primary analysis and counted as zero in the frozen sensitivity; every task-condition requires at least one valid replicate

Robustness and secondary family:
- a broad robust-improvement claim additionally requires both frozen cluster-bootstrap intervals above zero, every leave-one-task-out point estimate above zero, and the invalid-as-zero sensitivity estimate above zero
- the two confirmatory secondary endpoints are complete six-of-six success and total agent wall-clock seconds, analyzed as equal-weight paired task differences with Holm familywise alpha 0.05
- favorable directions are positive for complete success and negative for wall-clock cost
- secondary results cannot rescue a failed or inconclusive primary result
- treatment delivery, solution-hash change, invalid rates, rollback counts and invocation counts are descriptive mechanism evidence only

Power and interpretation boundary:
- planning assumptions are within-task SD `0.224` and treatment-effect heterogeneity SD `0.10`
- frozen simulated power is `0.061` for effect `0.12`, `0.367` for effect `0.18`, and `0.863` for effect `0.25`
- this is deliberately the smallest campaign with at least 0.80 frozen power for a strong `0.25` effect on the accepted 20-task pool; it is not adequately powered for `0.12` or `0.18`
- therefore an `inconclusive` result must not be represented as evidence that AgentHarness has no useful effect
- a supported result generalizes only to the frozen 20-task suite, GPT-5.6 Sol, the frozen tool/budget configuration and the tested AgentHarness treatment
- the authorized product claim, if and only if the primary and robustness gates pass, is that under the frozen configuration AgentHarness materially improves held-out task quality relative to the same model receiving a framework-neutral repair pass

Interim blindness and analysis authorization:
- before all 60 blocks are committed, no task score, arm score, task mean, effect, confidence interval, rank, endpoint summary or A-vs-B contrast may be computed or displayed
- progress is limited to completed block/cell counts, pause status, retry counts, elapsed time and safe quota state
- only after the 120-row dataset passes the exact shape and treatment-delivery gates is it sealed by SHA-256 and analysis authorized
- the finalizer has no CLI options for changing MME, seeds, resample counts, invalid handling or decision thresholds

Launch authorization:
- publication of this amendment and the matching freeze to clean synchronized `origin/main`, followed by a successful frozen preflight, authorizes this exact 120-cell campaign
- no different task pool, model, condition, replicate count, threshold, retry rule or endpoint is authorized without a new dated pre-data amendment

### 17.32 Pre-data quota-telemetry compatibility amendment (2026-07-17)

Trigger and contamination boundary:
- the first launch attempt under commit `b64e016421ba8656f3addd16c53b44b3acfdfd6c` stopped fail-closed at the first quota gate with exit code `11` because the authoritative `usage_api` snapshot exposed one `Session` window and no separately labelled `Weekly` window
- the stopped run recorded `physical_cell_attempts = {}`, zero agent-invocation metadata files, zero cell result commits and zero efficacy rows; therefore no treatment was delivered and no outcome or A-vs-B contrast existed or was read
- the original stopped run root is retained as audit evidence and must not be resumed under the amended manifest

Amended quota rule:
- the manifest payload SHA-256 is `c2dd73ecb1e262f391e6629c70843c6ccbc6f9293fce5eab6da2f164d3f2cc0f`
- if authoritative Codex telemetry exposes both `Session` and `Weekly`, the frozen 80% and 85% pause thresholds remain unchanged
- if it exposes exactly one authoritative window labelled `Session` or `Weekly`, launch and admission are permitted only while that window is below the more conservative frozen threshold of 80%
- zero recognized windows, unavailable telemetry, missing percentage or reset time, purchased-credit risk, or a single window at or above 80% remains fail-closed
- this amendment changes no task, condition, block order, replicate, endpoint, treatment, retry rule, analysis parameter or decision threshold
- a second launch requires a new run root, clean synchronized `origin/main`, matching amended manifest hashes and a successful preflight

### 17.33 Post-start, pre-reading held-out envelope repair (2026-07-17)

Observed failure boundary:
- campaign root: `/home/fabio/agentharness-stage2-efficacy-20260717-6e42176`;
- the first physical attempt, cell `b001-s1` (`pii-redaction-pipeline`, `A-baseline`), completed its two planned agent invocations;
- the hidden evaluator then wrote its private result, but the controller failed before endpoint construction and before `cell-result.commit.json`, because batch-3 task packs intentionally do not contain a visible `HELDOUT_EVALUATION_SUITE.template.json`;
- no block or cell was committed, no score or hidden-result content was read, no A/B contrast was calculated or inspected, and the failure output disclosed only the missing path;
- the private uncommitted attempt is therefore inadmissible for efficacy analysis and must be quarantined unread on resume.

Substantive amendment:
- add four hidden suite envelopes under `benchmarks/grading-env/stage2-heldout-suites/`, outside all task packs and outside agent workspaces;
- each envelope contains exactly the five check IDs already frozen in its corresponding batch-3 hidden evaluator plus the same sixth result-schema check used by the sixteen legacy tasks;
- add a deterministic resolver that prefers each legacy task-local held-out envelope and otherwise selects the frozen grading-environment envelope by exact task ID;
- freeze all four hidden-envelope hashes in the campaign manifest;
- do not modify any task `SPEC.md`, claims contract, task source, hidden evaluator behavior, scoring formula, randomization, treatment, task list, replication count, or analysis rule.

Recovery and rerun accounting:
- when an interrupted cell has two completed invocation metadata files but no committed cell result, recovery must quarantine the entire physical attempt as `harness_invalid_recovery`;
- that recovery consumes the cell's sole preregistered `harness_invalid_fresh_reruns` allowance;
- the next physical attempt preserves the original block, task, replicate, condition and slot assignment;
- if the fresh attempt is again harness-invalid, no second automatic rerun is allowed and adjudication is required.

Validation before resume:
- batch-3 canonical full audit: GO, with `static_ok=true`, `dynamic_ok=true`, `packaging_ok=true`, and `legacy_ok=true` under the repository runtime containing the declared build backend;
- unit tests bind each hidden envelope's check IDs to the corresponding frozen evaluator constants and verify legacy/hidden path resolution;
- a recovery test verifies quarantine plus consumption of the one harness-invalid rerun;
- the frozen manifest payload after this amendment is `f66b363c8ab2ec22e61eab128b8961468d30daf91830278e99fc6656f8cf94b9` and contains 75 frozen file hashes.

This amendment is recorded before resume and before any private outcome content is opened.

### 17.34 Corrective runtime amendment after failed resume, before hidden evaluation (2026-07-18)

Correction of the record:
- the statement in §17.33 that the hidden evaluator had already written a private functional result was an inference from the apparent call order, not a verified fact;
- inspection of the operational traceback and file boundary established that both failed executions stopped before `run_hidden_benchmark` and before any held-out endpoint evaluation;
- no hidden functional outcome was generated for either failed execution, and therefore no such outcome was read;
- these statements supersede the contrary hidden-result bullets in §17.33 while preserving its envelope-repair rationale.

Verified root cause:
- Hermes completed both physical invocations in the fresh attempt with exit code 0 and wrote a valid `session_id` line to stderr;
- `HermesCliInvoker` searched stdout only, recorded `session_id = null`, and therefore misclassified completed invocations as lacking evidence;
- the invalid-cell artifact writer then attempted the old task-local held-out suite path and raised `FileNotFoundError`, masking the session-parser defect;
- the workspace and persisted initial snapshot contain a non-empty candidate solution; the repair invocation made no workspace change.

Neutral runtime correction:
- `HermesCliInvoker` now extracts the session ID from stdout or stderr, without changing prompts, task logic, evaluator logic, randomization, treatment, scoring, or provider settings;
- both ordinary scoring and invalid-cell artifact writing resolve the same frozen legacy-or-hidden held-out envelope;
- a narrowly guarded replay path accepts only the current `A-baseline` cell with exactly two persisted, exit-0 invocations, session evidence recoverable from their streams, and identical pre-repair/current solution hashes;
- replay restores the persisted invocation evidence and treatment prompt, performs no agent invocation, and runs only the normal post-invocation pytest, verify, hidden evaluator, endpoint evaluation, provenance, and cell commit path;
- any condition mismatch, missing evidence, nonzero exit, missing treatment prompt, or repair hash change fails closed;
- direct non-mocked guard tests cover wrong condition, wrong attempt count, nonzero exit, missing session evidence, empty prompt, and pre/post hash mismatch;
- any replay guard rejection is surfaced as structured `AdjudicationRequired` before cell commit.

Rerun and analysis treatment:
- the already consumed `harness_reruns = 1` remains part of the audit trail;
- no third agent invocation is permitted for `b001-s1`;
- the second physical attempt is the only candidate execution eligible for scoring, via evidence replay and normal hidden evaluation;
- the first physical attempt remains quarantined and excluded;
- no A-versus-B contrast or hidden score was inspected while diagnosing or implementing this correction;
- the campaign block order, paired assignments, frozen estimand, invalidity gates, MME, quota policy, and analysis remain unchanged.

Corrected executable freeze:
- manifest: `benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-17.json`;
- manifest payload SHA-256: `cd2e4fcb5c10bbe280dd2b0b98620eeb750361613eee59e26c8ff99793797d8a`;
- frozen files: 75;
- this amendment is recorded before replay, hidden evaluation, or commit of the second physical attempt.

---

## Freeze

Appendice operativa congelata il 2 luglio 2026 da Fabio Scialanga. Da questa data i parametri, i seed, i budget e le regole inferenziali sopra sono immutabili. Il completato Stage 1 diagnostico resta attribuito al commit `e8e8504` come registrato negli emendamenti 17.7 e 17.8; il precedente commit `04db03d` resta riferito solo ai run scartati e non letti antecedenti alla correzione del path workspace. Dopo l'emendamento 17.9, qualunque nuovo Stage 1 analizzabile dovrà usare un successivo commit di hardening che includa sia la classificazione `provider_unavailable:` come invalid infrastrutturale sia la discovery FastAPI basata su oggetti importabili. Il testo dell'appendice operativa è stato introdotto nel repository al commit `10ea1a1`. Nessuna cella del benchmark era stata eseguita prima di questa data.
