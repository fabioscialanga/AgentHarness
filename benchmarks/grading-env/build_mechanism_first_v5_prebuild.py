from __future__ import annotations

import hashlib
import itertools
import json
import os
import tempfile
import fcntl
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "grading-env" / "mechanism-first-v5"
BASE_COMMIT = "95649a6ae0cbbbaf770f7f1363fbe6cc35d79f77"
DATE = "2026-08-24"
SELECTION_SEED = "agentharness-mechanism-first-v5-admission-v1"

GLOBAL_CONTRACTS = {
    "id_grammar": "ASCII [A-Za-z0-9][A-Za-z0-9._-]{0,63}; Unicode aliases, surrounding whitespace, and empty IDs reject",
    "rfc3339": "UTF-8 RFC3339 with Z or explicit numeric offset; compared as instants; leap seconds and naive timestamps reject",
    "canonical_json": "UTF-8 JSON, sorted object keys, compact separators, ensure_ascii=false; duplicate object keys and non-finite numbers reject",
    "http_errors": "FastAPI validation 422; unknown scoped object 404; stale version/token 412; state/idempotency conflict 409; no error body contains foreign or partial object state",
    "cli_errors": "controlled input or validation failure returns nonzero, writes one diagnostic to stderr, emits no success JSON, and preserves the documented commit boundary",
    "qualification_sync": "cross-process probes use an evaluator-owned barrier that releases already-started clients simultaneously; no implementation-private synchronization hook is required",
    "qualification_failures": "failure-atomicity probes use invalid inputs, SQLite constraints/triggers, or evaluator-owned output adapters frozen before implementation; process-kill recovery is a separate qualification class",
    "post_commit_result": "for stateful operations, commit persists the canonical result in the same durable resource; later file/stdout delivery failure is not a rejection and retry re-renders the persisted result without repeating effects",
}

NORMATIVE_PROFILES = {
    "ack-token-work-queue": "All success output is canonical JSON envelope {status:ok,result}; result command re-emits the originally stored envelope byte-for-byte. Exact inputs: init {}; enqueue {request_id,job_id,payload_object}; claim {request_id,worker,now,lease_seconds}; ack/nack {request_id,worker,job_id,token,now}; get {job_id,now}; result {request_id}. init result={initialized:true}; empty claim result=null; every job result exact keys={job_id,payload,state,worker,token,expires_at,attempts}. States are available->claimed->completed, claimed->available on valid nack or when caller now>=expires_at; worker/token/expires_at are nonnull only while claimed; attempts starts 0 and increments exactly on successful claim. Token is 64 lowercase hex characters encoding 32 bytes. Same request_id+canonical request replays exact envelope; mismatched reuse is controlled conflict without change.",
    "semaphore-permit-registry": "init fixes integer capacity 1..64; acquire JSON={request_id,owner,now,ttl_seconds}; release/renew require 32-hex token; expiry is now>=expires_at; active permits count inside BEGIN IMMEDIATE; result JSON sorts permit IDs.",
    "epoch-guarded-leader-heartbeat": "campaign is initialized with canonical campaign_id and ttl_seconds; acquire/renew/publish use caller-supplied RFC3339 now; epoch starts at 1 and increments only on ownership transfer; publish stores payload SHA-256 and canonical result in SQLite.",
    "atomic-snapshot-publisher": "Input is only inline JSON exact fields={request_id,expected_generation,generation,files{name:lowercase_even_hex}}; no source tree exists. Empty root means generation 0 and absent CURRENT. Names obey ID grammar with no slash; generation=expected_generation+1. Durable directory is root/generations/{generation as 20 zero-padded decimal}/ containing data/{name} decoded bytes and manifest.json; manifest/CURRENT/output are identical canonical JSON {generation,files:[{name,size,sha256}]} sorted by name. root/.publish.lock uses flock LOCK_EX before reading CURRENT through temp-file fsync+os.replace of CURRENT; generation dir is temp+rename first, and any pre-CURRENT failure removes that new generation dir.",
    "transactional-outbox-order": "outbox_order.create_app(db_path) exposes POST /orders/{order_id}/confirm body={command_id,account,amount,expected_version}, GET /outbox?after_seq&limit, POST /outbox/{event_id}/ack body={now RFC3339}. amount is a JSON string matching (0|[1-9][0-9]*)(\\.[0-9]{1,2})?, range 0..999999999.99; strings '1','1.0','1.00' are equivalent integer cents and rounding is forbidden. SQLite schema is orders(order_id,account,amount_cents,version,status), outbox_events(commit_seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id UNIQUE,aggregate_id,type,payload_json,version,acknowledged_at), command_results(command_id,request_hash,status_code,response_json). payload_json is canonical {account,amount_cents,order_id,type,version}; polling returns {events:[{commit_seq,event_id,aggregate_id,type,payload,version,acknowledged_at}],next_after_seq} ascending; first ack stores caller now and replay is unchanged.",
    "saga-compensation-engine": "plan JSON has saga_id and 1..16 unique step IDs with forward and compensation fixture outcomes; completion journal sequence is authoritative; compensation executes only completed uncompensated steps in descending completion sequence and records each result idempotently.",
    "atomic-batch-state-machine": "entities use states pending,active,suspended,closed and legal transitions pending->active, active<->suspended, active|suspended->closed; request has command_id and 1..32 unique entity operations; response and errors use canonical entity-id order and zero-based failing index.",
    "durable-retry-scheduler": "base_delay_seconds 1..3600, max_delay_seconds=86400; after failed attempt n (1-based), next_at=now+min(max_delay_seconds,base_delay_seconds*2**(n-1)); claim order is next_at then job_id; tokens are 32 lowercase hex; result is stored with request_id.",
    "canonical-query-signature": "algorithm is HMAC-SHA256 with lowercase 64-hex signature; canonical payload is uppercase method, RFC3986 path with uppercase percent hex, query pairs percent-encoded then sorted by encoded key/value preserving duplicates, selected lowercase headers with trimmed SP runs, lowercase body SHA-256, nonce,timestamp,key_id joined by LF; keyring gives hex keys and [not_before,not_after).",
    "envelope-context-decryptor": "algorithm is AES-256-GCM; key is 32 bytes hex, nonce 12 bytes hex, tag 16 bytes hex; AAD is canonical JSON of tenant,purpose,object_id,schema_version,key_id; envelope fields are exact and ciphertext is lowercase hex; plaintext output replaces prior file only after tag verification.",
    "rotating-key-token-verifier": "token is canonical unpadded base64url(header).base64url(payload).base64url(HMAC-SHA256); header exact alg=HS256,kid; payload exact iss,aud list,sub,iat,nbf,exp,jti; audience is exact case-sensitive membership; key validity and nbf are inclusive, exp and key end exclusive.",
    "merkle-batch-proof-verifier": "hash is SHA-256 with leaf H(0x00||u32be(index)||u32be(len)||leaf) and node H(0x01||left||right); odd node is promoted unchanged; proof steps are exact L/R plus 32-byte sibling hex; root and report are lowercase hex/canonical JSON.",
    "tenant-scoped-resource-api": "fixture initializes tenants, signed subjects, roles reader|writer, and colliding resource IDs; GET collection sorts by resource_id; PATCH body={expected_version,value}; X-Tenant/X-Subject are canonical IDs verified against fixture signatures; foreign and absent both return identical 404 JSON.",
    "attenuated-capability-verifier": "capability is canonical JSON signed HMAC-SHA256; root has tenant,subject,resource_prefix,actions,not_before,expires_at,depth; each child embeds parent digest and may only narrow prefix/actions/time while depth increments by one; verify-at uses caller RFC3339.",
    "field-projection-authorization": "field_auth.create_app(db_path,policy_store) uses importable field_auth.interfaces definitions: @dataclass(frozen=True) Policy(read_allow:frozenset[str],read_deny:frozenset[str],write_allow:frozenset[str],write_deny:frozenset[str]); class PolicyStoreProtocol(Protocol): def policy(self,tenant_id:str,subject_id:str,resource_type:str)->Policy. create_app calls policy(tenant, X-Subject, 'profile') synchronously. Effective readable=read_allow-read_deny and writable=write_allow-write_deny; deny always wins and all sets must be catalog subsets. GET/PATCH paths are /tenants/{tenant}/resources/{id}; PATCH exact {expected_version,fields}. SQLite table resources(tenant_id,resource_id,version,display_name,first_name,last_name,salary_cents,PRIMARY KEY(tenant_id,resource_id)) is evaluator-initialized; names are nonempty 1..128-codepoint strings, salary_cents integer 0..99999999999. Catalog/order is resource_id,display_name,first_name,last_name,salary_cents,initials; returning initials requires initials,first_name,last_name all effectively readable before loading and concatenates first codepoints; initials/resource_id are read-only. Success exact {resource_id,version,fields}; unknown/duplicate names 422 {detail:invalid_fields}; foreign/absent identical 404 {detail:not_found}.",
    "atomic-authorized-batch": "auth_batch.create_app(role_store: RoleStoreProtocol) exposes POST /batch body={command_id,subject,tenant,operations[object_id,action,expected_version,value]}; RoleStoreProtocol.snapshot(subject) captures immutable roles/version, calls public observer.snapshot_started(), then awaits observer.release_snapshot(); the app calls snapshot exactly once before preflight; operations sort by object_id; any denial/stale version changes nothing.",
    "version-fenced-read-cache": "create_app(source: SourceProtocol) is public; source.read returns {value,version} and qualification source exposes wait_started/release; cache key is tenant/resource; fill publishes only with source.compare_version; update increments integer version and persists canonical result.",
    "canonical-idempotent-command": "amount grammar and cents canonicalization match transactional-outbox-order; body exact account,operation debit|credit,amount,tags; tags are distinct canonical IDs and sort lexically; semantic hash is SHA-256 canonical JSON; key,hash,effect,response commit together.",
    "negative-cache-invalidation": "create_app(store: StoreProtocol, observer: FillObserver) is public; observer exposes wait_miss_started/release for qualification; authoritative tenant generation increments with create; negative key={tenant,object_id,generation,expires_at}; positive state always wins.",
    "singleflight-scope-key": "create_app(renderer: AsyncRendererProtocol) is public; renderer fixture exposes call_count, wait_started, release, fail_next, and cancellation; in-flight key is canonical JSON of tenant,subject authorization digest,resource,locale,format; completed values are never retained by singleflight.",
    "incremental-utf8-decoder": "CHUNKS_JSON is an array of lowercase even-length hex strings totaling <=1MiB; strict RFC3629 UTF-8 only; LF byte delimits records after decoding; maximum decoded record is 65536 UTF-8 bytes; parser retains at most one record plus 3 decoder bytes and writes a temp output then rename.",
    "length-prefixed-frame-parser": "CHUNKS_JSON hex totals <=2MiB; frame prefix is exactly unsigned u32 big-endian and max-frame 0..1048576; output is canonical JSON array of lowercase payload hex; parser retains four prefix bytes plus one bounded frame and temp output.",
    "ndjson-transactional-ingest": "CHUNKS_JSON hex totals <=2MiB; each line is canonicalizable JSON object with exact event_id canonical ID and integer value; max line 65536 bytes; duplicate keys/nonfinite values reject; report={batch_id,count,sha256} over LF-joined canonical records and is stored in batch row.",
    "streaming-csv-quoted-records": "CHUNKS_JSON hex totals <=2MiB; UTF-8 RFC3629, exact header id,name,value, CRLF records, comma separator, doubled-quote escaping, no bare CR/LF in unquoted fields; max-field-bytes applies to decoded UTF-8 bytes; output temp file is canonical JSON rows then rename.",
}

