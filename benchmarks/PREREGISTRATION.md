# Benchmark pre-registration draft, bozza di pre-registrazione

Status: draft for approval before any benchmark run.
Stato: bozza in attesa di approvazione prima di qualunque run di benchmark.

## English

### 1. Purpose
This document fixes the benchmark design before running any comparison between a no-framework condition and an AgentHarness condition.

The goal is to estimate whether AgentHarness improves coding-agent execution quality in a way that is reproducible, reviewable, and statistically defensible.

This pre-registration explicitly allows a null result. If the data do not show a defensible improvement, the report must say so.

### 2. Scope of the claim
The benchmark can support only a limited claim:
- a small benchmark suite may show a signal, or no signal, for the tested tasks, model, tool access, and runtime settings
- it cannot prove a universal law about all coding agents or all software tasks

### 3. Treatment choice
Proposed primary treatment: B-loop-closed.

Definition:
- Condition A, baseline: the agent receives only the task specification, execution environment description, allowed tools, time budget, and a fixed output contract that requires a run artifact and a claims document
- Condition B, AgentHarness: the agent receives the same task specification plus the AgentHarness framework context for that task, and must produce a run artifact plus a claims document that `agentharness verify-run` accepts. Unsupported or inconclusive blocking claims trigger one bounded repair pass inside the same run budget

Why this treatment is preferred:
- it tests the only framework capability that is genuinely distinctive, namely evidence-backed verification instead of narration alone
- a context-only treatment would mostly test whether more instructions help, which is a weaker and less interesting claim
- the closed loop makes the framework earn value through outcomes that survive verification, not through nicer looking structure

Bound on the repair loop:
- maximum 1 automated repair pass after the first `verify-run` result
- no human rescue beyond the pre-registered intervention policy
- the total wall-clock budget is identical across conditions

### 4. Explicit confounder statement
The main confounder is real and must be stated plainly.

Condition B adds two things at once:
1. more structured context, such as PROJECT.md, policies, workflows, checklists, generated metadata
2. a verification loop that can reject unsupported claims and trigger bounded correction

Therefore the primary A versus B comparison estimates the effect of AgentHarness as an operational package, not the isolated causal effect of framework context alone.

This benchmark must not claim:
- that every gain comes from verification only
- that every gain comes from context only
- that the framework effect is disentangled from the extra-context effect

Mitigation:
- both conditions use the same task spec, model, tools, time budget, intervention policy, and final output contract
- both conditions must emit raw artifacts, run metadata, and claims artifacts in the same schema
- the report will label the result as a package-effect estimate

Optional future extension, not part of this pre-registration unless approved before any run:
- add a third condition, B-context, or a matched-claims baseline, to separate context effects from closed-loop verification effects

### 5. Benchmark suite size
Proposed suite size: 4 independent tasks.

Rationale:
- one task is not enough for even limited generalization
- four tasks are still small enough to be operationally feasible, while covering more than one failure mode

Proposed task families:
1. support-ticket API, existing benchmark task
2. inventory-adjustment API with transactional business rules
3. webhook ingestion service with schema validation and idempotency constraints
4. export/report job with deterministic file output and negative-path validation

Task design requirements:
- each task must have a written spec
- each task must define allowed scope and forbidden scope
- each task must define an objective evaluation suite and a verify-run claims contract
- each task must be solvable in the same broad budget class

### 6. Number of runs
Proposed default: 6 paired runs per task, one pair per seed or replicate index.

This gives:
- 4 tasks
- 6 paired A/B replicates per task
- 24 paired comparisons total
- 48 total benchmark runs

Why this is the default draft:
- it is materially better than a single run
- it provides enough pairs for a non-parametric paired test to be meaningful, while staying within plausible cost
- it still requires honest uncertainty reporting, because 24 pairs is informative but not large

Open cost-sensitive alternative for approval before execution:
- stronger plan: 8 paired runs per task, 32 pairs total, 64 runs total
- cheaper plan: 4 paired runs per task, 16 pairs total, only if runtime budget is genuinely constrained, with the limitation stated prominently

