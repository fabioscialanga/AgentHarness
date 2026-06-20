# CivicTrack

## Scopo del progetto
CivicTrack è una piattaforma open source per la raccolta e gestione di segnalazioni civiche. Permette a cittadini e operatori di registrare problemi sul territorio, seguirne lo stato e mantenere una cronologia trasparente delle attività svolte.

## Problema che risolve
Molti piccoli enti locali e organizzazioni civiche gestiscono le segnalazioni tramite email, fogli Excel o messaggi informali. Questo produce:
- perdita di informazioni
- assegnazioni poco chiare
- nessuna audit trail
- tempi di risposta opachi
- difficile reporting operativo

CivicTrack vuole offrire una base leggera e open source per rendere questo processo tracciabile e verificabile.

## Utenti principali
- cittadini che inviano segnalazioni
- operatori comunali o associativi che prendono in carico i ticket
- coordinatori di area che assegnano e chiudono le attività
- amministratori tecnici che gestiscono configurazione e sicurezza

## Use case chiave
1. Un cittadino invia una segnalazione con descrizione, categoria, posizione e foto opzionale.
2. Il sistema valida i dati minimi richiesti.
3. La segnalazione entra in uno stato iniziale `new`.
4. Un operatore la assegna a un team o a un responsabile.
5. Il responsabile aggiorna lo stato: `in_review`, `in_progress`, `resolved`, `closed`.
6. Il cittadino riceve aggiornamenti sullo stato, se il canale di notifica è disponibile.
7. Il sistema mantiene audit trail e cronologia eventi.

## Non-obiettivi della V1
- GIS avanzato
- routing automatico basato su AI
- integrazione con sistemi ERP o protocolli comunali
- mobile app nativa
- analytics avanzata per grandi enti

## Vincoli tecnici
- backend Python con FastAPI
- database PostgreSQL
- autenticazione admin/operatori via account locali nella V1
- segreti solo via environment variables
- upload file con validazione tipo e dimensione
- API documentata con OpenAPI

## Vincoli di business / prodotto
- il progetto deve restare semplice da deployare anche da piccoli team
- la V1 deve poter girare in self-hosting senza infrastruttura complessa
- l'interfaccia API deve rimanere stabile e leggibile
- le funzionalità devono privilegiare affidabilità e auditabilità rispetto alla ricchezza funzionale

## Architettura desiderata
Componenti principali:
- API service per creazione e gestione segnalazioni
- modulo validation per input e regole di stato
- modulo notifications per invio email/webhook in forma astratta
- persistence layer per ticket, utenti, eventi e allegati metadata
- audit module per cronologia modifiche e attori

## Rischi noti
- validazione insufficiente degli input utente
- allegati malevoli o troppo pesanti
- gestione non sicura di dati personali di contatto
- transizioni di stato incoerenti
- scarsa copertura test su workflow principali

## Convenzioni del team
- funzioni piccole e leggibili
- nessuna logica business nascosta nei controller HTTP
- nomi espliciti, niente abbreviazioni ambigue
- ogni bug fix deve lasciare almeno un regression test
- nuove dipendenze vanno motivate
- modifiche a auth, upload o audit richiedono review umana

## Definizione sintetica di “fatto bene”
Una modifica è fatta bene quando:
- è limitata al perimetro necessario
- è testata
- non introduce regressioni evidenti
- rispetta sicurezza base e policy segreti
- lascia un comportamento leggibile anche per chi entra dopo nel progetto
