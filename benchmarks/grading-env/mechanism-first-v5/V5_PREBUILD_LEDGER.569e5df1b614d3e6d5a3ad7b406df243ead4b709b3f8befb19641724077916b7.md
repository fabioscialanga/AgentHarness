# AgentHarness mechanism-first V5 pre-build ledger

Freeze date: 2026-08-24
Base commit before this amendment: `95649a6ae0cbbbaf770f7f1363fbe6cc35d79f77`
Normative JSON SHA-256: `01a331c23895b764f84952d266350fa50e581007e9950039973e8ea3c42e816c`
Target-model calls: `0`
Efficacy cells: `0`

## Authorization boundary

pre-build identities, neutral public contracts, reference/evaluator/mutant construction, and qualification only after independent pre-build GO

Prohibited: no target-model repair pilot, A/B cell, contrast, task replacement, threshold change, or efficacy claim.

## Frozen families and candidates

### `concurrency-ownership`

exclusive ownership, stale-actor rejection, and publication under simultaneous operations

#### `ack-token-work-queue`

durable work claims whose opaque acknowledgement token prevents a timed-out worker from committing another worker's item

Interface: `python -m ack_queue.cli init|enqueue|claim|ack|nack|get|result --db DB --request JSON --output JSON`
Designated target: `ack_stale_worker_rejected`
Finding concept: Observed behavior: accepts an acknowledgement by item and worker while ignoring the current opaque token. Violated invariant: After timeout and reclaim, only the newest opaque ack token may complete the item.

Planned checks:
- `ack_stale_worker_rejected` (target): After timeout and reclaim, only the newest opaque ack token may complete the item.
- `ack_single_claim` (guard): Simultaneous claims expose one durable owner.
- `ack_visibility_timeout` (guard): Visibility expires at the exact documented instant.
- `ack_nack_requeues` (guard): A valid nack requeues once without changing payload.
- `ack_attempt_accounting` (guard): Every successful claim increments a persistent attempt counter once.

#### `semaphore-permit-registry`

bounded cross-process permits with unique lease identities and exact capacity under simultaneous acquire/release

Interface: `semaphore_api.main:app; POST /pools/{id}/acquire, POST /permits/{token}/release, GET /pools/{id}`
Designated target: `permit_capacity_contention`
Finding concept: Observed behavior: checks capacity before insert without a transactionally protected predicate. Violated invariant: At most capacity simultaneous acquisitions succeed, including under a barrier-start race.

Planned checks:
- `permit_capacity_contention` (target): At most capacity simultaneous acquisitions succeed, including under a barrier-start race.
- `permit_unique_token` (guard): Every successful acquisition receives a unique opaque token.
- `permit_release_once` (guard): A permit can be released exactly once by its token.
- `permit_pool_isolation` (guard): Contention and counts are isolated per pool.
- `permit_snapshot` (guard): GET returns capacity, active count, and sorted active token metadata consistently.

#### `epoch-guarded-leader-heartbeat`

leader heartbeats fenced by a monotonically increasing epoch so a paused former leader cannot extend or publish after takeover

Interface: `python -m epoch_leader.cli acquire|heartbeat|publish|status --db DB --request JSON --output JSON`
Designated target: `leader_stale_epoch_publish`
Finding concept: Observed behavior: authorizes publish by leader ID while ignoring the supplied epoch. Violated invariant: Heartbeat and publish require both current leader identity and current epoch.

Planned checks:
- `leader_stale_epoch_publish` (target): Heartbeat and publish require both current leader identity and current epoch.
- `leader_epoch_monotonic` (guard): Every takeover increments the persistent epoch.
- `leader_one_winner` (guard): Simultaneous acquisition has one durable winner.
- `leader_expiry_boundary` (guard): Takeover is allowed exactly at expiry, not before.
- `leader_publication_order` (guard): Current leader publications receive persistent contiguous sequence numbers.

#### `atomic-snapshot-publisher`

multi-writer publication of immutable snapshots through generation compare-and-swap and one atomic current pointer

Interface: `python -m snapshot_publish.cli publish --root ROOT --request REQUEST_JSON --output JSON`
Designated target: `snapshot_compare_and_swap`
Finding concept: Observed behavior: checks expected generation before staging but replaces current without a commit-time comparison. Violated invariant: Only one writer with the same expected generation may publish the next generation.

