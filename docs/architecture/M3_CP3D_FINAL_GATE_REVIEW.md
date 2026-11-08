# M3 CP3-D — decisione preliminare sul gating DEP

**Stato:** verifica isolata. Nessun matcher è collegato all'hook Codex. Nessuna modifica a dataset, manifest o label congelati.

## Gating proposto

1. Se il progetto è `disabled`, terminare prima di Git e prima del fingerprint dell'interprete.
2. Per un evento che richiede esplicitamente valutazione DEP nel working tree, usare il preflight conservativo sperimentato in `scripts/m3_cp3d_prepare.py`: validare root e HEAD, leggere `pyproject.toml` entro 1 MiB senza symlink, confrontarlo con il blob HEAD, normalizzare solo il sottoinsieme PEP 508 approvato, poi ricontrollare HEAD e i byte locali. Con equivalenza dimostrata, uscire senza matcher e senza attestare `covered`.
3. Su qualsiasi errore, file mancante/non regolare, sintassi non supportata o cambiamento materiale, passare alla detection CP3-A. Solo `risk` può avviare il matcher CP3-B; la ricattura finale indipendente resta obbligatoria. Range committed espliciti bypassano il preflight working-tree.

Questo schema non è stato inserito nella CLI né nell'hook. La modifica semanticamente equivalente è un'uscita `no_dep_risk`, non una prova che tutto il repository sia immutato o che una dipendenza sia sicura. Il path list di M2 (`git diff HEAD`) è solo un segnale positivo: non è completo per file non tracciati, `assume-unchanged` e `skip-worktree`, quindi la sua assenza non può essere usata per dichiarare no-risk. Eventuali path forniti dall'host devono avere un contratto di completezza verificato prima di sostituire le letture Git.

### Falsi negativi e limiti

| Caso | Trattamento conservativo |
| --- | --- |
| `pyproject.toml` non tracciato o assente in HEAD | `git show` fallisce: fallback alla detection, non no-risk. |
| Modifica staged o unstaged | Confronto dei byte correnti con HEAD; un cambio materiale passa alla detection. Se l'indice cambia ma i byte tornano identici a HEAD, non vi è un rischio DEP corrente. |
| `assume-unchanged` / `skip-worktree` | La lettura diretta dei byte impedisce di fidarsi del solo diff Git. Entrambi i flag hanno test espliciti su repository sintetici; resta da provare l'interazione con un worktree host reale prima dell'hook. |
| Symlink, file eccessivo/non leggibile, parsing ambiguo | Nessuna uscita no-risk: fallback alla detection, che può astenersi. |
| HEAD o file modificati durante il preflight | Ricontrollo finale; se divergono, fallback. Un cambio ABA che ripristina gli stessi byte resta fuori dalle garanzie v0. |
| Nuovo commit mentre il preflight legge | Il doppio HEAD impedisce il no-risk se il commit finale differisce; commit modificato dopo l'ultimo controllo resta una normale finestra di race. |
| Dipendenza proveniente da fonti esterne o sintassi PEP 508 non supportata | Astensione o fallback secondo CP3-A; nessuna inferenza di sicurezza generale. |

Il test sulle fixture working-tree congelate verifica che nessuna label DEP `S` venga saltata dal preflight. Il test di race modifica i byte durante il ricontrollo; il test `assume-unchanged` verifica la lettura diretta. Nessuna garanzia copre in modo assoluto un filesystem ostile che cambia dopo la verifica finale.

## Misura appaiata Windows del gating

Sonda [`m3_cp3d_gating_comparison.py`](../../scripts/m3_cp3d_gating_comparison.py): 30 coppie preflight/detection sullo stesso repository sintetico, processo Python già avviato. JSON grezzo: [M3_CP3D_GATING_WINDOWS.json](M3_CP3D_GATING_WINDOWS.json).

| Scenario | Preflight p50/p95 ms | Git preflight | Detection diretta p50/p95 ms | Git detection |
| --- | ---: | ---: | ---: | ---: |
| Nessuna modifica | 124,893 / 166,961 | 3 | 254,532 / 317,063 | 6 |
| Equivalenza semantica | 129,584 / 170,630 | 3 | 272,099 / 320,827 | 6 |
| Rischio DEP reale | 84,540 / 93,922 | 2 prima del fallback | 242,653 / 269,565 | 6 |

