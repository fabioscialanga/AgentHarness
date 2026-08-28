# Two-tier read-through cache

Implement `tiered_cache.TieredCache(l1, l2, origin)` using the public protocols in `tiered_cache.interfaces`.

The evaluator owns both tiers and the origin. Your implementation must not create another cache, database, file, network service, clock, process-global state, or test-only hook.

## Keys and values

A valid key is a case-sensitive ASCII string matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. `get` and `invalidate` reject any other value with `ValueError` before a callback.

A cache hit is a nonempty `bytes` value. `None` is a miss. Any other tier result is invalid and raises `ValueError`. The origin must return nonempty unpredictable `bytes`; another result raises `ValueError` before any `put`.

`OriginError` is the controlled origin failure. It propagates unchanged and must not cause any `put`.

## get(key)

For each valid call:

1. Call `l1.get(key)` exactly once.
2. On an L1 hit, return the exact same bytes object immediately. Do not call L2 or origin and do not write either tier.
3. On L1 miss, call `l2.get(key)` exactly once.
4. On an L2 hit, call `l1.put(key, value)` exactly once with the same key and exact bytes object, then return that object. Do not call origin or write L2.
5. When both tiers miss, call `origin.load(key)` exactly once. On valid bytes, call `l2.put(key, value)` and then `l1.put(key, value)`, preserving exact key and object identity, then return that object.
6. If `origin.load` raises `OriginError`, make no `put` and propagate the same exception. A later call follows the ordinary path and invokes origin again if both tiers still miss.

## invalidate(key)

For a valid key, call `l1.delete(key)` exactly once and then `l2.delete(key)` exactly once, with the exact case-sensitive key. Return `None`.

A subsequent `get` uses the ordinary algorithm. There is no key normalization or aliasing.

## Scope

The contract intentionally makes no claim about TTL, capacity, eviction, negative caching, authorization, versions, concurrency, singleflight, persistence, cross-process state, serialization, or store callback failures. Store callback exceptions other than `OriginError` are outside scope.
