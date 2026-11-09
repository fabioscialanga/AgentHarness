# M3 CP3-C — ottimizzazione isolata DEP

## Perimetro e modifiche

Il matcher riutilizza `DetectionResult` come cattura iniziale e verifica lo stato con una nuova detection alla fine, inclusa l'assenza di artifact. La cattura iniziale porta root e tempo monotono: un risultato di un altro repository o più vecchio di 2 secondi produce `unknown:capture_unverified`. `git rev-parse --show-toplevel HEAD` sostituisce due processi Git con uno; root, commit, payload e algoritmo di `state_id` non cambiano. Il test di confronto fra output combinato e separato e le 37 fixture congelate confermano la compatibilità. Non è stata aggiunta alcuna integrazione host.

Il limite di 2 secondi riguarda soltanto il passaggio detection→matcher, non la policy `DEP_LOCAL_24H_V0` per la freschezza delle evidenze. Il matcher continua a controllare l'interprete, gli hash, i budget, la provenienza e i risultati contraddittori. Una modifica dopo la ricattura finale o un cambio ABA che ripristina gli stessi byte resta fuori dalle garanzie v0.

## Verifiche

| Ambiente | Comando | Esito |
| --- | --- | --- |
| Windows, Python 3.12 virtualenv | `python -m pytest -q tests/test_risk_dep.py tests/test_dep_evidence.py tests/test_direct_check.py tests/test_host_prototype.py tests/test_claim_verify.py -k 'not test_cli_verify_run_reexecution_catches_a_lie and not test_verify_run_allows_controlled_relative_working_dir'` | 159 passed, 2 deselected, 79,10 s |
| Linux, `python:3.12` Docker, wheelhouse offline | stesso elenco senza `-k`, `PYTHONPATH=src`, `-p no:cacheprovider`, copia temporanea scrivibile | 161 passed, 33,69 s |
| Windows | `python benchmarks/m3_dep/validate_dataset.py` | 37/37 fixture valide |
| Windows | `python -m unittest discover -s benchmarks/m3_dep -p test_*.py -q` | 4 passed |
| Windows | test mirati su nuova race, manomissione run/output, contraddizione e race preesistente | 6 passed, 28 deselected, 11,30 s |

I due test esclusi su Windows usano `venv/bin/python` e il suffisso POSIX `/subproject`. Sono **NOT RUN su Windows** e inclusi nel risultato Linux. Nessun test è stato chiamato dall'hook. Dataset, manifest e label non sono stati modificati.

Un primo tentativo Linux con mount `:ro` ha prodotto 15 errori `Read-only file system` nei test M2 che scrivono trace nelle fixture; è stato scartato e ripetuto in una copia temporanea scrivibile, ottenendo 161 passed.

## Prestazioni

La sonda esplicita [`scripts/m3_cp3c_perf.py`](../../scripts/m3_cp3c_perf.py) crea un repository sintetico, produce una verifica locale autorizzata **una volta**, quindi misura 30 ripetizioni detection+matching con evidenza valida. Nello stesso avvio misura 30 processi M2 `host-event` **disabled** in un progetto separato. JSON grezzi: [Windows](M3_CP3C_PERF_WINDOWS.json), [Linux](M3_CP3C_PERF_LINUX.json).

| Percorso | Windows p50/p95 | Linux p50/p95 | Git |
| --- | ---: | ---: | ---: |
| CP3-C detection+matching, processo Python già avviato | 560,601 / 685,841 ms | 32,823 / 40,609 ms | 12 per esecuzione |
| M2 `host-event` disabled, nuovo processo | 121,715 / 133,726 ms | 325,502 / 382,794 ms | 0 |

Prima dell'ottimizzazione, il percorso detection+matching avrebbe avviato **21 processi Git** (7 detection iniziale, 14 matcher); ora ne avvia **12** (6 iniziale, 6 finale), riduzione del 42,9%. La vecchia sonda Windows misurava il solo matcher con 14 chiamate e p50/p95 538,876/627,157 ms; la nuova misura include anche detection e non va interpretata come riduzione proporzionale della latenza. Nel nuovo campione Git occupa una mediana di circa 90% del percorso Windows; resta il costo dominante.

I due percorsi della tabella hanno confini diversi: CP3-C misura il motore in-process, M2 l'intero avvio CLI. Il confronto indica il costo aggiuntivo potenziale, **non** la latenza di un hook CP3-C: questo hook non esiste. La misura Linux M2 comprende installazione offline delle dipendenze nel container prima della sonda, ma i 30 avvii misurati avvengono dopo l'installazione. Hardware, filesystem e cache influenzano i valori. Latenza percepita in Codex, token e turni host CP3-C: **NOT RUN**.

## Riproduzione

Windows: installare le dipendenze in virtualenv e lanciare `python scripts/m3_cp3c_perf.py`. Linux offline: usare `python:3.12`, montare il repository in sola lettura per la sonda, installare con `pip install --no-index --find-links benchmarks/grading-env/wheelhouse pytest PyYAML fastapi httpx`, impostare `PYTHONPATH=src`, poi lanciare lo stesso script. Per l'intera suite di test, copiare `src`, `tests`, `benchmarks`, `pyproject.toml`, `README.md`, `LICENSE` e `NOTICE` in `/work` scrivibile nel container prima di avviare pytest. Il pacchetto di revisione include l'intero albero tracciato, wheelhouse, diff e identificativi dei commit. Nessun merge, modifica a `main`, scansione automatica o integrazione Codex.
