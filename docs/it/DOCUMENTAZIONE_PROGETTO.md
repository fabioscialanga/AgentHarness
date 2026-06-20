# Documentazione di progetto di AgentHarness

## 1. Scopo

AgentHarness è un concetto di framework per trasformare l'intento di progetto in esecuzione controllata di agenti.

L'obiettivo non è creare un altro coding assistant. L'obiettivo è fornire il livello operativo attorno agli agenti AI, in modo che i team di ingegneria possano usarli con vincoli espliciti, confini di review e regole di verifica.

In sintesi:
- entra la definizione del progetto
- viene generato il contesto operativo
- gli agenti lavorano dentro regole delimitate
- gli output vengono verificati rispetto a qualità e sicurezza

## 2. Il problema che vuole risolvere

Molti team che sperimentano con lo sviluppo assistito da AI fanno sempre lo stesso errore: si concentrano sul modello e investono troppo poco nel sistema operativo attorno al modello.

I fallimenti tipici sono:
- contesto di progetto vago
- istruzioni incoerenti tra task diversi
- limiti di autonomia poco chiari
- disciplina di test debole
- controlli di sicurezza scarsi
- assenza di gate di review espliciti
- mancanza di template operativi riusabili

AgentHarness affronta questo problema rendendo il progetto più interpretabile dalla macchina senza perdere il controllo umano.

## 3. Tesi centrale

Un modello capace da solo non basta per consegne software affidabili.

Conta soprattutto l'harness attorno al modello:
- contesto strutturato
- strumenti consentiti
- azioni proibite
- template di workflow
- quality gate
- checkpoint di review
- regole di progetto tracciabili

AgentHarness si concentra nel formalizzare questo harness.

## 4. Che cos'è AgentHarness

AgentHarness vuole essere:
- un layer di definizione progetto per l'ingegneria assistita da AI
- un sistema di bootstrap per contesto agente riusabile
- un repository di regole di progetto e vincoli di esecuzione
- un modo per standardizzare workflow ricorrenti di ingegneria
- un ponte tra intenzione umana ed esecuzione agente delimitata

## 5. Che cosa non è

AgentHarness non è:
- un provider di modelli
- un sostituto del giudizio ingegneristico
- una garanzia di correttezza
- solo una libreria di prompt
- solo un generatore di scaffolding
- una software factory completamente autonoma

Il design assume che la review umana resti necessaria per i cambiamenti importanti.

## 6. Modello operativo

Il modello operativo parte da artefatti di progetto espliciti e li trasforma in guida di esecuzione per agenti.

Flusso tipico:
1. Un team definisce il progetto in forma leggibile per umani.
2. Lo stesso progetto viene catturato anche in forma strutturata e machine-readable.
3. File di governance definiscono autonomia, review, sicurezza e regole di test.
4. Template di workflow definiscono come eseguire task comuni.
5. Gli agenti operano dentro quei vincoli.
6. Gli umani revisionano il lavoro secondo il livello di rischio dichiarato.

## 7. Building block principali del repository

### `PROJECT.md`
Intento di progetto leggibile da umani.

Spiega:
- obiettivo del prodotto
- utenti
- use case
- limiti di scope
- vincoli tecnici
- vincoli business
- rischi
- convenzioni del team

### `project.yaml`
Definizione di progetto machine-readable.

Contiene informazioni strutturate come:
- tipo di progetto
- stack
- moduli
- servizi esterni
- requisiti di test
- quality gate
- regole di sicurezza
- policy agente
- deliverable generati

### `AGENTS.md`
Regole per gli agenti che operano nel repository.

Contenuti tipici:
- confini di coding
- limiti di rischio
- aree che richiedono review umana
- comportamento minimo di validazione
- criteri minimi di completamento

### `workflows/`
Template riusabili per task ricorrenti di ingegneria.

Esempi:
- creare una feature
- correggere un bug
- rifattorizzare un modulo
- aggiungere test

### `checklists/`
Criteri di completamento leggibili sia da umani sia da agenti.

Esempi:
- definition of done
- standard di testing
- security review
- checklist di AI code review

### `policies/`
File di governance orientati alla macchina.

Definiscono vincoli come:
- livelli di autonomia
- controlli obbligatori
- gestione dei segreti
- regole sulle dipendenze
- requisiti di review

### `.framework/`
Area riservata a metadata generati e output del framework.

