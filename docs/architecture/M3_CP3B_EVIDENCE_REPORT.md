# AgentHarness M3 — CP3-B Evidence Foundation

**Stato:** implementazione per revisione indipendente. CP3-C e CP3-D **non avviati**. Branch `feat/m3-dep-evidence-mvp`; dataset, manifest, schema e label Checkpoint 2 invariati.

## Contratto implementato

`src/agentharness/dep_evidence.py` aggiunge `ApprovedDepControl`, `check_dep_workspace` e `match_dep_evidence`. Il solo mapping v0 è `DEP-PEP621-PYTEST-V0`: comando esatto `python -m pytest -q tests/test_dep.py`, cwd `.`, scope `pyproject.toml` e `tests/test_dep.py`, progetto esplicito e `environment_id` locale. Un comando diverso è rifiutato; un report verde generico non diventa pertinente. Non sono state aggiunte chiavi alla configurazione M1.

L'utente può richiedere esplicitamente il binding con:

```powershell
agentharness check --workspace <repo> --command "python -m pytest -q tests/test_dep.py" --approve-dep-control --json
```

Senza `--approve-dep-control`, `check` conserva il percorso e l'output precedenti. La nuova opzione rifiuta cwd, output dir e scope alternativi, così non amplia implicitamente il mapping. `verify-run` mantiene il significato originario e **non** crea retroattivamente binding. Nessun hook chiama CP3-B.

### Cattura e coerenza

Il wrapper acquisisce detection e manifest dei file di input **prima** di `check_workspace`. Un callback opzionale del `direct_check` esistente registra il manifest della snapshot appena copiata e prima della riesecuzione. Dopo `verify-run`, il wrapper ricattura stato Git e manifest originale: scrive atomicamente `m3-binding-v0.json` soltanto se i due stati e i tre manifest coincidono. Un mutamento durante `check` lascia il report M2 ma non produce binding M3. Il matcher ricalcola stato all'inizio **e** alla fine; se cambia durante la lettura, il risultato è `unknown:state_changed`.

La sidecar usa lo schema v0 congelato con `provenance: local-capture`, commit, `diff_sha256`, `state_id`, mapping, scope, digest della snapshot, riferimenti e hash di run/claims/report/output, timestamp di cattura e `reexecution.finished_at`. I file generati dalla riesecuzione sotto `.agentharness` e le cache sono esclusi dal manifest degli **input** perché `direct_check` non li include nella copia iniziale o li genera durante il test. Symlink e file non regolari negli input impediscono il binding. Il confronto a tre punti non rende atomica la copia e non rileva un cambio ABA che torni esattamente agli stessi byte; hash locali non sono firme contro chi può riscrivere insieme binding e artifact.

### Selezione delle evidenze

`match_dep_evidence` legge solo `.agentharness/runs`, senza eseguire comandi dagli artifact. Verifica forma del binding v0, provenienza locale, mapping, scope, commit/diff/state, hash dei file e degli output attestati da `verify-run`, snapshot, claim `tests_executed`, `truth_source: reexecuted` ed exit code. Le candidate sono aggregate senza scegliere il verde più favorevole:

| Situazione | Esito |
| --- | --- |
| Nessuna candidata pertinente | `uncovered:absent` |
| Report M2 pertinente senza binding | `unknown:unverified` |
| Binding sullo stato precedente | `unknown:stale` o `unknown:state_changed`; una candidata corrente valida può prevalere su quella obsoleta |
| Hash alterato, path non sicuro, budget superato | `unknown:tampered`, `unknown:unsafe_path` o `unknown:budget` |
| Controllo corrente, rieseguito e positivo | `covered` **solo per quel controllo** |
| Controllo corrente, rieseguito con exit code non zero | `failed` |
| Positivo e negativo validi per stesso stato/controllo | `unknown:contradictory` |
| Timeout o risultato inconcludente | `unknown:unverified` |

La policy separata `DEP_LOCAL_24H_V0` usa UTC e `reexecution.finished_at`: età ≤24h inclusa, futuro fino a 5 minuti ammesso; futuro oltre soglia è `unknown:time`, vecchio oltre 24h `unknown:expired`. Cambiare `evaluated_at` non rinnova la prova. `covered` non significa che la dipendenza sia sicura.

### Budget e fail-open

