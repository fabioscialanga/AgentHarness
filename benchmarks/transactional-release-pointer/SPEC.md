# Transactional release pointer

Implement `release_pointer.create_app(store) -> FastAPI` using the public types in `release_pointer.interfaces`.

The evaluator owns all durable state and supplies `store`. Your implementation must use only this store boundary; it must not create a database, sidecar file, network dependency, process-global durable state, or test-only hook.

## Identifiers and values

`channel_id` and `request_id` are case-sensitive ASCII values matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`.

An artifact digest matches `sha256:[0-9a-f]{64}` exactly. A generation is an integer in `0..9223372036854775807`; booleans are not integers. Incrementing the maximum generation is rejected.

Malformed JSON, non-object roots, missing or extra fields, wrong types, invalid identifiers/digests, and invalid integer values are HTTP 422 with `{"detail":"invalid_request"}`. Validation occurs before any store callback.

## Store transaction boundary

Each `begin()` returns a fresh opaque transaction token. Pass that exact token to every callback for that transaction; do not inspect, copy, synthesize, or replace it.

Staged channel, event, and receipt values become durable only through `commit(tx)`. `rollback(tx)` discards them. `StoreError` and other callback exceptions are controlled store failures.

## POST /v1/channels/{channel_id}/publish

The exact JSON body is:

```json
{
  "request_id": "publish-8",
  "expected_generation": 7,
  "artifact_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

After input validation:

1. Begin one transaction.
2. Look up `request_id` with `find_receipt`.
3. If a receipt exists, compare its command fingerprint with this command's canonical fingerprint. An exact replay rolls back the read-only transaction and returns the stored status and exact response bytes without reading the channel, checking approval, or staging writes. Different command content under the same request ID rolls back and returns HTTP 409 `{"detail":"request_id_conflict"}`.
4. Read the channel. Missing channel returns HTTP 404 `{"detail":"channel_not_found"}` after rollback.
5. Compare `expected_generation` with the current generation. A mismatch rolls back and returns HTTP 409 `{"detail":"generation_conflict"}`.
6. Call `artifact_is_approved` in the same transaction. False rolls back and returns HTTP 422 `{"detail":"artifact_not_approved"}`.
7. Construct generation `current + 1`, one updated `Channel`, one `PublicationEvent`, and one `Receipt` containing the command fingerprint, HTTP 200, and exact response bytes.
8. Stage the channel, event, and receipt in that order, then commit once.
9. Return the same bytes stored in the receipt.

The canonical command fingerprint is lowercase SHA-256 of compact, sorted-key UTF-8 JSON with exact fields `artifact_digest`, `channel_id`, `expected_generation`, and `request_id`.

A successful body is compact sorted-key JSON, with no required trailing newline:

```json
{"artifact_digest":"sha256:bbbb...","channel_id":"stable","generation":8,"previous_digest":"sha256:aaaa...","request_id":"publish-8"}
```

If any store callback raises before commit succeeds, attempt to roll back the active transaction and return HTTP 503 `{"detail":"storage_failure"}`. Do not retry internally. The channel, publication events, and receipts must remain exactly at their pre-request values.

Generation overflow rolls back and returns HTTP 409 `{"detail":"generation_overflow"}`.

## Public reads

`GET /v1/channels/{channel_id}` returns the channel as JSON or `channel_not_found`.

`GET /v1/publication-events?channel_id=...` returns the channel's events in store order as JSON objects with `request_id`, `channel_id`, `previous_digest`, `artifact_digest`, and `generation`.

`GET /v1/publication-receipts/{request_id}` returns the stored status and exact response bytes, or HTTP 404 `{"detail":"receipt_not_found"}`.

Reads use a fresh transaction and close it with `rollback`; they stage no writes.

## Atomicity and replay scope

A fresh accepted publication has one durable unit: updated pointer, matching immutable event, and matching receipt. None may survive a controlled pre-commit failure unless all three commit successfully.

After a successful commit, exact sequential replay returns the stored response without another publication attempt. Reuse with different command content is a conflict. The contract claims idempotency only for evaluator-owned durable records; it does not claim exactly-once delivery to external consumers.
