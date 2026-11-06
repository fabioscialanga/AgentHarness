# M0 — audit dello stato attuale

Data: 2026-11-06. Ambito: checkout locale `C:\AgentAi\AgentHarness`, senza modifiche al codice applicativo.

## Provenienza e stato Git

`main` e `origin/main` puntano entrambi a `768ae296b53911ce484ccebce4c484fdf0a47596` dopo `git fetch origin`; `git diff --stat HEAD..origin/main` è vuoto. Il remoto è `https://github.com/fabioscialanga/AgentHarness.git`. `git status --short --branch` mostra `?? AGENTHARNESS_CODEX_HANDOFF.md`: file locale non tracciato, preservato. La storia recente (`git log --oneline --decorate -15`) riguarda soprattutto il benchmark Stage 2 e la migrazione delle credenziali. Nessun reset, merge, pull o push eseguito.

## Inventario verificato

| Area | Stato | Evidenza |
| --- | --- | --- |
| Package e CLI | Presente | `pyproject.toml`: `agentharness-verifier` 0.1.0, Python >=3.11, entry point `agentharness = agentharness.cli:main`; `src/agentharness/cli.py:20` `build_parser`, `:489` `main`. |
| Comandi | Presente | `cli.py` registra `check`, `validate`, `generate`, `verify`, `verify-run`, `evaluate`, `render-evaluation-suite`, `benchmark-evaluate-task`, `run-plan`, `bootstrap`. `enable`, `disable`, `status` sono assenti. |
| Verifica diretta | Presente | `direct_check.py:210` `check_workspace` crea una copia persistente e verifica il comando; `verify.py:116` `verify_run`, `checks.py:26` `evaluate_claim`, `reexecution.py:280` `reexecute_command`. |
| Contratti di progetto | Presente | `validation.py:580` `validate_project_directory`, `generation.py`, `verification.py:94` `verify_project_directory`, `bootstrap.py:458` `bootstrap_project`. |
| Valutazione e benchmark | Presente | `evaluation.py:285` `evaluate_run`, `benchmark_cells.py:1440` `execute_cell`, `benchmark_hidden_evaluators*.py`, `stage2_analysis.py`. Il benchmark include un invoker Hermes (`benchmark_cells.py:148`), senza dimostrare un adapter autopilot generale. |
| Tracce | Parziale per Autopilot | `observability.py:16` `EventLogger` scrive JSONL per esecuzioni esplicite; non emerge un motore di eventi di progetto sempre disponibile. |
| Configurazione Autopilot | Assente | Nessun comando enable/disable/status nella CLI; `.agentharness` è usata per artefatti delle run. `project.yaml` descrive il contratto di progetto, non lo stato Autopilot. |
| Adapter Claude Code / Codex | Non verificato | Nessun adapter host dedicato nell'entry point CLI; le capacità e gli hook delle versioni host non sono stati verificati. |
| Test | Presente, esito non verificato | `tests/test_*.py` coprono CLI, verifica, reexecution, benchmark e Stage 2. `python -m pytest -q` su Python 3.12 locale termina con exit code 1: `No module named pytest`. Nessuna installazione effettuata. |

Dipendenze runtime dichiarate: PyYAML >=6, FastAPI >=0.110, httpx >=0.27, pytest >=8,<9 (`pyproject.toml`). Sono relativamente pesanti per un futuro percorso CLI di solo stato; va valutata la separazione delle dipendenze, senza alterare il package esistente durante M1.

## Security posture e limiti

`SECURITY.md` dichiara esplicitamente che l'esecutore `workspace-copy` non è una sandbox: non blocca rete né filesystem host e non impone limiti CPU/memoria. `direct_check.py:52` riporta questi limiti anche nel risultato; `reexecution.py:166` limita i comandi ammessi. La copia protegge dalle normali scritture relative, non dall'esecuzione di codice non fidato. Da preservare la distinzione tra errore del software e guasto del verificatore descritta nel README e nei report del benchmark.

## Limiti dell'audit

Non sono stati eseguiti test perché manca pytest nell'interprete disponibile. Non sono state provate integrazioni Claude Code, Codex, Spec Kit o Bansat, né è stata verificata l'efficacia empirica dei risultati benchmark. Le affermazioni su questi sistemi restano non verificate.