Massimo 128 directory run, 1 MiB per JSON, 8 MiB letti complessivi, 256 path di manifest, 1 MiB per input e timeout monotono di 1 s per la **ricerca artifact**. Il matcher rifiuta traversal, symlink e riferimenti fuori dalla directory run. `risk_dep._git` è stato corretto: un thread legge al massimo il budget di byte e interrompe Git appena superato; ogni chiamata ha timeout monotono di 1 s. Errori Git o filesystem producono astensione/`unknown`, mai `covered`. Il tetto temporale della ricerca è controllato fra le letture; una singola syscall filesystem bloccata non è interrompibile in modo portabile. CP3-B non è collegato all'hook, quindi non può bloccare Codex.

## Evidenze

- CP3-A, stesso dataset congelato: **37/37** label detection, **57/57** test mirati; manifest e quattro test CP2 invariati.
- CP3-B: **30/30** test di binding positivo/negativo, racing Git, modifica dopo verifica, report M2 non legato, scope estraneo, manomissione run/stdout, traversal, limiti, timeout, policy temporale, contraddizione, opt-in CLI e compatibilità del `check` senza opzione. La suite combinata CP3-A/CP3-B/M2 ha restituito **112 passed** prima dell'ultimo test CLI, che è passato separatamente: **113 test distinti passati**, senza insuccessi osservati.
- Retrocompatibilità mirata: `tests/test_direct_check.py` e `tests/test_host_prototype.py` sono stati rieseguiti con **26 passed**. Nessun adapter host è stato modificato.
- Artifact avversariali del dataset congelato D03, D25–D29, D32–D33, D35 e D37 sono stati letti senza produrre `covered` locale. Le sidecar `benchmark-oracle` **non** sono accettate come `local-capture`: le fixture etichettate `C` non sono pertanto una prova positiva del matcher production. Un bridge di valutazione del benchmark, senza riscrivere le fixture o promuovere arbitrariamente le sidecar, resta da progettare e revisionare prima di CP3-D.

### Costo misurato

La [misura CP3-A Windows](M3_CP3A_WINDOWS_EVAL.json) e quella [Linux](M3_CP3A_LINUX_EVAL.json) registrano **253 chiamate Git** sulle 37 fixture, media 6,84 per caso. Windows: **10,480 s Git cumulati**, p50/p95 detection **287,154/344,378 ms**; Linux: **0,473 s Git cumulati**, p50/p95 **12,206/21,878 ms**. I byte Git restituiti sono rispettivamente 25.193 e 24.120. Sono misure di detection, non dell'hook.

La [sonda CP3-B Windows](M3_CP3B_PERF_WINDOWS.json) crea un controllo locale esplicito e ripete dieci matching read-only sullo stesso stato. Check più binding: **961,341 ms**. Matching p50/p95: **620,939/742,902 ms**; **14 chiamate Git per matching** (due ricatture complete) e circa **16 KiB di artifact letti per matching**. Le cifre variano con cache e carico della macchina. La latenza Windows supera la soglia prospettata per un futuro hook: **non** è autorizzato collegare questo percorso allo Stop in CP3-B. CP3-C dovrà ridurre le ricatture senza indebolire il controllo delle corse e misurare l'overhead end-to-end contro M2.

## Riproduzione e limiti

```powershell
python benchmarks/m3_dep/validate_dataset.py
python -m unittest discover -s benchmarks/m3_dep -p test_*.py -v
python -m pytest -q tests/test_risk_dep.py tests/test_dep_evidence.py
python -m pytest -q tests/test_direct_check.py tests/test_host_prototype.py
python scripts/m3_cp3a_eval.py
python scripts/m3_cp3b_perf.py
```

La matrice completa `C/U/F/?` sulle 37 fixture, prove Codex reali, CI completa, confronto M2 end-to-end e integrazione hook sono **NOT RUN**: appartengono a CP3-C/CP3-D o richiedono il bridge delle sidecar `benchmark-oracle`. Il modello d'ambiente v0 confronta versione Python/piattaforma dichiarate e non prova che ogni input esterno o dipendenza sia identico; D29 resta una dimostrazione di tale limite. Nessun LLM, daemon, polling o test automatico allo Stop è stato introdotto. `main` e il dataset congelato non sono stati modificati; nessun merge.