Planned checks:
- `snapshot_compare_and_swap` (target): Only one writer with the same expected generation may publish the next generation.
- `snapshot_inline_integrity` (guard): Published manifest exactly binds every supplied inline name and decoded byte string by name, size, and SHA-256.
- `snapshot_name_safety` (guard): Slash, dot-segment, non-ASCII, empty, and noncanonical inline names reject before staging.
- `snapshot_generation_contiguity` (guard): Committed generations increase by exactly one without gaps.
- `snapshot_manifest_order` (guard): Manifest file rows are sorted by canonical name regardless of JSON object insertion order.

### `transactional-transitions`

failure-atomic multi-record state transitions and compensating state machines

#### `transactional-outbox-order`

business state and ordered outbox event creation committed together, with retry-safe dispatch acknowledgement

Interface: `outbox_order.create_app(db_path); POST /orders/{order_id}/confirm, GET /outbox, POST /outbox/{event_id}/ack`
Designated target: `outbox_commit_coupling`
Finding concept: Observed behavior: commits order state before inserting the outbox event. Violated invariant: A confirmed order and its event become durable together or neither does.

Planned checks:
- `outbox_commit_coupling` (target): A confirmed order and its event become durable together or neither does.
- `outbox_one_event` (guard): Idempotent replay yields the same single event.
- `outbox_canonical_payload` (guard): Event payload is canonical and binds the committed order version.
- `outbox_ordering` (guard): Polling returns events in commit sequence order.
- `outbox_ack_once` (guard): Acknowledgement is monotonic and repeat-safe.

#### `saga-compensation-engine`

durable forward and compensating steps whose restart state never repeats completed effects or skips required compensation

Interface: `python -m saga_engine.cli start|advance|fail|resume|status --db DB --request JSON --output JSON`
Designated target: `saga_reverse_compensation`
Finding concept: Observed behavior: compensates in forward declaration order. Violated invariant: After a forward failure, completed steps are compensated exactly once in reverse completion order.

Planned checks:
- `saga_reverse_compensation` (target): After a forward failure, completed steps are compensated exactly once in reverse completion order.
- `saga_forward_once` (guard): Completed forward steps are never emitted again after restart.
- `saga_compensation_once` (guard): A compensation acknowledgement is idempotent.
- `saga_terminal_states` (guard): Completed and compensated workflows reject further mutation.
- `saga_history` (guard): Status exposes an immutable ordered transition history.

#### `atomic-batch-state-machine`

all-or-none transitions of multiple versioned entities with validation against the same pre-state

Interface: `batch_state_api.main:app; POST /batch-transition, GET /entities/{id}`
Designated target: `batch_all_or_none`
Finding concept: Observed behavior: preflights structure and legal transitions but checks versions and commits sequentially, leaving prior operations committed on a later stale version. Violated invariant: After structural and legal-transition preflight, all expected versions are checked against one pre-batch snapshot and either every operation commits or none do.

Planned checks:
- `batch_all_or_none` (target): After structural and legal-transition preflight, all expected versions are checked against one pre-batch snapshot and either every operation commits or none do.
- `batch_duplicate_entity` (guard): A batch rejects duplicate entity IDs before mutation.
- `batch_error_index` (guard): A rejected batch reports the zero-based index of the first failing preflight or version check without exposing partial results.
- `batch_idempotent_replay` (guard): Same command and canonical batch replays; conflicting reuse rejects.
- `batch_response_order` (guard): Success response uses documented canonical entity order and committed versions.

#### `durable-retry-scheduler`

retry scheduling whose attempt completion and next-at computation are one durable transition under crash/replay

Interface: `python -m retry_scheduler.cli enqueue|claim|complete|fail|status --db DB --request JSON --output JSON`
Designated target: `retry_failure_transition`
Finding concept: Observed behavior: commits failed history before writing the next schedule. Violated invariant: Failing a current claim records the attempt and either schedules exactly one next attempt or terminals atomically.

Planned checks:
- `retry_failure_transition` (target): Failing a current claim records the attempt and either schedules exactly one next attempt or terminals atomically.
- `retry_backoff` (guard): next_at follows the exact capped exponential formula from attempt number.
- `retry_current_token` (guard): Only the current claim token may complete/fail.
- `retry_max_attempts` (guard): The final allowed failure enters terminal failed without another schedule.
- `retry_due_order` (guard): Claims select due jobs by next_at then canonical ID.

