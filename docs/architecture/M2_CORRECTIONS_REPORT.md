# M2 — correzioni dopo la revisione architetturale

Data: 7 novembre 2026. Branch: `feat/m2-host-prototype`. Questa fase resta un prototipo opt-in; nessun hook è installato dal pacchetto.

## Correzioni e comportamento osservabile

- Il fingerprint accetta solo `pyproject.toml`, `SECURITY.md` e file direttamente in `.github/workflows/`. Rifiuta percorsi assoluti, componenti `..` o `.`, backslash, NUL e risoluzioni fuori dal progetto. Legge file regolari in blocchi, con limite di 1 MiB per file. File illeggibili, troppo grandi, sostituiti da symlink o rimossi durante la lettura producono `{}`. Su Windows, l'assenza di `O_NOFOLLOW` lascia una finestra di race tra controllo del symlink e apertura; l'uso futuro in ambienti ostili richiede un'apertura sicura specifica della piattaforma.
- Lo stato di deduplicazione viene scritto con file temporaneo e `os.replace`. Un lock di directory creato atomicamente serializza le invocazioni concorrenti; se esiste, l'invocazione successiva tace. Un lock oltre 10 secondi viene considerato obsoleto. La rimozione di un lock obsoleto mentre il proprietario è ancora attivo può causare un doppio messaggio: è un limite residuo, non una garanzia distribuita. Errori di lock o scrittura producono `{}`. Il comando CLI intercetta anche eccezioni inattese e risponde con `{}` e codice 0.
- Git usa `git diff --name-only HEAD` sui percorsi osservati, timeout 2 secondi. Una modifica staged è rilevata; un file non tracciato e una modifica già committata non lo sono. Una modifica unstaged a un file tracciato è rilevata. Strategia futura: confrontare l'ultimo commit visto e lo stato di index/worktree, interrogando Git solo sull'evento host e mantenendo un cursore locale; nessun watcher o polling.
- Dopo `disable`, `handle_stop` torna prima di Git. Una seconda lettura dello stato prima di emettere il messaggio riduce la race con `disable`. Una disabilitazione simultanea esattamente dopo la seconda lettura resta una race residua: l'hook non è un sistema transazionale. Nessuna verifica o scansione viene lanciata automaticamente.

## Contratto host e prova Codex

Le [specifiche Codex degli hook](https://learn.chatgpt.com/docs/hooks) descrivono `Stop`, payload JSON con `stop_hook_active`, risposta JSON su stdout e `systemMessage` come avviso UI. La prova locale ha usato `codex-cli 0.154.0`, un repository Git temporaneo e un override di sessione per l'hook; nessuna impostazione globale è stata modificata. `hooks/list` dell'app-server ha elencato l'hook `Stop` con sorgente `sessionFlags`, `enabled: true`, `trustStatus: untrusted`. Tre turni `codex exec` con modello disponibile `gpt-5.6-luna` si sono completati, ma il file di prova dell'hook non è stato creato. Un tentativo con la TUI non ha prodotto evidenza di invocazione. Perciò l'esecuzione end-to-end dell'hook Codex è **NON VERIFICATA** e l'adapter non è pronto per l'installazione. Il primo tentativo `codex exec` con il modello predefinito dell'ambiente è fallito per indisponibilità del modello per l'account, non per AgentHarness. Claude Code non è installato: **NON VERIFICATO**.

## Test e misure

Nel virtualenv Windows Python 3.12 con dipendenze installate: `python -m pytest -q tests/test_host_prototype.py tests/test_foundation.py` ha dato **32 passed**, exit 0. La regressione core Windows ha dato **116 passed, 4 failed**: i fallimenti sono in test esistenti che assumono percorsi Unix o separatori `/`. La prima prova Linux in `python:3.12-slim` ha dato **112 passed, 8 failed**; l'immagine non conteneva `git` e la copia della working tree Windows ha alterato i file dell'esempio. La ripetizione da clone Git pulito, in `python:3.12` con Git e dipendenze installate, ha dato **120 passed in 21,10 s**, exit 0, sui nove moduli core della CI più `test_host_prototype.py`. I benchmark/Stage 2 sono **NOT RUN** in questa fase.

30 invocazioni complete di `python -m agentharness host-event --host codex` nel repository temporaneo Windows, stato abilitato e una modifica significativa: **p50 281,71 ms, p95 504,50 ms, massimo 553,15 ms**, un `systemMessage` e 29 risposte vuote. Sono misure del processo hook, non della latenza interna del turno Codex. Il prototipo non invoca LLM e invoca Git al massimo una volta per evento abilitato; l'host ha usato il proprio modello nelle prove reali. Token aggiunti da `systemMessage` nel contesto Codex: **NON MISURATI**, perché l'hook non è stato osservato in esecuzione.

## Checkpoint

Richiedere una prova reale del trust e dell'invocazione `Stop` su Codex, poi una prova separata su Claude Code, prima del packaging degli adapter o dell'Autopilot completo. Nessun merge M2.
