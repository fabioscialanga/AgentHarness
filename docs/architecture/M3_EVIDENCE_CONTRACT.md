# M3 Checkpoint 1 — Contratto delle evidenze

**Stato:** contratto proposto, non implementato. `covered` significa soltanto «la verifica pertinente è stata eseguita con esito positivo sullo stato valutato»; non significa assenza di difetti. Gli artifact già prodotti da `check` e `verify-run` sono la fonte degli esiti. Un testo dell'agente («test passati») non è evidenza.

## Binding minimo v0

| Campo logico | Significato e origine |
| --- | --- |
| `risk_id`, `rule_id`, `risk_scope` | Identità stabile della regola e percorsi/hunk cui si riferisce il rischio; creati dalla detection deterministica. |
| `base_commit`, `target_commit` | SHA Git completo. Per working tree non committato, `target_commit = HEAD` e `base_commit = HEAD`; per intervallo già committato, base e target sono espliciti. Se la base manca, stato `unknown`. |
| `diff_digest`, `state_id` | Hash SHA-256 di una rappresentazione canonica del diff/stato osservato: path, tipo di modifica, contenuto rilevante e staged/unstaged/untracked. `state_id` include commit e stato del workspace osservato. Un file non leggibile, un symlink non sicuro, un diff troncato o una voce non tracciata non inclusa rendono il binding `unknown`. Gli hash non sono una prova di test. |
| `evidence_scope` | Scope dichiarato dal controllo e file effettivamente nella snapshot. Deve includere `risk_scope` e gli input necessari al comando; se non si può dimostrare tale inclusione, `unknown`. `changed_files` da solo non dimostra copertura funzionale. |
| `command`, `cwd`, `environment_id` | Comando esatto o token normalizzati, directory di esecuzione e identificatori non segreti dell'ambiente (versione Python, lock/dependency digest, piattaforma quando rilevante). Il matcher usa un mapping rischio→verifica approvato, non accetta qualsiasi `pytest` verde. Non memorizzare credenziali o variabili d'ambiente sensibili. |
| `run_id`, `artifact_refs` | Riferimenti a `.agentharness/runs/<run_id>/run.json`, `claims.json`, `verify-report.json` e, se presente, a stdout/stderr della riesecuzione. Verificare path confinati, schema, `run_id`, SHA-256 di run/claims già nel report e hash degli output disponibili. |
| `result`, `executed_at`, `evaluated_at` | Esito del comando e della claim pertinente, timestamp UTC della **esecuzione** e della valutazione. `evaluated_at` di una rivalutazione non rinnova `executed_at`. Timeout, errore dell'harness e risultato assente non sono successi. |

Un piccolo binding aggiuntivo, prodotto **solo quando l'utente invoca una verifica**, potrà collegare `run_id` e `state_id` senza cambiare il significato degli artifact esistenti. In M2, `verify-report.json` include `run_sha256`, `claims_sha256`, `evaluated_at`, risultati e `audit_trail`; la riesecuzione registra comando, exit code, stdout/stderr con hash, `started_at` e `finished_at`. `check` conserva una copia del workspace e i file in `.agentharness/runs/<run_id>/`. Questi dati **non includono da soli** un binding attendibile a commit/diff: un vecchio report M2 senza binding M3 rimane `unknown` per un rischio M3, anche quando `ok: true`.

## Stati esclusivi per un rischio rilevato

| Stato | Condizione |
| --- | --- |
| `covered` | Esiste una verifica pertinente, realmente eseguita e positiva, con artifact leggibili e hash coerenti, stesso `state_id`/commit/diff, scope sufficiente, comando/cwd/ambiente accettati e timestamp fresco. Per il primo MVP richiedere `tests_executed: supported` con `truth_source: reexecuted`, exit code 0 e `verify-run.ok: true`; `run-artifact` o sola dichiarazione non bastano. |
| `uncovered` | Il rischio è concreto e **nessuna** verifica candidata pertinente è presente. È un'assenza di evidenza, non un fallimento del codice. |
| `failed` | Una verifica pertinente con binding valido è stata eseguita sullo stato corrente e ha fallito (`unsupported` da riesecuzione con exit code non zero). Riportare comando, exit code e riferimenti agli artifact; non trasformare un timeout in `failed`. |
| `unknown` | Esiste una candidata ma è obsoleta, non legata allo stato corrente, incompleta, corrotta, non pertinente, solo dichiarata, inconclusive/invalid, con timeout o con ambiente incompatibile. Anche errori Git/filesystem e casi di matching ambiguo sono `unknown`. Non viene presentata come `covered`. |

In presenza di più candidate, valutare solo quelle pertinenti allo stato corrente. Un fallimento valido non viene cancellato da un successo di comando diverso; successi e fallimenti contraddittori per lo **stesso** comando/stato danno `unknown` con i due artifact mostrati, finché la causa non è chiarita. L'ordine di priorità non permette di «scegliere il verde».

## Freschezza e pertinenza

1. **Identità dello stato:** commit, diff e stato del workspace devono corrispondere all'istante della verifica. Una modifica dopo il test, anche se in un altro file che può influenzare la suite, invalida conservativamente il binding. Per il primo MVP non si tenta una dependency closure completa. Se la stessa modifica viene committata, occorre un nuovo binding sul commit; non si trasferisce automaticamente il verde dalla working tree.
2. **Tempo:** usare il tempo di esecuzione attestato, non il tempo di importazione del report. Come soglia iniziale da validare nel benchmark, evidenza locale più vecchia di 24 ore è `unknown`; per CI si richiede almeno il commit esatto e una policy di freschezza esplicita. Clock skew o timestamp assente: `unknown`.
3. **Comando e scope:** il controllo deve essere associato alla categoria/rischio tramite una regola approvata. Un test unitario di modulo estraneo, un lint o una build senza test non coprono automaticamente una modifica di dipendenza. Un test con scope ristretto può essere pertinente solo se il mapping ne esplicita il motivo. `verify-run` può produrre `supported` anche da `parsed-evidence` o `run-artifact`; M3 non converte quei valori automaticamente in `covered`.
4. **Integrità e sicurezza:** verificare hash e path dentro il workspace o l'area artifact approvata; rifiutare symlink/traversal e letture illimitate. Non eseguire mai comandi letti dagli artifact durante il matching. Un'eventuale nuova riesecuzione richiede un'azione esplicita dell'utente attraverso i comandi esistenti.

**Esempio:** rischio DEP su un vincolo in `pyproject.toml`, `HEAD=abc…` e `diff_digest=d1`. Un `check` esplicitamente richiesto per `python -m pytest -q` con report di riesecuzione positiva, `state_id` corrispondente e timestamp fresco è `covered`. Lo stesso report dopo un'ulteriore modifica al progetto, o senza binding M3, è `unknown`; nessun report è `uncovered`.