QUALIFICATION_CONTROLS = {
    "version-fenced-read-cache": "Evaluator supplies the public blocking SourceProtocol, waits for the old-version read signal, commits an update, then releases the fill and observes compare_version plus cache provenance.",
    "negative-cache-invalidation": "Evaluator supplies StoreProtocol and FillObserver, waits for a miss observation, commits create/generation increment, then releases negative publication and checks the authoritative object.",
    "singleflight-scope-key": "Evaluator supplies AsyncRendererProtocol with explicit start/release/fail/cancel controls and call_count; all interleavings are driven through that public dependency.",
    "atomic-authorized-batch": "Evaluator supplies RoleStoreProtocol: snapshot captures roles/version, signals observer.snapshot_started, blocks on observer.release_snapshot; evaluator mutates its role store after the signal, releases, and verifies the app used exactly the captured snapshot for every operation.",
    "atomic-snapshot-publisher": "Evaluator acquires root/.publish.lock with flock LOCK_EX before starting the CLI, verifies publication blocks before reading CURRENT, then releases; immutable generation directories and CURRENT rename define the two observable publication boundaries.",
    "transactional-outbox-order": "Evaluator initializes the frozen orders/outbox_events/command_results schema and installs BEFORE INSERT ON outbox_events RAISE(ABORT); POST then deterministically exercises rollback without any implementation-private name or hook.",
    "durable-retry-scheduler": "Evaluator installs SQLite abort triggers independently on history and schedule writes and verifies rollback/restart through the public CLI.",
    "epoch-guarded-leader-heartbeat": "Independent clients use the evaluator barrier and caller-supplied time; a SQLite read transaction freezes the old epoch while ownership transfer commits in another process.",
}

FAMILIES = {
    "concurrency-ownership": "exclusive ownership, stale-actor rejection, and publication under simultaneous operations",
    "transactional-transitions": "failure-atomic multi-record state transitions and compensating state machines",
    "cryptographic-binding": "canonical messages, key context, and proof verification bound to the intended object",
    "authorization-isolation": "subject, tenant, scope, and response-data authorization without cross-boundary disclosure",
    "cache-idempotency": "identity-consistent caching, replay, invalidation, and duplicate suppression",
    "streaming-parser-boundaries": "incremental parsing across arbitrary chunk boundaries with bounded failure-atomic output",
}

PRIOR = {
    "support-ticket-api": "support-ticket state transitions, assignment, filtering, and API persistence",
    "csv-member-import": "CSV normalization, duplicate handling, accepted/rejected rows, and import summaries",
    "incident-escalation-api": "time-based incident escalation and timezone-aware state transitions",
    "inventory-adjustment-api": "transactional inventory adjustments, recount semantics, and stock invariants",
    "leave-request-api": "overlap-aware leave approval and terminal workflow states",
    "refund-approval-api": "threshold-based staged refund authorization",
    "report-export-job": "deterministic filtered report generation, totals, and output formatting",
    "webhook-ingestion-service": "HMAC-authenticated ingestion, idempotency, and event normalization",
    "appointment-booking-api": "resource interval scheduling, conflicts, cancellation, and availability",
    "shipment-event-api": "append-only shipment events, idempotency, ordering, projection, and terminal states",
    "jsonl-event-aggregation": "JSONL validation, UTC normalization, duplicate semantics, rejection, and aggregation",
    "invoice-payment-reconciliation": "decimal invoice/payment matching, cutoff semantics, duplicates, and financial summaries",
    "dependency-impact-planner": "reverse dependency closure, topological levels, cycle rejection, and canonical plans",
    "access-policy-evaluator": "wildcard policy matching, subject/group composition, deny precedence, and temporal validity",
    "versioned-document-api": "optimistic concurrency, JSON Merge Patch, immutable revisions, and historical restore",
    "safe-archive-extraction": "ZIP path and entry safety, normalized collisions, limits, and extraction manifests",
    "signed-artifact-verifier": "offline signed-manifest trust, exact inventory, key windows, and content integrity",
    "pii-redaction-pipeline": "recursive selector-driven redaction, keyed pseudonymization, and field-level audit",
    "lease-coordination-api": "durable expiring mutual exclusion with monotonic fencing tokens",
    "double-entry-ledger-api": "immutable balanced posting, idempotency, balances, and compensating reversal",
}


def check(check_id: str, contract: str, probe: str, mutant: str, atomicity: str) -> dict[str, str]:
    return {
        "id": check_id,
        "public_contract": contract,
        "planned_probe": probe,
        "planned_mutant": mutant,
        "failure_atomicity": atomicity,
    }


def candidate(
    candidate_id: str,
    family_id: str,
    interface_kind: str,
    construct: str,
    entrypoint: str,
    input_contract: str,
    state_boundary: str,
    target: dict[str, str],
    guards: list[dict[str, str]],
    finding: str,
    reasoning_steps: list[str],
    near_miss: str,
    latent_invariant: str = "",
    adversarial_axis: str = "",
    repair_mechanism_class: str = "",
    discriminating_counterexample: str = "",
) -> dict[str, Any]:
    assert len(guards) == 4
    return {
        "candidate_id": candidate_id,
        "family_id": family_id,
        "interface_kind": interface_kind,
        "construct": construct,
        "public_interface": {
            "entrypoint": entrypoint,
            "input_contract": input_contract,
            "state_or_output_boundary": state_boundary,
            "failure_contract": "controlled input, authorization, precondition, or transaction rejection preserves the documented durable pre-state; a post-commit delivery failure follows global_contracts.post_commit_result and never rolls back or repeats a committed effect",
        },
        "target_check_id": target["id"],
        "checks": [target, *guards],
        "finding_concept": finding,
        "private_static_reasoning_rubric": reasoning_steps,
        "independent_near_miss": near_miss,
        "latent_invariant": latent_invariant or target["public_contract"],
        "adversarial_axis": adversarial_axis or target["planned_probe"],
        "repair_mechanism_class": repair_mechanism_class or "restore the violated public invariant without weakening sibling guards",
        "discriminating_counterexample": discriminating_counterexample or f"An implementation can satisfy all four guards while exhibiting only: {target['planned_mutant']}.",
        "admission_status": "candidate",
    }


