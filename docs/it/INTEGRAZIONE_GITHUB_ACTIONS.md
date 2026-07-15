# Integrazione con GitHub Actions

AgentHarness può trasformare il claim sui test di una pull request in un artefatto di verifica persistente. La repository include un workflow copiabile in:

`examples/github-actions/agentharness-check.yml`

## Cosa fa il workflow

1. Esegue il checkout della pull request.
2. Installa il progetto da verificare e AgentHarness.
3. Esegue `agentharness check` sul workspace.
4. Riesegue `python -m pytest -q` in una copia persistente del workspace.
5. Carica envelope, claim, stdout, stderr, hash e report di verifica anche quando la verifica fallisce.

## Installazione

Dopo la pubblicazione di `agentharness-verifier` versione `0.1.0` su PyPI:

```bash
mkdir -p .github/workflows
cp examples/github-actions/agentharness-check.yml .github/workflows/agentharness.yml
```

Prima della release, sostituisci nel workflow copiato la riga di installazione da PyPI con un'installazione Git fissata a un commit:

```bash
python -m pip install \
  "git+https://github.com/fabioscialanga/AgentHarness.git@main"
```

## Adattamento al progetto

Il template presuppone:

```bash
python -m pip install -e .
python -m pytest -q
```

Modifica l'installazione del progetto se la repository usa un altro gestore delle dipendenze. Il comando di verifica deve restare una delle forme pytest consentite da AgentHarness.

Per controllare anche lo scope delle modifiche, aggiungi:

```bash
--allowed-path "src/*" \
--allowed-path "tests/*" \
--forbidden-path "secrets/*"
```

## Comportamento in CI

AgentHarness usa exit code stabili:

- `0`: tutti i claim bloccanti sono supportati
- `1`: almeno un claim bloccante non è supportato oppure è inconclusivo
- `2`: input o configurazione di verifica non validi

Lo step di caricamento usa `if: always()`, quindi una verifica fallita lascia comunque gli artefatti diagnostici.

## Confine di isolamento

La directory di lavoro del comando è una copia persistente del workspace. Questo impedisce alle normali scritture relative di finire nel checkout originale, ma non costituisce una sandbox di sicurezza:

- il workspace originale non è protetto in scrittura dal sistema operativo
- la rete non è isolata
- i percorsi assoluti del filesystem host non sono isolati

Non usare l'executor attuale per eseguire codice non fidato su un runner sensibile. Consulta `SECURITY.md`.
