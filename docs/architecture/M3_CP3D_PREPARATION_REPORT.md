# M3 CP3-D — preparazione isolata, senza attivazione host

## Proposta e confini

La sonda [`m3_cp3d_prepare.py`](../../scripts/m3_cp3d_prepare.py) sperimenta un preflight conservativo **solo per il working tree**. Legge `pyproject.toml` con il limite esistente di 1 MiB, confronta il contenuto con `HEAD:pyproject.toml` e normalizza il sottoinsieme PEP 508 già approvato. Prima di concludere che non vi è un rischio DEP, ricontrolla HEAD e i byte locali. Errori, symlink, file assenti, sintassi incerta o cambiamento materiale passano alla detection CP3-A; solo una detection `risk` arriva al matcher CP3-B. `disabled` termina prima di Git. Il codice è confinato agli script di misura e non è importato da CLI, hook o adapter.

Il preflight non produce un binding e non attribuisce mai `covered`. Sul percorso di rischio restano la cattura di stato CP3-C e la ricattura finale indipendente del matcher. Il filtro può osservare un file semanticamente equivalente mentre altri file cambiano: in quel caso non segnala un rischio DEP, ma non dichiara invariato lo stato globale. Per range di commit espliciti e file non tracciati o assenti, la futura integrazione dovrà usare direttamente la detection esistente. Prima di attivare un hook serve una revisione della policy di gating, inclusi costi Windows e comportamento con `assume-unchanged`/`skip-worktree`.

Il [bridge oracle](../../scripts/m3_cp3d_oracle_bridge.py) richiama prima il validatore congelato, estrae le 37 fixture e riporta accanto a ciascuna la label oracle e il risultato della detection. Invoca il matcher production solo sui rischi working-tree con il normale controllo locale: **non** converte `benchmark-oracle` in `local-capture`, non riscrive binding e non esegue i comandi contenuti negli artifact. Il risultato è un inventario di valutazione riproducibile, non una matrice `C/U/F/?` di accuratezza del matcher: le sidecar oracle non sono attestazioni locali. Il JSON [M3_CP3D_ORACLE_BRIDGE.json](M3_CP3D_ORACLE_BRIDGE.json) registra 37 fixture, zero `covered` production da oracle, 15 `unknown`, 6 `uncovered` e 16 `not_applicable`.

## Misure

Le due sonde preparano una volta l'evidenza valida con il percorso `check` esplicito, fuori dalla finestra misurata, poi eseguono 30 ripetizioni per scenario. [Windows in-process](M3_CP3D_PREP_WINDOWS.json), [Linux in-process](M3_CP3D_PREP_LINUX.json), [Windows con nuovo processo](M3_CP3D_PROCESS_WINDOWS.json), [Linux con nuovo processo](M3_CP3D_PROCESS_LINUX.json). Linux usa Python 3.12 Docker e wheel offline; Windows usa il virtualenv Python 3.12. I p95 sono il ventottesimo campione ordinato su 30. La sonda Linux di processo è stata ripetuta dopo la suite Stage 2 per togliere il carico concorrente.

| Scenario | Git | Windows in-process p50/p95 ms | Linux in-process p50/p95 ms | Windows nuovo processo p50/p95 ms | Linux nuovo processo p50/p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| disabled | 0 | ~0 / ~0 | ~0 / ~0 | 153,749 / 199,824 | 399,037 / 426,078 |
| nessuna modifica | 3 | 171,557 / 202,506 | 5,849 / 10,570 | 289,825 / 331,286 | 396,923 / 452,342 |
| modifica semanticamente equivalente | 3 | 162,193 / 180,975 | 4,985 / 6,258 | 273,884 / 312,513 | 472,877 / 584,541 |
| rischio senza evidenza | 14 | 810,316 / 887,011 | 25,116 / 29,037 | 728,126 / 791,650 | 525,323 / 645,481 |
| rischio con evidenza valida | 14 | 727,827 / 828,894 | 30,433 / 35,901 | 1.195,630 / 2.159,483 | 475,357 / 632,554 |