No change to N is allowed after the first benchmark run starts.

### 7. Reproducibility controls
These settings must be fixed and logged for every run:
- model provider and exact model name
- agent runtime, for example Claude Code, Cursor, Codex CLI, with exact version when available
- temperature and other stochasticity controls when exposed
- seed or replicate index, when the runtime exposes a real seed. If not available, use paired replicate indices and keep launch procedure identical
- tool access and network policy
- wall-clock budget
- maximum repair-pass count
- workspace template and starting files
- benchmark task version hash
- AgentHarness commit SHA
- benchmark script version hash

### 8. Objective metrics, primary and secondary
The benchmark will minimize subjective scoring. Most metrics must be objective and regenerated from raw artifacts.

#### 8.1 Primary endpoint
Primary endpoint: verified task success, binary per run.

A run counts as primary success only if all of the following are true:
- the agent produced a run artifact and a claims document
- `agentharness verify-run` returns `ok = true`
- the task evaluation suite returns `ok = true`
- no allowed-scope or forbidden-scope claim is unsupported
- the run finished within the fixed time budget

This endpoint answers a simple question: did the run produce an evidence-backed, in-scope, task-correct outcome.

#### 8.2 Secondary objective metrics
Secondary objective metrics, computed per run:
- verify-run overall pass, binary
- evaluation-suite overall pass, binary
- proportion of supported claims in `verify-run`
- count of unsupported claims
- count of inconclusive claims
- count of invalid claims
- business-rule claim pass count
- scope-adherence claim pass count
- reexecuted test command pass, binary when applicable
- number of changed files outside allowed scope, deterministic count
- elapsed wall-clock time
- number of repair passes consumed
- number of human interventions, expected to stay at the pre-registered maximum
- run artifact completeness, binary, meaning all required raw files are present

Objective metric sources:
- `agentharness verify-run` report JSON
- task evaluation report JSON
- deterministic filesystem checks on required raw artifacts
- benchmark metadata file

### 9. Residual subjective metrics
Subjective review is residual only.

Planned use:
- only for reviewability and clarity properties that are not yet defensible through deterministic checks
- not as the primary endpoint

Protocol:
- 2 blinded raters
- artifacts anonymized and stripped of condition labels and obvious framework markers when possible
- each rater scores only these items on a 1 to 5 scale:
  - code reviewability
  - README operational clarity
- the reported value is the mean of the two raters
- inter-rater agreement must be reported descriptively

If blinded anonymization is not credible for a given artifact set, subjective results must be labeled exploratory and cannot overturn the objective result.

### 10. Hypotheses
Primary hypothesis, directional:
- H1: Condition B has a higher probability of verified task success than condition A

Null hypothesis:
- H0: there is no difference, or the observed difference is consistent with noise in this benchmark design

Secondary hypotheses:
- H1a: Condition B increases the supported-claim rate
- H1b: Condition B reduces unsupported plus inconclusive blocking claims
- H1c: Condition B improves scope adherence
- H1d: any gain in verified success is not offset by an impractical explosion in time cost

### 11. Statistical analysis plan
Unit of analysis:
- one run is one observation
- primary paired structure: task x replicate index

Primary test:
- paired comparison of the binary primary endpoint using a paired non-parametric procedure on per-pair differences across task-replicate cells
- for the main scalar comparison, use Wilcoxon signed-rank on task-level paired summaries if the pairing is valid and there are enough non-zero differences
- if pairing breaks, fall back to Mann-Whitney U and label the analysis as unpaired

Effect size reporting, mandatory:
- absolute difference in verified success rate, B minus A
- bootstrap 95 percent confidence interval
- matched-pair effect summary when pairing is used

Secondary metrics:
- Wilcoxon signed-rank for paired ordinal or count-like summaries when applicable
- Mann-Whitney U for non-paired comparisons
- bootstrap 95 percent confidence interval for each reported effect size

Multiple comparisons:
- one primary endpoint, no multiplicity correction for the primary endpoint
- secondary endpoints controlled with Holm correction within the secondary family
- subjective exploratory outcomes reported separately and not mixed into the primary claim

