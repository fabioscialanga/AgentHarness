# Benchmark A/B: con AgentHarness vs senza framework

## Perché esiste
Se AgentHarness vuole essere un framework serio, deve superare un test semplice ma duro:

stesso progetto,
stesse specifiche iniziali,
stesso agente,
due modalità diverse:
- senza framework
- con AgentHarness

Questo benchmark serve a capire se il framework produce davvero un miglioramento operativo oppure solo più struttura.

## Cosa contiene il benchmark pack
Il benchmark pratico si trova in:
- `benchmarks/support-ticket-api/SPEC.md`
- `benchmarks/support-ticket-api/RUN_PROTOCOL.md`
- `benchmarks/support-ticket-api/SCORECARD.md`

## Caso di test scelto
Il progetto scelto è una piccola API interna di support ticket.

Perché è una buona prova:
- non è banale come una toy app
- è abbastanza piccola da essere completata in una sessione focalizzata
- è abbastanza ricca da far emergere differenze su:
  - chiarezza
  - validazione
  - test
  - vincoli di business
  - reviewabilità

## Come eseguire il benchmark
### Scenario A — senza framework
Usa solo:
- la specifica iniziale del progetto
- istruzioni minime
- stessi tool e stesso ambiente

Non usare:
- `PROJECT.md`
- `project.yaml`
- policies
- workflow template
- checklist
- output `.framework`

### Scenario B — con AgentHarness
Usa la stessa specifica di base, ma all'interno del flusso AgentHarness:
- bootstrap del progetto
- adattamento di `PROJECT.md`
- aggiornamento di `project.yaml`
- uso di policy/workflow/checklist
- validate/generate
- implementazione dentro il contesto del framework

## Regole di correttezza
Per non falsare il confronto, devi mantenere costanti:
- stessa specifica
- stesso modello/agente
- stesso budget di tempo
- stessa policy di intervento umano
- stessa scorecard finale

## Cosa misurare davvero
Le metriche più importanti non sono solo velocità o quantità di codice.

Misura soprattutto:
- completezza funzionale
- rispetto dei vincoli
- qualità della validazione
- disciplina di test
- chiarezza architetturale
- facilità di review umana
- quantità di cleanup manuale necessario

## Come leggere il risultato
Il benchmark non serve a dimostrare che AgentHarness “vince” sempre.
Serve a rispondere onestamente a questa domanda:

"Il framework migliora abbastanza il risultato da giustificare la sua struttura aggiuntiva?"

Se la risposta è sì, il framework ha sostanza.
Se la risposta è no, va semplificato.

## Criterio di successo
Il risultato con AgentHarness dovrebbe idealmente essere:
- più coerente
- più verificabile
- più aderente ai vincoli
- più facile da revisionare

Non è obbligatorio che sia sempre più veloce.
Il valore potrebbe stare soprattutto nella riduzione del caos e del rework.
