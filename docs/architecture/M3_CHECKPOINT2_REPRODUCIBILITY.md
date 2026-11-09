# AgentHarness M3 — Checkpoint 2: riproducibilità del benchmark DEP

## Consegna

Il dataset è in `benchmarks/m3_dep/`:

- `fixtures/D01.zip`–`D37.zip`: ogni ZIP contiene `repo/.git`, working tree sintetico, `scenario.diff`, `scenario.json` e, quando previsto, `.agentharness/runs/` con artifact reali del `check` esistente.
- `ledger.json`: label pre-registrate, commit base/target, tipo di stato, SHA-256 del diff, clock di valutazione e inventario per run con comando, claim, exit code, timeout e hash degli artifact.
- `MANIFEST.sha256`: SHA-256 di tutti i 37 ZIP, ledger, schema, generatore e validatore. Questo è il congelamento dei byte prima dell'implementazione M3.
- `.gitattributes`: forza LF nei file testuali del dataset e tratta gli ZIP come binari, così gli hash restano stabili dopo checkout Windows/Linux.
- `m3-binding-v0.schema.json`: sidecar serializzata proposta; gli artifact M1/M2 non sono stati modificati. Le sidecar nelle fixture sono marcate `benchmark-oracle`.
- `build_fixtures.py` e `validate_dataset.py`: preparazione esplicita e validazione **in sola lettura**. `test_validate_dataset.py` esercita D26 su Windows/Linux e i vincoli dello schema. Nessuno è chiamato dagli hook.

Il [contratto DEP](M3_DEP_CHECKPOINT2_CONTRACT.md) specifica mapping rischio→controllo, modello di fiducia, budget e fail-open. Il [piano del benchmark](M3_BENCHMARK_PLAN.md) conserva tutte le label e i criteri di valutazione. D37 è l'unica aggiunta rispetto ai 36 casi DEP approvati: il report termina due minuti dopo il clock di valutazione e resta entro la tolleranza di cinque minuti.

## Verifica dei byte congelati

Da una copia del repository con Python 3.11+:

```powershell
python benchmarks/m3_dep/validate_dataset.py
```

Il validatore confronta tutti gli SHA-256 del manifest, ZIP CRC, `scenario.diff`, label e artifact elencati nel ledger; verifica la presenza del repository Git, la forma dei binding secondo i keyword dello schema v0 e cerca nomi di credenziali e percorsi personali nei file testuali. **Non** esegue `check`, test, scansioni, Git su progetti reali, detection o matching M3. Per ispezionare una fixture: estrarre uno ZIP in una directory temporanea e leggere `repo/scenario.json`, `repo/scenario.diff`, `repo/.agentharness/runs/*/verify-report.json`; `git -C repo log --oneline` mostra i commit sintetici. Per D10 il `pyproject.toml` è non tracciato; per D11–D12 il cambiamento è già committato.

La validazione schema usa solo la libreria standard e applica tutti i keyword **assertivi presenti nello schema v0**: `type`, `required`, `additionalProperties`, `properties`, `patternProperties`, `const`, `enum`, `pattern`, `$ref`, `minLength`, `minItems`, `items`, `minProperties` e `format: date-time` con timezone. Un keyword assertivo sconosciuto causa errore esplicito. I metadati `$schema`, `$id`, `title`, `description` e `$defs` non sono asserzioni sul valore; `$defs` è risolto solo per i riferimenti usati. Non vengono verificati dalla sola validazione schema: confinamento dei path, corrispondenza del commit Git reale, canonicalizzazione del diff, identità dell'ambiente, freschezza effettiva, autenticità del produttore, pertinenza del controllo e correttezza delle label. Alcuni di questi hanno controlli di integrità separati nel validatore; nessuno equivale al futuro matching M3.

La rigenerazione semantica, **non bit a bit**, è possibile in un ambiente isolato con AgentHarness e pytest installati:

```powershell
python benchmarks/m3_dep/build_fixtures.py
```

Il generatore rifiuta di sovrascrivere `fixtures/`. Per una rigenerazione comparativa usare un checkout o directory separata; timestamp, Git SHA e path degli artifact variano e producono nuovi ZIP/hash. Il dataset valutativo è esclusivamente quello del manifest committato. Non si aggiornano fixture o label sulla base dei futuri risultati del motore; eventuali nuovi casi vanno in un holdout revisionato separatamente.

## Evidenze della preparazione

