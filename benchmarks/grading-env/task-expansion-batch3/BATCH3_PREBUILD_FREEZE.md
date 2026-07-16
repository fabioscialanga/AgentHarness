# Stage 2 task-expansion batch 3 pre-build freeze

Freeze date: 2026-07-16
Base commit: `6178b855d806687bd09624c43815f2688f82008d`
JSON SHA-256: `63f7404b1e62967e42c7f258ef3031b18a1699276e440bcd0bf30431c18b4713`
Efficacy cells collected: `0`

## Frozen task identities

### `signed-artifact-verifier`

offline trust verification combining canonical signed manifests, key validity, exact inventory, and byte integrity

Interface: deterministic CLI with manifest, keyring, artifact-root, as-of, and output-report arguments

Frozen public interface:
- `entrypoint`: python -m artifact_verifier.verify --manifest MANIFEST --keyring KEYRING --artifact-root ROOT --as-of RFC3339 --output REPORT
- `manifest_schema`: exact object: schema_version=1, key_id, valid_from, valid_until, files, signature; IDs match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; signature and sha256 are 64 lowercase hex; size is integer 0..9223372036854775807; files are exact path,size,sha256 objects
- `keyring_schema`: exact object: schema_version=1, keys; each exact key object is key_id,secret_hex,valid_from,valid_until; key IDs are unique and secret_hex encodes 16..64 bytes
- `signature_payload`: manifest without signature, UTF-8 JSON with sorted object keys, compact separators, ensure_ascii=false; HMAC-SHA256 lowercase hex
- `path_rules`: POSIX relative regular-file paths only; reject absolute, empty, dot, dot-dot, backslash, duplicate-normalized, symlink, device, FIFO, and socket entries; directories are not inventory records
- `inventory_boundary`: all regular files recursively below artifact-root must appear exactly once; output must be outside artifact-root
- `time_boundary`: each valid_from must precede valid_until; valid_from <= as_of < valid_until for both selected key and manifest; Z or explicit offset required and compared as instants
- `success_report`: exact object: ok=true,key_id,manifest_sha256,file_count,total_bytes,files; files sorted by path with path,size,sha256
- `failure`: controlled nonzero exit, diagnostic on stderr, and byte-identical preservation of a pre-existing report

Planned functional checks:
- `signed_manifest_authenticity`: Select the declared key ID and verify an HMAC-SHA256 signature over the documented canonical manifest payload.
- `signed_manifest_inventory`: Require a normalized, unique, exact file inventory with no missing, unexpected, absolute, escaping, or ambiguous paths.
- `signed_manifest_content_integrity`: Verify declared byte size and SHA-256 for every regular file in the exact inventory.
- `signed_manifest_trust_window`: Evaluate key and manifest validity intervals only against the required request-supplied RFC3339 as-of instant.
- `signed_manifest_atomic_report`: Validate the complete input before atomically committing one deterministic verification report; malformed input and I/O failures preserve prior output.

### `pii-redaction-pipeline`

recursive structure-preserving privacy transformation with selector semantics, keyed pseudonymization, and field-level audit

Interface: deterministic CLI with input JSON, rule document, secret-key file, and one atomic output-bundle path

Frozen public interface:
- `entrypoint`: python -m pii_redactor.redact --input INPUT --rules RULES --key KEY --output-bundle BUNDLE
- `input_schema`: one UTF-8 JSON object or array root
- `rules_schema`: exact object schema_version=1,rules; each unique rule is id,selector,action and replacement only for redact
- `selector_grammar`: non-root RFC6901-style pointer beginning slash; segments use ~0 and ~1 escapes; a whole segment * matches one object key or one existing array index
- `selector_semantics`: unmatched selectors are valid no-ops; exact segments outrank wildcard segments; equal-specificity rules selecting one path must be identical or the rules document is invalid
- `actions`: redact replaces any selected JSON value with the rule replacement string; remove deletes the selected object member or array element with array removals applied by descending original index; pseudonymize replaces any selected value with hmac-sha256:HEX over canonical compact sorted-key UTF-8 JSON
- `key_schema`: exact object secret_hex with a non-empty even-length hexadecimal HMAC key
- `bundle_schema`: exact object redacted,audit; audit records are exact path,rule_id,selector,action objects sorted by canonical path then rule_id
- `failure`: controlled nonzero exit and byte-identical preservation of a pre-existing single bundle; staging is same-filesystem and removed after failure

Planned functional checks:
- `pii_selector_resolution`: Resolve documented JSON-pointer-like exact and wildcard selectors over nested objects and arrays without implicit fuzzy matching.
- `pii_redaction_actions`: Apply the documented redact, remove, and HMAC-SHA256 pseudonymize actions with deterministic canonical value encoding.
- `pii_structure_preservation`: Preserve ordering-independent JSON meaning and every non-selected value while applying removals without index drift.
- `pii_rule_precedence`: Reject conflicting equal-specificity rules and apply the documented most-specific selector precedence deterministically.
- `pii_atomic_audit`: Atomically commit one deterministic JSON bundle containing the redacted document and a sorted audit with selector, action, and canonical path for every transformed field.

### `lease-coordination-api`

durable expiring mutual exclusion with monotonic fencing tokens and concurrent stale-holder protection

Interface: FastAPI plus SQLite/SQLAlchemy service with explicit resource, owner, duration, and request-supplied RFC3339 now values

