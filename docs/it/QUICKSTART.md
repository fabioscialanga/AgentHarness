# Quickstart di AgentHarness

## A cosa serve AgentHarness
AgentHarness aiuta i team a usare coding agent con più struttura e meno caos.

Invece di partire da un prompt vago, fornisce all'agente un contratto di progetto:
- intento del progetto
- configurazione machine-readable
- workflow
- policy
- checklist
- metadata `.framework` generati

Oggi il repository fornisce già un nucleo operativo funzionante:
- `agentharness validate` controlla se un progetto nello stile AgentHarness è coerente
- `agentharness generate` rigenera i metadata principali in `.framework` a partire da `project.yaml`
- `agentharness verify` controlla validità del contratto, coerenza semantica tra AGENTS.md e project.yaml, e drift negli artefatti `.framework` generati
- `agentharness verify-run` controlla i claim di un agente con prova severa di default, preferisce la riesecuzione controllata per i wrapper pytest supportati (`pytest`, `python -m pytest`, `uv run pytest`) e per working directory relative controllate dentro il workspace, e restituisce `inconclusive` quando la verità non è difendibile
- `agentharness bootstrap` crea lo skeleton iniziale di un nuovo progetto contract-first

## Per chi è utile
AgentHarness è utile soprattutto se vuoi:
- rendere il lavoro con agenti più ripetibile
- aggiungere struttura di review, test e sicurezza attorno agli agenti
- standardizzare come vengono impostati i task di ingegneria
- confrontare un'esecuzione governata con prompting ad hoc

È meno utile per prototipi usa-e-getta dove nessuno vuole mantenere struttura di progetto aggiuntiva.

## Prerequisiti
- Python 3.11+
- git

## Installazione
Clona il repository e installalo in editable mode:

```bash
git clone https://github.com/fabioscialanga/AgentHarness.git
cd AgentHarness
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Verifica che la CLI sia disponibile:

```bash
agentharness --help
```

## Primi comandi utili
### 1. Valida l'esempio incluso
```bash
agentharness validate examples/civictrack --json
```

Questo controlla che il contratto del progetto di esempio sia internamente coerente e che AGENTS.md rifletta ancora le regole chiave dichiarate in project.yaml.

### 2. Rigenera i metadata del framework
```bash
agentharness generate examples/civictrack --json
```

Questo ricostruisce:
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

### 3. Verifica l'esempio end-to-end
```bash
agentharness verify examples/civictrack --json
```

Questo conferma che i file `.framework` versionati corrispondano ancora agli output derivati da `project.yaml`.

### 4. Verifica evidenza claim-based di un run
```bash
agentharness verify-run \
  --run tests/fixtures/run_invite_schema_success.json \
  --claims tests/fixtures/claims_invite_schema.json \
  --json
```

Questo usa prova severa di default. Quando possibile, AgentHarness riesegue i comandi di test ammessi. Se non riesce a difendere la verità di un claim, restituisce `inconclusive` invece di un successo falso.

### 5. Smaschera un finto test verde dichiarato dall'agente
```bash
agentharness verify-run \
  --run tests/fixtures/run_invite_lie.json \
  --claims tests/fixtures/claims_invite_lie.json \
  --json
```

Questo esempio deve fallire. Il fixture dichiara un comando pytest verde, ma AgentHarness lo riesegue e cattura il vero exit code non zero in `.agentharness/evidence/<run_id>/reexecuted/`.

### 6. Crea un nuovo progetto
```bash
agentharness bootstrap ./my-project \
  --project-name "My Project" \
  --project-slug my-project \
  --json
```

Questo crea un nuovo skeleton di progetto con:
- `PROJECT.md`
- `project.yaml`
- `AGENTS.md`
- `workflows/`
- `checklists/`
- `policies/`
- `tests/`
- `.framework/`

poi genera i metadata e valida il risultato.

## Percorso consigliato per iniziare
Se sei nuovo nel repo, segui questo ordine:
1. leggi `README.md`
2. esegui `agentharness validate examples/civictrack --json`
3. esegui `agentharness bootstrap ...` su una directory temporanea
4. apri i file generati
5. leggi `docs/it/DOCUMENTAZIONE_PROGETTO.md` per capire il modello più a fondo

## Limiti attuali
AgentHarness è ancora in una fase iniziale.

Cosa esiste oggi:
- comandi CLI funzionanti per validate, generate, verify, verify-run e bootstrap
- un progetto di esempio completo
- test che coprono i flussi base

Cosa non esiste ancora:
- integrazione completa con il runtime esecutivo degli agenti
- integrazione CI pronta all'uso
- copertura ampia di template per molti tipi di progetto

## Dove andare dopo
- Panoramica framework: `README.md`
- Spiegazione completa del progetto: `docs/it/DOCUMENTAZIONE_PROGETTO.md`
- Dettagli validatore: `docs/it/VALIDATORE.md`
- Dettagli bootstrap: `docs/it/BOOTSTRAP.md`
- Benchmark A/B: `docs/it/BENCHMARK_AB.md`
