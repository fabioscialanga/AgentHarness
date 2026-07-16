from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "grading-env" / "task-expansion-batch3"
BASE_COMMIT = "6178b855d806687bd09624c43815f2688f82008d"
DATE = "2026-07-16"

PRIOR = {
    "support-ticket-api": "support-ticket state transitions, assignment, filtering, and API persistence",
    "csv-member-import": "CSV normalization, duplicate handling, accepted/rejected rows, and import summaries",
    "incident-escalation-api": "time-based incident escalation and timezone-aware state transitions",
    "inventory-adjustment-api": "transactional inventory adjustments, recount semantics, and stock invariants",
    "leave-request-api": "overlap-aware leave approval and terminal workflow states",
    "refund-approval-api": "threshold-based staged refund authorization",
    "report-export-job": "deterministic filtered report generation, totals, and output formatting",
    "webhook-ingestion-service": "HMAC-authenticated ingestion, idempotency, and event normalization",
    "appointment-booking-api": "resource interval scheduling, conflicts, cancellation, and availability",
    "shipment-event-api": "append-only shipment events, idempotency, ordering, projection, and terminal states",
    "jsonl-event-aggregation": "JSONL validation, UTC normalization, duplicate semantics, rejection, and aggregation",
    "invoice-payment-reconciliation": "decimal invoice/payment matching, cutoff semantics, duplicates, and financial summaries",
    "dependency-impact-planner": "reverse dependency closure, topological levels, cycle rejection, and canonical plans",
    "access-policy-evaluator": "wildcard policy matching, subject/group composition, deny precedence, and temporal validity",
    "versioned-document-api": "optimistic concurrency, JSON Merge Patch, immutable revisions, and historical restore",
    "safe-archive-extraction": "ZIP path and entry safety, normalized collisions, limits, and extraction manifests",
}

