# Pubblicare AgentHarness

AgentHarness usa PyPI Trusted Publishing. Nessun token PyPI di lunga durata deve essere salvato nei secret GitHub.

## Configurazione PyPI iniziale

Crea un pending publisher su PyPI con questi valori esatti:

- nome progetto PyPI: `agentharness-verifier`
- owner GitHub: `fabioscialanga`
- repository GitHub: `AgentHarness`
- file workflow: `release.yml`
- nome environment: `pypi`

Crea anche l'environment `pypi` nelle impostazioni della repository GitHub. Eventuali reviewer dell'environment possono proteggere la pubblicazione in produzione.

## Gate di release

Prima del tag:

```bash
python scripts/check_release.py --tag v0.1.0
python -m pytest -q
python -m build
python -m twine check dist/*
```

Esegui manualmente il workflow `Release` con `release_tag=v0.1.0`. L'esecuzione manuale valida e carica le distribuzioni come artefatto del workflow, ma non le pubblica.

## Pubblicazione

Solo dopo il dry run e la CI ordinaria verdi:

```bash
git tag -a v0.1.0 -m "AgentHarness 0.1.0"
git push origin v0.1.0
```

Il workflow attivato dal tag:

1. controlla tag, versione del package e voce datata del changelog
2. costruisce wheel e source distribution
3. esegue `twine check`
4. carica le distribuzioni e genera attestazioni di provenienza
5. pubblica su PyPI tramite OIDC Trusted Publishing
6. crea la GitHub Release solo dopo la pubblicazione PyPI riuscita

## Verifica della release pubblica

```bash
python3 -m venv /tmp/agentharness-release-check
/tmp/agentharness-release-check/bin/python -m pip install agentharness-verifier==0.1.0
/tmp/agentharness-release-check/bin/agentharness --help
```

Esegui poi `agentharness check` su un piccolo workspace esterno e verifica che `verify-report.json` esista.

Non riutilizzare una versione già pubblicata. Le release PyPI sono immutabili.