### `cryptographic-binding`

canonical messages, key context, and proof verification bound to the intended object

#### `canonical-query-signature`

request signatures bound to canonical method, path, multivalue query, selected headers, body digest, nonce value, and key/time window

Interface: `python -m query_signature.verify --request REQUEST --keyring KEYRING --as-of RFC3339 --output REPORT`
Designated target: `signature_query_multiplicity`
Finding concept: Observed behavior: canonicalizes query through a dictionary and drops duplicate keys. Violated invariant: Canonicalization preserves duplicate query keys, sorts encoded key/value pairs, and distinguishes absent from empty values.

Planned checks:
- `signature_query_multiplicity` (target): Canonicalization preserves duplicate query keys, sorts encoded key/value pairs, and distinguishes absent from empty values.
- `signature_method_path` (guard): Method and normalized path are signature-bound.
- `signature_header_selection` (guard): Only the declared lowercase selected headers are normalized and bound.
- `signature_body_digest` (guard): Exact body bytes are bound through SHA-256.
- `signature_key_window` (guard): The nonce value is signature-bound and key validity uses inclusive-start/exclusive-end request-supplied time.

#### `envelope-context-decryptor`

authenticated envelope decryption bound to tenant, purpose, object ID, algorithm, and key version as associated context

Interface: `python -m envelope_crypto.decrypt --envelope ENVELOPE --context CONTEXT --keyring KEYRING --output PLAINTEXT; importable envelope_crypto.decrypt.decrypt_to_file(envelope_path,context_path,keyring_path,output_path,*,replace=os.replace)`
Designated target: `envelope_context_binding`
Finding concept: Observed behavior: authenticates ciphertext without including purpose in associated data. Violated invariant: The authentication tag binds canonical tenant, purpose, object ID, algorithm, and key version context.

Planned checks:
- `envelope_context_binding` (target): The authentication tag binds canonical tenant, purpose, object ID, algorithm, and key version context.
- `envelope_key_version` (guard): Only the declared active key version may decrypt.
- `envelope_nonce_tag` (guard): Nonce/tag lengths and authentication are exact.
- `envelope_schema` (guard): Unknown fields, wrong types, and noncanonical encodings reject.
- `envelope_output_atomicity` (guard): A post-authentication commit failure preserves prior output and removes staging residue.

#### `rotating-key-token-verifier`

offline token verification with issuer/audience binding, key rotation overlap, retirement, and algorithm pinning

Interface: `python -m rotating_token.verify --token TOKEN --keyring KEYRING --issuer ISS --audience AUD --as-of RFC3339 --output REPORT`
Designated target: `token_rotation_window`
Finding concept: Observed behavior: accepts any known key version regardless of retirement. Violated invariant: A key verifies only during its inclusive activation and exclusive retirement window, including documented overlap.

Planned checks:
- `token_rotation_window` (target): A key verifies only during its inclusive activation and exclusive retirement window, including documented overlap.
- `token_issuer_audience` (guard): Issuer and exact audience are signature-bound and request-matched.
- `token_algorithm_pin` (guard): Header algorithm must exactly match the key's frozen algorithm.
- `token_time_claims` (guard): nbf is inclusive and exp exclusive against supplied as-of.
- `token_canonical_encoding` (guard): Noncanonical JSON/base64 encodings reject rather than aliasing identity.

#### `merkle-batch-proof-verifier`

domain-separated Merkle inclusion proofs bound to tree size, leaf index, ordered sibling direction, and expected root

Interface: `python -m merkle_verify.verify --proof PROOF --root ROOT --output REPORT`
Designated target: `merkle_index_direction`
Finding concept: Observed behavior: sorts child hashes lexically instead of honoring left/right position. Violated invariant: Proof verification binds every sibling direction to the declared leaf index and tree size.

Planned checks:
- `merkle_index_direction` (target): Proof verification binds every sibling direction to the declared leaf index and tree size.
- `merkle_domain_separation` (guard): Leaf and internal node hashes use distinct frozen prefixes.
- `merkle_tree_size` (guard): Proof depth and unbalanced-tree behavior are validated against tree_size.
- `merkle_encoding` (guard): All hashes and leaf bytes use canonical lowercase even-length hex.
- `merkle_root_binding` (guard): Computed root must match the request-supplied expected root exactly.

