# Documentazione dell'esempio CivicTrack

## 1. Che cos'è l'esempio

CivicTrack è una web API open source fittizia ma realistica usata per dimostrare come possono essere scritte definizioni di progetto nello stile AgentHarness.

Non è un'applicazione pronta per la produzione. È un esempio ragionato progettato per mostrare come un repository possa codificare:
- intento di progetto
- vincoli tecnici
- aspettative di qualità
- regole di sicurezza
- confini operativi per gli agenti
- workflow riusabili

## 2. Sintesi del prodotto

CivicTrack è una piattaforma leggera per raccogliere e tracciare segnalazioni civiche.

Il suo scopo è aiutare cittadini e operatori locali a gestire segnalazioni come:
- buche
- illuminazione guasta
- rifiuti abbandonati
- problemi di manutenzione di quartiere

Lo scope della V1 è intenzionalmente ristretto:
- ricevere segnalazioni
- validarle
- assegnarle
- tracciare i cambi di stato
- mantenere un audit trail
- notificare facoltativamente gli stakeholder

## 3. Il problema che risolve

Piccoli comuni e organizzazioni civiche spesso gestiscono le segnalazioni tramite email, fogli di calcolo o messaggistica informale.

Questo crea:
- perdita di informazioni
- responsabilità poco chiare
- bassa accountability
- reporting debole
- follow-up incoerente

CivicTrack è pensato come base semplice, self-hostable e auditabile per rendere questo flusso visibile e gestibile.

## 4. Utenti principali

L'esempio identifica quattro gruppi principali di utenti:
- cittadini che inviano segnalazioni
- operatori comunali o civici che gestiscono i ticket
- coordinatori di area che assegnano e chiudono il lavoro
- amministratori tecnici che gestiscono configurazione e sicurezza

## 5. Workflow chiave

Il flusso canonico descritto nell'esempio è:
1. Un cittadino invia una segnalazione con descrizione, categoria, posizione e foto opzionale.
2. Il sistema valida i campi minimi richiesti.
3. La segnalazione entra nello stato `new`.
4. Un operatore assegna il problema a un team o a un responsabile.
5. Il responsabile fa avanzare la segnalazione tra stati come `in_review`, `in_progress`, `resolved` e `closed`.
6. Il cittadino riceve aggiornamenti di stato quando è disponibile un canale di notifica.
7. Il sistema mantiene una cronologia eventi e un audit trail.

## 6. Non-obiettivi espliciti della V1

L'esempio esclude volutamente:
- GIS avanzato
- routing basato su AI
- integrazioni con ERP o protocolli comunali
- app mobile native
- analytics avanzata per grandi enti

Questo è utile perché mostra come i limiti di scope debbano essere codificati fin dall'inizio.

## 7. Profilo tecnico

La config strutturata descrive uno stack API Python semplice:
- linguaggio: Python
- framework: FastAPI
- database: PostgreSQL
- package manager: uv
- ORM: SQLModel
- stile API: REST

I moduli definiti sono:
- api
- domain
- validation
- notifications
- persistence
- audit

I servizi esterni opzionali sono:
- SMTP
- webhook

## 8. Modello di governance

L'esempio usa un modello di autonomia media.

Gli agenti possono:
- ispezionare file
- proporre modifiche a scope limitato
- implementare feature isolate
- aggiungere o aggiornare test
- eseguire controlli locali

Gli agenti non possono in autonomia:
- cambiare il comportamento di autenticazione
- indebolire le regole di validazione
- alterare i vincoli di sicurezza sugli upload
- rimuovere copertura di audit
- modificare comportamento di CI o release senza review

La review umana è richiesta esplicitamente per aree ad alto rischio come:
- cambiamenti di auth
- cambiamenti di dipendenze
- cambiamenti della pipeline CI
- cambiamenti nella gestione upload
- cambiamenti del modello di audit

## 9. Aspettative di qualità

L'esempio rende i quality gate centrali.

I controlli richiesti includono:
- formattazione
- lint
- type checking
- unit test
- assenza di segreti hardcoded

Per i bug fix è atteso un regression test quando tecnicamente fattibile.

La definition of done richiede inoltre:
- scope delimitato
- test aggiornati quando rilevante
- considerazione degli edge case
- rispetto dei requisiti di review
- un execution summary

## 10. Postura di sicurezza

L'esempio codifica un livello di sicurezza medio e assume che possano essere presenti dati personali.

I vincoli importanti includono:
- i segreti devono arrivare da environment variables
- i file caricati devono essere validati
- i cambiamenti alle dipendenze devono essere controllati
- la validazione input è obbligatoria
- il logging deve essere sicuro rispetto ai dati personali

Questo è utile perché dimostra che la policy di sicurezza appartiene alla definizione del progetto, non solo a note implementative successive.

## 11. Perché questo esempio conta per AgentHarness

CivicTrack è importante perché trasforma un'idea astratta di framework in una forma concreta di repository.

Dimostra come un progetto possa esprimere:
- scopo leggibile da umani
- vincoli machine-readable
- istruzioni operative per agenti
- checklist per umani e macchine
- confini di autonomia e review

Senza un esempio così, AgentHarness resterebbe troppo concettuale.

## 12. File da leggere per primi

Per capire rapidamente l'esempio, conviene partire da:
- `examples/civictrack/PROJECT.md`
- `examples/civictrack/project.yaml`
- `examples/civictrack/AGENTS.md`
- `examples/civictrack/docs/ARCHITECTURE_SUMMARY.md`
- `examples/civictrack/docs/DELIVERY_MODEL.md`

## 13. Riassunto in una frase

CivicTrack è il primo esempio concreto che mostra come AgentHarness possa codificare intento di progetto, governance e workflow di ingegneria in una struttura riusabile.
