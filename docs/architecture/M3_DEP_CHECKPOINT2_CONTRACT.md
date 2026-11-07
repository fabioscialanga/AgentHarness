# M3 Checkpoint 2 — contratto DEP e limiti operativi

**Stato:** specifica e dataset, nessuna detection o ricerca evidenze implementata. Il file `benchmarks/m3_dep/m3-binding-v0.schema.json` è lo schema JSON serializzato proposto per una sidecar M3. Gli artifact `run.json`, `claims.json` e `verify-report.json` M1/M2 mantengono il loro significato. Le sidecar delle fixture hanno `provenance: benchmark-oracle`: sono dati preparati per il benchmark, non attestazioni prodotte dal software di produzione.

## Cattura e fiducia del binding v0

Una futura implementazione può emettere `provenance: local-capture` soltanto quando l'utente invoca esplicitamente `check`: il processo cattura HEAD, diff e file non tracciati prima della copia, lascia creare la snapshot al `check` esistente, poi ricontrolla HEAD e diff e calcola il manifest dei file della snapshot. Se lo stato cambia, se un file non è leggibile o se manca un byte della snapshot, non finalizza il binding. `verify-run` da solo non aggiunge retroattivamente un binding M3. La sidecar collega `run_id`, commit, diff SHA-256, `state_id`, scope, mapping approvato, comando, ambiente, manifest della snapshot e hash degli artifact. `captured_at` non rinnova la freschezza: conta `reexecution_finished_at`. Tutti i timestamp sono UTC ISO 8601.

Il valore `state_id` v0 è un digest del commit target e del diff canonico. Per working tree serve anche il contenuto dei file non tracciati; il dataset codifica ciascuno con path, lunghezza e byte. Nella futura produzione la canonizzazione dovrà essere formalizzata e versionata **prima** di accettare binding esterni. Un digest locale dimostra coerenza dei byte inclusi, non autenticità contro chi può modificare insieme report e binding. L'ambiente e gli input esterni possono sfuggire alla snapshot: D29 lo mostra intenzionalmente. Un matcher prudente restituisce `unknown` quando l'ambiente richiesto non è dimostrabile.

## Mapping concreto DEP → controllo approvato

| Campo | Valore del solo benchmark/MVP DEP |
| --- | --- |
| Risk rule | `DEP-PEP621-V0`, variazione supportata in `[project].dependencies` o `[project.optional-dependencies]` di `pyproject.toml` |
| Mapping ID | `DEP-PEP621-PYTEST-V0` |
| Comando esatto | `python -m pytest -q tests/test_dep.py` |
| Cwd | Radice del repository sintetico, `.` |
| Scope minimo | `pyproject.toml` e `tests/test_dep.py` nella snapshot; stato complessivo invariato fra cattura e valutazione |
| Claim necessaria | `tests_executed`, `truth_source: reexecuted`, `status: supported`, exit code 0, report `ok: true` |
| Esito negativo | La stessa claim rieseguita con exit code non zero e binding valido ⇒ `failed` |
| Policy temporale | `DEP_LOCAL_24H_V0`: età da `finished_at` ≤24 ore; futuro ≤5 minuti ammesso, senza prolungare la scadenza |

Il comando è un **controllo campione approvato per questi repository sintetici**, non una scelta automatica per qualunque progetto Python. In produzione un mapping progetto→controllo necessita approvazione esplicita e un test pertinente. Il controllo non viene eseguito dagli hook: il benchmark conserva esecuzioni `check` preparate esplicitamente. D08, D30 e il secondo comando di D36 dimostrano che un test estraneo non copre DEP. `covered` indica solo che il controllo pertinente è stato eseguito e superato sullo stato dichiarato; non certifica compatibilità, assenza di vulnerabilità o sicurezza generale della dipendenza.

## Budget di lettura e comportamento in errore

Questi sono limiti **proposti**, non codice attivo. La ricerca delle evidenze, se autorizzata in un checkpoint futuro, deve essere solo lettura locale:

| Risorsa | Limite v0 proposto | Superamento |
| --- | ---: | --- |
| Directory run visitate | 128, ordine stabile per nome | `unknown:budget` se altre candidate potrebbero esistere |
| File JSON per run | 1 MiB ciascuno | `unknown:budget` per la candidata |
| Byte letti complessivi | 8 MiB | `unknown:budget` |
| `pyproject.toml` | 1 MiB | Astensione detection; nessun controllo |
| Diff canonico | 1 MiB | Astensione/`unknown:budget` |
| Path per manifest | 256 | `unknown:budget` |
| Tempo di ricerca evidenze | 250 ms soft, 1 s hard monotonic | `unknown:timeout`, output hook non bloccante |
| Subprocess Git | Al massimo uno, timeout 500 ms; nessuno se disabled | `unknown:git`, nessun retry/polling |

Il limite hard di 1 s è un tetto, non una latenza obiettivo. Un processo o I/O che non risponde deve essere interrotto dal timeout del percorso host; non si promette che ogni syscall su filesystem sia interrompibile. Path relativi confinati a `.agentharness/runs`, risoluzione senza symlink/traversal, niente comandi letti da artifact. Errore di parsing, permessi, file rimosso, hash non corrispondente o budget esaurito danno `unknown`/astensione; non impediscono a Codex di proseguire e non diventano `covered` o `uncovered`. `disable` termina prima di Git e della ricerca. Nessun daemon, polling, rete, LLM o test automatico.

## Limiti intenzionali

Non sono implementati il motore DEP, il matcher, la canonizzazione production-grade del `state_id`, mapping per progetti reali, CIR/SEC, importazione CI, firme, sandbox di rete o verifica di dipendenze esterne. D29 è una prova del limite di binding ambientale; D25/D26/D32 sono artifact manipolati da rigettare. Le label restano quelle preregistrate nel piano M3; il dataset congela i byte prima di qualunque valutazione del motore.