TASKS = {
    "signed-artifact-verifier": {
        "interface": "deterministic CLI with manifest, keyring, artifact-root, as-of, and output-report arguments",
        "construct": "offline trust verification combining canonical signed manifests, key validity, exact inventory, and byte integrity",
        "public_interface": {
            "entrypoint": "python -m artifact_verifier.verify --manifest MANIFEST --keyring KEYRING --artifact-root ROOT --as-of RFC3339 --output REPORT",
            "manifest_schema": "exact object: schema_version=1, key_id, valid_from, valid_until, files, signature; IDs match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; signature and sha256 are 64 lowercase hex; size is integer 0..9223372036854775807; files are exact path,size,sha256 objects",
            "keyring_schema": "exact object: schema_version=1, keys; each exact key object is key_id,secret_hex,valid_from,valid_until; key IDs are unique and secret_hex encodes 16..64 bytes",
            "signature_payload": "manifest without signature, UTF-8 JSON with sorted object keys, compact separators, ensure_ascii=false; HMAC-SHA256 lowercase hex",
            "path_rules": "POSIX relative regular-file paths only; reject absolute, empty, dot, dot-dot, backslash, duplicate-normalized, symlink, device, FIFO, and socket entries; directories are not inventory records",
            "inventory_boundary": "all regular files recursively below artifact-root must appear exactly once; output must be outside artifact-root",
            "time_boundary": "each valid_from must precede valid_until; valid_from <= as_of < valid_until for both selected key and manifest; Z or explicit offset required and compared as instants",
            "success_report": "exact object: ok=true,key_id,manifest_sha256,file_count,total_bytes,files; files sorted by path with path,size,sha256",
            "failure": "controlled nonzero exit, diagnostic on stderr, and byte-identical preservation of a pre-existing report",
        },
        "checks": [
            {
                "id": "signed_manifest_authenticity",
                "public_contract": "Select the declared key ID and verify an HMAC-SHA256 signature over the documented canonical manifest payload.",
                "planned_probe": "Exercise valid signing plus altered payload, signature, and unknown-key failures without exposing literal fixtures.",
                "planned_mutant": "accepts an invalid signature",
                "failure_atomicity": "no success report is committed on authentication failure",
                "nearest": "webhook-ingestion-service",
                "difference": "verifies a complete offline artifact-set trust statement and key identity, not an individual inbound webhook request",
            },
            {
                "id": "signed_manifest_inventory",
                "public_contract": "Require a normalized, unique, exact file inventory with no missing, unexpected, absolute, escaping, or ambiguous paths.",
                "planned_probe": "Exercise missing, unexpected, duplicate-normalized, and unsafe inventory entries.",
                "planned_mutant": "ignores unexpected files",
                "failure_atomicity": "inventory rejection preserves any pre-existing report",
                "nearest": "safe-archive-extraction",
                "difference": "audits an already materialized tree against a signed inventory rather than safely extracting archive members",
            },
            {
                "id": "signed_manifest_content_integrity",
                "public_contract": "Verify declared byte size and SHA-256 for every regular file in the exact inventory.",
                "planned_probe": "Exercise same-size content mutation, size mismatch, and non-regular file rejection.",
                "planned_mutant": "skips SHA-256 comparison",
                "failure_atomicity": "integrity rejection writes no replacement success report",
                "nearest": "safe-archive-extraction",
                "difference": "checks authenticity-bound integrity of a complete existing artifact set rather than producing an extraction manifest",
            },
            {
                "id": "signed_manifest_trust_window",
                "public_contract": "Evaluate key and manifest validity intervals only against the required request-supplied RFC3339 as-of instant.",
                "planned_probe": "Exercise inclusive start, exclusive end, expired manifest, inactive key, and malformed timestamps.",
                "planned_mutant": "ignores only the key valid_until boundary",
                "failure_atomicity": "temporal rejection does not replace an existing report",
                "nearest": "access-policy-evaluator",
                "difference": "evaluates cryptographic key and signed-manifest trust windows rather than authorization-rule applicability",
            },
            {
                "id": "signed_manifest_atomic_report",
                "public_contract": "Validate the complete input before atomically committing one deterministic verification report; malformed input and I/O failures preserve prior output.",
                "planned_probe": "Exercise malformed JSON, invalid field types, deterministic pre-commit validation failure, rerun byte stability, staging cleanup, and pre-existing report preservation.",
                "planned_mutant": "writes a partial report before validation completes",
                "failure_atomicity": "complete byte-identical preservation on every controlled failure",
                "nearest": "report-export-job",
                "difference": "the output is a trust verdict committed only after whole-set cryptographic verification, not a business data export",
            },
        ],
    },
    "pii-redaction-pipeline": {
        "interface": "deterministic CLI with input JSON, rule document, secret-key file, and one atomic output-bundle path",
        "construct": "recursive structure-preserving privacy transformation with selector semantics, keyed pseudonymization, and field-level audit",
        "public_interface": {
            "entrypoint": "python -m pii_redactor.redact --input INPUT --rules RULES --key KEY --output-bundle BUNDLE",
            "input_schema": "one UTF-8 JSON object or array root",
            "rules_schema": "exact object schema_version=1,rules; each unique rule is id,selector,action and replacement only for redact",
            "selector_grammar": "non-root RFC6901-style pointer beginning slash; segments use ~0 and ~1 escapes; a whole segment * matches one object key or one existing array index",
            "selector_semantics": "unmatched selectors are valid no-ops; exact segments outrank wildcard segments; equal-specificity rules selecting one path must be identical or the rules document is invalid",
            "actions": "redact replaces any selected JSON value with the rule replacement string; remove deletes the selected object member or array element with array removals applied by descending original index; pseudonymize replaces any selected value with hmac-sha256:HEX over canonical compact sorted-key UTF-8 JSON",
            "key_schema": "exact object secret_hex with a non-empty even-length hexadecimal HMAC key",
            "bundle_schema": "exact object redacted,audit; audit records are exact path,rule_id,selector,action objects sorted by canonical path then rule_id",
            "failure": "controlled nonzero exit and byte-identical preservation of a pre-existing single bundle; staging is same-filesystem and removed after failure",
        },
        "checks": [
            {
                "id": "pii_selector_resolution",
                "public_contract": "Resolve documented JSON-pointer-like exact and wildcard selectors over nested objects and arrays without implicit fuzzy matching.",
                "planned_probe": "Exercise nested objects, arrays, wildcard segments, escaped pointer tokens, and unmatched selectors.",
                "planned_mutant": "treats wildcard selectors as shallow matches",
                "failure_atomicity": "selector-validation failure commits neither output nor audit",
                "nearest": "access-policy-evaluator",
                "difference": "selectors locate fields inside recursive JSON values for transformation, not action/resource strings for authorization",
            },
            {
                "id": "pii_redaction_actions",
                "public_contract": "Apply the documented redact, remove, and HMAC-SHA256 pseudonymize actions with deterministic canonical value encoding.",
                "planned_probe": "Exercise all actions on strings, numbers, booleans, nulls, objects, and arrays according to public type rules.",
                "planned_mutant": "uses unkeyed hashing for pseudonymization",
                "failure_atomicity": "unsupported action/type combinations preserve prior outputs",
                "nearest": "webhook-ingestion-service",
                "difference": "performs keyed privacy transformation over selected data fields rather than authenticating and normalizing events",
            },
            {
                "id": "pii_structure_preservation",
                "public_contract": "Preserve ordering-independent JSON meaning and every non-selected value while applying removals without index drift.",
                "planned_probe": "Exercise adjacent array/object selections, non-selected sentinels, and removal from multiple nesting levels.",
                "planned_mutant": "rebuilds only selected branches and drops unrelated data",
                "failure_atomicity": "input remains immutable and output appears only after full transformation",
                "nearest": "csv-member-import",
                "difference": "preserves arbitrary recursive JSON structure while transforming selected fields, rather than normalizing tabular member rows",
            },
            {
                "id": "pii_rule_precedence",
                "public_contract": "Reject conflicting equal-specificity rules and apply the documented most-specific selector precedence deterministically.",
                "planned_probe": "Exercise exact-over-wildcard precedence, conflicting ties, duplicate rule IDs, and input-order permutations.",
                "planned_mutant": "uses first-rule-wins input order",
                "failure_atomicity": "conflict rejection preserves existing output and audit bundles",
                "nearest": "access-policy-evaluator",
                "difference": "resolves transformation specificity and rejects ambiguous mutations, rather than combining allow/deny decisions",
            },
            {
                "id": "pii_atomic_audit",
                "public_contract": "Atomically commit one deterministic JSON bundle containing the redacted document and a sorted audit with selector, action, and canonical path for every transformed field.",
                "planned_probe": "Exercise exact bundle consistency, rerun byte stability, malformed inputs, staging cleanup, and preservation of a pre-existing bundle.",
                "planned_mutant": "commits a bundle whose audit omits one transformed field",
                "failure_atomicity": "one same-filesystem staging file is renamed over the single output-bundle path only after complete validation",
                "nearest": "jsonl-event-aggregation",
                "difference": "produces a field-level privacy transformation audit over one recursive document, not row rejection and aggregate statistics",
            },
        ],
    },
    "lease-coordination-api": {
        "interface": "FastAPI plus SQLite/SQLAlchemy service with explicit resource, owner, duration, and request-supplied RFC3339 now values",
        "construct": "durable expiring mutual exclusion with monotonic fencing tokens and concurrent stale-holder protection",
        "public_interface": {
            "entrypoint": "lease_api.main:app with SQLite path from LEASE_DB_PATH",
            "acquire": "POST /leases/{resource}/acquire body owner,duration_seconds,now; success 201",
            "renew": "POST /leases/{resource}/renew body owner,fencing_token,duration_seconds,now; success 200",
            "release": "POST /leases/{resource}/release body owner,fencing_token,now; success 200",
            "read": "GET /leases/{resource}?as_of=RFC3339 returns latest generation or 404 if the resource has never had a lease",
            "request_schema": "resource and owner match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; request bodies have exactly the documented fields and reject additional fields",
            "lease_schema": "every successful operation and GET returns an exact resource,owner,fencing_token,acquired_at,expires_at,status object where status is active,expired,or released",
            "time_rules": "now/as_of require Z or explicit offset; duration_seconds is integer 1..86400; expiry=now+duration; each mutating now is not earlier than the latest accepted operation time; GET as_of before the latest generation acquired_at is invalid; released when as_of is at/after release, else expired when as_of is at/after expiry, else active",
            "generation_rules": "first token is 1 per resource; every acquisition after release or expiry increments by one; renew and release never increment; counters survive release, expiry, and process restart",
            "statuses": "unknown resource is 404; malformed/extra fields are 422; active-owner conflict and double release are 409; wrong owner or stale token are 412; all preserve full state",
            "concurrency": "simultaneous acquire operations for one resource must have one durable winner; SQLite busy/lock errors are not valid business responses",
        },
        "checks": [
            {
                "id": "lease_acquire_fencing",
                "public_contract": "Acquire an absent or expired resource lease and issue a persistent strictly increasing fencing token for that resource.",
                "planned_probe": "Exercise first acquisition, expiry takeover, process restart, and monotonic token continuity.",
                "planned_mutant": "fails to persist the next-token counter across a process restart before expiry takeover",
                "failure_atomicity": "failed acquisition creates no lease or token advancement",
                "nearest": "versioned-document-api",
                "difference": "coordinates temporary ownership with fencing across lease generations, rather than versioning document content",
            },
            {
                "id": "lease_concurrent_contention",
                "public_contract": "For concurrent acquisition of the same available resource, commit exactly one owner and reject every loser atomically.",
                "planned_probe": "Launch genuinely concurrent same-resource acquisitions and verify one winner, one durable lease, and one token increment.",
                "planned_mutant": "reports success to a losing barrier-synchronized contender while durable state contains one winner",
                "failure_atomicity": "losers do not mutate owner, expiry, or fencing state",
                "nearest": "appointment-booking-api",
                "difference": "arbitrates one ephemeral ownership lease under simultaneous writers, not interval bookings among scheduled appointments",
            },
            {
                "id": "lease_renewal",
                "public_contract": "Allow only the current unexpired owner with the current fencing token to extend expiry, without issuing a new token.",
                "planned_probe": "Exercise valid renew, wrong owner, stale token, expired lease, and non-increasing expiry.",
                "planned_mutant": "renews based on owner alone and ignores the fencing token",
                "failure_atomicity": "rejected renewals preserve the complete lease row",
                "nearest": "incident-escalation-api",
                "difference": "guards continuation of exclusive ownership using a fencing capability, not escalation transitions based on elapsed incident time",
            },
            {
                "id": "lease_release_reacquire",
                "public_contract": "Allow only the current owner/token to release; a later acquisition receives a higher token and stale holders remain powerless.",
                "planned_probe": "Exercise valid release, stale release, double release, reacquire, and stale operations after reacquisition.",
                "planned_mutant": "accepts a stale token after a newer lease generation exists",
                "failure_atomicity": "invalid release leaves the current generation unchanged",
                "nearest": "shipment-event-api",
                "difference": "uses fencing generations to invalidate stale actors, rather than enforcing append-only domain-event transitions",
            },
            {
                "id": "lease_state_and_failure_atomicity",
                "public_contract": "Expose the current lease deterministically and preserve complete state across malformed, missing, stale, and unknown-resource operations.",
                "planned_probe": "Compare full database-visible state before and after every controlled failure and across process termination.",
                "planned_mutant": "GET reports a released lease generation as active while active and expired generation reads remain correct",
                "failure_atomicity": "all rejected operations preserve complete durable state",
                "nearest": "versioned-document-api",
                "difference": "audits lease ownership and fencing state under temporal operations, not immutable content revision history",
            },
        ],
    },
    "double-entry-ledger-api": {
        "interface": "FastAPI plus SQLite/SQLAlchemy service for accounts, transactions, entries, balances, and reversals using exact decimal strings",
        "construct": "immutable balanced double-entry posting with idempotency, derived balances, and compensating reversal",
        "public_interface": {
            "entrypoint": "ledger_api.main:app with SQLite path from LEDGER_DB_PATH",
            "accounts": "POST /accounts body exact id,currency returns 201 exact id,currency; GET /accounts/{id} returns the same exact object; IDs match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; no account update or delete route",
            "posting": "POST /transactions with Idempotency-Key matching the ID grammar and exact body entries; each exact entry is account_id,direction,amount where direction is debit or credit",
            "decimal_grammar": "positive base-10 string matching 0|[1-9][0-9]* followed optionally by dot and one or two digits; value must be greater than zero; signs, exponent, locale separators, leading zeroes, NaN, and infinity are invalid",
            "currency_rule": "account currency is exactly three uppercase ASCII letters; every transaction is single-currency and all referenced accounts must share that currency",
            "balance_rule": "sum debit amounts must equal sum credit amounts exactly in decimal arithmetic; reported account balance is total credits minus total debits",
            "amount_canonicalization": "parse with exact Decimal, require grammar and value, then render exactly two fractional digits; 1, 1.0, and 1.00 are one canonical amount and response entries use that form",
            "idempotency": "canonical payload normalizes amounts to two decimals and sorts entries by account_id,direction,canonical amount; initial commit returns 201, same key plus same canonical payload returns 200 with the same transaction, and same key plus different payload returns 409",
            "transaction_schema": "exact id,idempotency_key,currency,entries,reverses object; entries use the exact entry schema and canonical amount; reverses is null or the original transaction ID",
            "reads": "GET /transactions/{id} returns the exact transaction schema; GET /accounts/{id}/balance returns exact account_id,currency,balance; GET /accounts/{id}/journal returns exact account_id,entries where each exact record is transaction_id,sequence,account_id,direction,amount ordered by transaction sequence then canonical entry order",
            "reversal": "POST /transactions/{id}/reverse with Idempotency-Key appends one linked transaction with every debit/credit swapped; initial success is 201, replay with the same key is 200 with the same reversal, another key after reversal is 409; no original row is edited or deleted",
            "failure": "all invalid, stale, duplicate-conflict, and losing concurrent operations preserve complete accounts, transactions, entries, and derived balances",
        },
        "checks": [
            {
                "id": "ledger_account_identity",
                "public_contract": "Create durable uniquely identified accounts with immutable currency and reject duplicate or malformed account definitions.",
                "planned_probe": "Exercise persistence across process termination, duplicate IDs, malformed IDs, unsupported currency codes, and absence of any account-update operation.",
                "planned_mutant": "accepts a lowercase two-letter currency code while valid account creation and persistence remain correct",
                "failure_atomicity": "rejected account creation leaves no row",
                "nearest": "inventory-adjustment-api",
                "difference": "establishes immutable posting identities and currencies, not mutable stock quantities",
            },
            {
                "id": "ledger_balanced_posting",
                "public_contract": "Commit a transaction only when exact per-currency debit and credit totals balance and every entry is valid.",
                "planned_probe": "Exercise balanced multi-entry postings, imbalance, mixed currencies, zero/negative amounts, and unknown accounts.",
                "planned_mutant": "accepts a transaction whose aggregate debits and credits differ",
                "failure_atomicity": "invalid posting creates neither transaction nor entries nor balance changes",
                "nearest": "invoice-payment-reconciliation",
                "difference": "enforces an immutable accounting equation at write time rather than matching external invoices and payments",
            },
            {
                "id": "ledger_idempotency_conflict",
                "public_contract": "Replay the same idempotency key and canonical payload without duplication, but reject reuse with a different payload.",
                "planned_probe": "Exercise identical replay, reordered-equivalent payload, conflicting payload, process restart, and concurrent duplicate submission.",
                "planned_mutant": "creates a second transaction on identical replay",
                "failure_atomicity": "conflicts do not add journal entries or change balances",
                "nearest": "shipment-event-api",
                "difference": "binds a complete balanced multi-entry posting to one idempotency identity, not a single shipment event",
            },
            {
                "id": "ledger_balances_and_journal",
                "public_contract": "Derive exact account balances from the immutable journal and return canonical transaction and entry ordering.",
                "planned_probe": "Exercise multiple postings, decimal exactness, debit/credit orientation, filtered account journal, and process restart.",
                "planned_mutant": "GET account journal reverses canonical entry order within one transaction while balances remain correct",
                "failure_atomicity": "reads never mutate journal or balances",
                "nearest": "report-export-job",
                "difference": "derives auditable financial state from immutable postings, not a one-time filtered export",
            },
            {
                "id": "ledger_compensating_reversal",
                "public_contract": "Reverse a posted transaction exactly once by appending a linked compensating transaction; never edit or delete original entries.",
                "planned_probe": "Exercise reversal balance restoration, immutable original, double reversal, unknown transaction, and concurrent reversal attempts.",
                "planned_mutant": "allows a second compensating reversal for the same original transaction while leaving the original journal intact",
                "failure_atomicity": "exactly one concurrent reversal wins and losers leave the journal unchanged",
                "nearest": "versioned-document-api",
                "difference": "corrects immutable financial history through compensating entries rather than restoring prior document content as a new revision",
            },
        ],
    },
}