Frozen public interface:
- `entrypoint`: lease_api.main:app with SQLite path from LEASE_DB_PATH
- `acquire`: POST /leases/{resource}/acquire body owner,duration_seconds,now; success 201
- `renew`: POST /leases/{resource}/renew body owner,fencing_token,duration_seconds,now; success 200
- `release`: POST /leases/{resource}/release body owner,fencing_token,now; success 200
- `read`: GET /leases/{resource}?as_of=RFC3339 returns latest generation or 404 if the resource has never had a lease
- `request_schema`: resource and owner match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; request bodies have exactly the documented fields and reject additional fields
- `lease_schema`: every successful operation and GET returns an exact resource,owner,fencing_token,acquired_at,expires_at,status object where status is active,expired,or released
- `time_rules`: now/as_of require Z or explicit offset; duration_seconds is integer 1..86400; expiry=now+duration; each mutating now is not earlier than the latest accepted operation time; GET as_of before the latest generation acquired_at is invalid; released when as_of is at/after release, else expired when as_of is at/after expiry, else active
- `generation_rules`: first token is 1 per resource; every acquisition after release or expiry increments by one; renew and release never increment; counters survive release, expiry, and process restart
- `statuses`: unknown resource is 404; malformed/extra fields are 422; active-owner conflict and double release are 409; wrong owner or stale token are 412; all preserve full state
- `concurrency`: simultaneous acquire operations for one resource must have one durable winner; SQLite busy/lock errors are not valid business responses

Planned functional checks:
- `lease_acquire_fencing`: Acquire an absent or expired resource lease and issue a persistent strictly increasing fencing token for that resource.
- `lease_concurrent_contention`: For concurrent acquisition of the same available resource, commit exactly one owner and reject every loser atomically.
- `lease_renewal`: Allow only the current unexpired owner with the current fencing token to extend expiry, without issuing a new token.
- `lease_release_reacquire`: Allow only the current owner/token to release; a later acquisition receives a higher token and stale holders remain powerless.
- `lease_state_and_failure_atomicity`: Expose the current lease deterministically and preserve complete state across malformed, missing, stale, and unknown-resource operations.

### `double-entry-ledger-api`

immutable balanced double-entry posting with idempotency, derived balances, and compensating reversal

Interface: FastAPI plus SQLite/SQLAlchemy service for accounts, transactions, entries, balances, and reversals using exact decimal strings

Frozen public interface:
- `entrypoint`: ledger_api.main:app with SQLite path from LEDGER_DB_PATH
- `accounts`: POST /accounts body exact id,currency returns 201 exact id,currency; GET /accounts/{id} returns the same exact object; IDs match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; no account update or delete route
- `posting`: POST /transactions with Idempotency-Key matching the ID grammar and exact body entries; each exact entry is account_id,direction,amount where direction is debit or credit
- `decimal_grammar`: positive base-10 string matching 0|[1-9][0-9]* followed optionally by dot and one or two digits; value must be greater than zero; signs, exponent, locale separators, leading zeroes, NaN, and infinity are invalid
- `currency_rule`: account currency is exactly three uppercase ASCII letters; every transaction is single-currency and all referenced accounts must share that currency
- `balance_rule`: sum debit amounts must equal sum credit amounts exactly in decimal arithmetic; reported account balance is total credits minus total debits
- `amount_canonicalization`: parse with exact Decimal, require grammar and value, then render exactly two fractional digits; 1, 1.0, and 1.00 are one canonical amount and response entries use that form
- `idempotency`: canonical payload normalizes amounts to two decimals and sorts entries by account_id,direction,canonical amount; initial commit returns 201, same key plus same canonical payload returns 200 with the same transaction, and same key plus different payload returns 409
- `transaction_schema`: exact id,idempotency_key,currency,entries,reverses object; entries use the exact entry schema and canonical amount; reverses is null or the original transaction ID
- `reads`: GET /transactions/{id} returns the exact transaction schema; GET /accounts/{id}/balance returns exact account_id,currency,balance; GET /accounts/{id}/journal returns exact account_id,entries where each exact record is transaction_id,sequence,account_id,direction,amount ordered by transaction sequence then canonical entry order
- `reversal`: POST /transactions/{id}/reverse with Idempotency-Key appends one linked transaction with every debit/credit swapped; initial success is 201, replay with the same key is 200 with the same reversal, another key after reversal is 409; no original row is edited or deleted
- `failure`: all invalid, stale, duplicate-conflict, and losing concurrent operations preserve complete accounts, transactions, entries, and derived balances

Planned functional checks:
- `ledger_account_identity`: Create durable uniquely identified accounts with immutable currency and reject duplicate or malformed account definitions.
- `ledger_balanced_posting`: Commit a transaction only when exact per-currency debit and credit totals balance and every entry is valid.
- `ledger_idempotency_conflict`: Replay the same idempotency key and canonical payload without duplication, but reject reuse with a different payload.
- `ledger_balances_and_journal`: Derive exact account balances from the immutable journal and return canonical transaction and entry ordering.
- `ledger_compensating_reversal`: Reverse a posted transaction exactly once by appending a linked compensating transaction; never edit or delete original entries.

## Preventive diversity evidence

- 64 comparisons between the four proposed tasks and all 16 accepted tasks
- 20 nearest-existing-task comparisons, one for every planned functional check
- 6 pairwise distinctions within batch 3

## Authorization boundary

Only public task-pack construction and non-efficacy evaluator/reference validation are authorized after this freeze. No task-solving run, A/B cell, hidden efficacy score, contrast, campaign launcher, or efficacy claim is authorized.
