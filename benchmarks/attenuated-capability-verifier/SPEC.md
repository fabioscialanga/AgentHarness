# Attenuated capability verifier

Implement an offline verifier for an ordered chain of HMAC-SHA256 signed capabilities.

## Public interface

Run:

`python -m capability.verify --chain CHAIN --request REQUEST --keyring KEYRING --as-of RFC3339 --output REPORT`

All JSON inputs must be canonical compact sorted UTF-8, reject duplicate keys, unknown or missing fields, invalid UTF-8, non-finite values, booleans in integer fields, and noncanonical encodings.

CHAIN is `{"links":[LINK,...],"schema_version":1}`. Each LINK is `{"capability":CAPABILITY,"signature_hex":"..."}`. A root CAPABILITY has exactly `actions,depth,expires_at,id,issuer,max_depth,not_before,resource_prefix,subject,tenant`. A delegated capability additionally has `parent_digest`. IDs, issuer, subject, and tenant are nonempty strings. Actions are a sorted nonempty list of unique nonempty strings. `resource_prefix` is an absolute canonical path: `/` or begins and ends with `/`, with no empty, `.` or `..` segment. Times are UTC `YYYY-MM-DDTHH:MM:SSZ`, with `not_before < expires_at`. `depth` and `max_depth` are nonnegative integers.

KEYRING is `{"keys":[{"delegator":"...","secret_hex":"64 lowercase hex"},...],"schema_version":1}` with unique delegators.

REQUEST is exactly `{"action":"...","path":"...","subject":"...","tenant":"..."}` and uses a canonical absolute path.

The root has depth 0 and no parent digest. Its signature is HMAC-SHA256 by its issuer over the canonical CAPABILITY bytes. Every child has depth exactly parent depth + 1, `parent_digest` equal to lowercase SHA-256 of the canonical parent CAPABILITY, and is signed by the parent subject. Every child must narrow or preserve tenant, actions, resource prefix, time interval, and maximum depth. A child may not exceed any ancestor maximum depth.

The leaf must match request tenant and subject, contain the action, and authorize the request path on a segment boundary. `--as-of` must lie in every link's half-open interval `[not_before, expires_at)`.

On success atomically replace REPORT with exactly the canonical JSON bytes `{"action":ACTION,"allowed":true,"as_of":AS_OF,"capability_id":LEAF_ID,"path":PATH,"subject":SUBJECT,"tenant":TENANT}`. On controlled rejection return nonzero, emit exactly one diagnostic line on stderr, emit no stdout or traceback, preserve a pre-existing REPORT byte-for-byte, create no REPORT if absent, and leave no staging file.