Per il rischio reale il costo del preflight si **aggiunge** ai 6 processi della detection e ai 6 del matcher: 14 totali nel prototipo CP3-D contro 12 senza preflight. In una sessione Windows il solo no-risk ha ancora p95 circa 167–171 ms in-process; nel probe con nuovo processo CP3-D il caso senza modifica era 318,167/380,626 ms p50/p95. Il precedente M2 enabled con fingerprint già visto era 231,13/267,07 ms, misurato in una campagna diversa. Non è un confronto causale, ma il margine è sfavorevole. **Raccomandazione: non attivare questo preflight a ogni Stop** finché un segnale host completo o una riduzione verificata del costo Windows non soddisfa il budget dell'hook. Un controllo esplicito richiesto dall'utente rimane il contesto appropriato per l'MVP.

## Benchmark matcher con evidenze production

La sonda [`m3_cp3d_local_evidence_perf.py`](../../scripts/m3_cp3d_local_evidence_perf.py) crea repository locali temporanei e usa `check_dep_workspace` per produrre binding **`local-capture` effettivi**. Il check esplicito che crea l'artifact è fuori dalla misura; ogni matching parte da una detection fresca, verifica l'interprete e ricattura lo stato alla fine. Le 30 decisioni per scenario sono state uniformi sia su Windows sia su Linux. JSON grezzi: [Windows](M3_CP3D_LOCAL_EVIDENCE_WINDOWS.json), [Linux](M3_CP3D_LOCAL_EVIDENCE_LINUX.json).

| Stato | Evidenza | Windows matcher p50/p95 ms | Linux matcher p50/p95 ms | Git/match |
| --- | --- | ---: | ---: | ---: |
| `covered` | check riuscito e binding locale valido | 343,733 / 396,924 | 21,653 / 25,777 | 6 |
| `failed` | check rieseguito con fallimento | 348,627 / 432,717 | 19,985 / 26,478 | 6 |
| `uncovered` | nessun artifact | 287,126 / 327,702 | 12,895 / 18,065 | 6 |
| `unknown:tampered` | stdout alterato dopo il binding | 342,258 / 463,791 | 14,910 / 21,086 | 6 |
| `unknown:state_changed` | binding di stato precedente | 289,632 / 460,480 | 12,384 / 19,647 | 6 |
| `unknown:contradictory` | due check locali validi con esiti opposti | 289,132 / 365,412 | 20,765 / 25,780 | 6 |

Le righe `unknown` non sono diventate `covered`; il benchmark conferma i controlli su hash, stato obsoleto e contraddizione. La detection iniziale non è inclusa nei tempi matcher; aggiunge 6 processi Git. Il numero di byte letti dagli artifact per riga è nel JSON, insieme ai motivi di ogni decisione. Le sidecar `benchmark-oracle` non sono usate in questa sonda.

## Astensione Windows

La prima campagna CP3-D aveva osservato **1 `abstain` su 30** nel caso local-capture valido, senza diagnostica della causa. La nuova campagna di processo registra `detection_status` e `detection_reason`: **30/30 `covered`, zero astensioni** su Windows; [JSON](M3_CP3D_DIAGNOSTIC_WINDOWS.json). L'episodio originario non è riproducibile da questi dati, perciò **non attribuiamo con certezza la causa**. Un timeout Git di 1 s sotto carico è un'ipotesi plausibile, non un fatto osservato. Il test `test_git_timeout_abstains_without_matching` inietta la stessa condizione di astensione prevista da CP3-A e verifica che il pipeline restituisca `abstain` senza chiamare il matcher; quindi il timeout non produce un falso `covered`. Prima di un host reale servono motivi strutturati anche nel punto d'ingresso e prove sotto carico Windows con budget approvato.

## Esiti e riproduzione

Il file CP3-D completo registra **12 passed** su Windows (35,72 s) e **12 passed** su Linux (6,31 s). La regressione finale CP3-A/CP3-B/CP3-D/M2, incluso `skip-worktree`, ha dato **171 passed, 2 deselected** su Windows (112,03 s) e **173 passed** su Linux (37,07 s). I due deselected Windows sono i test M2 con assunzioni POSIX, **NOT RUN** su Windows e inclusi nel run Linux. La suite aggregata Stage 2 più core era stata eseguita al checkpoint precedente (385 passed, 1 deselected Hermes esterno); **non è stata rieseguita integralmente in questa verifica**. Il validatore del dataset registra **37/37 fixture valide** e **4/4 test**; dataset, manifest e label congelati non sono stati modificati.

Per le sonde: `python scripts/m3_cp3d_gating_comparison.py`, `python scripts/m3_cp3d_local_evidence_perf.py`, `python scripts/m3_cp3d_process_perf.py`. Linux usa l'immagine `python:3.12` con wheel locali; nessuna sonda chiama LLM, scansioni automatiche o hook. Nessun merge o modifica a `main`.
