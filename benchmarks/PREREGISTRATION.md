# Benchmark pre-registration

Status: freeze-ready, pending final sign-off before any benchmark run.
Stato: freeze-ready, in attesa di rilettura finale e firma prima di qualunque run di benchmark.

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

Final sign-off is needed before any benchmark execution.

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
5. da definire prima del freeze
6. da definire prima del freeze
7. da definire prima del freeze
8. da definire prima del freeze

Requisiti per ogni task:
- spec scritta
- scope consentito e scope vietato
- evaluation suite indipendente e tenuta da parte
- claims contract per `verify-run`
- difficoltà compatibile con lo stesso ordine di budget

Quality gate prima dell'avvio:
- tutti e 8 i task devono soddisfare i requisiti sopra allo stesso livello di qualità
- un task aggiunto in modo raffazzonato è considerato peggiore di una suite più piccola ma solida
- se task 7 o task 8 non raggiungono lo standard, il benchmark non parte finché la pre-registrazione non viene emendata formalmente

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

### 8. Metriche
#### 8.1 Endpoint primario
Endpoint primario: task evaluation score, continuo tra 0 e 1, calcolato per run dalla task evaluation suite indipendente e tenuta da parte.

La task evaluation suite:
- è indipendente da `verify-run`
- non viene mai mostrata a nessuna delle due condizioni durante il run
- verifica correttezza task-specific, regole di business, schema esatto e negative path

Lo score è la proporzione di controlli di accettazione indipendenti superati.

Motivazione:
- è l'unico esito che B non ottimizza direttamente, quindi non è circolare
- uno score continuo porta informazione graduata e riduce effetti di ceiling e floor rispetto a un solo binario

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
- per il secondario binario task evaluation pass usare un modello lineare generalizzato a effetti misti, logistico
- riportare l'effetto aggiustato B meno A con intervallo di confidenza al 95 percento

Analisi di robustezza:
- cluster bootstrap che ricampiona i task con le loro repliche
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
- niente esclusioni post hoc, salvo hard invalidation dell'harness prima della partenza dell'agente, con motivo loggato

Limite onesto da dichiarare fin d'ora:
- con 6 task l'inferenza a livello di cluster resta delicata
- con 8 task è migliore, ma ancora modesta
- il benchmark può produrre evidenza utile, non una legge universale

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
   - per ogni nuovo task definire la sua evaluation suite indipendente prima di qualunque run
   - tutti gli 8 task devono superare il quality gate dichiarato nella sezione 5

6. Residuo soggettivo:
   - se incluso nella fase uno, resta secondario ed esplorativo

### 16. Freeze rule
Nessun benchmark run parte finché questo documento non riceve sign-off finale.
Dopo il sign-off finale, si congelano:
- trattamento
- task list
- N
- metriche
- MME
- regola di decisione

Se gli 8 task non raggiungono il quality gate prima del primo run, il benchmark resta bloccato e richiede un emendamento formale della pre-registrazione.

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
5. to be defined before freeze
6. to be defined before freeze
7. to be defined before freeze
8. to be defined before freeze

Each task must define:
- written spec
- allowed and forbidden scope
- independent held-out evaluation suite
- `verify-run` claims contract
- comparable budget class

Quality gate before launch:
- all 8 tasks must satisfy the requirements above at the same quality level
- a rushed eighth task is considered worse than a smaller but solid suite
- if task 7 or task 8 fail that bar, benchmark execution is blocked until the pre-registration is formally amended

### 6. Fixed sample size
Replicates per task:
- 6 paired A/B replicates per task

Frozen plan:
- 8 tasks x 6 replicates = 48 paired comparisons, 96 total runs

Hard rule:
- neither task count nor replicate count changes after the first benchmark run starts

### 7. Reproducibility controls
Log for every run:
- exact model and provider
- runtime and version when available
- temperature and stochastic controls
- seed if available, otherwise paired replicate index
- tool and network policy
- wall-clock budget
- repair-pass limit
- workspace template
- task version hash
- AgentHarness commit SHA
- benchmark script version hash

### 8. Metrics
#### 8.1 Primary endpoint
Primary endpoint: task evaluation score, continuous from 0 to 1, computed per run by the independent held-out task evaluation suite.

The task evaluation suite:
- is independent of `verify-run`
- is never shown to either condition during the run
- checks task-specific correctness, business rules, exact schema, and negative paths

The score is the proportion of independent acceptance checks passed.

Rationale:
- this is the only outcome B does not directly optimize against, so it is not circular
- a continuous score carries graded information and reduces ceiling and floor effects relative to a single binary

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
- for the binary secondary task evaluation pass, use a logistic generalized linear mixed model
- report the adjusted B minus A effect with a 95 percent confidence interval

Robustness analysis:
- cluster bootstrap that resamples tasks with their replicates
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
- with 6 tasks, cluster-level inference remains delicate
- with 8 tasks it is better, but still modest
- the benchmark can produce useful evidence, not a universal law

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
   - every new task must define its independent evaluation suite before any run
   - all 8 tasks must pass the quality gate declared in section 5

6. Residual subjective metrics:
   - if included in phase one, they remain exploratory secondary outputs

### 16. Freeze rule
No benchmark run starts until this document receives final sign-off.
After final sign-off, the following are frozen:
- treatment
- task list
- sample size
- metrics
- MME
- decision rule

If the 8-task quality gate is not met before the first run, benchmark execution stays blocked and requires a formal pre-registration amendment.
