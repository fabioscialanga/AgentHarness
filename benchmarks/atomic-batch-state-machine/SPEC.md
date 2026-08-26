# Atomic batch state machine

Implement `batch_state_api.main:app`, a FastAPI application backed by SQLite.

The database path is read from `BATCH_STATE_DB`. The evaluator creates the database before importing the app.

## Durable schema

```sql
CREATE TABLE entities(entity_id TEXT PRIMARY KEY, state TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE commands(command_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, response_json TEXT NOT NULL);
```

States are `pending`, `active`, `suspended`, `closed`. Legal transitions are `pending->active`, `active->suspended`, `suspended->active`, `active->closed`, and `suspended->closed`.

## POST /batch-transition

The body has exact keys `command_id` and `operations`. Both `command_id` and `entity_id` use the exact ASCII grammar `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`. `operations` contains 1..32 exact objects with `entity_id`, nonnegative integer `expected_version` (booleans excluded), and target-state `transition`.

Canonical operation order is ascending Unicode `entity_id`. For structural validation, an operation with a missing or non-string `entity_id` has ordering key `""`; ties preserve input order. Duplicate IDs are rejected before any state change. Structural validation, entity existence, legal transitions, and all versions are evaluated against one pre-batch snapshot in canonical order. The entire batch commits in one SQLite transaction or changes nothing.

Success is HTTP 200 canonical JSON:

`{"command_id":"...","entities":[{"entity_id":"...","state":"...","version":N}]}`

`entities` is in canonical order and contains committed versions.

Errors use `{"detail":{"code":"CODE","index":N}}`, where index is zero-based in canonical operation order: `invalid_operation` (422), `duplicate_entity` (422), `not_found` (404), `illegal_transition` (422), or `stale_version` (409). A command reuse conflict is HTTP 409 `{"detail":{"code":"command_conflict"}}`.

The canonical command identity is SHA-256 of canonical JSON containing `command_id` and operations in canonical order. Replaying the same command with an equivalent operation permutation returns the byte-equivalent stored response without another mutation. Reusing the ID for different canonical content rejects without mutation.

## GET /entities/{entity_id}

Returns HTTP 200 `{"entity_id":"...","state":"...","version":N}` or HTTP 404 `{"detail":{"code":"not_found"}}`.

All success and error JSON uses sorted keys, compact separators, UTF-8 and a trailing newline. Controlled rejection preserves all entity rows and command rows. A post-commit delivery failure must never roll back or repeat the committed effect.
