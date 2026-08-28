# Context-complete authorization cache

Implement `decision_cache.create_app(policy_store, clock, ttl_seconds=60)`, returning a FastAPI app.

Public interfaces are defined in `decision_cache.interfaces`:

- frozen `PolicySnapshot(revision: int, evaluation_token: object)`
- `PolicyStoreProtocol.snapshot(tenant_id, subject_id) -> PolicySnapshot`
- `PolicyStoreProtocol.evaluate(snapshot, resource_id, action) -> bool`
- `ClockProtocol.now() -> int`

The snapshot token is opaque, non-None, never part of cache identity, and must be passed unchanged to `evaluate`. A revision identifies immutable policy content for one tenant/subject, is never reused for changed decisions, and strictly increases when policy changes.

`ttl_seconds` must be a non-boolean integer 1..3600. Otherwise `create_app` raises `ValueError` before creating an app.

`POST /authorize` accepts the exact JSON body `{"tenant":ID,"subject":ID,"resource_id":ID,"action":ID}`. IDs match ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and are case-sensitive.

Processing order for a schema-valid request is exact:

1. call `snapshot(tenant, subject)` once and validate an exact `PolicySnapshot` with non-boolean revision 1..9223372036854775807 and non-None token;
2. call `clock.now()` once and validate a non-boolean integer 1..9223372036854775807;
3. look up the complete key `(tenant, subject, resource_id, action, revision)`;
4. on a nonexpired hit, return the stored decision and do not call `evaluate`;
5. on miss/expiry, call `evaluate` exactly once with the unchanged snapshot; accept only an exact bool and cache both allow and deny decisions.

Success is exact `200 {"allowed":BOOL,"policy_revision":INT,"cache":"hit"|"miss"}`.

Malformed body uses no callbacks. Snapshot failure/invalidity uses no clock/evaluate; clock failure/invalidity uses no evaluate; evaluate failure/non-boolean creates no entry. All controlled failures return exact `422 {"detail":"invalid_request"}`.

Expiry is half-open and non-sliding: an entry created at `t` is valid while `now - t < ttl_seconds` and expired when `now - t >= ttl_seconds`. Expiry reevaluates and replaces it.

The cache is process-local. Repeated requests at one revision must hit even when `snapshot` returns newly allocated snapshot/token objects each time. Disabling/flushing the cache, always returning misses, or caching only allow/deny decisions violates this contract.