CANDIDATES = [
    candidate(
        "ack-token-work-queue", "concurrency-ownership", "SQLite CLI",
        "durable work claims whose opaque acknowledgement token prevents a timed-out worker from committing another worker's item",
        "python -m ack_queue.cli init|enqueue|claim|ack|nack|get|result --db DB --request JSON --output JSON",
        "command-specific exact JSON follows normative_profile; every mutating request carries request_id; token is 64 lowercase hex characters encoding 32 bytes",
        "one SQLite transaction per mutating command stores queue state and request result; output is emitted only after durable state",
        check("ack_stale_worker_rejected", "After timeout and reclaim, only the newest opaque ack token may complete the item.", "Claim, expire, reclaim, then race old and new acknowledgements.", "accepts an acknowledgement by item and worker while ignoring the current opaque token", "a stale acknowledgement changes neither item state nor attempt count"),
        [
            check("ack_single_claim", "Simultaneous claims expose one durable owner.", "Barrier-start two claim processes.", "returns the same available item successfully to two claimants", "the loser leaves ownership unchanged"),
            check("ack_visibility_timeout", "Visibility expires at the exact documented instant.", "Probe just before, at, and after expiry.", "uses a strict-greater comparison at expiry", "boundary reads do not mutate the queue"),
            check("ack_nack_requeues", "A valid nack requeues once without changing payload.", "Nack and reclaim across process restart.", "drops the payload when requeuing", "invalid nack preserves payload and owner"),
            check("ack_attempt_accounting", "Every successful claim increments a persistent attempt counter once.", "Replay and concurrent claim probes.", "increments attempts on losing claims", "failed claims do not change counters"),
        ],
        "The completion path authorizes by worker identity but does not bind the acknowledgement to the current claim generation; require the current opaque ack token before committing completion.",
        ["trace the token from claim response to durable current ownership", "make completion compare the supplied token atomically with the current generation"],
        "checks a token before the transaction but fails to compare it again in the conditional update",
    ),
    candidate(
        "semaphore-permit-registry", "concurrency-ownership", "FastAPI + SQLite",
        "bounded cross-process permits with unique lease identities and exact capacity under simultaneous acquire/release",
        "semaphore_api.main:app; POST /pools/{id}/acquire, POST /permits/{token}/release, GET /pools/{id}",
        "pool capacity is integer 1..64; holder and pool IDs follow the frozen grammar; extra fields rejected",
        "capacity and active permits live in one SQLite database and every response reflects committed state",
        check("permit_capacity_contention", "At most capacity simultaneous acquisitions succeed, including under a barrier-start race.", "Launch capacity+2 independent processes against one pool.", "checks capacity before insert without a transactionally protected predicate", "losing acquisitions create no permit or counter drift"),
        [
            check("permit_unique_token", "Every successful acquisition receives a unique opaque token.", "Acquire/release/reacquire across restart.", "derives tokens only from holder ID", "collision rejection preserves active permits"),
            check("permit_release_once", "A permit can be released exactly once by its token.", "Double and concurrent release.", "treats repeated release as a second success", "repeated release does not alter available capacity"),
            check("permit_pool_isolation", "Contention and counts are isolated per pool.", "Operate two pools with the same holders.", "uses one global active count", "one pool never mutates another"),
            check("permit_snapshot", "GET returns capacity, active count, and sorted active token metadata consistently.", "Read during completed operations and restart.", "reports capacity minus releases rather than counting active permits", "reads are non-mutating"),
        ],
        "Capacity is checked separately from permit insertion, allowing simultaneous contenders to oversubscribe; serialize the capacity predicate and insertion in one database transaction.",
        ["identify the check-then-insert race across processes", "enforce capacity in the same locked/conditional commit that creates the permit"],
        "adds an in-process mutex that does not coordinate independent service processes",
    ),
    candidate(
        "epoch-guarded-leader-heartbeat", "concurrency-ownership", "SQLite CLI",
        "leader heartbeats fenced by a monotonically increasing epoch so a paused former leader cannot extend or publish after takeover",
        "python -m epoch_leader.cli acquire|heartbeat|publish|status --db DB --request JSON --output JSON",
        "cluster and leader IDs are canonical ASCII IDs; request-supplied instants and durations are explicit and bounded",
        "epoch allocation, current leader, expiry, and publication sequence are transactionally durable",
        check("leader_stale_epoch_publish", "Heartbeat and publish require both current leader identity and current epoch.", "Acquire, expire, take over, then invoke old leader operations.", "authorizes publish by leader ID while ignoring the supplied epoch", "stale operations preserve current leader and publication log"),
        [
            check("leader_epoch_monotonic", "Every takeover increments the persistent epoch.", "Take over across restart.", "resets epoch after no active leader", "failed acquire does not consume an epoch"),
            check("leader_one_winner", "Simultaneous acquisition has one durable winner.", "Barrier-start two processes.", "reports success before checking conditional-update row count", "loser creates no heartbeat"),
            check("leader_expiry_boundary", "Takeover is allowed exactly at expiry, not before.", "Probe adjacent boundary instants.", "uses expiry < now instead of expiry <= now", "early takeover preserves state"),
            check("leader_publication_order", "Current leader publications receive persistent contiguous sequence numbers.", "Concurrent publishes and restart.", "allocates sequence outside the commit", "failed publish leaves no sequence gap"),
        ],
        "The publish authorization verifies the leader name but not its fencing epoch, so a resumed stale process can publish after takeover; compare both identity and epoch atomically.",
        ["follow epoch issuance across takeover", "bind every privileged mutation to the persisted current epoch"],
        "checks the epoch only in heartbeat while leaving publish guarded by identity alone",
    ),
    candidate(
        "atomic-snapshot-publisher", "concurrency-ownership", "filesystem CLI",
        "multi-writer publication of immutable snapshots through generation compare-and-swap and one atomic current pointer",
        "python -m snapshot_publish.cli publish --root ROOT --request REQUEST_JSON --output JSON",
        "exact JSON request_id,expected_generation,generation,files object; file names are canonical IDs without slash and values are lowercase even-length hex bytes",
        "immutable generation directory is completed before one atomic current-manifest replacement; losing writers leave no visible generation",
        check("snapshot_compare_and_swap", "Only one writer with the same expected generation may publish the next generation.", "Barrier-start writers with distinct content and inspect current plus residue.", "checks expected generation before staging but replaces current without a commit-time comparison", "loser leaves current and immutable generations byte-identical"),
        [
            check("snapshot_inline_integrity", "Published manifest exactly binds every supplied inline name and decoded byte string by name, size, and SHA-256.", "Change equal-size hex bytes and add or remove map entries.", "omits byte hashes from the manifest", "validation failure preserves current"),
            check("snapshot_name_safety", "Slash, dot-segment, non-ASCII, empty, and noncanonical inline names reject before staging.", "Submit each invalid JSON object key directly.", "accepts names outside the frozen ID grammar", "unsafe input creates no generation"),
            check("snapshot_generation_contiguity", "Committed generations increase by exactly one without gaps.", "Induce deterministic precommit failure and retry.", "allocates generation before validation", "failed publish leaves no reserved generation"),
            check("snapshot_manifest_order", "Manifest file rows are sorted by canonical name regardless of JSON object insertion order.", "Submit permutations of the same inline files map.", "preserves request object iteration order in the manifest", "rendering does not change current generation"),
        ],
        "The publisher performs generation validation before staging but does not protect the final pointer replacement with the same generation comparison; make the current-generation check and publication commit one CAS boundary.",
        ["separate immutable snapshot preparation from visibility", "guard the single visibility commit against the persisted expected generation"],
        "serializes staging names but still allows two writers to overwrite the current pointer",
    ),
    candidate(
        "transactional-outbox-order", "transactional-transitions", "FastAPI + SQLite",
        "business state and ordered outbox event creation committed together, with retry-safe dispatch acknowledgement",
        "outbox_order.create_app(db_path); POST /orders/{order_id}/confirm, GET /outbox, POST /outbox/{event_id}/ack",
        "POST confirm exact body command_id,account,amount,expected_version; POST ack exact body now; GET /outbox exact after_seq>=0 and limit 1..100; IDs obey global grammar",
        "order transition, canonical event, commit_seq, and command result share one SQLite transaction; ack sets acknowledged_at once and never edits business state",
        check("outbox_commit_coupling", "A confirmed order and its event become durable together or neither does.", "Inject a deterministic failure between state update and event insertion, then restart.", "commits order state before inserting the outbox event", "failure preserves order version and outbox bytes"),
        [
            check("outbox_one_event", "Idempotent replay yields the same single event.", "Replay equivalent requests across restart.", "inserts another event on replay", "conflict adds no event"),
            check("outbox_canonical_payload", "Event payload is canonical and binds the committed order version.", "Compare lexical amount forms and field order.", "serializes request field order directly", "reads do not rewrite events"),
            check("outbox_ordering", "Polling returns events in commit sequence order.", "Commit several orders and acknowledgements.", "orders by event ID text", "polling is non-mutating"),
            check("outbox_ack_once", "Acknowledgement is monotonic and repeat-safe.", "Double/concurrent ack.", "increments an ack count on replay", "unknown ack preserves all rows"),
        ],
        "The order transition commits before its outbox event, permitting durable business state without publishable evidence; place both writes in one transaction and commit only after both succeed.",
        ["identify the two durable records that form one logical transition", "move their writes and failure handling under one commit/rollback boundary"],
        "adds compensation that reopens the order after failure but still exposes a transient committed confirmation",
    ),
    candidate(
        "saga-compensation-engine", "transactional-transitions", "SQLite CLI",
        "durable forward and compensating steps whose restart state never repeats completed effects or skips required compensation",
        "python -m saga_engine.cli start|advance|fail|resume|status --db DB --request JSON --output JSON",
        "workflow definitions contain ordered unique step IDs and paired compensation IDs; command IDs are idempotent",
        "step intent, completion, and compensation status are persisted before exposing the next runnable action",
        check("saga_reverse_compensation", "After a forward failure, completed steps are compensated exactly once in reverse completion order.", "Complete three steps, fail the fourth, restart during compensation.", "compensates in forward declaration order", "failed/replayed compensation does not alter completed siblings"),
        [
            check("saga_forward_once", "Completed forward steps are never emitted again after restart.", "Crash/restart at each durable marker.", "marks completion only after emitting the next action", "resume preserves completed effects"),
            check("saga_compensation_once", "A compensation acknowledgement is idempotent.", "Replay and concurrently acknowledge.", "advances twice on duplicate ack", "duplicate ack preserves cursor"),
            check("saga_terminal_states", "Completed and compensated workflows reject further mutation.", "Invoke all commands on terminals.", "allows resume from compensated", "terminal rejection preserves history"),
            check("saga_history", "Status exposes an immutable ordered transition history.", "Compare history across failures/restarts.", "rewrites forward completion rows as compensated", "reads are non-mutating"),
        ],
        "Compensation follows declaration order rather than reverse completion order, which can violate dependencies; derive compensation from the durable completed-step stack in reverse.",
        ["reconstruct which effects actually committed", "walk the durable completion sequence backward while recording idempotent compensation completion"],
        "reverses the declared list but includes steps that never completed",
    ),
    candidate(
        "atomic-batch-state-machine", "transactional-transitions", "FastAPI + SQLite",
        "all-or-none transitions of multiple versioned entities with validation against the same pre-state",
        "batch_state_api.main:app; POST /batch-transition, GET /entities/{id}",
        "body has exact command_id and nonempty operations; each operation has entity_id, expected_version, transition",
        "all operations validate against one database snapshot and commit in one transaction",
        check("batch_all_or_none", "After structural and legal-transition preflight, all expected versions are checked against one pre-batch snapshot and either every operation commits or none do.", "Place a stale expected version after valid operations that would otherwise commit.", "preflights structure and legal transitions but checks versions and commits sequentially, leaving prior operations committed on a later stale version", "stale-version rejection preserves every entity and command record"),
        [
            check("batch_duplicate_entity", "A batch rejects duplicate entity IDs before mutation.", "Repeat an entity with compatible/conflicting transitions.", "applies duplicate operations sequentially", "rejection preserves all versions"),
            check("batch_error_index", "A rejected batch reports the zero-based index of the first failing preflight or version check without exposing partial results.", "Fail the first, middle, and final operation for distinct reasons.", "reports the final operation index for every rejection", "diagnostic generation is non-mutating"),
            check("batch_idempotent_replay", "Same command and canonical batch replays; conflicting reuse rejects.", "Reorder equivalent operations and conflict payload.", "binds idempotency to raw input order", "conflict preserves state"),
            check("batch_response_order", "Success response uses documented canonical entity order and committed versions.", "Submit permutations.", "returns request order", "response generation is non-mutating"),
        ],
        "The loop commits valid entity transitions before discovering a later stale operation; validate the complete batch against one pre-state and commit all writes in one transaction.",
        ["separate whole-batch validation from mutation", "apply the validated transition set under one transaction with rollback on every error"],
        "wraps each operation in its own transaction rather than the complete batch",
    ),
    candidate(
        "durable-retry-scheduler", "transactional-transitions", "SQLite CLI",
        "retry scheduling whose attempt completion and next-at computation are one durable transition under crash/replay",
        "python -m retry_scheduler.cli enqueue|claim|complete|fail|status --db DB --request JSON --output JSON",
        "jobs have canonical IDs, max_attempts 1..20, RFC3339 now, and integer base_delay_seconds",
        "claim token, attempt number, outcome, and next_at update atomically",
        check("retry_failure_transition", "Failing a current claim records the attempt and either schedules exactly one next attempt or terminals atomically.", "Inject failure between history append and next_at update, then resume.", "commits failed history before writing the next schedule", "transition failure preserves claim, history, and schedule"),
        [
            check("retry_backoff", "next_at follows the exact capped exponential formula from attempt number.", "Probe attempts and cap boundaries.", "uses zero-based exponent after the first failure", "reads do not change schedule"),
            check("retry_current_token", "Only the current claim token may complete/fail.", "Expire/reclaim then use stale token.", "authorizes by worker alone", "stale outcome preserves state"),
            check("retry_max_attempts", "The final allowed failure enters terminal failed without another schedule.", "Exercise max_attempts boundaries.", "schedules one extra attempt", "terminal state has no claim"),
            check("retry_due_order", "Claims select due jobs by next_at then canonical ID.", "Enqueue ties and future jobs.", "orders only by insertion rowid", "claiming one job leaves others unchanged"),
        ],
        "The failure path durably appends attempt history before it durably creates the next schedule, leaving a stranded job after interruption; commit history and next state together.",
        ["enumerate all durable fields of one failed-attempt transition", "write history, terminal/scheduled state, and claim release in one transaction"],
        "on startup infers missing schedules from history but can duplicate an already committed schedule",
    ),
    candidate(
        "canonical-query-signature", "cryptographic-binding", "CLI verifier",
        "request signatures bound to canonical method, path, multivalue query, selected headers, body digest, nonce value, and key/time window",
        "python -m query_signature.verify --request REQUEST --keyring KEYRING --as-of RFC3339 --output REPORT",
        "request JSON has exact method,path,query pairs,headers pairs,body_hex,nonce,timestamp,key_id,signature fields",
        "one deterministic report is atomically replaced only after complete verification",
        check("signature_query_multiplicity", "Canonicalization preserves duplicate query keys, sorts encoded key/value pairs, and distinguishes absent from empty values.", "Sign requests differing only in duplicate values, empty values, and encoding.", "canonicalizes query through a dictionary and drops duplicate keys", "signature failure preserves prior report"),
        [
            check("signature_method_path", "Method and normalized path are signature-bound.", "Alter method, slash, and percent encoding.", "omits method from payload", "rejection writes no success"),
            check("signature_header_selection", "Only the declared lowercase selected headers are normalized and bound.", "Alter selected/unselected headers and whitespace.", "binds header names but not values", "malformed header rejection is atomic"),
            check("signature_body_digest", "Exact body bytes are bound through SHA-256.", "Mutate same-length bytes.", "binds decoded text rather than bytes", "body mismatch preserves report"),
            check("signature_key_window", "The nonce value is signature-bound and key validity uses inclusive-start/exclusive-end request-supplied time.", "Alter the nonce and probe key/time boundaries.", "accepts signatures from a known key after its exclusive validity end", "time rejection preserves prior report"),
        ],
        "The canonicalizer converts query pairs to a mapping, collapsing repeated keys and changing the signed request identity; canonicalize the complete multivalue pair sequence.",
        ["preserve lexical query multiplicity before sorting", "construct and verify the canonical payload from encoded key/value pairs rather than a dictionary"],
        "sorts duplicate keys but also sorts values after decoding, losing encoded-form identity",
    ),
    candidate(
        "envelope-context-decryptor", "cryptographic-binding", "CLI transformer",
        "authenticated envelope decryption bound to tenant, purpose, object ID, algorithm, and key version as associated context",
        "python -m envelope_crypto.decrypt --envelope ENVELOPE --context CONTEXT --keyring KEYRING --output PLAINTEXT",
        "exact JSON schemas; ciphertext, nonce, tag, and keys are lowercase hex; context IDs use frozen grammar",
        "plaintext output is atomically committed only after tag and complete context validation",
        check("envelope_context_binding", "The authentication tag binds canonical tenant, purpose, object ID, algorithm, and key version context.", "Swap each context dimension between otherwise valid envelopes.", "authenticates ciphertext without including purpose in associated data", "authentication failure preserves prior plaintext"),
        [
            check("envelope_key_version", "Only the declared active key version may decrypt.", "Use unknown, retired, and cross-tenant versions.", "selects the latest key regardless of declared version", "key rejection emits no plaintext"),
            check("envelope_nonce_tag", "Nonce/tag lengths and authentication are exact.", "Truncate, extend, and alter tag/nonce.", "accepts truncated tags", "malformed envelope preserves output"),
            check("envelope_schema", "Unknown fields, wrong types, and noncanonical encodings reject.", "Fuzz envelope and context shape.", "ignores extra context fields", "schema rejection is atomic"),
            check("envelope_output_atomicity", "No plaintext or staging residue is visible before full success.", "Inject deterministic precommit failure.", "writes plaintext before tag verification completes", "prior output remains byte-identical"),
        ],
        "The AEAD associated data omits the declared purpose, so ciphertext can be replayed across operations in the same tenant/object; include every frozen context dimension in canonical associated data.",
        ["derive the security identity represented by context", "canonicalize and bind the full context to authentication rather than checking fields after decryption"],
        "checks purpose after successful decryption but authenticates a context that still omits it",
    ),
    candidate(
        "rotating-key-token-verifier", "cryptographic-binding", "CLI verifier",
        "offline token verification with issuer/audience binding, key rotation overlap, retirement, and algorithm pinning",
        "python -m rotating_token.verify --token TOKEN --keyring KEYRING --issuer ISS --audience AUD --as-of RFC3339 --output REPORT",
        "compact token has canonical header/payload/signature; keyring versions have explicit activation and retirement intervals",
        "verification is stateless except atomic report replacement",
        check("token_rotation_window", "A key verifies only during its inclusive activation and exclusive retirement window, including documented overlap.", "Probe old/new keys before, during, and after overlap boundaries.", "accepts any known key version regardless of retirement", "time rejection preserves prior report"),
        [
            check("token_issuer_audience", "Issuer and exact audience are signature-bound and request-matched.", "Swap issuer/audience and audience list order.", "checks issuer but ignores audience", "claim mismatch emits no success"),
            check("token_algorithm_pin", "Header algorithm must exactly match the key's frozen algorithm.", "Try algorithm substitution and none.", "trusts token-declared algorithm", "algorithm rejection is atomic"),
            check("token_time_claims", "nbf is inclusive and exp exclusive against supplied as-of.", "Probe malformed and boundary NumericDate values.", "treats exp as inclusive", "time rejection is non-mutating"),
            check("token_canonical_encoding", "Noncanonical JSON/base64 encodings reject rather than aliasing identity.", "Use padded and duplicate-key variants.", "accepts duplicate JSON keys last-wins", "parse failure preserves report"),
        ],
        "Known retired keys remain accepted because lookup checks key ID but not its activation/retirement interval; apply the request-supplied instant to the selected version before signature acceptance.",
        ["select the exact declared key version", "evaluate that version's half-open validity window before accepting its proof"],
        "checks only token expiration and assumes it cannot outlive the signing key",
    ),
    candidate(
        "merkle-batch-proof-verifier", "cryptographic-binding", "CLI verifier",
        "domain-separated Merkle inclusion proofs bound to tree size, leaf index, ordered sibling direction, and expected root",
        "python -m merkle_verify.verify --proof PROOF --root ROOT --output REPORT",
        "exact JSON with algorithm, tree_size, leaf_index, leaf_hex, and ordered side/hash siblings",
        "deterministic atomic report; no filesystem traversal",
        check("merkle_index_direction", "Proof verification binds every sibling direction to the declared leaf index and tree size.", "Swap directions and reuse a proof at another index.", "sorts child hashes lexically instead of honoring left/right position", "invalid proof preserves prior report"),
        [
            check("merkle_domain_separation", "Leaf and internal node hashes use distinct frozen prefixes.", "Construct ambiguous concatenation trees.", "hashes leaves and nodes without prefixes", "mismatch emits no success"),
            check("merkle_tree_size", "Proof depth and unbalanced-tree behavior are validated against tree_size.", "Use too short/long proofs and non-power-of-two sizes.", "ignores tree_size", "shape rejection is atomic"),
            check("merkle_encoding", "All hashes and leaf bytes use canonical lowercase even-length hex.", "Try uppercase, odd, and malformed hex.", "normalizes uppercase hex instead of rejecting", "parse failure preserves report"),
            check("merkle_root_binding", "Computed root must match the request-supplied expected root exactly.", "Substitute roots and algorithms.", "reports computed root without comparing expected root", "failure writes no success"),
        ],
        "The verifier orders child hashes lexically, making proof validity independent of the leaf's structural position; combine siblings according to the declared side and validate that path against leaf_index/tree_size.",
        ["reconstruct the positional path represented by index and size", "hash ordered left/right children with domain separation at every level"],
        "uses sibling direction but never checks that the direction sequence is compatible with leaf_index",
    ),
    candidate(
        "tenant-scoped-resource-api", "authorization-isolation", "FastAPI + SQLite",
        "resource lookup and mutation whose authorization predicate is inseparable from tenant-scoped database selection",
        "tenant_resource.main:app; GET /resources, GET/PATCH /resources/{id} with signed X-Tenant and X-Subject context",
        "resource IDs may collide across tenants; patch has exact expected_version and value fields",
        "queries and conditional updates include tenant identity in the database predicate",
        check("tenant_lookup_scope", "A resource ID resolves and mutates only within the authenticated tenant, including when another tenant owns the same ID.", "Create the same ID in two tenants; patch one tenant and prove only its row/version changes.", "the conditional update predicates only on globally nonunique resource ID and changes the other tenant's colliding row", "unauthorized/not-found responses disclose no state and mutate nothing"),
        [
            check("tenant_subject_role", "Subject role is evaluated within its tenant membership.", "Reuse subject IDs across tenants.", "loads roles globally by subject ID", "denial preserves resources"),
            check("tenant_version_cas", "Authorized patch requires the tenant-local expected version.", "Use versions from the colliding resource.", "compares version before tenant filter", "stale patch is atomic"),
            check("tenant_error_indistinguishability", "Foreign and nonexistent resources share the documented response shape/status.", "Compare body, headers, and timing class.", "returns forbidden for foreign and not-found for absent", "errors are non-mutating"),
            check("tenant_list_filter", "Collection results contain only the authenticated tenant and stable ordering.", "Populate interleaved tenant rows.", "filters after pagination", "listing is non-mutating"),
        ],
        "Resource lookup uses the globally colliding object ID before tenant scope, allowing cross-tenant data to be loaded and distinguished; include tenant identity in the primary selection and mutation predicate.",
        ["treat tenant as part of resource identity rather than a post-load attribute", "push tenant scope into read, authorization, and conditional update queries"],
        "scopes reads correctly but the PATCH conditional update omits tenant, so a colliding foreign row changes while read/error guards remain correct",
    ),
    candidate(
        "attenuated-capability-verifier", "authorization-isolation", "CLI verifier",
        "delegated capabilities whose child scope, actions, path prefix, time window, and depth can only narrow the signed parent",
        "python -m capability.verify --chain CHAIN --request REQUEST --keyring KEYRING --as-of RFC3339 --output REPORT",
        "ordered signed capability chain with canonical IDs, subject, actions, path prefix, not-before, expiry, and max_depth",
        "offline verification emits one atomic decision report",
        check("capability_attenuation", "Every delegated capability must be a subset of its parent across actions, path, time, and remaining depth.", "Widen one dimension at a time in otherwise valid signed chains.", "checks signatures but does not reject a child path prefix broader than its parent", "invalid chain preserves prior report"),
        [
            check("capability_chain_signatures", "Each link is signed by the prior authorized delegator over canonical content.", "Swap, alter, and truncate links.", "verifies only the leaf signature", "signature failure emits no allow"),
            check("capability_request_match", "Leaf subject/action/path exactly authorizes the request.", "Probe prefix boundaries and unlisted actions.", "uses substring path matching", "denial is non-mutating"),
            check("capability_time_intersection", "As-of must lie in every half-open link interval.", "Probe parent/child interval boundaries.", "checks only leaf expiry", "time denial preserves output"),
            check("capability_depth", "Delegation count must respect every ancestor's remaining depth.", "Exercise zero and nested depth.", "checks only root max_depth", "depth rejection is atomic"),
        ],
        "The chain validates signatures but permits a child path prefix broader than its parent, violating monotonic attenuation; compare every child scope dimension with the immediate parent.",
        ["compute the effective parent authority as an intersection", "prove the child is a subset before using it as the next delegation authority"],
        "checks action subsets and time windows but treats path prefixes as independent strings",
    ),
    candidate(
        "field-projection-authorization", "authorization-isolation", "FastAPI",
        "response field projection where authorization is applied before derived fields and serialization, preventing forbidden-source inference",
        "field_auth.create_app(db_path, policy_store); GET /tenants/{tenant}/resources/{id}?fields=comma-list; PATCH same path; both require X-Subject header",
        "GET fields are unique canonical names; PATCH exact body expected_version,fields object; PolicyStoreProtocol and success/error JSON follow normative_profile exactly",
        "policy evaluation precedes field loading; each PATCH and version increment commits in one SQLite transaction; forbidden dependencies never enter output or errors",
        check("projection_derived_dependency", "A derived field is authorized only when the subject may read every source field it depends on.", "Request derived fields whose hidden inputs have mixed permissions.", "authorizes the derived field name without checking its source dependencies", "denial returns no partial projected object"),
        [
            check("projection_explicit_fields", "Only explicitly requested and authorized fields appear.", "Request subsets and duplicates.", "returns all authorized fields regardless of request", "invalid request emits no data"),
            check("projection_deny_precedence", "Explicit field deny overrides role allow.", "Compose role and resource denies.", "allow overrides deny", "denial is non-mutating"),
            check("projection_unknown_fields", "Unknown and duplicate fields reject with a data-independent error.", "Mix unknown names with forbidden names.", "silently drops unknown fields", "no partial body"),
            check("projection_order", "Response fields use the frozen canonical order independent of request order.", "Submit permutations.", "preserves requester field order", "reads are non-mutating"),
        ],
        "Derived fields are authorized only by their output name while their restricted source fields are still read, enabling indirect disclosure; require authorization of the complete dependency closure before computation.",
        ["expand requested derived fields to their source dependency closure", "authorize the closure before reading or computing any value and then project canonically"],
        "removes unauthorized sources from output but computes the derived value before filtering",
    ),
    candidate(
        "atomic-authorized-batch", "authorization-isolation", "FastAPI + SQLite",
        "multi-resource command that authorizes every operation against one subject snapshot before any mutation",
        "auth_batch.create_app(role_store); POST /batch, GET /objects/{id}, qualification-only POST /admin/subjects/{id}/role on the evaluator fixture",
        "operations have exact object_id,action,expected_version,value fields; duplicate objects reject",
        "authorization snapshot, version validation, and all writes share one transaction",
        check("auth_batch_preflight", "If any operation is unauthorized, every operation is rejected and no object changes.", "Place one unauthorized operation at each batch position.", "authorizes and commits operations sequentially", "denial preserves all objects and command state"),
        [
            check("auth_batch_subject_snapshot", "All operations use one immutable subject-role snapshot.", "Mutate role metadata concurrently.", "reloads roles between operations", "conflict commits no object"),
            check("auth_batch_object_scope", "Authorization is evaluated for each concrete object and action.", "Mix same action across differently scoped objects.", "authorizes action once for the batch", "denial leaks no object detail"),
            check("auth_batch_versions", "Authorized operations still require all expected versions.", "Mix stale and current versions.", "skips version check after authorization", "stale rejection is atomic"),
            check("auth_batch_replay", "Canonical identical command replay returns the original result; conflict rejects.", "Reorder operations and reuse command ID.", "duplicates mutations on replay", "conflict preserves state"),
        ],
        "The endpoint authorizes and mutates one operation at a time, so an unauthorized later item leaves earlier writes committed; preflight the complete authorization/version set and commit once.",
        ["evaluate authorization and versions for every operation without mutation", "perform all prevalidated writes in one transaction or roll back the complete command"],
        "wraps mutations in one transaction but performs an externally visible side effect before all authorization checks finish",
    ),
    candidate(
        "version-fenced-read-cache", "cache-idempotency", "library + SQLite",
        "read-through cache entries accepted only when their source version fence still matches the authoritative record",
        "fenced_cache.create_app(source: SourceProtocol); public get|update|invalidate service methods persist cache in caller DB and return canonical result objects",
        "keys are canonical IDs; authoritative records expose monotonic integer versions; cache records bind key, version, value",
        "authoritative update commits before cache invalidation; stale cache never overwrites a newer version",
        check("cache_version_fence", "A cache fill may publish only if the authoritative version still equals the version read before computation.", "Pause fill, update source, then release fill.", "writes a computed cache value without comparing the source version at cache commit", "losing fill leaves current cache/source unchanged"),
        [
            check("cache_key_isolation", "Cache identity includes the complete canonical resource key.", "Use colliding IDs in namespaces.", "keys cache only by local ID", "one key never invalidates another"),
            check("cache_update_invalidation", "Successful source update invalidates only older cache versions.", "Update around concurrent reads.", "deletes cache before source commit", "failed update preserves prior valid cache"),
            check("cache_restart", "Version fences and entries remain coherent across process restart.", "Fill/update/restart/get.", "stores version only in memory", "startup is non-mutating"),
            check("cache_output_provenance", "Get reports value, source version, and hit/miss consistently.", "Compare hit, miss, and raced fill.", "reports hit for rejected stale fill", "reads do not change source"),
        ],
        "A delayed fill publishes data computed from an obsolete source version after a newer update; make cache publication conditional on the authoritative version fence still matching.",
        ["capture the source version with the value used for computation", "compare that version atomically at cache publication and discard stale fills"],
        "invalidates on updates but does not stop an already running old fill from repopulating stale data",
    ),
    candidate(
        "canonical-idempotent-command", "cache-idempotency", "FastAPI + SQLite",
        "idempotency binding over a semantic canonical command rather than raw JSON bytes or key alone",
        "idempotent_cmd.main:app; POST /commands with Idempotency-Key; GET /commands/{key}",
        "command has exact account, operation, decimal amount, and an unordered tag list whose duplicate values are invalid; accepted tags canonicalize by sorting",
        "key, canonical request hash, committed effect, and response are persisted atomically",
        check("idempotency_semantic_binding", "Equivalent lexical commands replay one result, while semantically different commands under the same key conflict.", "Vary field order, decimal forms, tag order, and one semantic field.", "binds the key only and replays the first response for any later payload", "conflict creates no effect or response replacement"),
        [
            check("idempotency_concurrent_first", "Concurrent identical first submissions create one effect and one response.", "Barrier-start independent clients.", "executes effect before unique-key insert", "loser creates no effect"),
            check("idempotency_canonical_decimal", "Allowed decimal lexical forms share the frozen canonical amount.", "Use 1, 1.0, 1.00 and invalid forms.", "hashes raw decimal strings", "invalid amount is atomic"),
            check("idempotency_tag_set", "Distinct tags are order-insensitive after sorting; any duplicate tag rejects.", "Permute distinct tags, then submit duplicate tags.", "treats distinct tag order as significant", "duplicate-tag rejection preserves state"),
            check("idempotency_response_replay", "Replay returns the exact original committed response and status semantics.", "Restart then replay.", "recomputes response from mutable current state", "reads do not mutate effects"),
        ],
        "The idempotency table associates only the key with the first result, so conflicting commands silently replay success; persist and compare a canonical semantic request hash before replay.",
        ["define canonical equivalence for every command field", "atomically bind key, canonical hash, effect, and original response, rejecting mismatched reuse"],
        "hashes sorted JSON but leaves semantically equivalent decimal and tag forms distinct",
    ),
    candidate(
        "negative-cache-invalidation", "cache-idempotency", "FastAPI + SQLite",
        "negative lookup caching whose absence generation is invalidated by create and never masks a newly committed object",
        "negative_cache.create_app(store: StoreProtocol, observer: FillObserver); GET/POST /tenants/{tenant}/objects/{id}; POST /tenants/{tenant}/cache/expire",
        "tenant and object IDs are canonical; negative entries bind the complete tenant/object key and authoritative tenant generation",
        "create and namespace generation increment commit together before success",
        check("negative_create_invalidation", "A cached absence cannot be served after a successful create, including when a prior miss completes late.", "Pause a miss fill across object creation and then issue reads.", "stores a negative cache entry after create without checking the namespace generation", "stale negative fill is discarded without changing object"),
        [
            check("negative_ttl_boundary", "Negative entries expire exactly at the documented instant.", "Probe before/at expiry.", "treats expiry as inclusive", "expiry read is non-mutating except allowed cache removal"),
            check("negative_namespace_isolation", "Absence generations are isolated by tenant namespace.", "Create colliding IDs in two tenants.", "uses a global generation", "tenant operations do not evict peers"),
            check("negative_positive_precedence", "Authoritative positive state always outranks any negative entry.", "Inject a stale negative fixture with newer object.", "checks cache before authoritative version metadata", "read does not alter object"),
            check("negative_restart", "Generation and expiry semantics survive restart.", "Miss/create/restart/read.", "stores generation only in memory", "restart introduces no cache entries"),
        ],
        "A delayed negative fill can commit after object creation and mask the new object; bind absence observations to a namespace generation and compare it when publishing the negative entry.",
        ["version the authoritative absence namespace at creation", "publish a negative result only if the observed generation is still current"],
        "deletes existing negatives on create but does not fence in-flight miss computations",
    ),
    candidate(
        "singleflight-scope-key", "cache-idempotency", "async service",
        "request coalescing keyed by complete authorization and representation scope so only truly equivalent work shares a result",
        "singleflight_api.create_app(renderer: AsyncRendererProtocol); POST /render body tenant,subject,resource,locale,format",
        "exact canonical scope fields; deterministic backend fixture and bounded concurrent requests",
        "in-flight entries are removed after completion/failure and results are never persisted across requests",
        check("singleflight_complete_scope", "Only requests identical in tenant, authorization subject, resource, locale, and format may share an in-flight result.", "Overlap requests differing in one scope dimension.", "coalesces only by resource ID", "scope mismatch shares neither data nor error"),
        [
            check("singleflight_one_backend", "Equivalent simultaneous requests invoke the backend once.", "Barrier-start identical calls with a backend counter.", "creates the future after starting backend work", "waiters do not duplicate side effects"),
            check("singleflight_failure_cleanup", "A failed shared computation reaches all waiters and removes its in-flight key.", "Fail once then retry.", "leaves a failed future cached", "failure leaves no durable result"),
            check("singleflight_cancel_isolation", "Cancelling one waiter does not cancel work needed by remaining waiters.", "Cancel one of several waiters.", "propagates waiter cancellation to shared task", "cancellation emits no partial response"),
            check("singleflight_result_copy", "Each caller receives an immutable-equivalent result without shared mutable aliasing.", "Mutate one caller's decoded result.", "returns one mutable object instance", "response mutation does not affect peers"),
        ],
        "The coalescing key contains only resource ID, so requests from different tenants or representations can receive another caller's result; derive the key from the full security and representation scope.",
        ["enumerate every input dimension that can change authorization or bytes", "canonicalize all such dimensions into the in-flight identity before lookup/create"],
        "adds tenant but still omits subject permissions, locale, or output format",
    ),
    candidate(
        "incremental-utf8-decoder", "streaming-parser-boundaries", "streaming CLI",
        "strict UTF-8 decoding and newline record emission across arbitrary byte chunks without replacement or premature output",
        "python -m utf8_stream.decode --chunks CHUNKS_JSON --output RECORDS_JSON",
        "chunks are lowercase hex byte strings; decoded records are LF-delimited Unicode strings; final unterminated record is allowed",
        "one output file is committed only after the full stream validates",
        check("utf8_split_codepoint", "A multibyte code point split across any non-final chunk boundary decodes exactly once without replacement.", "Split valid 2/3/4-byte sequences at every byte while separately probing strict final flush.", "raises controlled rejection when a non-final chunk ends inside an otherwise valid code point, while retaining strict EOF validation for genuinely truncated input", "decode rejection preserves prior output"),
        [
            check("utf8_invalid_sequences", "Overlong, surrogate, stray continuation, and truncated sequences reject strictly.", "Exercise each invalid class.", "uses errors=ignore", "invalid stream emits no records"),
            check("utf8_newline_split", "LF framing works when newline and adjacent bytes cross chunks.", "Split around consecutive and empty records.", "drops empty records", "framing failure is atomic"),
            check("utf8_final_record", "A valid final unterminated record is emitted once.", "End after ASCII and multibyte content.", "requires trailing LF", "read-only parsing"),
            check("utf8_output_atomicity", "No partial record file replaces prior output on late invalid bytes.", "Place invalid sequence after many valid records.", "streams output directly to destination", "prior output byte-identical"),
        ],
        "Each chunk is decoded independently, so code points split between chunks are replaced or rejected despite a valid byte stream; retain incremental decoder state across chunks and flush strictly at EOF.",
        ["distinguish transport chunks from Unicode boundaries", "carry decoder state across chunks and perform one strict final flush before committing output"],
        "carries ordinary two- and three-byte prefixes but rejects a valid four-byte code point split 2+2, while strict invalid-sequence, newline, EOF, and atomic-output guards remain correct",
    ),
    candidate(
        "length-prefixed-frame-parser", "streaming-parser-boundaries", "streaming CLI",
        "bounded big-endian length-prefixed frame parsing across arbitrary chunks with exact EOF and allocation limits",
        "python -m frame_parser.parse --chunks CHUNKS_JSON --max-frame N --output FRAMES_JSON",
        "stream is repeated 4-byte unsigned big-endian length plus payload; zero length allowed; max 1048576",
        "all frames are atomically emitted as lowercase hex only after complete validation",
        check("frame_split_prefix_payload", "Prefixes and payloads may be split at every chunk boundary and yield identical frames.", "Fragment one stream byte-by-byte and in mixed chunks.", "assumes each chunk begins on a frame boundary", "parse failure preserves output"),
        [
            check("frame_max_before_alloc", "Oversize lengths reject before allocating or waiting for payload.", "Declare max+1 with no payload.", "buffers declared payload before checking limit", "oversize creates no output"),
            check("frame_truncated_eof", "EOF with partial prefix or payload rejects.", "Truncate at every byte.", "silently discards trailing partial frame", "late EOF preserves prior output"),
            check("frame_zero_and_multiple", "Zero-length and adjacent frames retain exact order.", "Mix empty/nonempty frames.", "treats zero as stream terminator", "parsing is non-mutating"),
            check("frame_endianness", "Length is unsigned big-endian exactly.", "Use asymmetric prefix bytes.", "decodes little-endian", "invalid length is atomic"),
        ],
        "The parser resets framing state at each transport chunk, so split length prefixes or payloads fail; maintain one bounded state machine independent of chunk boundaries.",
        ["model prefix and payload as persistent parser states", "consume arbitrary chunk slices while retaining only bounded incomplete-frame state"],
        "retains payload state across chunks but requires the four-byte length prefix to be contiguous, so split prefixes fail while size, EOF, zero-frame, and endian guards remain correct",
    ),
    candidate(
        "ndjson-transactional-ingest", "streaming-parser-boundaries", "SQLite CLI",
        "incremental NDJSON ingestion where one malformed or truncated record rolls back the complete stream batch",
        "python -m ndjson_ingest.cli --chunks CHUNKS_JSON --db DB --batch-id ID; canonical report is emitted on stdout after commit",
        "UTF-8 JSON objects separated by LF; exact event_id and value fields; final unterminated object allowed; batch ID idempotent",
        "all records, batch identity, and canonical report JSON stored in the batch row commit in one SQLite transaction after EOF validation; stdout is a post-commit rendering and is not a second durable resource",
        check("ndjson_late_error_rollback", "Any malformed JSON or truncated final record leaves no rows or batch marker.", "Place malformed syntax or truncation after valid records across chunk splits.", "the malformed-JSON/EOF exception path commits previously staged valid records instead of rolling them back; duplicate and schema-error paths still roll back", "controlled malformed-input failure preserves the SQLite database; no success report is emitted"),
        [
            check("ndjson_chunk_framing", "Records parse identically under arbitrary byte chunking.", "Split UTF-8 and newline bytes.", "splits chunks rather than the logical byte stream", "framing error is atomic"),
            check("ndjson_duplicate_event", "Duplicate event IDs within/across batches reject under frozen semantics.", "Use an immediate duplicate before any new valid row, plus a duplicate against a prior committed batch.", "detects duplicates only within one transport chunk", "duplicate rejection preserves all rows"),
            check("ndjson_batch_replay", "Same batch and canonical stream replays the original report; conflict rejects.", "Rechunk equivalent bytes and alter one record.", "binds replay to chunk-array JSON rather than stream bytes", "conflict changes nothing"),
            check("ndjson_report", "Report count and digest bind the committed canonical records in input order.", "Check empty and multi-record streams.", "sorts records before digest", "report generation shares transaction"),
        ],
        "Records are committed as they are parsed, so a late malformed line leaves a partial batch; stage all row effects and commit records, batch identity, and report only after strict EOF validation.",
        ["separate incremental syntax parsing from durable publication", "hold the database transaction or equivalent staging until the final decoder/parser flush succeeds"],
        "deletes inserted rows on error but leaves sequence counters or batch metadata changed",
    ),
    candidate(
        "streaming-csv-quoted-records", "streaming-parser-boundaries", "streaming CLI",
        "RFC4180-style quoted CSV records parsed across chunks with embedded CRLF, escaped quotes, and bounded field size",
        "python -m csv_stream.parse --chunks CHUNKS_JSON --max-field-bytes N --output ROWS_JSON",
        "UTF-8 byte chunks; comma separator; CRLF record boundary; doubled quote escapes; exact header frozen in input",
        "rows JSON is atomically replaced only after full strict stream validation",
        check("csv_quoted_chunk_state", "Quoted fields with embedded CRLF and doubled quotes parse identically across arbitrary chunk splits.", "Split before/inside/after quotes, CRLF, and escape pairs.", "parses each chunk as an independent CSV fragment", "parse failure preserves prior output"),
        [
            check("csv_header_exact", "Header names, order, uniqueness, and count are exact.", "Use duplicate, reordered, and missing headers.", "accepts header columns by set equality", "header rejection emits no rows"),
            check("csv_row_width", "Every row has exactly the header field count, including empty trailing fields.", "Probe short/long/trailing-empty rows.", "drops trailing empty fields", "row rejection is atomic"),
            check("csv_field_limit", "Decoded field bytes are bounded during streaming before unbounded accumulation.", "Feed an unterminated oversized quoted field.", "checks size only after closing quote", "oversize preserves output"),
            check("csv_strict_eof", "EOF inside a quoted field or after bare CR rejects.", "Truncate every terminal state.", "implicitly closes a quote at EOF", "EOF failure writes no partial rows"),
        ],
        "The parser delegates each transport chunk to a fresh CSV reader, losing quote/CRLF state across chunks; implement a bounded persistent parser state machine over the logical byte stream.",
        ["track quoted/unquoted, escape, and CR states independently of chunks", "enforce field bounds while accumulating and commit rows only after strict EOF"],
        "retains quoted-field state across chunks but mishandles a doubled quote split between chunks, while header, row-width, field-limit, and strict-EOF guards remain correct",
    ),
]


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_immutable(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"content-addressed collision at {path}")
        return
    atomic_write(path, data)


