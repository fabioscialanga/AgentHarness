# Mini-pilot esplorativo actionable repair — freeze pre-dati 2026-07-27

## Stato e scopo

Questo documento congela, prima della raccolta, `exploratory_actionable_repair_v1`. È un pilot esplorativo e non confirmatory. Con quattro sole coppie non autorizza inferenze forti, test d'ipotesi confermativi, intervalli di confidenza interpretati come evidenza definitiva o claim di efficacia.

Il pilot verifica operabilità, consegna del treatment, accounting del nuovo actionable repair loop, mantenimento/rollback delle riparazioni e presenza di un eventuale segnale direzionale.

Manifest normativo: `EXPLORATORY_ACTIONABLE_REPAIR_V1_2026-07-27.json`.

## Disegno congelato

Quattro task, un blocco appaiato A/B per task, otto celle:

1. `p001` — `pii-redaction-pipeline` — A, B
2. `p002` — `lease-coordination-api` — B, A
3. `p003` — `double-entry-ledger-api` — A, B
4. `p004` — `signed-artifact-verifier` — B, A

L'ordine è deterministico; due blocchi iniziano con A e due con B. Ogni task compare una volta e ogni blocco contiene esattamente una cella `A-baseline` e una `B-agentharness`.

Runtime congelato: provider `openai-codex`, modello `gpt-5.6-sol`, comando `/home/fabio/.local/bin/stage2codex2`, `HERMES_HOME=/home/fabio/.hermes/profiles/stage2codex2`, toolsets `terminal,file`, `max_turns=40`. Il runner usa `prepare_fresh_cell` ed `execute_cell`; non riusa e non modifica il runner/freeze storico Stage 2.

Prima di ogni cella il runner interroga la finestra quota dell'account fissato. Richiede esattamente una finestra autorevole, si mette in pausa fail-closed se la telemetria non è disponibile e non avvia nuove invocazioni quando l'uso raggiunge l'80%. Fallback di provider e crediti acquistati sono vietati.

## Preflight, distruzione e provenienza

Prima di qualunque riconciliazione distruttiva o chiamata a `prepare_fresh_cell`, il runner:

- verifica manifest normativo, hash canonico del payload e hash dei file congelati;
- verifica forma, pairing e controbilanciamento;
- valida tutte e quattro le suite heldout (sei casi ciascuna) e l'eseguibilità degli entry point `evaluate` e `benchmark-evaluate-task`;
- verifica wrapper Hermes e relativo hash;
- richiede il `HERMES_HOME` congelato;
- richiede repository pulito e `HEAD` identico al ref pubblicato congelato;
- richiede un run root esterno al repository.

Quindi i nuovi file devono essere revisionati, committati e pubblicati sul ref indicato dal manifest prima di una raccolta reale. Questa freeze non autorizza invocazioni durante sviluppo o test.

## Cecità, resume e simmetria

Durante la raccolta stdout contiene esclusivamente stato e contatori strutturali oppure la classe di invalidità. Score, outcome, differenze A/B e metriche di repair non vengono stampati. Gli outcome sono conservati soltanto in `progress.private.json` e negli artefatti privati delle celle, con permessi 0600.

Il progresso pubblico-operativo è ricostruito solo da blocchi pair-complete. Una cella interrotta resta privata ed è spostata in quarantena solo alla ripresa, dopo un nuovo preflight completo. Le celle già committate sono riusate senza invocazione. Una raccolta è completa solo con quattro coppie esatte A/B.

Il runner si interrompe immediatamente con exit code distinto su `quota_pause`, `provider_unavailable` o `treatment_not_delivered`. Alla ripresa l'artefatto incompleto è preservato in quarantena e la cella viene ricreata; i suoi tentativi restano inclusi nel proxy di costo. Non si produce contrasto da dati incompleti.

Al completamento vengono prodotti progress privato e audit finale con hash, completezza delle coppie e autorizzazione all'analisi. Il contrasto diventa disponibile esclusivamente tramite il flag esplicito `--finalize`; il finalizer rifiuta stato, audit, hash o shape incompleti.

## Metriche congelate

Primaria: score heldout appaiato `B-agentharness - A-baseline`, separatamente per ciascun task, e media descrittiva delle quattro differenze.

Secondarie descrittive:

- in B: adozione (`repair_response_valid`) e accounting (`feedback_items_accounted`);
- in B: feedback post-repair supported e unresolved;
- su tutte le celle: repair change retained e rollback;
- durata totale delle invocazioni e numero di invocazioni come proxy di costo, includendo tentativi in quarantena.

## Regola del verdetto, congelata pre-dati

Siano i quattro delta heldout appaiati `B-A`:

- `directional_signal_positive`: almeno tre delta sono strettamente positivi e la loro media è strettamente positiva;
- `no_directional_signal`: almeno tre delta sono non positivi e la loro media è non positiva;
- `mixed_or_inconclusive`: ogni altro pattern completo e valido.

Queste sono le sole etichette ammesse. Anche `directional_signal_positive` indica esclusivamente un segnale esplorativo da sottoporre a uno studio successivo adeguatamente dimensionato.

## Uso operativo (non eseguire durante la preparazione)

Preflight:

    HERMES_HOME=/home/fabio/.hermes/profiles/stage2codex2 \
      python benchmarks/grading-env/run_exploratory_actionable_repair_v1.py \
      --run-root /percorso/esterno --preflight

Raccolta/resume: stesso comando senza `--preflight`.

Finalizzazione esplicita, solo dopo completezza:

    python benchmarks/grading-env/run_exploratory_actionable_repair_v1.py \
      --run-root /percorso/esterno --finalize