CURATED_OVERLAP = {
    "signed-artifact-verifier": {
        "support-ticket-api": ("both expose deterministic success/failure results", "ticket correctness is mutable workflow behavior; signing competence does not establish cryptographic authenticity, exact filesystem inventory, or key validity"),
        "csv-member-import": ("both validate a complete input set and summarize rejection", "member import reasons over tabular rows do not require a signed canonical payload or byte-level verification of an existing file tree"),
        "incident-escalation-api": ("both use explicit RFC3339 boundary instants", "incident time advances a domain state; verifier time decides whether a key and manifest are cryptographically trusted without mutating domain state"),
        "inventory-adjustment-api": ("both use the word inventory and enforce completeness/invariants", "stock inventory is a mutable business quantity; artifact inventory is an exact signed enumeration of regular filesystem objects"),
        "leave-request-api": ("both reject invalid requests atomically", "approval and overlap workflow competence does not imply canonical signing, key selection, path safety, or content-hash verification"),
        "refund-approval-api": ("both apply validity rules before accepting an operation", "monetary authorization thresholds do not exercise cryptographic payload canonicalization or whole-tree integrity"),
        "report-export-job": ("both are deterministic CLIs with committed output files", "export correctness concerns filters and totals; verifier output is a trust verdict gated on signature, inventory, path, and byte integrity"),
        "webhook-ingestion-service": ("both use HMAC authentication and key material", "webhook HMAC authenticates one inbound body before ingestion; artifact verification authenticates a canonical manifest and then proves every declared file"),
        "appointment-booking-api": ("both evaluate explicit interval boundaries", "booking handles resource interval conflicts and cancellation; verifier intervals govern key and manifest trust without scheduling resources"),
        "shipment-event-api": ("both retain auditable ordered evidence", "shipment projection and terminal-state events do not require filesystem inventory or cryptographic binding of evidence bytes"),
        "jsonl-event-aggregation": ("both validate complete inputs and emit deterministic audit-like output", "JSONL aggregation reasons over records do not prove signer identity, exact tree membership, or per-file hash integrity"),
        "invoice-payment-reconciliation": ("both reconcile a declared set against observed data", "financial matching uses amounts and cutoff semantics; signed inventory reconciliation uses normalized paths, sizes, hashes, and key trust"),
        "dependency-impact-planner": ("both are deterministic offline CLIs over canonical structured input", "graph closure and topological ordering do not exercise authentication, key windows, or filesystem byte integrity"),
        "access-policy-evaluator": ("both select keyed/rule material and use request-supplied time", "authorization decides allow or deny from matching rules; verifier establishes cryptographic trust in a manifest and artifact set"),
        "versioned-document-api": ("both protect integrity and expose immutable evidence", "document revisions coordinate mutable content through ETags; verifier performs stateless authenticity and whole-tree consistency checks"),
        "safe-archive-extraction": ("both enforce normalized path safety and produce hash manifests", "archive extraction controls creation from untrusted ZIP members; verifier never extracts and instead authenticates an exact pre-existing tree with a signed manifest"),
    },
    "pii-redaction-pipeline": {
        "support-ticket-api": ("both process structured JSON fields", "ticket routes mutate workflow entities; redaction recursively transforms selected values while proving all non-selected content is preserved"),
        "csv-member-import": ("both perform deterministic data normalization/transformation", "CSV import classifies tabular rows; redaction applies recursive selectors, precedence, removal, and keyed pseudonymization to arbitrary JSON"),
        "incident-escalation-api": ("both preserve unrelated state while changing selected fields", "escalation follows temporal domain transitions; redaction follows selector-specific privacy actions without a workflow clock"),
        "inventory-adjustment-api": ("both require atomic multi-field changes", "inventory adjusts business quantities; redaction transforms a recursive document and emits a field-level audit in one output bundle"),
        "leave-request-api": ("both have rule conflicts and deterministic rejection", "leave overlap/approval conflicts are domain states; redaction conflicts arise from equal-specificity selectors targeting the same JSON path"),
        "refund-approval-api": ("both interpret declarative rules", "refund rules authorize a monetary workflow; privacy rules transform values and must preserve every non-selected subtree"),
        "report-export-job": ("both are deterministic CLIs producing structured output", "report export filters and aggregates records; redaction rewrites selected recursive values and binds every change to an audit record"),
        "webhook-ingestion-service": ("both use HMAC and structured JSON", "webhook HMAC authenticates a request; redaction HMAC pseudonymizes selected canonical JSON values and intentionally changes the document"),
        "appointment-booking-api": ("both resolve overlapping selections or intervals", "appointment overlap is temporal resource exclusion; selector overlap is precedence among recursive JSON paths and actions"),
        "shipment-event-api": ("both preserve an audit trail", "shipment history is an append-only domain event log; redaction audit describes field transformations in a single deterministic bundle"),
        "jsonl-event-aggregation": ("both validate JSON and produce deterministic audit/rejection material", "JSONL work is row-oriented aggregation; redaction is path-oriented recursive transformation with non-selected structure preservation"),
        "invoice-payment-reconciliation": ("both reconcile inputs to auditable outputs", "invoice/payment matching does not exercise selector grammar, recursive mutation, keyed pseudonymization, or removal precedence"),
        "dependency-impact-planner": ("both traverse structured relationships deterministically", "graph traversal follows dependency edges; redaction traversal follows JSON path selectors and mutates selected values"),
        "access-policy-evaluator": ("both interpret wildcard rules with precedence", "policy rules return an authorization decision without changing input; redaction rules choose irreversible/transforming actions over recursive data"),
        "versioned-document-api": ("both operate on recursive JSON document values", "merge patch versions a mutable document through CAS; redaction performs one offline privacy transform with selector audit and no revision history"),
        "safe-archive-extraction": ("both require atomic output and reject unsafe input", "archive safety concerns filesystem members and extraction; redaction concerns semantic JSON selectors, value transformation, and privacy audit"),
    },
    "lease-coordination-api": {
        "support-ticket-api": ("both are persistent APIs with mutable state", "ticket transitions model assignment/status rules; lease correctness is exclusive temporal ownership guarded by monotonic fencing under concurrent writers"),
        "csv-member-import": ("both reject malformed input deterministically", "batch row import has no durable ownership generation, expiry, concurrent contention, or stale-holder capability"),
        "incident-escalation-api": ("both use explicit RFC3339 time and boundary behavior", "incident time triggers escalation state; lease time controls exclusivity, expiry takeover, renewal, and fencing-token validity"),
        "inventory-adjustment-api": ("both use SQLite transactions and enforce invariants under writes", "stock deltas/recounts do not arbitrate temporary owners or invalidate stale actors through fencing generations"),
        "leave-request-api": ("both prevent conflicting claims", "leave conflicts are durable calendar overlaps; a lease is one expiring ownership claim with renew/release and stale-token rejection"),
        "refund-approval-api": ("both reject unauthorized state changes", "approval authorization has staged thresholds; lease authority derives from current owner plus fencing token and temporal validity"),
        "report-export-job": ("both expose deterministic state/output", "report generation has no concurrent mutation, persistent token counter, expiration, or ownership arbitration"),
        "webhook-ingestion-service": ("both require idempotent durable API behavior", "webhook deduplicates event identities; lease coordination serializes competing owners and issues monotonic fencing capabilities"),
        "appointment-booking-api": ("both manage time-bound resource conflicts", "bookings allow multiple non-overlapping durable intervals; a resource lease allows exactly one current owner and supports renew/release/fencing"),
        "shipment-event-api": ("both retain monotonic state generations and reject stale transitions", "shipment generations are domain events; lease tokens are capabilities that protect external work after ownership changes"),
        "jsonl-event-aggregation": ("both handle malformed values with stable classification", "offline record aggregation cannot demonstrate simultaneous acquisition, durable ownership, or fencing after process restart"),
        "invoice-payment-reconciliation": ("both enforce atomic consistency", "financial matching is deterministic batch reconciliation; leases are mutable concurrent coordination with expiry and owner capabilities"),
        "dependency-impact-planner": ("both reason about ordering", "topological levels order dependent work statically; fencing tokens order successive owners dynamically under concurrent API operations"),
        "access-policy-evaluator": ("both use request-supplied time and reject unauthorized operations", "policy evaluation is stateless allow/deny composition; leases persist and mutate exclusive ownership generations"),
        "versioned-document-api": ("both use SQLite compare-and-swap, stale rejection, and cross-process persistence", "document CAS protects content revisions; lease CAS chooses temporal owners and emits monotonic fencing tokens that outlive lease expiry"),
        "safe-archive-extraction": ("both promise failure atomicity", "filesystem staging atomicity has no shared mutable database contender; lease atomicity is tested under simultaneous writers and durable state"),
    },
    "double-entry-ledger-api": {
        "support-ticket-api": ("both are persistent CRUD-like APIs", "ticket state/assignment transitions do not enforce exact decimal balancing, immutable postings, or compensating reversal"),
        "csv-member-import": ("both validate structured records and reject malformed values", "member import accepts/rejects independent rows; ledger entries form one atomic balanced transaction with derived account state"),
        "incident-escalation-api": ("both expose immutable evidence of state changes", "incident escalation is time-triggered workflow behavior; ledger state derives solely from balanced append-only financial entries"),
        "inventory-adjustment-api": ("both enforce transactional quantity invariants", "inventory permits domain updates and recounts; ledger requires equal debit/credit totals and corrects history only by compensation"),
        "leave-request-api": ("both reject conflicting operations atomically", "leave conflicts depend on dates and approval state; ledger conflicts concern idempotency identity and balanced financial posting"),
        "refund-approval-api": ("both use monetary amounts and financial-domain terminology", "refund approval authorizes thresholds and stages; ledger posting proves double-entry balance and immutable journal effects"),
        "report-export-job": ("both calculate exact totals and deterministic ordered output", "report totals are exported snapshots; ledger balances are derived continuously from immutable debit/credit entries"),
        "webhook-ingestion-service": ("both require durable idempotency", "webhook idempotency suppresses duplicate events; ledger idempotency binds an order-insensitive canonical multi-entry transaction and detects payload conflict"),
        "appointment-booking-api": ("both have concurrent conflict prevention", "booking protects time intervals; ledger protects balanced posting, idempotency identity, and one compensating reversal"),
        "shipment-event-api": ("both use idempotency and append-only history", "shipment events project a domain state machine; ledger entries preserve a mathematical debit/credit invariant and derived balances"),
        "jsonl-event-aggregation": ("both use exact parsing and deterministic summaries", "aggregation computes batch metrics over events; ledger atomically appends balanced entries and exposes persistent journals"),
        "invoice-payment-reconciliation": ("both use exact decimals and financial records", "reconciliation matches pre-existing invoices/payments at a cutoff; ledger accepts new balanced postings and compensation under transactional concurrency"),
        "dependency-impact-planner": ("both produce deterministic orderings", "graph planning orders components by dependencies; ledger ordering is an immutable transaction/entry journal with financial semantics"),
        "access-policy-evaluator": ("both validate operations against public rules", "policy returns stateless allow/deny; ledger commits balanced economic events and derives account balances"),
        "versioned-document-api": ("both preserve immutable history and use concurrent write guards", "document restore copies historical content into a new revision; ledger reversal appends direction-swapped entries and never restores mutable snapshots"),
        "safe-archive-extraction": ("both require all-or-nothing commit on validation", "archive commit creates a filesystem tree; ledger commit creates interdependent financial rows whose totals must balance exactly"),
    },
}