### `authorization-isolation`

subject, tenant, scope, and response-data authorization without cross-boundary disclosure

#### `tenant-scoped-resource-api`

resource lookup and mutation whose authorization predicate is inseparable from tenant-scoped database selection

Interface: `tenant_resource.main:app; GET /resources, GET/PATCH /resources/{id} with signed X-Tenant and X-Subject context`
Designated target: `tenant_lookup_scope`
Finding concept: Observed behavior: the conditional update predicates only on globally nonunique resource ID and changes the other tenant's colliding row. Violated invariant: A resource ID resolves and mutates only within the authenticated tenant, including when another tenant owns the same ID.

Planned checks:
- `tenant_lookup_scope` (target): A resource ID resolves and mutates only within the authenticated tenant, including when another tenant owns the same ID.
- `tenant_subject_role` (guard): Subject role is evaluated within its tenant membership.
- `tenant_version_cas` (guard): Authorized patch requires the tenant-local expected version.
- `tenant_error_indistinguishability` (guard): Foreign and nonexistent resources share the documented response shape/status.
- `tenant_list_filter` (guard): Collection results contain only the authenticated tenant and stable ordering.

#### `attenuated-capability-verifier`

delegated capabilities whose child scope, actions, path prefix, time window, and depth can only narrow the signed parent

Interface: `python -m capability.verify --chain CHAIN --request REQUEST --keyring KEYRING --as-of RFC3339 --output REPORT`
Designated target: `capability_attenuation`
Finding concept: Observed behavior: checks signatures but does not reject a child path prefix broader than its parent. Violated invariant: Every delegated capability must preserve tenant and be a subset of its parent across actions and path prefix.

Planned checks:
- `capability_attenuation` (target): Every delegated capability must preserve tenant and be a subset of its parent across actions and path prefix.
- `capability_chain_signatures` (guard): Each link is signed by the prior authorized delegator over canonical content.
- `capability_request_match` (guard): Leaf subject/action/path exactly authorizes the request.
- `capability_time_intersection` (guard): Every child interval must be a subset of its parent and as-of must lie in every half-open link interval.
- `capability_depth` (guard): Depth increments exactly by one, max_depth never broadens, and delegation depth respects every ancestor's limit.

#### `field-projection-authorization`

response field projection where authorization is applied before derived fields and serialization, preventing forbidden-source inference

Interface: `field_auth.create_app(db_path, policy_store); GET /tenants/{tenant}/resources/{id}?fields=comma-list; PATCH same path; both require X-Subject header`
Designated target: `projection_derived_dependency`
Finding concept: Observed behavior: authorizes the derived field name without checking its source dependencies. Violated invariant: A derived field is authorized only when the subject may read every source field it depends on.

Planned checks:
- `projection_derived_dependency` (target): A derived field is authorized only when the subject may read every source field it depends on.
- `projection_explicit_fields` (guard): Only explicitly requested and authorized fields appear.
- `projection_deny_precedence` (guard): Explicit field deny overrides role allow.
- `projection_unknown_fields` (guard): Unknown and duplicate fields reject with a data-independent error.
- `projection_order` (guard): Response fields use the frozen canonical order independent of request order.

#### `atomic-authorized-batch`

multi-resource command that authorizes every operation against one subject snapshot before any mutation

Interface: `auth_batch.create_app(role_store); POST /batch, GET /objects/{id}, qualification-only POST /admin/subjects/{id}/role on the evaluator fixture`
Designated target: `auth_batch_preflight`
Finding concept: Observed behavior: authorizes and commits operations sequentially. Violated invariant: If any operation is unauthorized, every operation is rejected and no object changes.

Planned checks:
- `auth_batch_preflight` (target): If any operation is unauthorized, every operation is rejected and no object changes.
- `auth_batch_subject_snapshot` (guard): All operations use one immutable subject-role snapshot.
- `auth_batch_object_scope` (guard): Authorization is evaluated for each concrete object and action.
- `auth_batch_versions` (guard): Authorized operations still require all expected versions.
- `auth_batch_replay` (guard): Canonical identical command replay returns the original result; conflict rejects.

### `cache-idempotency`

identity-consistent caching, replay, invalidation, and duplicate suppression

#### `version-fenced-read-cache`

