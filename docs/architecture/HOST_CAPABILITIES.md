# M2 — capacità degli host (ricerca del 7 novembre 2026)

Fonti primarie: [Claude hooks](https://code.claude.com/docs/en/hooks), [Claude skills](https://code.claude.com/docs/en/skills), [Claude commands](https://code.claude.com/docs/en/commands), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [Codex custom prompts](https://learn.chatgpt.com/docs/custom-prompts), [Codex customization](https://learn.chatgpt.com/docs/customization/overview#skills), [Codex app-server](https://learn.chatgpt.com/docs/app-server). Le pagine descrivono capacità documentate, non una prova end-to-end dell'installazione locale.

Ambiente locale verificato: `codex-cli 0.154.0` tramite `codex.cmd --version`; `claude` non è nel PATH. Gli hook di entrambi gli host non sono stati installati o eseguiti in una sessione reale in questo prototipo.

| Capacità | Claude Code | Codex | Conseguenza per AgentHarness |
| --- | --- | --- | --- |
| Evento di fine turno | Hook `Stop`, con `stop_hook_active`; `systemMessage` è una notifica all'utente. | Hook `Stop`, con `stop_hook_active`; output JSON e `systemMessage` come warning UI/event stream. | Un solo evento condiviso è fattibile; usare un messaggio non bloccante e non continuare il turno. |
| Altri eventi | Hook per sessione, prompt, tool e altro. | Hook per sessione, prompt, tool, model request e altro. | Rinviare gli eventi frequenti; `Stop` limita invocazioni e overhead. |
| Installazione hook | Configurazione settings/hooks di progetto o utente. | `.codex/hooks.json` o `[hooks]` in config; trust review per hook non gestiti. | L'installazione richiede passaggi specifici per host; `enable` M1 non installa nulla. |
| Comando utente | Skill di progetto `.claude/skills/agentharness/SKILL.md` invocabile con `/agentharness`. | Skill di progetto `.agents/skills/agentharness/SKILL.md`, invocazione esplicita secondo la UI; vecchi custom prompt espongono `/prompts:agentharness` ma sono deprecati. | Non promettere `/agentharness enabled` identico nei due host. La CLI `agentharness enable|disable|status` resta il contratto certo. |
| Funzioni native | Skills, hook, subagent, permessi, comandi di review/test disponibili a seconda della configurazione. | Skills, hook, app-server, sandbox/approvazioni, review e strumenti di coding. | Usare gli host per eseguire lavoro e controlli richiesti; AgentHarness decide solo quando suggerirli e verifica evidenze con il motore esistente. |
| API profonda | Agent SDK e hook documentati. | App-server JSON-RPC con eventi di thread, turn e tool; SDK per automazioni. | Evitare un client app-server in M2: richiederebbe processo/connessione e duplicazione del loop host. |

## Semantica dell'esperienza desiderata

- Claude Code può offrire una skill `/agentharness enabled|disabled|status` che delega ai comandi CLI; è un'interfaccia esplicita, non la sorgente dello stato.
- Codex può offrire una skill esplicita, ma la documentazione non garantisce che il nome appaia come `/agentharness`. I custom prompt slash sono deprecati e usano `/prompts:...`; non sono una base durevole per il contratto.
- Gli hook sono opt-in e soggetti alla trust review dell'host. `agentharness enable` da solo non equivale a installarli o abilitarli.
- Il prototipo non assume che una skill intercetti eventi continui. L'eventuale Engineering Advisor LLM resta fuori da questa fase.

## Limiti delle prove

Versione locale Claude Code non verificata perché l'eseguibile non è installato. Per Codex è verificata la versione CLI, ma il comportamento di hook del build locale non è stato provato con una sessione reale. Le capacità di desktop, IDE, cloud e configurazioni gestite possono differire dalle CLI locali. L'output `systemMessage` è documentato come UI/event warning; il suo costo in token in una sessione concreta resta non misurato.