HIGH_OVERLAP_DISCRIMINANTS = {
    tuple(sorted(("ack-token-work-queue", "durable-retry-scheduler"))): "A queue can correctly reject stale acknowledgement tokens yet have no failed-attempt history or backoff schedule; a retry scheduler can atomically schedule failures while still allowing a stale worker to acknowledge a reassigned queue job.",
    tuple(sorted(("atomic-batch-state-machine", "atomic-authorized-batch"))): "The state-machine task can pass with no authorization model at all but fail transition preconditions; the authorized-batch task can pass transition atomicity yet fail when one denied item is mixed with allowed items.",
    tuple(sorted(("version-fenced-read-cache", "negative-cache-invalidation"))): "The version-fenced cache can fail by publishing an obsolete positive value even when absence is never cached; the negative-cache task can fail by publishing stale absence after create even when every positive fill is correctly fenced.",
    tuple(sorted(("incremental-utf8-decoder", "length-prefixed-frame-parser"))): "A correct UTF-8 decoder need not understand binary length prefixes; conversely a correct frame parser can preserve arbitrary opaque payload bytes and framing without implementing or guaranteeing UTF-8 decoding.",
    tuple(sorted(("incremental-utf8-decoder", "streaming-csv-quoted-records"))): "Correct UTF-8 carry does not preserve CSV quote/CRLF state, while an ASCII-only CSV parser can satisfy quote framing without implementing multibyte decoder carry.",
    tuple(sorted(("transactional-outbox-order", "ndjson-transactional-ingest"))): "Outbox coupling can fail after a fully valid command due to split business/event commits; NDJSON ingestion can fail before commit because a late record is malformed even when no outbox exists.",
}