read-through cache entries accepted only when their source version fence still matches the authoritative record

Interface: `fenced_cache.create_app(source: SourceProtocol); public get|update|invalidate service methods persist cache in caller DB and return canonical result objects`
Designated target: `cache_version_fence`
Finding concept: Observed behavior: writes a computed cache value without comparing the source version at cache commit. Violated invariant: A cache fill may publish only if the authoritative version still equals the version read before computation.

Planned checks:
- `cache_version_fence` (target): A cache fill may publish only if the authoritative version still equals the version read before computation.
- `cache_key_isolation` (guard): Cache identity includes the complete canonical resource key.
- `cache_update_invalidation` (guard): Successful source update invalidates only older cache versions.
- `cache_restart` (guard): Version fences and entries remain coherent across process restart.
- `cache_output_provenance` (guard): Get reports value, source version, and hit/miss consistently.

#### `canonical-idempotent-command`

idempotency binding over a semantic canonical command rather than raw JSON bytes or key alone

Interface: `idempotent_cmd.main:app; POST /commands with Idempotency-Key; GET /commands/{key}`
Designated target: `idempotency_semantic_binding`
Finding concept: Observed behavior: binds the key only and replays the first response for any later payload. Violated invariant: Equivalent lexical commands replay one result, while semantically different commands under the same key conflict.

Planned checks:
- `idempotency_semantic_binding` (target): Equivalent lexical commands replay one result, while semantically different commands under the same key conflict.
- `idempotency_concurrent_first` (guard): Concurrent identical first submissions create one effect and one response.
- `idempotency_canonical_decimal` (guard): Allowed decimal lexical forms share the frozen canonical amount.
- `idempotency_tag_set` (guard): Distinct tags are order-insensitive after sorting; any duplicate tag rejects.
- `idempotency_response_replay` (guard): Replay returns the exact original committed response and status semantics.

#### `negative-cache-invalidation`

negative lookup caching whose absence generation is invalidated by create and never masks a newly committed object

Interface: `negative_cache.create_app(store: StoreProtocol, observer: FillObserver); GET/POST /tenants/{tenant}/objects/{id}; POST /tenants/{tenant}/cache/expire`
Designated target: `negative_create_invalidation`
Finding concept: Observed behavior: stores a negative cache entry after create without checking the namespace generation. Violated invariant: A cached absence cannot be served after a successful create, including when a prior miss completes late.

Planned checks:
- `negative_create_invalidation` (target): A cached absence cannot be served after a successful create, including when a prior miss completes late.
- `negative_ttl_boundary` (guard): Negative entries expire exactly at the documented instant.
- `negative_namespace_isolation` (guard): Absence generations are isolated by tenant namespace.
- `negative_positive_precedence` (guard): Authoritative positive state always outranks any negative entry.
- `negative_restart` (guard): Generation and expiry semantics survive restart.

#### `singleflight-scope-key`

request coalescing keyed by complete authorization and representation scope so only truly equivalent work shares a result

Interface: `singleflight_api.create_app(renderer: AsyncRendererProtocol); POST /render body tenant,subject,resource,locale,format`
Designated target: `singleflight_complete_scope`
Finding concept: Observed behavior: coalesces only by resource ID. Violated invariant: Only requests identical in tenant, authorization subject, resource, locale, and format may share an in-flight result.

Planned checks:
- `singleflight_complete_scope` (target): Only requests identical in tenant, authorization subject, resource, locale, and format may share an in-flight result.
- `singleflight_one_backend` (guard): Equivalent simultaneous requests invoke the backend once.
- `singleflight_failure_cleanup` (guard): A failed shared computation reaches all waiters and removes its in-flight key.
- `singleflight_cancel_isolation` (guard): Cancelling one waiter does not cancel work needed by remaining waiters.
- `singleflight_result_copy` (guard): Each caller receives an immutable-equivalent result without shared mutable aliasing.

### `streaming-parser-boundaries`

incremental parsing across arbitrary chunk boundaries with bounded failure-atomic output

#### `incremental-utf8-decoder`

strict UTF-8 decoding and newline record emission across arbitrary byte chunks without replacement or premature output

