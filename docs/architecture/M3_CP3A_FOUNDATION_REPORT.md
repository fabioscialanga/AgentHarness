# AgentHarness M3 — CP3-A Foundation

**Stato:** CP3-A completato sul branch `feat/m3-dep-evidence-mvp`; consegna per revisione indipendente. **Non** sono stati avviati CP3-B, CP3-C o CP3-D.

## Congelamento prima del codice

- `main` era al commit `497bcd84aba6ad39cd77d9d6d4f6d743bc376b88`; il branch CP3-A nasce dal Checkpoint 2 approvato `655c3b704f7c242bcde0c2483d589112ee52f20d`.
- Il commit separato `d3371ad` registra il congelamento prima del commit implementativo. `benchmarks/m3_dep/MANIFEST.sha256`, 37 ZIP, ledger, label e schema non sono stati modificati.
- Prima del codice: validatore del dataset **37/37**, test del dataset **4/4** su Windows. I tre file locali non tracciati preesistenti sono stati preservati ed esclusi dai commit.

## Codice introdotto in CP3-A

`src/agentharness/risk_dep.py` è un modulo deterministico e indipendente dall'host. L'API `detect_dependency_change(project, base_commit=None, target_commit=None)` restituisce `risk`, `no_change` o `abstain`. Solo `risk` contiene un `RiskCandidate`; l'astensione ha un motivo e **non** inventa un rischio o uno stato di evidenza. Non viene chiamata da hook o CLI in CP3-A.

Il parser usa `tomllib` e il solo sottoinsieme PEP 508 approvato: nome PEP 503, extras normalizzati e ordinati, clausole `==`, `!=`, `<`, `<=`, `>`, `>=` su release numeriche, zeri finali e ordine delle liste irrilevanti. Marker, URL, `~=`, `===`, wildcard, epoch, prerelease, metadata dinamici e duplicati ambigui portano ad astensione se interessano il confronto. Una voce fuori sottoinsieme identica nei due stati resta opaca e non blocca altre modifiche supportate. Non vengono installati pacchetti né consultata la rete.

`StateIdentity` v0 usa SHA-256 e campi con lunghezza prefissata: commit base/target, diff staged e unstaged separati, diff esplicito tra due commit quando richiesto, file `pyproject.toml` non tracciato e digest del contenuto corrente. Lo staging diverso produce quindi un ID diverso anche a parità di working tree; una modifica tracciata fuori da `pyproject.toml` modifica conservativamente lo stato. Il confronto di commit già effettuati richiede entrambi gli SHA espliciti. Con HEAD pulito e senza base esplicita il risultato è `abstain:committed_base_unspecified`, perché non si può dedurre l'intervallo storico da un working tree pulito.

Le letture Git hanno timeout di 1 secondo per chiamata e output massimo di 1 MiB; `pyproject.toml` ha limite di 1 MiB e apertura con `O_NOFOLLOW` ove disponibile. I percorsi di repository e file simbolici, file non regolari, TOML malformato e errori Git/lettura generano astensione. I comandi Git sono argomenti fissi, senza shell, `--no-ext-diff` e `--no-textconv`. Il modulo non esegue test, scansioni o comandi provenienti dal repository. **Correzione CP3-B:** un reader a buffer limitato interrompe Git appena supera il budget, con timeout monotono; non accumula più output illimitato in un file temporaneo.

## Evidenze eseguite

`tests/test_risk_dep.py` esegue 57 test, inclusi tutti i 37 repository congelati, equivalenze, astensioni, cambiamenti staged/unstaged, gruppi opzionali vuoti, file non tracciato, file troppo grande, symlink, errore, timeout e output Git oltre budget. Risultato Windows: **57 passed**. Il dataset CP2 resta **37/37** e i suoi quattro test restano **4/4**.

La valutazione riproducibile `scripts/m3_cp3a_eval.py` ha prodotto [Windows](M3_CP3A_WINDOWS_EVAL.json) e [Linux](M3_CP3A_LINUX_EVAL.json). Sono misure **solo della detection**, senza unzip, hook, binding o matching:

| Label attesa | `risk` | `no_change` | `abstain` |
| --- | ---: | ---: | ---: |
| S | 22 | 0 | 0 |
| N | 0 | 7 | 0 |
| A | 0 | 0 | 8 |

Sul campione congelato: precisione e recall per `S` = 22/22 = **1,00**, F1 = **1,00**, astensioni corrette = **8/8**. Sono risultati preliminari della detection e non dimostrano la qualità dell'evidence matching o un vantaggio rispetto a Codex solo. Nessuna label è stata cambiata in funzione dell'output.

| Ambiente | p50 detection | p95 detection | Esito |
| --- | ---: | ---: | --- |
| Windows, `.venv` locale | 287,154 ms | 344,378 ms | 37/37 |
| Linux, Docker `python:3.11`, repository montato read-only | 12,206 ms | 21,878 ms | 37/37 |

Le latenze Windows sono un rischio per la futura soglia dell'hook; CP3-C dovrà misurare e ridurre il percorso effettivamente invocato allo Stop, senza aggirare i controlli di stato. Queste cifre non sono overhead M2-vs-M3 e non includono avvio del processo host. La strumentazione aggiunta in CP3-B ha misurato **253 chiamate Git** sulle 37 fixture (media 6,84; intervallo 2–7), **10,480 s** cumulati e **25.193 byte** restituiti su Windows; su Linux **0,473 s** cumulati e **24.120 byte**. Il reader ora arresta il processo quando l'output supera il limite, anziché attendere la terminazione. L'integrazione Codex, la deduplicazione M3, il benchmark end-to-end e la CI completa restano **NOT RUN** in CP3-A/CP3-B.

## Riproduzione

Da una copia del branch con Python 3.11+ e dipendenze di sviluppo installate:

```powershell
python benchmarks/m3_dep/validate_dataset.py
python -m unittest discover -s benchmarks/m3_dep -p test_*.py -v
python -m pytest -q tests/test_risk_dep.py
python scripts/m3_cp3a_eval.py
```

Per la valutazione Linux senza dipendenze aggiuntive del progetto, il solo script di benchmark importa direttamente il modulo CP3-A puro dalla directory `src/agentharness`; il codice applicativo continua a usare il package normale. Esempio con immagine locale `python:3.11` e mount read-only:

```sh
docker run --rm --mount type=bind,source="$PWD",target=/work,readonly -w /work python:3.11 python scripts/m3_cp3a_eval.py
```

## Limiti per la revisione

CP3-A classifica **modifiche potenzialmente rischiose**, non vulnerabilità. La rappresentazione dello stato è locale e non è ancora un binding di evidenza: CP3-B dovrà verificare snapshot, artifact, ambiente e tempo prima di attribuire `covered`. Le sidecar `benchmark-oracle` del Checkpoint 2 usano digest preparati dal generatore del dataset, mentre CP3-A introduce una canonicalizzazione versionata che separa staged/unstaged e include il contenuto corrente. I loro `state_id` non sono automaticamente intercambiabili. **CP3-B deve definire e far revisionare un confronto esplicito con le sidecar congelate, senza riscriverle né trattarle come attestazioni production `local-capture`.** Fino ad allora nessuna fixture può essere classificata `covered` dal nuovo codice. Git diff può essere influenzato da caratteristiche del repository non ancora simulate dal dataset (per esempio submodule o filtri particolari); in caso di stato non affidabile la scelta prevista è l'astensione. Il campione di 37 scenari è piccolo e costruito dal contratto: 37/37 non è una stima di accuratezza su progetti reali.
