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

---

## Freeze

Appendice operativa congelata il 2 luglio 2026 da Fabio Scialanga. Da questa data i parametri, i seed, i budget e le regole inferenziali sopra sono immutabili. Il completato Stage 1 diagnostico resta attribuito al commit `e8e8504` come registrato negli emendamenti 17.7 e 17.8; il precedente commit `04db03d` resta riferito solo ai run scartati e non letti antecedenti alla correzione del path workspace. Dopo l'emendamento 17.9, qualunque nuovo Stage 1 analizzabile dovrà usare un successivo commit di hardening che includa sia la classificazione `provider_unavailable:` come invalid infrastrutturale sia la discovery FastAPI basata su oggetti importabili. Il testo dell'appendice operativa è stato introdotto nel repository al commit `10ea1a1`. Nessuna cella del benchmark era stata eseguita prima di questa data.