def prior_shared(candidate_row: dict[str, object], prior_id: str, prior_construct: str) -> str:
    return (
        f"{candidate_row['candidate_id']} and {prior_id} both expose deterministic validation/state behavior, "
        f"but the former uses {candidate_row['interface_kind']} while the accepted task covers {prior_construct}."
    )


def prior_difference(candidate_row: dict[str, object], prior_id: str, prior_construct: str) -> str:
    return (
        f"{candidate_row['candidate_id']} measures {candidate_row['construct']}; {prior_id} measures {prior_construct}. "
        f"The candidate-specific counterexample is: {candidate_row['discriminating_counterexample']} Correctness on {prior_id} therefore does not establish that invariant."
    )


def pair_shared(left: dict[str, object], right: dict[str, object]) -> str:
    if left["family_id"] == right["family_id"]:
        return f"Both exercise {left['family_id']}; {left['candidate_id']} exposes {left['public_interface']['entrypoint']}, while {right['candidate_id']} exposes {right['public_interface']['entrypoint']}."  # type: ignore[index]
    return f"Both require deterministic rejection and observable commit boundaries, but {left['candidate_id']} uses {left['interface_kind']} and {right['candidate_id']} uses {right['interface_kind']}."


def pair_difference(left: dict[str, object], right: dict[str, object]) -> str:
    return (
        f"{left['candidate_id']} freezes invariant [{left['latent_invariant']}] under [{left['adversarial_axis']}]; "
        f"{right['candidate_id']} freezes invariant [{right['latent_invariant']}] under [{right['adversarial_axis']}]. "
        f"Their repair classes are respectively [{left['repair_mechanism_class']}] and [{right['repair_mechanism_class']}]."
    )