Interface: `python -m utf8_stream.decode --chunks CHUNKS_JSON --output RECORDS_JSON`
Designated target: `utf8_split_codepoint`
Finding concept: Observed behavior: raises controlled rejection when a non-final chunk ends inside an otherwise valid code point, while retaining strict EOF validation for genuinely truncated input. Violated invariant: A multibyte code point split across any non-final chunk boundary decodes exactly once without replacement.

Planned checks:
- `utf8_split_codepoint` (target): A multibyte code point split across any non-final chunk boundary decodes exactly once without replacement.
- `utf8_invalid_sequences` (guard): Overlong, surrogate, stray continuation, and truncated sequences reject strictly.
- `utf8_newline_split` (guard): LF framing works when newline and adjacent bytes cross chunks.
- `utf8_final_record` (guard): A valid final unterminated record is emitted once.
- `utf8_output_atomicity` (guard): No partial record file replaces prior output on late invalid bytes.

#### `length-prefixed-frame-parser`

bounded big-endian length-prefixed frame parsing across arbitrary chunks with exact EOF and allocation limits

Interface: `python -m frame_parser.parse --chunks CHUNKS_JSON --max-frame N --output FRAMES_JSON`
Designated target: `frame_split_prefix_payload`
Finding concept: Observed behavior: assumes each chunk begins on a frame boundary. Violated invariant: Prefixes and payloads may be split at every chunk boundary and yield identical frames.

Planned checks:
- `frame_split_prefix_payload` (target): Prefixes and payloads may be split at every chunk boundary and yield identical frames.
- `frame_max_before_alloc` (guard): Oversize lengths reject before allocating or waiting for payload.
- `frame_truncated_eof` (guard): EOF with partial prefix or payload rejects.
- `frame_zero_and_multiple` (guard): Zero-length and adjacent frames retain exact order.
- `frame_endianness` (guard): Length is unsigned big-endian exactly.

#### `ndjson-transactional-ingest`

incremental NDJSON ingestion where one malformed or truncated record rolls back the complete stream batch

Interface: `python -m ndjson_ingest.cli --chunks CHUNKS_JSON --db DB --batch-id ID; canonical report is emitted on stdout after commit`
Designated target: `ndjson_late_error_rollback`
Finding concept: Observed behavior: the malformed-JSON/EOF exception path commits previously staged valid records instead of rolling them back; duplicate and schema-error paths still roll back. Violated invariant: Any malformed JSON or truncated final record leaves no rows or batch marker.

Planned checks:
- `ndjson_late_error_rollback` (target): Any malformed JSON or truncated final record leaves no rows or batch marker.
- `ndjson_chunk_framing` (guard): Records parse identically under arbitrary byte chunking.
- `ndjson_duplicate_event` (guard): Duplicate event IDs within/across batches reject under frozen semantics.
- `ndjson_batch_replay` (guard): Same batch and canonical stream replays the original report; conflict rejects.
- `ndjson_report` (guard): Report count and digest bind the committed canonical records in input order.

#### `streaming-csv-quoted-records`

RFC4180-style quoted CSV records parsed across chunks with embedded CRLF, escaped quotes, and bounded field size

Interface: `python -m csv_stream.parse --chunks CHUNKS_JSON --max-field-bytes N --output ROWS_JSON`
Designated target: `csv_quoted_chunk_state`
Finding concept: Observed behavior: parses each chunk as an independent CSV fragment. Violated invariant: Quoted fields with embedded CRLF and doubled quotes parse identically across arbitrary chunk splits.

Planned checks:
- `csv_quoted_chunk_state` (target): Quoted fields with embedded CRLF and doubled quotes parse identically across arbitrary chunk splits.
- `csv_header_exact` (guard): Header names, order, uniqueness, and count are exact.
- `csv_row_width` (guard): Every row has exactly the header field count, including empty trailing fields.
- `csv_field_limit` (guard): Decoded field bytes are bounded during streaming before unbounded accumulation.
- `csv_strict_eof` (guard): EOF inside a quoted field or after bare CR rejects.

## Preventive evidence shape

- 24 candidates across 6 families
- 120 planned singleton mutants
- 480 candidate-versus-prior comparisons
- 276 within-bank pair comparisons
- Selection is seeded and mechanical; no target-model screening is authorized
- Fewer than 12 qualified candidates means no V5 launch

## Next gate

Independent read-only review must return GO before visible bundles, references, hidden evaluators, or mutants are implemented. This artifact does not authorize provider calls.
