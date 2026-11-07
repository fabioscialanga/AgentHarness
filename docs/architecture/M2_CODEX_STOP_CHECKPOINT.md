# M2 — checkpoint di invocazione reale dell'hook Codex Stop

Data: 7 novembre 2026. Branch: `feat/m2-host-prototype`. Nessun merge e nessun hook globale installato. Prova limitata a un repository Git temporaneo `C:\AgentAi\AgentHarness\m2_hook_probe`, poi rimosso.

## Contratto e trust

Versione osservata: `codex-cli 0.154.0` su Windows, Python 3.12.10, modello host `gpt-5.6-luna`. Le [specifiche ufficiali degli hook Codex](https://learn.chatgpt.com/docs/hooks) descrivono `Stop` per la fine di un turno, input JSON su stdin, output JSON su stdout e `systemMessage` come warning UI. Un hook non gestito è **configurato ma non eseguibile** quando `trustStatus: untrusted`: Codex richiede la revisione della definizione esatta, registra il trust per il suo hash e salta gli hook nuovi o modificati finché non vengono autorizzati. Il trust della directory di progetto è distinto dal trust dell'hook. La prova precedente con override di sessione aveva rilevato l'hook, ma `trustStatus: untrusted` impediva di attribuirgli un'invocazione.

La TUI ha mostrato prima il prompt di trust della directory e poi `Hooks need review`. In `/hooks`, l'hook di progetto `Stop` risultava `Installed 1, Active 0, Review 1`; dopo la revisione del comando e la scelta `t`, risultava `Installed 1, Active 1` e `Trusted`. Il cambio successivo del comando Windows l'ha marcato `Modified since last trusted`; è stato revisionato e autorizzato di nuovo. Nessun flag `--dangerously-bypass-hook-trust` è stato usato in questa indagine.

## Configurazione diagnostica e prova minima

Il file temporaneo `.codex/hooks.json` usava la struttura ufficiale:

```json
{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"python marker.py","commandWindows":"python C:\\AgentAi\\AgentHarness\\m2_hook_probe\\marker.py","timeout":5}]}]}}
```

`marker.py` leggeva stdin JSON, scriveva solo `hook_event_name`, `stop_hook_active` e `cwd` in `stop-marker.json`, poi emetteva `{"systemMessage":"M2 DIAGNOSTIC STOP HOOK"}`. Il marker osservato in un turno reale della TUI era:

```json
{"event":"Stop","stop_hook_active":false,"cwd":"C:\\AgentAi\\AgentHarness\\m2_hook_probe"}
```

Comando TUI: `codex.cmd -C C:\AgentAi\AgentHarness\m2_hook_probe -m gpt-5.6-luna --no-alt-screen --sandbox read-only`, con `TERM=xterm` per il terminale PTY. Il prompt del turno chiedeva solo `Reply exactly OK. Do not run tools.`. La TUI ha indicato `Running hook` e il marker è stato creato. Anche `codex.cmd exec -C ... --ephemeral -m gpt-5.6-luna --sandbox read-only --json "Reply exactly OK; do not use tools."` ha sostituito un marker sentinella con il medesimo payload: **Stop è invocato sia dalla TUI sia da `codex exec`** in questa versione quando l'hook è autorizzato. Non è stato eseguito un turno tramite app-server; la sola precedente `hooks/list` non provava l'invocazione.

Il primo comando Windows diagnostico iniziava con un percorso quotato e la TUI riportava `Hook failed: hook exited with code 1`. La forma `python C:\...\marker.py` ha funzionato. L'hook era dunque autorizzato ma non eseguibile con la prima forma di comando; la distinzione è rilevante per l'adapter Windows.

## Prototipo AgentHarness nella TUI

Nel repository temporaneo, `pyproject.toml` è stato committato come baseline e poi modificato senza commit. `agentharness enable --project ...` ha impostato `enabled: true`; lo stato risultava `profile: balanced`, `automatic_checks: false`, `llm_calls: false`. Il comando Windows dell'hook, revisionato nuovamente in `/hooks`, era:

```text
C:\AgentAi\AgentHarness\.venv\Scripts\python.exe -m agentharness host-event --host codex --project C:\AgentAi\AgentHarness\m2_hook_probe
```

Nel primo turno TUI (`Reply exactly FIRST; do not use tools.`), l'interfaccia ha mostrato il messaggio effettivo:

```text
↳ Hook · AgentHarness: modificati pyproject.toml. Valuta un controllo mirato prima del rilascio.
```

Lo stato `.agentharness/host-prototype.json` conteneva un fingerprint. In due turni successivi, senza modifiche al file, il fingerprint e il timestamp dello stato sono rimasti identici; dopo il terzo turno il timestamp UTC era ancora `639296473528635071` tick. La TUI ridisegna la cronologia, quindi il testo del primo warning può comparire di nuovo nell'output del terminale senza rappresentare un nuovo warning del turno. Nessun nuovo messaggio è stato osservato dopo `THIRD`.

`agentharness disable --project ...` ha restituito stato `enabled: false`. Nel turno TUI successivo (`Reply exactly DISABLED; do not use tools.`), la TUI ha ancora eseguito il **processo hook** (`Running hook`), ma non ha mostrato alcun nuovo `AgentHarness:` e non ha riscritto il fingerprint. Un'invocazione diretta successiva con il medesimo payload `Stop` ha restituito `{}` e il timestamp dello stato è rimasto `639296473528635071` tick UTC. `disable` sopprime l'intervento AgentHarness; non disinstalla o disabilita l'hook presso l'host. Questo comporta il costo di avvio del comando hook anche da disabilitato. `agentharness status --json` riporta `host_adapter_installed: false` perché M1 non rileva installazioni host manuali: non va interpretato come inventario degli hook Codex.

## Esito e limiti

| Stato | Evidenza |
| --- | --- |
| Hook configurato | `.codex/hooks.json` di progetto, voce `Stop` visibile in `/hooks`. |
| Hook autorizzato | `/hooks`: `Active 1`, `Trusted` dopo revisione della definizione. |
| Hook invocato | Marker con `event: Stop` prodotto dalla TUI e da `codex exec`. |
| Messaggio ricevuto | Warning `↳ Hook · AgentHarness: ...` osservato nella TUI. L'output JSON di `codex exec` non ha mostrato il warning, pur invocando l'hook. |
| Dopo `disable` | Hook ancora avviato; nessun nuovo suggerimento AgentHarness nel turno osservato. |

La prova non misura i token aggiunti al contesto del modello: `systemMessage` è un warning UI documentato. Non sono stati acquisiti transcript o payload completi, per evitare dati personali; il marker conserva solo i tre campi riportati sopra. Nessun test, scansione o chiamata LLM è stata lanciata dall'hook. Questa prova non autorizza ancora packaging degli adapter, Autopilot completo o merge M2. Il checkpoint successivo può definire il flusso opt-in di installazione/rimozione e una misura separata della latenza con hook reale.