def build_payload() -> dict[str, Any]:
    candidate_ids = [str(row["candidate_id"]) for row in CANDIDATES]
    seeded_candidate_order = sorted(
        candidate_ids,
        key=lambda candidate_id: hashlib.sha256(f"{SELECTION_SEED}{candidate_id}".encode("utf-8")).hexdigest(),
    )
    seeded_family_orders = {
        family_id: [candidate_id for candidate_id in seeded_candidate_order if next(row for row in CANDIDATES if row["candidate_id"] == candidate_id)["family_id"] == family_id]
        for family_id in FAMILIES
    }
    for row in CANDIDATES:
        candidate_id = str(row["candidate_id"])
        row["normative_profile"] = NORMATIVE_PROFILES[candidate_id]
        row["qualification_control"] = QUALIFICATION_CONTROLS.get(
            candidate_id,
            "Qualification uses only public entrypoints, caller-supplied deterministic time, independent processes released by the evaluator barrier, and documented SQLite constraints or invalid inputs; no internal pause is required.",
        )
        check_ids = [str(item["id"]) for item in row["checks"]]
        for item in row["checks"]:
            item["expected_mutant_failed_checks"] = [item["id"]]
            item["expected_mutant_passed_checks"] = [other for other in check_ids if other != item["id"]]
        target = row["checks"][0]
        row["finding_concept"] = f"Observed behavior: {target['planned_mutant']}. Violated invariant: {target['public_contract']}"

    all_prior = []
    for row in CANDIDATES:
        for prior_id, prior_construct in PRIOR.items():
            all_prior.append({
                "candidate_id": row["candidate_id"],
                "prior_task": prior_id,
                "shared_shell_or_surface": prior_shared(row, prior_id, prior_construct),
                "substantive_difference": prior_difference(row, prior_id, prior_construct),
                "non_implication": f"Passing {prior_id} cannot substitute for qualifying {row['candidate_id']}.",
            })

    pairwise = []
    for left, right in itertools.combinations(CANDIDATES, 2):
        pairwise.append({
            "left": left["candidate_id"],
            "right": right["candidate_id"],
            "shared_shell_or_surface": pair_shared(left, right),
            "substantive_difference": pair_difference(left, right),
            "left_only_counterexample": left["discriminating_counterexample"],
            "right_only_counterexample": right["discriminating_counterexample"],
            "left_pass_right_fail": f"Keep {left['candidate_id']} conformant to [{left['checks'][0]['public_contract']}], while {right['candidate_id']} exhibits [{right['checks'][0]['planned_mutant']}]; the right target probe fails without changing the left interface or state identity.",
            "right_pass_left_fail": f"Keep {right['candidate_id']} conformant to [{right['checks'][0]['public_contract']}], while {left['candidate_id']} exhibits [{left['checks'][0]['planned_mutant']}]; the left target probe fails without changing the right interface or state identity.",
            "high_overlap_manual_discriminant": HIGH_OVERLAP_DISCRIMINANTS.get(tuple(sorted((str(left["candidate_id"]), str(right["candidate_id"]))))),
        })

    family_coverage = []
    for family_id, definition in FAMILIES.items():
        members = [row["candidate_id"] for row in CANDIDATES if row["family_id"] == family_id]
        family_coverage.append({
            "family_id": family_id,
            "definition": definition,
            "required_candidates": 4,
            "candidate_ids": members,
            "inclusion_rule": "candidate directly exercises the family invariant through one localized deterministic semantic mutant",
            "exclusion_rule": "exclude packaging-only, syntax-only, literal-fixture, or target-model-outcome-derived defects",
        })

    return {
        "schema_version": 1,
        "freeze_date": DATE,
        "base_commit": BASE_COMMIT,
        "selection_seed": SELECTION_SEED,
        "seeded_candidate_order": seeded_candidate_order,
        "seeded_family_orders": seeded_family_orders,
        "global_contracts": GLOBAL_CONTRACTS,
        "efficacy_cells_collected": 0,
        "target_model_calls_before_freeze": 0,
        "authorization": "pre-build identities, neutral public contracts, reference/evaluator/mutant construction, and qualification only after independent pre-build GO",
        "campaign_boundary": "no target-model repair pilot, A/B cell, contrast, task replacement, threshold change, or efficacy claim",
        "neutrality_policy": {
            "allowed": ["public interface", "reference implementation", "deterministic hidden evaluator", "localized mutants", "clean-room qualification"],
            "forbidden": ["heldout literal in visible bundle", "check ID in visible bundle", "implementation recipe in finding", "V4 or PII outcome-based selection", "target-model screening", "A/B result"],
        },
        "families": family_coverage,
        "candidates": CANDIDATES,
        "all_prior_overlap_matrix": all_prior,
        "candidate_pairwise_matrix": pairwise,
        "admission_gate": {
            "ordering": f"within each family, SHA-256({SELECTION_SEED} + candidate_id), ascending",
            "selection": "first two qualifying candidates per family in frozen within-family order; no cross-family backfill; any family with fewer than two qualified candidates means no launch",
            "requirements": [
                "reference target and four guards pass in two clean-room runs",
                "designated target mutant fails only the target in two clean-room runs",
                "each of the five planned check mutants has its exact singleton failure set",
                "reverting only the designated mutation restores all checks",
                "at least one independent near-miss remains target-failing while guards pass",
                "visible bundle excludes private IDs, probes, mutants, findings, fixtures, references, and run artifacts",
                "finding passes leakage lint and independent read-only review",
                "repair requires both frozen reasoning steps under a static rubric",
                "canonical pytest and heldout import audits are hermetic",
            ],
        },
        "planned_campaign_rule": {
            "planned_pairs": 12,
            "minimum_valid_pairs": 10,
            "endpoint": "target_passed AND all_four_guards_passed AND repair_retained",
            "status": "not_yet_frozen",
            "calibration_required": "provider-free exhaustive and Monte Carlo calibration over 10-12 valid binary pairs must freeze win/loss/tie/invalid definitions, null and alternative generators, error-rate objectives, accounting denominator, and one immutable threshold before any target-model call",
            "launch_rule": "prebuild and build qualification cannot authorize a V5 launch until the calibrated decision rule has a separate hash-bound independent GO",
        },
        "expected_counts": {
            "families": 6,
            "candidates": 24,
            "candidates_per_family": 4,
            "checks_per_candidate": 5,
            "planned_mutants": 120,
            "all_prior_rows": len(CANDIDATES) * len(PRIOR),
            "pairwise_rows": len(candidate_ids) * (len(candidate_ids) - 1) // 2,
        },
    }