Missing data and failures:
- all runs are included
- missing required raw artifacts count as run failures on artifact completeness
- crashed or timed-out runs count as primary failures
- no post-hoc exclusion except pre-registered hard invalidation, such as benchmark harness crash before the agent starts. Any invalidation must be logged with reason

### 12. Decision rule
AgentHarness will be described as showing evidence of benefit only if all of the following hold:
1. the primary endpoint favors B over A
2. the effect size is positive and the bootstrap interval is not centered on a trivial difference
3. the primary test does not fail under the pre-registered analysis plan
4. the gain is not explained away by grossly impractical time cost
5. the report remains honest about the package-effect confounder

If these conditions do not hold, the headline result must be one of:
- no effect detected
- mixed evidence
- improvement with unresolved confounding, depending on the observed pattern

### 13. Raw artifact retention
Every run must save enough raw material to regenerate the metrics and audit the result.

Required per-run artifacts:
- prompt.txt
- task spec snapshot
- framework-context snapshot for B, baseline-context snapshot for A
- transcript or agent raw output log
- stdout.log
- stderr.log
- workspace snapshot or manifest of changed files
- run.json
- claims.json
- verify-run-report.json
- evaluation-report.json
- metadata.json
- repair-pass logs, if any

Suggested directory shape:
- `benchmarks/runs/<task_id>/<condition>/<replicate_id>/...`

### 14. Planned measurement harness design
No execution code is approved yet. This section records the intended design only.

Harness responsibilities:
1. materialize a fresh workspace for a single task-condition-replicate cell
2. render the correct prompt and context package for A or B
3. launch the coding agent with fixed runtime settings
4. capture all raw outputs and benchmark metadata
5. invoke `agentharness verify-run` on the produced `run.json` and `claims.json`
6. invoke the task evaluation suite on the produced workspace outputs
7. write a normalized cell summary JSON derived only from raw artifacts and tool reports

Planned command surface:
- one command to execute a single cell
- one command to execute a full pre-registered matrix, only after approval
- one command to anonymize artifacts for blinded review
- one command to aggregate raw reports into analysis tables

Cell execution logic, planned:
- baseline A runs once within the fixed budget, with no framework files
- treatment B runs once, then gets at most one bounded repair pass if `verify-run` returns blocking unsupported or inconclusive claims
- both conditions use the same total budget and same tool policy

How `verify-run` provides objective metrics:
- it validates run/claim envelope consistency
- it checks scope claims, required artifacts, and explicit test-execution claims
- it reexecutes supported pytest wrappers when possible, which avoids trusting narrated success
- it returns machine-readable counts of supported, unsupported, inconclusive, and invalid claims
- its JSON report is the primary source for evidence-backed execution metrics

How deterministic task checks fit in:
- task-specific correctness that is not generic enough for `verify-run`, such as exact schema or file-content expectations, is captured in an evaluation suite
- the evaluation suite report remains secondary to raw artifacts, and is also regenerated from those raw artifacts

Blind subjective protocol, planned:
- a separate anonymizer copies only the files needed for human review
- condition labels are replaced with random IDs
- raters score reviewability and README clarity without seeing the original benchmark condition

### 15. Open decisions requiring approval
1. Treatment confirmation:
   - proposed default is B-loop-closed
   - alternative is B-context only
   - recommendation: approve B-loop-closed if the goal is to test the strongest real claim of AgentHarness

2. Run count confirmation:
   - proposed default is 4 tasks x 6 paired replicates = 48 total runs
   - stronger option is 4 tasks x 8 paired replicates = 64 total runs
   - cheaper option is 4 tasks x 4 paired replicates = 32 total runs, with weaker inference

3. Task-suite confirmation:
   - keep support-ticket API
   - approve the other 3 task families before any run starts

4. Baseline contract confirmation:
   - proposed baseline still emits `run.json` and `claims.json`, so objective measurement is symmetric
   - this is recommended, because otherwise B would benefit from measurement affordances that A lacks

