# Ack-token work queue

Implement the SQLite CLI:

`python -m ack_queue.cli init|enqueue|claim|ack|nack|get|result --db DB --request JSON --output JSON`

`DB`, `REQUEST`, and `OUTPUT` are caller-supplied paths. Request files contain UTF-8 JSON. Success writes one canonical UTF-8 JSON envelope plus newline to `OUTPUT` and exits 0. Rejections exit nonzero, emit exactly one diagnostic line on stderr and no stdout, preserve database bytes logically, preserve an existing output byte-for-byte, and do not create an absent output.

Canonical JSON uses sorted keys, UTF-8, no insignificant whitespace, booleans/null in JSON form, and a trailing newline. Success envelopes have exact keys `status` and `result`, with `status:"ok"`.

## Database

`init` accepts exact request `{}` and creates these public tables if absent:

`jobs(job_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, state TEXT NOT NULL, worker TEXT, token TEXT, expires_at INTEGER, attempts INTEGER NOT NULL)`

`requests(request_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, envelope BLOB NOT NULL)`

Initialization is idempotent. All mutating commands use one `BEGIN IMMEDIATE` transaction and store state plus their exact success envelope before output delivery.

IDs and worker names use `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`. `now` and `lease_seconds` are JSON integers in `0..9223372036854775807` with booleans excluded; `lease_seconds` is positive and `now+lease_seconds` must not exceed `9223372036854775807`. Tokens are exactly 64 lowercase hexadecimal characters encoding 32 opaque bytes. Input is strict RFC 8259 JSON: duplicate object keys, `NaN`, and infinities are rejected.

## Commands

`enqueue` request has exact keys `{request_id,job_id,payload_object}`. `payload_object` is a JSON object. A new job is stored as available with attempts 0 and null worker/token/expires_at. Duplicate job IDs are conflicts.

`claim` request has exact keys `{request_id,worker,now,lease_seconds}`. It selects the lexicographically smallest available job, treating a claimed job as available when `now >= expires_at`. A successful claim sets worker, a fresh token, `expires_at=now+lease_seconds`, increments attempts exactly once, and returns that job. If none is visible it returns null without changing any job. Concurrent claim processes may expose a job successfully to only one durable owner.

`ack` and `nack` requests have exact keys `{request_id,worker,job_id,token,now}`. They succeed only when job state is claimed and worker plus token match the current durable ownership generation. `ack` completes the job. `nack` requeues it without changing payload or attempts. Worker, token, and expires_at become null. An old token remains invalid after timeout and reclaim, even for the same worker.

`get` request has exact keys `{job_id,now}`. It is read-only. It returns the job's effective state at `now`; an expired claimed job is projected as available with null worker/token/expires_at without mutating SQLite.

`result` request has exact key `{request_id}` and re-emits the originally stored success envelope byte-for-byte.

Every returned job object has exact keys `{job_id,payload,state,worker,token,expires_at,attempts}`. States are `available`, `claimed`, and `completed`.

## Idempotency

Every mutating request except `init` carries `request_id`. The command name plus canonical request defines request identity. Repeating the same identity returns the stored envelope byte-for-byte and does not repeat state changes or attempt increments. Reusing a request_id for any different command or canonical request is a controlled conflict with no change.

A delivery failure after commit never rolls back or repeats a committed effect. A later identical request or `result` returns the durable stored envelope.