La seconda sonda Windows ha prodotto 29 `covered` e **1 `abstain`** nel caso valido: l'astensione resta un limite prestazionale/affidabilità da chiarire prima dell'host, non un falso `covered`. Negli altri quattro scenari le 30 decisioni per scenario erano attese. I valori in-process e processo sono campagne diverse con cache/carico differenti; non si sommano.

Il confronto più vicino a M2 sullo stesso Windows è l'avvio di processo: nel probe CP3-C precedente M2 `host-event` disabled p50/p95 era **121,715/133,726 ms**, mentre il prototipo CP3-D disabled è **153,749/199,824 ms**. Il precedente M2 enabled con fingerprint già visto era **231,13/267,07 ms**, mentre il prototipo CP3-D senza modifica è **289,825/331,286 ms**; i campioni risalgono a momenti e processi differenti e non sono una misura causale. Anche nel caso senza modifica, il preflight aggiunge circa 136 ms alla mediana del processo CP3-D disabled. Il percorso rischio sale a 14 processi Git contro 12 di CP3-C, perché il preflight aggiunge due chiamate prima del fallback; l'ottimizzazione favorisce i casi senza rischio e peggiora quelli con rischio. Questo compromesso va approvato prima di qualunque integrazione. Latenza percepita Codex e token CP3-D: **NOT RUN**.

## Test ed evidenze

- `tests/test_cp3d_preparation.py`: **8 passed** sia su Windows (26,77 s) sia su Linux (4,76 s), compresi no-change/equivalenza/rischio, sintassi incerta, symlink, race, `assume-unchanged`, zero Git disabled, assenza di matching su equivalenza e divieto di promuovere oracle.
- `validate_dataset.py`: **37/37** fixture valide; `unittest` del validatore: **4 passed**. Dataset, manifest e label non sono stati alterati.
- Suite CI completa nel container Linux Python 3.12 con dipendenze Stage 2: **382 passed, 1 deselected, 362 warning statistici, 1.439,50 s**; exit 0. Il deselected è il preflight Hermes esterno, **NOT RUN**. Il run completo è stato avviato prima dell'aggiunta del test `assume-unchanged` e degli script di misura di processo; il file CP3-D aggiornato è stato poi eseguito per intero separatamente su Windows e Linux (8 passed). CP3-A, CP3-B e M2 sono inclusi nella suite completa. Due prove preparatorie non costituiscono PASS: copia incompleta (66 failure) e archivio creato da Git Windows con CRLF (hash Stage 2 errato). Il run canonico usa `git archive` Linux e byte conformi al manifest.
- Regressione finale CP3-A/CP3-B/CP3-D/M2: **169 passed** su Linux (37,91 s) e **167 passed, 2 deselected** su Windows (124,57 s). I due deselected Windows sono i test M2 con assunzioni POSIX e sono **NOT RUN** su Windows, ma inclusi nel run Linux.

## Riproduzione

1. Creare uno snapshot con Git Linux, perché su questo checkout Windows `git archive` converte alcuni file LF in CRLF e invalida gli hash Stage 2 congelati.
2. Estrarlo in un container Python 3.12 scrivibile, copiare `.git` e gli script/test CP3-D del commit di revisione, creare nel solo container `/usr/bin/python3.12` come nella CI, installare `pip install -e . 'numpy>=2.0' 'scipy>=1.14' 'pandas>=2.2' 'statsmodels>=0.14'`.
3. Eseguire `PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q --deselect=tests/test_stage2_campaign.py::Stage2CampaignRunnerTests::test_preflight_accepts_frozen_hashes_on_clean_synced_commit`.
4. Eseguire separatamente `python scripts/m3_cp3d_prepare.py`, `python scripts/m3_cp3d_process_perf.py` e `python scripts/m3_cp3d_oracle_bridge.py` per rigenerare le misure e il bridge. Le sonde non sono richiamate dagli hook.

Nessun LLM, nuovo host, CIR/SEC, modifica di configurazione Codex, merge o modifica a `main`.