Esempi possibili:
- dati di progetto normalizzati
- matrici di rischio
- mappe dipendenze
- input generati per i task
- riassunti di verifica

## 8. Struttura del repository

Struttura attuale del repository:
- `README.md` — panoramica di alto livello
- `docs/en/` — documentazione in inglese
- `docs/it/` — documentazione in italiano
- `examples/civictrack/` — esempio concreto che mostra lo stile del framework

Dentro `examples/civictrack/` trovi:
- `PROJECT.md`
- `project.yaml`
- `AGENTS.md`
- `docs/`
- `workflows/`
- `checklists/`
- `policies/`
- `tests/`
- `.framework/`

## 9. L'esempio CivicTrack

Il primo esempio in questo repository è CivicTrack, una API open source fittizia ma credibile per la raccolta e gestione di segnalazioni civiche.

Serve a dimostrare in pratica come possono essere costruiti input e policy nello stile AgentHarness.

CivicTrack mostra:
- come scrivere un project brief
- come una config strutturata può codificare stack e vincoli
- come rendere esplicite le regole per gli agenti
- come standardizzare i workflow di task
- come rappresentare testing e sicurezza fin dal primo giorno

È intenzionalmente un progetto di esempio, non un prodotto pronto.

## 10. Livello di maturità attuale

Questo repository è in fase di bootstrap.

Significa che:
- la direzione concettuale è definita
- la forma iniziale del repository esiste
- è presente un esempio concreto
- il motore vero e proprio del framework non è ancora costruito

Questa è al tempo stesso una forza e un limite.

Forza:
- il repository esprime già una filosofia coerente
- l'esempio rende l'idea concreta

Limite:
- non esistono ancora validator, generator, CLI o runtime esecutivo
- gran parte del valore è ancora codificata come documentazione e struttura di progetto

## 11. Roadmap di breve periodo

Prossimi passi consigliati:
1. Definire lo schema canonico di `project.yaml`.
2. Aggiungere regole di validazione e controlli di schema.
3. Definire il contratto di generazione per gli output del framework.
4. Decidere quali artefatti sono scritti a mano e quali generati automaticamente.
5. Aggiungere un piccolo validator o una CLI di bootstrap.
6. Aggiungere altri esempi con profili di rischio diversi.
7. Dimostrare che il framework migliora la coerenza, non solo la qualità della documentazione.

## 12. Per chi è pensato

AgentHarness è soprattutto rilevante per:
- team di ingegneria che adottano sviluppo assistito da AI
- organizzazioni che vogliono più governance attorno agli agenti
- team che cercano workflow ripetibili invece di prompting ad hoc
- progetti in cui test, sicurezza e disciplina di review contano davvero

È meno utile per:
- prototipi usa-e-getta
- team non disposti a mantenere metadata di progetto
- contesti in cui non esiste nessun modello di review

## 13. Principi di design

Il repository esprime attualmente questi principi:
- l'esplicito batte l'implicito
- i vincoli fanno parte dell'enablement, non dell'attrito
- test e sicurezza appartengono al modello operativo
- l'autonomia deve essere delimitata dal rischio
- gli esempi devono essere abbastanza concreti da essere riusabili
- la review umana resta necessaria quando il rischio è significativo

## 14. Valore pratico atteso

Se sviluppato bene, AgentHarness potrebbe aiutare le aziende a:
- ridurre l'ambiguità nei task assistiti da AI
- rendere il comportamento degli agenti più prevedibile
- migliorare la coerenza del lavoro ingegneristico
- ridurre la probabilità di modifiche insicure o di bassa qualità
- passare dall'improvvisazione via prompt a un'esecuzione governata

## 15. Limiti attuali e domande aperte

Le domande ancora aperte più importanti sono:
- Qual è lo schema minimo che resta davvero utile?
- Quali output devono essere generati automaticamente?
- Quanto deve essere rigida l'enforcement delle policy?
- In pratica, come consumeranno questi file gli agenti?
- Come standardizzare la verifica tra stack diversi?
- Come evitare che il framework diventi solo overhead documentale?

Non sono difetti da nascondere. Sono le vere domande di prodotto da risolvere adesso.

## 16. Riassunto in una frase

AgentHarness è un tentativo di trasformare la specifica di progetto in esecuzione agente delimitata, revisionabile e ripetibile.
