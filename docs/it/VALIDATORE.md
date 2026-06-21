# Validatore di AgentHarness

## Scopo

Il validatore è la prima parte eseguibile di AgentHarness.

Il suo compito è verificare se una definizione di progetto nello stile AgentHarness è internamente coerente prima di aggiungere automazione più profonda.

## Cosa valida

Il validatore attuale controlla:
- presenza dei file di repository richiesti come `PROJECT.md`, `README.md` e `AGENTS.md`
- campi top-level obbligatori in `project.yaml`
- struttura di `stack`, `testing`, `quality`, `security` e `agent_policy`
- formato di `project_slug`
- workflow abilitati rispetto ai file attesi
- deliverable dichiarati rispetto a file e directory reali
- `.framework/required-checks.json` rispetto ai controlli dichiarati in `project.yaml`
- `.framework/risk-matrix.yaml` per i livelli di rischio richiesti

## Uso da riga di comando

Dalla root del repository:

- `PYTHONPATH=src python3 -m agentharness validate examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness validate examples/civictrack --json`

Dopo `pip install -e .`, puoi anche eseguire:

- `agentharness validate examples/civictrack`
- `agentharness validate examples/civictrack --json`

## Exit code

- `0` = validazione superata
- `1` = validazione fallita
- `2` = errore d'uso della CLI

## Generatore complementare

Il validatore ora è affiancato da un comando di generazione:

- `PYTHONPATH=src python3 -m agentharness generate examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness generate examples/civictrack --json`

Il generatore ricostruisce i file principali in `.framework` a partire da `project.yaml`:
- `required-checks.json`
- `risk-matrix.yaml`
- `generation-report.json`

Questo significa che AgentHarness adesso può sia validare l'intento di progetto sia rigenerare alcuni artefatti machine-facing che dipendono da esso.

## Verifica complementare

AgentHarness ora include anche un comando di verifica:

- `PYTHONPATH=src python3 -m agentharness verify examples/civictrack`
- `PYTHONPATH=src python3 -m agentharness verify examples/civictrack --json`
- `PYTHONPATH=src python3 -m agentharness verify examples/civictrack --write-report`

`verify` è volutamente ristretto nella v1.
Fa insieme due cose:
- esegue la stessa validazione strutturale di `validate`
- rigenera in una directory temporanea gli output `.framework` attesi e li confronta con i file versionati

Questo intercetta un failure mode molto pratico:
il contratto del repository è cambiato, ma gli artefatti generati del framework non sono stati aggiornati.

Quando usi `--write-report`, AgentHarness scrive `.framework/verification-report.json` con il risultato della verifica.

## Perché è importante

Questa combinazione validatore + generatore trasforma AgentHarness da concetto solo documentale a framework con veri punti di controllo eseguibili.

È ancora volutamente ristretto, ma dimostra un'idea critica:
la definizione di progetto può essere verificata e parzialmente materializzata in modo programmatico prima di essere usata per guidare agenti o automazione.

## Limiti attuali

Il tooling attuale non fa ancora:
- normalizzazione delle definizioni di progetto in uno schema canonico
- generazione dello scaffold completo del repository
- enforcement delle policy durante task di coding
- integrazione automatica con CI
- validazione di mapping custom arbitrari per i workflow

Questi sono passi successivi sensati una volta stabilizzati i contratti base di validazione e generazione.
