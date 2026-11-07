# Ciclo di vita dell'adapter Codex — M2 sperimentale

## Interfaccia

`agentharness install --host codex [--project PATH] [--yes] [--json]` aggiunge un solo hook `Stop` in `<project>/.codex/hooks.json`. `agentharness uninstall --host codex` rimuove soltanto quel gruppo. I comandi richiedono conferma interattiva `y/yes`, oppure `--yes` esplicito per automazione. In assenza di terminale e di `--yes`, escono con codice 2 senza scrivere. Successo: 0; errore: 1. `--json` riporta `ok`, `action`, `changed` e `project`.

L'installazione non modifica `~/.codex`, `config.toml`, la trust store o la configurazione di AgentHarness M1. `enable`/`disable` controllano il messaggio emesso dal processo hook; non installano o disinstallano hook. Dopo `install`, l'utente deve revisionare e autorizzare l'hook nella TUI con `/hooks`, secondo la [documentazione ufficiale Codex](https://learn.chatgpt.com/docs/hooks). Codex può saltare l'hook finché il progetto o la definizione dell'hook non sono trusted.

## Formato e proprietà

L'adapter usa la struttura ufficiale `hooks.Stop[].hooks[]` con un handler `type: command`, `timeout: 5`, `command` Unix e `commandWindows` PowerShell. Il comando esegue l'interprete Python dell'installazione, `-m agentharness host-event --host codex --project <percorso assoluto>`. Non prende comandi dal payload. `commandWindows` usa l'operatore PowerShell `&` e quote singole con escape delle quote interne; `command` usa quoting POSIX. L'installazione può quindi essere invalidata se l'interprete viene rimosso o spostato; in quel caso occorre reinstallare dopo rimozione esplicita.

Il gruppo AgentHarness ha un `statusMessage` identificativo. Uninstall verifica che il gruppo e i comandi corrispondano esattamente alla forma generata; se qualcuno modifica quel gruppo, si ferma senza rimuoverlo. Hook di altri eventi e altri gruppi `Stop` rimangono nel documento. La serializzazione JSON può cambiare spaziatura e ordine visivo, ma preserva le chiavi e i valori sconosciuti; JSON malformato, chiavi duplicate o struttura non compatibile causano rifiuto. Quando l'ultimo hook è rimosso, resta `{"hooks": {}}`: così un file host preesistente vuoto non viene cancellato per errore.

La scrittura usa un lock locale di directory, file temporaneo nella stessa `.codex`, confronto ottimistico con i byte letti all'inizio e `os.replace` atomico. Un errore prima di `replace` lascia il file originale intatto. Il lock non viene eliminato automaticamente se il processo muore: un'installazione successiva si ferma e richiede ispezione manuale. Scrittori esterni che ignorano il lock possono modificare il file nell'intervallo tra il controllo finale e `os.replace`; il filesystem non offre una compare-and-swap portabile sul file. Questa race residua è documentata e l'adapter non è un meccanismo di coordinamento multi-processo universale.

`.codex` o `hooks.json` simbolici sono rifiutati. La lettura di `hooks.json` è limitata a 1 MiB. Il file JSON può contenere hook di terzi, che non vengono eseguiti dall'installer. Le loro definizioni sono solo lette e riscritte come dati. Uninstall non disabilita AgentHarness M1 e conserva `.agentharness` e le evidenze.

## Limiti e prossimo checkpoint

Questa fase riguarda solo Codex CLI locale. Non implementa Claude Code, app-server adapter, skill slash, Autopilot completo, daemon o scansioni automatiche. `status --json` M1 non inventaria ancora gli hook host installati manualmente o da questo comando; `host_adapter_installed: false` conserva il significato M1. La latenza del processo hook resta pagata anche con `enabled: false`; un futuro design potrebbe offrirne la rimozione, senza cambiare la semantica di `disable`.