5. Subjective review confirmation:
   - approve whether to include the blinded human-review residual at all in phase one
   - recommendation: keep it, but exploratory and strictly secondary

### 16. Freeze rule
No benchmark execution may start until this document is approved.
After approval, treatment definition, metrics, task list, N, and decision rule are frozen.

## Italiano

### 1. Scopo
Questo documento fissa il design del benchmark prima di eseguire qualunque confronto tra una condizione senza framework e una condizione con AgentHarness.

L'obiettivo è stimare se AgentHarness migliora la qualità di esecuzione di un coding agent in modo riproducibile, revisionabile e statisticamente difendibile.

Questa pre-registrazione ammette esplicitamente un risultato nullo. Se i dati non mostrano un miglioramento difendibile, il report dovrà dirlo.

### 2. Portata della claim
Il benchmark può sostenere solo una claim limitata:
- una suite piccola può mostrare un segnale, oppure nessun segnale, per i task, il modello, i tool e le impostazioni runtime testate
- non può dimostrare una legge universale su tutti i coding agent o su tutti i task software

### 3. Scelta del trattamento
Trattamento primario proposto: B-loop-chiuso.

Definizione:
- Condizione A, baseline: l'agente riceve solo la specifica del task, la descrizione dell'ambiente di esecuzione, i tool consentiti, il budget di tempo e un contratto di output fisso che richiede un run artifact e un documento di claim
- Condizione B, AgentHarness: l'agente riceve la stessa specifica del task più il contesto framework AgentHarness per quel task, e deve produrre un run artifact più un documento di claim che `agentharness verify-run` accetta. Claim blocking unsupported o inconclusive attivano un solo repair pass limitato dentro lo stesso budget totale

Perché questo trattamento è preferito:
- testa l'unica capacità davvero distintiva del framework, cioè la verifica evidence-backed invece della sola narrazione
- un trattamento solo contesto misurerebbe soprattutto se più istruzioni aiutano, che è una claim più debole e meno interessante
- il loop chiuso obbliga il framework a guadagnarsi valore tramite outcome che sopravvivono alla verifica, non tramite una struttura solo più ordinata

Vincolo sul repair loop:
- massimo 1 repair pass automatico dopo il primo risultato di `verify-run`
- nessun salvataggio umano oltre la policy di intervento pre-registrata
- il budget totale wall-clock è identico tra le condizioni

### 4. Dichiarazione esplicita del confondente
Il confondente principale è reale e va dichiarato senza ambiguità.

La condizione B aggiunge due cose insieme:
1. più contesto strutturato, come PROJECT.md, policy, workflow, checklist, metadata generati
2. un loop di verifica che può rifiutare claim unsupported e attivare una correzione limitata

Quindi il confronto primario A contro B stima l'effetto di AgentHarness come pacchetto operativo, non l'effetto causale isolato del solo contesto framework.

Questo benchmark non deve sostenere:
- che ogni guadagno derivi solo dalla verifica
- che ogni guadagno derivi solo dal contesto
- che l'effetto framework sia già separato dall'effetto del contesto extra

Mitigazione:
- entrambe le condizioni usano la stessa task spec, lo stesso modello, gli stessi tool, lo stesso budget di tempo, la stessa policy di intervento e lo stesso contratto finale di output
- entrambe le condizioni devono emettere raw artifact, metadata di run e artifact di claim nello stesso schema
- il report etichetterà il risultato come stima di effetto di pacchetto

Estensione futura opzionale, non parte di questa pre-registrazione salvo approvazione prima di qualunque run:
- aggiungere una terza condizione, B-contesto, oppure una baseline con claim simmetrici, per separare l'effetto del contesto da quello della verifica a loop chiuso

### 5. Dimensione della suite benchmark
Dimensione proposta della suite: 4 task indipendenti.

Motivazione:
- un task solo non basta nemmeno per una generalizzazione limitata
- quattro task restano abbastanza pochi da essere sostenibili, ma coprono più di una modalità di fallimento

