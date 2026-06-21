# Bootstrap di AgentHarness

## Perché esiste

Una delle idee più forti di SIA non è solo il loop di self-improvement, ma anche il fatto che i task custom devono rispettare un contratto esplicito di directory layout.

AgentHarness beneficia della stessa disciplina.

Il comando bootstrap crea uno skeleton di repository che contiene già:
- intento di progetto leggibile da umani
- definizione di progetto machine-readable
- regole operative per agenti
- workflow, policy e checklist
- metadata `.framework` generati

## Comando

Dalla root del repository AgentHarness:

- `PYTHONPATH=src python3 -m agentharness bootstrap ./my-project --project-name "My Project" --project-slug my-project`

Dopo `pip install -e .`, puoi anche eseguire:

- `agentharness bootstrap ./my-project --project-name "My Project" --project-slug my-project`

## Flag opzionali

- `--project-type`
- `--language`
- `--framework`
- `--database`
- `--package-manager`
- `--license`
- `--json`

## Cosa viene creato

Il comando scrive:
- `PROJECT.md`
- `project.yaml`
- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE_SUMMARY.md`
- `docs/DELIVERY_MODEL.md`
- `workflows/*.md`
- `checklists/*.md`
- `policies/*.yaml`
- `tests/unit/README.md`
- `tests/integration/README.md`
- `tests/regression/README.md`
- `.framework/required-checks.json`
- `.framework/risk-matrix.yaml`
- `.framework/generation-report.json`

Dopo aver scritto i file, AgentHarness genera subito gli output `.framework` e valida il contratto del progetto.

## Perché è importante

Questo avvicina AgentHarness a essere un framework operativo, non solo una pattern library.

Il repository ora può:
- fare scaffolding di un nuovo contratto di progetto
- generare artefatti derivati di controllo
- validare il risultato

È una base molto più solida per l'automazione successiva.
