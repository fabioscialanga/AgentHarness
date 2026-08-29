# Portable command receipt ledger

Implement `command_ledger.create_app(db_path, execute_once) -> FastAPI`.

The evaluator supplies an absolute SQLite path and a callback. That SQLite file is the only permitted durable receipt state. Do not use another file, database, service, process-global receipt map, environment variable, or test-only hook.

## Endpoint

`POST /commands/{command}` requires:

- `X-Tenant`
- `X-API-Revision`
- `Idempotency-Key`
- JSON body with exactly one field: `{"value": "..."}`

`command`, tenant, idempotency key, and body value are case-sensitive ASCII identifiers matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`.

The revision header is canonical base-10 ASCII with no sign or leading zero and value from 1 through 9223372036854775807.

Reject malformed requests with HTTP 422 before invoking `execute_once` or recording a receipt.

## Receipt identity

The exact receipt identity is the four-tuple:

`(tenant, command, api_revision, idempotency_key)`

All four dimensions are case-sensitive. The JSON payload is not an identity dimension; payload-conflict behavior is intentionally unclaimed.

## First execution

When no receipt exists for the exact identity, call:

`execute_once(tenant, command, api_revision, idempotency_key, payload)`

exactly once. The callback returns an unpredictable visible-ASCII string of length 1 through 128. Persist canonical JSON bytes:

`{"receipt":"<callback value>"}`

and return those exact bytes with HTTP 200 and JSON media type.

If execution fails or returns an invalid value, return HTTP 503 and do not admit a receipt. The particular callback exception response beyond this non-admission rule is otherwise out of scope.

## Replay

When the exact identity already has a receipt, return the exact persisted status/body bytes without calling `execute_once`.

The behavior must survive interpreter restart. After process P1 closes all connections, copying the sole SQLite file to a fresh root and starting process P2 against that copied path must preserve replay. P2 must also execute a genuinely new identity once and persist it in the copied database.

Implementations must not depend on SQLite WAL sidecars for committed receipt portability. The evaluator copies only the supplied database file after P1 has closed.

## Scope

Concurrency, payload conflicts, receipt expiry, deletion, authorization, retries inside the callback, and database corruption are intentionally unclaimed. The evaluator does not inspect candidate-private state; it observes HTTP bytes, callback calls, the supplied SQLite artifact, and fresh-process behavior.
