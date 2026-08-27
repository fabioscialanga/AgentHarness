# Epoch-guarded leader heartbeat

Implement:

`python -m epoch_leader.cli acquire|heartbeat|publish|status --db DB --request JSON --output JSON`

Requests are strict UTF-8 RFC 8259 JSON files: duplicate keys and non-finite numbers reject. IDs use ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Times use the exact extended RFC3339 spelling `YYYY-MM-DDTHH:MM:SS[.ffffff](Z|±HH:MM)`, with one through six fractional digits when present; basic, week-date, reduced-precision, comma-fraction, naive, leap-second and noncanonical forms reject. Stored/rendered times are normalized to UTC as `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`, trimming trailing fractional zeroes. `ttl_seconds` is a JSON integer in `1..86400`; booleans reject. Payloads are JSON objects.

Success exits 0 with no stdout/stderr and atomically writes one canonical JSON envelope plus LF to `OUTPUT`: `{"result":...,"status":"ok"}`. Canonical JSON uses sorted keys, compact separators and UTF-8. Controlled rejection exits nonzero, emits exactly one diagnostic line on stderr and no stdout, leaves durable state logically unchanged, and preserves an existing output byte-for-byte or leaves an absent output absent.

## Durable schema and transactions

The first successful `acquire` creates a WAL-mode SQLite database and exact public tables:

`campaign(singleton INTEGER PRIMARY KEY CHECK(singleton=1), campaign_id TEXT NOT NULL, ttl_seconds INTEGER NOT NULL, current_leader TEXT, current_epoch INTEGER NOT NULL, expires_at_us INTEGER, next_sequence INTEGER NOT NULL)`

`publications(sequence INTEGER PRIMARY KEY, leader_id TEXT NOT NULL, epoch INTEGER NOT NULL, payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL)`

`requests(request_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, envelope BLOB NOT NULL)`

Every mutation uses one `BEGIN IMMEDIATE` transaction and persists its exact success envelope in `requests` in the same commit. Request identity is command plus canonical request. Repeating an identical `request_id` returns the stored envelope without repeating effects; reuse with another command or request rejects. A delivery failure after commit does not roll back; retry renders the stored result.

## Commands

`acquire` has exact request `{request_id,campaign_id,ttl_seconds,leader_id,now}`. The first acquisition creates the campaign and issues epoch 1. Later values of campaign ID and TTL must match. While `now < expires_at`, acquisition rejects. At `now >= expires_at`, exactly one concurrent caller durably wins, including at the exact boundary. Every successful acquisition after the first increments the persisted epoch by one, even when the leader ID is reused. Failed acquisition consumes no epoch. Expiry becomes `now + ttl_seconds`.

`heartbeat` has exact request `{request_id,leader_id,epoch,now}`. It succeeds only when leader ID and epoch both equal the current durable generation and `now < expires_at`; it sets expiry to `now + ttl_seconds`. Epoch is an integer in `1..9223372036854775807` with booleans excluded.

`publish` has exact request `{request_id,leader_id,epoch,now,payload_object}` and uses the same identity, epoch and unexpired checks. It stores canonical `payload_object`, its lowercase SHA-256, and the next persistent sequence. Successful publications have contiguous sequences starting at 1. Rejected or rolled-back publications consume no sequence.

`status` has exact request `{now}` and is read-only. It returns exact keys `{campaign_id,ttl_seconds,leader,publications}`. `leader` is `{leader_id,epoch,expires_at,active}`; `active` is true only when `now < expires_at`. Publications are ordered by sequence and have exact keys `{sequence,leader_id,epoch,payload_sha256,payload}`.

Acquire and heartbeat results have exact keys `{campaign_id,leader_id,epoch,expires_at}`. Publish results have exact keys `{sequence,leader_id,epoch,payload_sha256}`.
