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

Questo controlla che il contratto del progetto di esempio sia internamente coerente.

### 2. Rigenera i metadata del framework
```bash
agentharness generate examples/civictrack --json
```

Questo ricostruisce:
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

### 3. Crea un nuovo progetto
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
- comandi CLI funzionanti per validate, generate e bootstrap
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
