# M3 — consultazione DEP esplicita prima della PR

## Scopo e contratto

Il nuovo comando è **`agentharness dep-assess`**. Il nome distingue la consultazione in sola lettura da `check` (che esegue un controllo), `verify-run` (che valuta un run) e `status` (che descrive l'attivazione del progetto). Detection e matching riusano rispettivamente `detect_dependency_change` e `match_dep_evidence`; nessuna logica DEP parallela, categoria nuova o mapping nuovo. `src/agentharness/dep_assessment.py` orchestra soltanto le chiamate; `approved_dep_control_from_run` seleziona in modo limitato e sicuro un binding locale esplicitamente indicato. Nessun hook o adapter importa questo nuovo percorso.

`dep-assess` non esegue test, scansioni, comandi dagli artifact o LLM, non scrive artifact e non modifica `enable`/`disable`. L'utente può selezionare il mapping fisso già approvato con `--control DEP-PEP621-PYTEST-V0`, oppure un binding `local-capture` di un precedente check esplicito con `--control-run <id>`. Le opzioni sono mutuamente esclusive. Senza selezione, un rischio dà `unknown:control_not_selected`; un mapping diverso o un binding oracle/malformato non può dare `covered`. La selezione del mapping non salva approvazioni e non esegue il comando mappato.

Il JSON `m3.dep-assess.v0` ha campi `schema_version`, `project`, `detection`, `evidence`. Detection è `risk/no_change/abstain`. Se non è `risk`, `evidence` è `null`; altrimenti lo stato è `covered/uncovered/failed/unknown`. Motivazioni, mapping selezionato, run id e riferimenti relativi agli artifact sono inclusi. I riferimenti sono candidati, non prove autonomamente attendibili. `covered` significa copertura del controllo DEP pertinente, non sicurezza generale. Testo e istruzioni d'uso in [M3_DEP_ASSESS_CLI.md](M3_DEP_ASSESS_CLI.md), in inglese e italiano.

## Test

- Nuovo file CLI: **10 passed** su Windows (17,13 s) e **10 passed** su Linux (2,06 s), incluso un vero `python -m agentharness dep-assess` in sottoprocesso. I casi coprono assenza di controllo, mapping fisso senza evidenza, binding locale valido, `failed`, stdout alterato `unknown`, binding oracle/malformato/eccessivo, percorso run non sicuro, `no_change`, `abstain`, output testuale e JSON, nessuna riesecuzione/rete e nessuna modifica agli artifact.
- Regressione M1/M2/M3 su Linux Python 3.12, package editable installato da snapshot Git canonico: **254 passed**, 40,14 s. Comando: `pytest -q` sui dieci moduli core della matrice CI più `test_risk_dep.py`, `test_dep_evidence.py`, `test_cp3d_preparation.py`, `test_dep_assessment_cli.py`.
- Stessa selezione su Windows: **250 passed, 2 deselected, 2 failed**, 151,82 s. I due deselected sono i test M2 con assunzioni POSIX (`venv/bin/python` e `/subproject`), **NOT RUN su Windows**, ma compresi nel run Linux. I failure Windows sono `RuntimeFeaturesTests.test_run_plan_retries_then_uses_fallback` (percorso Python Windows non quotato nella command line del piano) e `GenerationTests.test_generate_framework_outputs_repairs_required_checks` (asserzione su `/` contro `\\` nei path restituiti). Test e sorgenti responsabili non hanno diff rispetto a `main`; non sono stati cambiati perché fuori dal perimetro DEP. Il run Windows **non è PASS**.
- Dataset congelato: validatore **37/37 fixture valide**, quattro test del validatore **4/4 passed**. Manifest e label invariati.
- La suite Stage 2 completa **NOT RUN in questa verifica**; al checkpoint precedente aveva dato 385 passed e 1 Hermes esterno deselected. Hermes esterno resta **NOT RUN** qui. Nessun esito Stage 2 nuovo viene dichiarato PASS.

## Costo Windows della nuova CLI

Sonda esplicita [M3_DEP_ASSESS_CLI_PERF_WINDOWS.json](M3_DEP_ASSESS_CLI_PERF_WINDOWS.json): 30 ripetizioni per scenario in repository sintetici temporanei. Il check che prepara l'evidenza valida è fuori dal tempo misurato. Le due colonne misurano rispettivamente chiamata `cli.main` nello stesso processo e `python -m agentharness dep-assess` in un nuovo processo; i processi Git sono contati nel percorso in-process, che usa la stessa detection/matching.

| Scenario | Detection / evidence | Git | In-process p50/p95 ms | Nuovo processo p50/p95 ms |
| --- | --- | ---: | ---: | ---: |
| Equivalenza semantica | `no_change` / null | 6 | 247,101 / 293,683 | 375,414 / 414,820 |
| Rischio senza controllo selezionato | `risk` / `unknown` | 6 | 252,660 / 312,860 | 376,824 / 447,640 |
| Rischio, mapping selezionato, nessun artifact | `risk` / `uncovered` | 12 | 523,842 / 600,452 | 657,207 / 760,070 |
| Rischio, binding locale valido | `risk` / `covered` | 12 | 519,612 / 553,909 | 644,389 / 690,010 |

Queste sono misure del comando esplicito, **non** di un hook Codex. Il comando usa la detection completa e conserva il controllo finale indipendente nel matcher. Anche per questo costo Windows non è prevista alcuna esecuzione automatica a Stop.

## Riproduzione e limiti

1. Installare il package in un ambiente Python 3.12 isolato (`pip install -e .`), con Git disponibile.
2. Eseguire `python -m pytest -q tests/test_dep_assessment_cli.py` e la selezione core/M3 sopra descritta. In Linux, usare uno snapshot creato con Git Linux: su questo checkout `git archive` Windows converte alcuni file LF congelati in CRLF e invalida test che confrontano hash. Installare il package editable nel container, così i sottoprocessi CLI risolvono `agentharness`.
3. Eseguire `python benchmarks/m3_dep/validate_dataset.py` e `python -m unittest discover -s benchmarks/m3_dep -p test_*.py -q`.
4. Eseguire `python scripts/m3_dep_assess_cli_perf.py` per rigenerare la misura Windows. La sonda esegue un check **solo in fase di setup esplicito** del repository sintetico; le chiamate misurate a `dep-assess` sono read-only.

Limiti M3 v0: solo working tree implicito, mapping fisso PEP 621, subset PEP 508 approvato, identità dell'eseguibile Python senza attestazione dell'intero site-packages, hash locali non firmati contro chi può riscrivere insieme binding e artifact. Un HEAD pulito può produrre `abstain:committed_base_unspecified`. Nessuna funzione CIR/SEC, Advisor, nuovo adapter o integrazione host è stata introdotta.
