# lease-coordination-api

## Objective

Durable expiring mutual exclusion with monotonic fencing tokens and concurrent stale-holder protection.

## Required stack

Python 3.12, FastAPI, Pydantic, SQLAlchemy, SQLite, pytest

## Public interface and behavior

- POST /leases/{resource}/acquire body owner,duration_seconds,now; success 201
- simultaneous acquire operations for one resource must have one durable winner; SQLite busy/lock errors are not valid business responses
- lease_api.main:app with SQLite path from LEASE_DB_PATH
- first token is 1 per resource; every acquisition after release or expiry increments by one; renew and release never increment; counters survive release, expiry, and process restart
- every successful operation and GET returns an exact resource,owner,fencing_token,acquired_at,expires_at,status object where status is active,expired,or released
- GET /leases/{resource}?as_of=RFC3339 returns latest generation or 404 if the resource has never had a lease
- POST /leases/{resource}/release body owner,fencing_token,now; success 200
- POST /leases/{resource}/renew body owner,fencing_token,duration_seconds,now; success 200
- resource and owner match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; request bodies have exactly the documented fields and reject additional fields
- unknown resource is 404; malformed/extra fields are 422; active-owner conflict and double release are 409; wrong owner or stale token are 412; all preserve full state
- now/as_of require Z or explicit offset; duration_seconds is integer 1..86400; expiry=now+duration; each mutating now is not earlier than the latest accepted operation time; GET as_of before the latest generation acquired_at is invalid; released when as_of is at/after release, else expired when as_of is at/after expiry, else active

## Packaging and quality requirements

- The workspace root is the runnable project.
- Keep the importable implementation in the package named by the public entrypoint.
- Declare runtime and test dependencies in pyproject.toml.
- Include automated tests and exact run instructions.
- Do not use network services, implicit wall-clock time, or files outside the workspace.
- Invalid input must produce a controlled CLI failure or HTTP 4xx response, not an uncaught traceback.