Famiglie di task proposte:
1. support-ticket API, task benchmark esistente
2. inventory-adjustment API con regole transazionali di business
3. servizio di webhook ingestion con validazione schema e vincoli di idempotenza
4. job di export o report con output file deterministico e validazione dei negative path

Requisiti di design dei task:
- ogni task deve avere una spec scritta
- ogni task deve definire scope consentito e scope vietato
- ogni task deve definire una evaluation suite oggettiva e un contratto di claim per verify-run
- ogni task deve essere risolvibile nella stessa classe generale di budget

### 6. Numero di run
Default proposto: 6 run appaiati per task, una coppia per seed o indice di replica.

Questo produce:
- 4 task
- 6 repliche appaiate A/B per task
- 24 confronti appaiati totali
- 48 run benchmark totali

Perché questo è il default di bozza:
- è materialmente migliore di un run singolo
- fornisce abbastanza coppie perché un test non parametrico appaiato abbia senso, restando entro un costo plausibile
- richiede comunque reporting onesto dell'incertezza, perché 24 coppie sono informative ma non grandi

Alternativa sensibile al costo, da approvare prima dell'esecuzione:
- piano più forte: 8 run appaiati per task, 32 coppie totali, 64 run totali
- piano più economico: 4 run appaiati per task, 16 coppie totali, solo se il budget runtime è davvero vincolato, con limitazione dichiarata in evidenza

Nessun cambiamento a N è consentito dopo l'avvio del primo run benchmark.

### 7. Controlli di riproducibilità
Queste impostazioni devono essere fissate e loggate per ogni run:
- provider del modello e nome esatto del modello
- runtime dell'agente, per esempio Claude Code, Cursor, Codex CLI, con versione esatta quando disponibile
- temperatura e altri controlli di stocasticità, quando esposti
- seed o indice di replica, quando il runtime espone un seed reale. Se non è disponibile, usare indici di replica appaiati e mantenere identica la procedura di avvio
- accesso ai tool e policy di rete
- budget wall-clock
- numero massimo di repair pass
- template del workspace e file iniziali
- hash della versione del task benchmark
- commit SHA di AgentHarness
- hash della versione dello script benchmark

### 8. Metriche oggettive, primarie e secondarie
Il benchmark ridurrà al minimo il punteggio soggettivo. La maggior parte delle metriche deve essere oggettiva e rigenerabile dai raw artifact.

#### 8.1 Endpoint primario
Endpoint primario: verified task success, binario per run.

Un run conta come successo primario solo se tutte le condizioni seguenti sono vere:
- l'agente ha prodotto un run artifact e un documento di claim
- `agentharness verify-run` restituisce `ok = true`
- la task evaluation suite restituisce `ok = true`
- nessun claim di allowed scope o forbidden scope è unsupported
- il run finisce entro il budget di tempo fissato

Questo endpoint risponde a una domanda semplice: il run ha prodotto un outcome evidence-backed, in scope e corretto sul task.

#### 8.2 Metriche oggettive secondarie
Metriche oggettive secondarie, calcolate per run:
- pass complessivo di verify-run, binario
- pass complessivo della evaluation suite, binario
- proporzione di claim supported in `verify-run`
- conteggio dei claim unsupported
- conteggio dei claim inconclusive
- conteggio dei claim invalid
- conteggio dei claim di business rule superati
- conteggio dei claim di scope adherence superati
- pass della riesecuzione del test command, binario quando applicabile
- numero di file cambiati fuori scope consentito, conteggio deterministico
- tempo wall-clock trascorso
- numero di repair pass consumati
- numero di interventi umani, che dovrebbe restare al massimo pre-registrato
- completezza del run artifact, binaria, cioè presenza di tutti i raw file richiesti

Fonti delle metriche oggettive:
- report JSON di `agentharness verify-run`
- report JSON della task evaluation
- controlli deterministici sul filesystem dei raw artifact richiesti
- file metadata del benchmark

### 9. Metriche soggettive residue
La review soggettiva è solo residuale.

Uso previsto:
- solo per proprietà di reviewability e chiarezza non ancora difendibili con controlli deterministici
- non come endpoint primario