def render_markdown(payload: dict[str, Any], digest: str) -> str:
    lines = [
        "# AgentHarness mechanism-first V5 pre-build ledger",
        "",
        f"Freeze date: {DATE}",
        f"Base commit before this amendment: `{BASE_COMMIT}`",
        f"Normative JSON SHA-256: `{digest}`",
        "Target-model calls: `0`",
        "Efficacy cells: `0`",
        "",
        "## Authorization boundary",
        "",
        str(payload["authorization"]),
        "",
        f"Prohibited: {payload['campaign_boundary']}.",
        "",
        "## Frozen families and candidates",
        "",
    ]
    for family in payload["families"]:  # type: ignore[index]
        lines.extend([f"### `{family['family_id']}`", "", str(family["definition"]), ""])
        for row in [r for r in payload["candidates"] if r["family_id"] == family["family_id"]]:  # type: ignore[index]
            lines.extend([
                f"#### `{row['candidate_id']}`",
                "",
                str(row["construct"]),
                "",
                f"Interface: `{row['public_interface']['entrypoint']}`",
                f"Designated target: `{row['target_check_id']}`",
                f"Finding concept: {row['finding_concept']}",
                "",
                "Planned checks:",
            ])
            for item in row["checks"]:
                marker = "target" if item["id"] == row["target_check_id"] else "guard"
                lines.append(f"- `{item['id']}` ({marker}): {item['public_contract']}")
            lines.append("")
    counts = payload["expected_counts"]
    lines.extend([
        "## Preventive evidence shape",
        "",
        f"- {counts['candidates']} candidates across {counts['families']} families",
        f"- {counts['planned_mutants']} planned singleton mutants",
        f"- {counts['all_prior_rows']} candidate-versus-prior comparisons",
        f"- {counts['pairwise_rows']} within-bank pair comparisons",
        "- Selection is seeded and mechanical; no target-model screening is authorized",
        "- Fewer than 12 qualified candidates means no V5 launch",
        "",
        "## Next gate",
        "",
        "Independent read-only review must return GO before visible bundles, references, hidden evaluators, or mutants are implemented. This artifact does not authorize provider calls.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lock_path = OUT / ".publish.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        payload = build_payload()
        json_bytes = canonical_bytes(payload)
        digest = hashlib.sha256(json_bytes).hexdigest()
        markdown_bytes = render_markdown(payload, digest).encode("utf-8")
        markdown_digest = hashlib.sha256(markdown_bytes).hexdigest()
        json_path = OUT / f"V5_PREBUILD_LEDGER.{digest}.json"
        md_path = OUT / f"V5_PREBUILD_LEDGER.{markdown_digest}.md"
        manifest_path = OUT / "V5_PREBUILD_CURRENT.json"
        manifest = {
            "schema_version": 1,
            "base_commit": BASE_COMMIT,
            "json_file": json_path.name,
            "json_sha256": digest,
            "markdown_file": md_path.name,
            "markdown_sha256": markdown_digest,
        }
        publish_immutable(json_path, json_bytes)
        publish_immutable(md_path, markdown_bytes)
        atomic_write(OUT / "V5_PREBUILD_LEDGER.json", json_bytes)
        atomic_write(OUT / "V5_PREBUILD_LEDGER.md", markdown_bytes)
        atomic_write(manifest_path, canonical_bytes(manifest))
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    print(json.dumps({
        "json": str(json_path),
        "markdown": str(md_path),
        "manifest": str(manifest_path),
        "sha256": digest,
        **payload["expected_counts"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