Esecuzione locale del 7 novembre 2026, Windows, `.venv` con dipendenze installate:

| Verifica | Risultato osservato |
| --- | --- |
| Preparazione esplicita | 37/37 ZIP creati; D01–D36 più D37. Il generatore ha invocato `check_workspace` solo per i casi con artifact previsti. |
| Validazione dataset | `VALID: 37 fixture; manifest, ZIP CRC, diff, artifact hash, binding schema v0, label e path sensibili coerenti` |
| Distribuzione label | 8 `A/?`, 7 `N/—`, 10 `S/?`, 5 `S/C`, 2 `S/F`, 5 `S/U` |
| D02, D19, D31, D37 | `check` corrente: claim `supported`, `truth_source: reexecuted`, exit code 0, `report_ok: true` |
| D04, D36 | Controllo richiesto: claim `unsupported`, exit code 1, `report_ok: false` |
| D29 | Stesso codice/comando: un run `supported`/0 e uno `unsupported`/1; il test legge un input esterno non catturato. Caso intenzionalmente ambiguo per il modello di ambiente. |
| D33 | `inconclusive`, `timed_out: true`, nessun exit code. |
| D25, D26, D32 | Artifact modificati dopo la verifica; gli hash o i contenuti non concordano con il report. |
| D27 | `evaluated_at` spostato oltre 24h dall'esecuzione; la freschezza non si rinnova. |
| D28 | Il binding conserva il digest precedente; `scenario.diff` è il working tree successivo, con SHA diverso. |
| D35, D37 | Clock congelato rispettivamente 6 e 2 minuti prima di `finished_at`; il primo supera la tolleranza, il secondo no. |

Il controllo di integrità è **PASS**. Il motore M3, il matching, la regressione applicativa e le misure di overhead sono **NOT RUN** perché il Checkpoint 2 non ne autorizza l'implementazione o l'esecuzione. Il validatore controlla l'integrità del dataset e alcuni vincoli strutturali; non conferma da solo la correttezza semantica di ogni label. Questa è oggetto della revisione indipendente.

## Revisione correttiva multipiattaforma

La revisione esterna ha individuato che `Path(...).name` applicava la sintassi del sistema ospite al percorso Windows di D26. `portable_basename()` ora separa lessicalmente sia `\\` sia `/`, senza consultare il filesystem. Il test apre lo ZIP D26, legge il vero `stdout_path` Windows dal report, trova il file incluso e conferma la discordanza dell'hash. D13 usa ora realmente `My_Pkg>=2,<3` → `my-pkg>=2,<3`, con diff controllato dal validatore; la label `N/—` è invariata. Solo D13 è stata rigenerata: gli altri 36 ZIP e le loro label sono rimasti invariati. Manifest e ledger sono stati aggiornati prima di qualsiasi codice del motore.

| Ambiente | Comando | Esito effettivo |
| --- | --- | --- |
| Windows, `.venv` | `python benchmarks/m3_dep/validate_dataset.py` | PASS, 37/37 fixture e schema binding v0 |
| Windows, `.venv` | `python -m unittest discover -s benchmarks/m3_dep -p test_*.py -v` | PASS, 4/4 test |
| Linux, Docker `python:3.11`, mount repository read-only | `python benchmarks/m3_dep/validate_dataset.py` | PASS, 37/37 fixture e schema binding v0 |
| Linux, Docker `python:3.11`, mount repository read-only | `python -m unittest discover -s benchmarks/m3_dep -p test_*.py -v` | PASS, 4/4 test, incluso D26 |

La validazione multipiattaforma è **strutturale e di integrità**. Il giudizio che D13 sia semanticamente equivalente secondo PEP 503, o che un artifact sia davvero pertinente al rischio, rimane una valutazione del contratto e della revisione indipendente: il motore M3 è **NOT RUN**.

## Limiti e dati

Gli ZIP conservano path assoluti sintetici nei report M2: provengono dalla directory di preparazione sotto `benchmarks/m3_dep/.build-*`, che non esiste più. Per il replay bisogna rigenerare con `check`; non si deve considerare la semplice estrazione una nuova esecuzione verificata. I report sono prove locali non firmate e non isolano rete o filesystem host. L'input esterno del test D29 rende esplicito che un `environment_id` incompleto non prova identità ambientale. Non sono inclusi `.venv`, cache, `.env`, credenziali, segreti o dati personali. Nessun hook, daemon, LLM, adapter host o configurazione Codex è stato avviato o modificato per questo checkpoint.