Protocollo:
- 2 valutatori in cieco
- artifact anonimizzati e privati delle etichette di condizione e, quando possibile, di marcatori framework evidenti
- ogni valutatore assegna un voto solo su questi item da 1 a 5:
  - reviewability del codice
  - chiarezza operativa del README
- il valore riportato è la media dei due valutatori
- l'accordo inter-valutatore deve essere riportato in modo descrittivo

Se l'anonimizzazione in cieco non è credibile per un certo set di artifact, i risultati soggettivi vanno etichettati come esplorativi e non possono ribaltare il risultato oggettivo.

### 10. Ipotesi
Ipotesi primaria, direzionale:
- H1: la condizione B ha una probabilità più alta di verified task success rispetto alla condizione A

Ipotesi nulla:
- H0: non c'è differenza, oppure la differenza osservata è compatibile con rumore dentro questo design benchmark

Ipotesi secondarie:
- H1a: la condizione B aumenta il supported-claim rate
- H1b: la condizione B riduce i claim blocking unsupported più inconclusive
- H1c: la condizione B migliora lo scope adherence
- H1d: eventuali guadagni nel verified success non sono compensati da un'esplosione impraticabile del costo temporale

### 11. Piano di analisi statistica
Unità di analisi:
- un run è un'osservazione
- struttura appaiata primaria: task x indice di replica

Test primario:
- confronto appaiato dell'endpoint primario binario usando una procedura non parametrica appaiata su differenze per coppia task-replica
- per il confronto scalare principale, usare Wilcoxon signed-rank sui riassunti appaiati a livello task se l'appaiamento è valido e ci sono abbastanza differenze non nulle
- se l'appaiamento si rompe, usare Mann-Whitney U e dichiarare l'analisi come non appaiata

Reporting dell'effect size, obbligatorio:
- differenza assoluta nel verified success rate, B meno A
- intervallo di confidenza bootstrap al 95 percento
- sintesi dell'effetto su coppie appaiate quando si usa l'appaiamento

Metriche secondarie:
- Wilcoxon signed-rank per riassunti appaiati ordinali o count-like, quando applicabile
- Mann-Whitney U per confronti non appaiati
- intervallo di confidenza bootstrap al 95 percento per ogni effect size riportato

Confronti multipli:
- un endpoint primario, nessuna correzione di molteplicità per l'endpoint primario
- endpoint secondari controllati con correzione Holm dentro la famiglia secondaria
- outcome soggettivi esplorativi riportati separatamente e non mischiati nella claim primaria

Dati mancanti e fallimenti:
- tutti i run sono inclusi
- i raw artifact richiesti mancanti contano come fallimento sul criterio di artifact completeness
- run crashati o andati in timeout contano come fallimenti sull'endpoint primario
- nessuna esclusione post hoc salvo hard invalidation pre-registrata, per esempio crash dell'harness benchmark prima che l'agente parta. Ogni invalidazione deve essere loggata con motivazione

### 12. Regola di decisione
AgentHarness verrà descritto come supportato da evidenza di beneficio solo se tutte le condizioni seguenti tengono:
1. l'endpoint primario favorisce B rispetto ad A
2. l'effect size è positivo e l'intervallo bootstrap non è centrato su una differenza banale
3. il test primario non fallisce sotto il piano di analisi pre-registrato
4. il guadagno non è spiegato da un costo temporale grossolanamente impraticabile
5. il report resta onesto sul confondente di effetto di pacchetto

Se queste condizioni non tengono, il risultato headline dovrà essere uno tra:
- nessun effetto rilevato
- evidenza mista
- miglioramento con confondimento non risolto, a seconda del pattern osservato

### 13. Conservazione dei raw artifact
Ogni run deve salvare materiale sufficiente per rigenerare le metriche e auditare il risultato.

Artifact richiesti per run:
- prompt.txt
- snapshot della task spec
- snapshot del framework context per B, snapshot del baseline context per A
- transcript o raw output log dell'agente
- stdout.log
- stderr.log
- snapshot del workspace oppure manifest dei file cambiati
- run.json
- claims.json
- verify-run-report.json
- evaluation-report.json
- metadata.json
- log dei repair pass, se presenti