PAIRWISE_DIFFERENCE = {
    tuple(sorted(("signed-artifact-verifier", "pii-redaction-pipeline"))): "trust verification rejects or accepts an immutable artifact set; privacy redaction intentionally transforms selected JSON fields",
    tuple(sorted(("signed-artifact-verifier", "lease-coordination-api"))): "offline cryptographic and filesystem verification is stateless across runs; lease coordination measures durable temporal ownership under concurrency",
    tuple(sorted(("signed-artifact-verifier", "double-entry-ledger-api"))): "artifact authenticity and integrity have no mutable business journal; the ledger measures balanced immutable financial postings",
    tuple(sorted(("pii-redaction-pipeline", "lease-coordination-api"))): "recursive deterministic data transformation is a CLI batch operation; lease coordination is a concurrent persistent API state machine",
    tuple(sorted(("pii-redaction-pipeline", "double-entry-ledger-api"))): "privacy rules transform arbitrary JSON structure; ledger rules append balanced domain transactions without rewriting history",
    tuple(sorted(("lease-coordination-api", "double-entry-ledger-api"))): "leases expire and are replaced by higher fencing generations; financial postings never expire and are corrected only by compensation",
}
PAIRWISE_SHARED = {
    tuple(sorted(("signed-artifact-verifier", "pii-redaction-pipeline"))): "deterministic CLI, canonical JSON, HMAC, validation before atomic file commit",
    tuple(sorted(("signed-artifact-verifier", "lease-coordination-api"))): "request-supplied RFC3339 boundaries and controlled failure classification",
    tuple(sorted(("signed-artifact-verifier", "double-entry-ledger-api"))): "integrity invariants, canonical identity, and no partial commit",
    tuple(sorted(("pii-redaction-pipeline", "lease-coordination-api"))): "structured JSON validation, preservation of unrelated state, and atomic rejection",
    tuple(sorted(("pii-redaction-pipeline", "double-entry-ledger-api"))): "canonical structured values, deterministic auditability, and all-or-nothing output/state",
    tuple(sorted(("lease-coordination-api", "double-entry-ledger-api"))): "FastAPI, SQLite persistence, simultaneous writers, and stale/conflicting operation rejection",
}


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for task in TASKS.values():
        check_ids = [check["id"] for check in task["checks"]]
        for check in task["checks"]:
            check["expected_mutant_failed_checks"] = [check["id"]]
            check["expected_mutant_passed_checks"] = [item for item in check_ids if item != check["id"]]
    all_prior = []
    for new_id, task in TASKS.items():
        for prior_id, prior_construct in PRIOR.items():
            shared, distinction = CURATED_OVERLAP[new_id][prior_id]
            all_prior.append({
                "new_task": new_id,
                "prior_task": prior_id,
                "shared_shell_or_surface": shared,
                "new_construct": task["construct"],
                "prior_construct": prior_construct,
                "substantive_difference": distinction,
                "non_implication": f"Success on {prior_id} does not imply success on {new_id}: {distinction}",
            })
    nearest = []
    for task_id, task in TASKS.items():
        for check in task["checks"]:
            nearest.append({
                "new_task": task_id,
                "new_check": check["id"],
                "nearest_existing_task": check["nearest"],
                "substantive_difference": check["difference"],
                "planned_probe": check["planned_probe"],
                "planned_mutant": check["planned_mutant"],
                "expected_mutant_failed_checks": check["expected_mutant_failed_checks"],
                "expected_mutant_passed_checks": check["expected_mutant_passed_checks"],
            })
    pairwise = []
    for left, right in itertools.combinations(TASKS, 2):
        pairwise.append({
            "left": left,
            "right": right,
            "shared_shell": PAIRWISE_SHARED[tuple(sorted((left, right)))],
            "substantive_difference": PAIRWISE_DIFFERENCE[tuple(sorted((left, right)))],
        })
    payload = {
        "schema_version": 1,
        "freeze_date": DATE,
        "base_commit": BASE_COMMIT,
        "efficacy_cells_collected": 0,
        "authorization": "pre-build task identity, public contract planning, and non-efficacy evaluator construction only",
        "neutrality_policy": {
            "allowed": ["packaging", "import path", "runnable entrypoint", "route and CLI interface", "public schemas", "public business rules"],
            "forbidden": ["held-out literal fixtures", "hidden expected outputs", "evaluator check IDs in visible files", "implementation recipes", "A/B performance evidence"],
        },
        "tasks": TASKS,
        "all_prior_overlap_matrix": all_prior,
        "nearest_check_matrix": nearest,
        "new_task_pairwise_matrix": pairwise,
        "acceptance_gate": {
            "endpoint": "exactly five functional checks plus one result-envelope schema check per task",
            "reference_positive": "all five functional checks pass",
            "mutation_sensitivity": "one planned mutant per functional check with an exact one-check failure set",
            "clean_room": "three independent copied-workspace evaluations per task are classification-identical",
            "persistence": "API durable state is proven across process termination",
            "concurrency": "promised concurrent behavior is exercised by simultaneous writers, not sequential stale requests",
            "atomicity": "full pre/post state or output snapshots are equal after every controlled failure",
            "diversity": "64 new-versus-prior, 20 nearest-check, and 6 within-batch distinctions remain complete after implementation",
            "blind_review": "independent review returns GO before post-build acceptance",
            "forbidden_artifact": "visible task bundles are allowlisted and must exclude this pre-build ledger, check IDs, probes, mutants, hidden evaluator source, references, and prior run artifacts",
            "campaign_boundary": "no task-solving pilot, A/B cell, hidden efficacy score, contrast, or confirmatory launch",
        },
    }
    json_path = OUT / "BATCH3_PREBUILD_FREEZE.json"
    json_path.write_bytes(canonical_bytes(payload))
    digest = hashlib.sha256(json_path.read_bytes()).hexdigest()
    lines = [
        "# Stage 2 task-expansion batch 3 pre-build freeze",
        "",
        f"Freeze date: {DATE}",
        f"Base commit: `{BASE_COMMIT}`",
        f"JSON SHA-256: `{digest}`",
        "Efficacy cells collected: `0`",
        "",
        "## Frozen task identities",
        "",
    ]
    for task_id, task in TASKS.items():
        lines.extend([f"### `{task_id}`", "", task["construct"], "", f"Interface: {task['interface']}", "", "Frozen public interface:"])
        for key, value in task["public_interface"].items():
            lines.append(f"- `{key}`: {value}")
        lines.extend(["", "Planned functional checks:"])
        for check in task["checks"]:
            lines.append(f"- `{check['id']}`: {check['public_contract']}")
        lines.append("")
    lines.extend([
        "## Preventive diversity evidence",
        "",
        "- 64 comparisons between the four proposed tasks and all 16 accepted tasks",
        "- 20 nearest-existing-task comparisons, one for every planned functional check",
        "- 6 pairwise distinctions within batch 3",
        "",
        "## Authorization boundary",
        "",
        "Only public task-pack construction and non-efficacy evaluator/reference validation are authorized after this freeze. No task-solving run, A/B cell, hidden efficacy score, contrast, campaign launcher, or efficacy claim is authorized.",
        "",
    ])
    (OUT / "BATCH3_PREBUILD_FREEZE.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "sha256": digest, "tasks": list(TASKS), "all_prior": len(all_prior), "nearest": len(nearest), "pairwise": len(pairwise)}, indent=2))


if __name__ == "__main__":
    main()
