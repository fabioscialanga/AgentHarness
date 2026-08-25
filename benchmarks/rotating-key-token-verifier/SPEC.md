# Rotating key token verifier

## Objective

Implement a deterministic verifier for compact HMAC-signed tokens across an explicit key-rotation window.

## Public interface

Run:

`python -m rotating_token.verify --token TOKEN --keyring KEYRING --issuer ISSUER --audience AUDIENCE --as-of RFC3339 --output REPORT`

A token is `base64url(header).base64url(payload).base64url(signature)`. Segments are canonical unpadded base64url. Header and payload are canonical UTF-8 JSON (sorted keys, compact separators, no duplicate keys or non-finite numbers).

The header has exactly `alg` and `kid`; `alg` is `HS256`. The payload has exactly `aud`, `exp`, `iat`, `iss`, `jti`, `nbf`, and `sub`. `aud` is a non-empty duplicate-free string list; times are JSON integers in `[0, 2^63-1]`; `nbf < exp`. IDs follow ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`.

The keyring has exact shape `{"schema_version":1,"keys":[...]}`. Each key has exactly `kid`, `alg`, `secret_hex`, `active_from`, `retire_at`; IDs are unique, `alg` is `HS256`, secret is 32 bytes lowercase hex, and `active_from < retire_at`. Select only the token-declared `kid`.

Accept only when the HMAC-SHA256 signature is valid, `active_from <= as_of < retire_at`, `nbf <= as_of < exp`, issuer matches exactly, and audience is an exact list member. RFC3339 requires `Z` or a numeric offset; naive timestamps and leap seconds reject.

On success atomically replace REPORT with canonical JSON containing `alg`, `aud`, `exp`, `iat`, `iss`, `jti`, `kid`, `nbf`, `ok:true`, and `sub`, plus one newline. On controlled rejection return non-zero, emit one diagnostic line to stderr, preserve an existing REPORT byte-for-byte, and leave no staging file.

## Quality

Use Python 3.12, include tests and exact run instructions, use no network or implicit wall clock, and keep all files inside the workspace.