Struttura directory suggerita:
- `benchmarks/runs/<task_id>/<condition>/<replicate_id>/...`

### 14. Design previsto dell'harness di misura
Nessun codice di esecuzione è ancora approvato. Questa sezione registra solo il design previsto.

Responsabilità dell'harness:
1. materializzare un workspace fresco per una singola cella task-condizione-replica
2. renderizzare il prompt corretto e il pacchetto contesto per A o B
3. lanciare il coding agent con impostazioni runtime fissate
4. catturare tutti i raw output e i metadata benchmark
5. invocare `agentharness verify-run` sul `run.json` e `claims.json` prodotti
6. invocare la task evaluation suite sugli output workspace prodotti
7. scrivere un cell summary JSON normalizzato derivato solo da raw artifact e report tool

Superficie di comando pianificata:
- un comando per eseguire una singola cella
- un comando per eseguire una matrice completa pre-registrata, solo dopo approvazione
- un comando per anonimizzare artifact per review in cieco
- un comando per aggregare i report grezzi in tabelle di analisi

Logica prevista di esecuzione cella:
- la baseline A esegue una volta sola entro il budget fissato, senza file framework
- il trattamento B esegue una volta, poi riceve al massimo un repair pass limitato se `verify-run` restituisce claim blocking unsupported o inconclusive
- entrambe le condizioni usano lo stesso budget totale e la stessa policy tool

Come `verify-run` fornisce metriche oggettive:
- valida la coerenza tra run envelope e claim envelope
- controlla claim di scope, artifact richiesti e claim espliciti di test execution
- riesegue i wrapper pytest supportati quando possibile, evitando di fidarsi della sola narrazione di successo
- restituisce conteggi machine-readable di claim supported, unsupported, inconclusive e invalid
- il suo report JSON è la fonte primaria per le metriche evidence-backed sull'esecuzione

Come si inseriscono i controlli deterministici sul task:
- correttezza task-specific non abbastanza generica per `verify-run`, come schema esatto o attese su contenuti file, viene catturata in una evaluation suite
- anche il report della evaluation suite resta secondario rispetto ai raw artifact, ed è rigenerato a partire da quei raw artifact

Protocollo cieco soggettivo, pianificato:
- un anonymizer separato copia solo i file necessari alla review umana
- le etichette di condizione vengono sostituite da ID casuali
- i valutatori assegnano il punteggio a reviewability e chiarezza README senza vedere la condizione benchmark originale

### 15. Decisioni aperte che richiedono approvazione
1. Conferma del trattamento:
   - default proposto è B-loop-chiuso
   - alternativa è B-contesto soltanto
   - raccomandazione: approvare B-loop-chiuso se l'obiettivo è testare la claim più forte e reale di AgentHarness

2. Conferma del numero di run:
   - default proposto è 4 task x 6 repliche appaiate = 48 run totali
   - opzione più forte è 4 task x 8 repliche appaiate = 64 run totali
   - opzione più economica è 4 task x 4 repliche appaiate = 32 run totali, con inferenza più debole

3. Conferma della task suite:
   - mantenere support-ticket API
   - approvare le altre 3 famiglie di task prima che parta qualunque run

4. Conferma del contratto baseline:
   - la baseline proposta emette comunque `run.json` e `claims.json`, così la misurazione oggettiva è simmetrica
   - questa scelta è raccomandata, altrimenti B beneficerebbe di affordance di misura che A non ha

5. Conferma sulla review soggettiva:
   - approvare se includere oppure no il residuo di human review in cieco già in fase uno
   - raccomandazione: mantenerlo, ma come elemento esplorativo e strettamente secondario

### 16. Regola di freeze
Nessuna esecuzione benchmark può iniziare finché questo documento non viene approvato.
Dopo l'approvazione, definizione del trattamento, metriche, lista task, N e regola di decisione sono congelati.
