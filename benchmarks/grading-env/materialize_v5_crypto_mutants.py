from __future__ import annotations

import shutil
from pathlib import Path

SELECTORS = (
    'os.environ.get("AGENTHARNESS_MUTANT", "")',
    'os.environ.get("AGENTHARNESS_MUTANT")',
)
MODULES = {
    "rotating-key-token-verifier": Path("rotating_token/verify.py"),
    "envelope-context-decryptor": Path("envelope_crypto/decrypt.py"),
    "attenuated-capability-verifier": Path("capability/verify.py"),
    "atomic-batch-state-machine": Path("batch_state_api/main.py"),
    "ack-token-work-queue": Path("ack_queue/cli.py"),
    "length-prefixed-frame-parser": Path("frame_parser/parse.py"),
    "streaming-csv-quoted-records": Path("csv_stream/parse.py"),
    "epoch-guarded-leader-heartbeat": Path("epoch_leader/cli.py"),
    "context-complete-authorization-cache": Path("decision_cache/app.py"),
    "transactional-release-pointer": Path("release_pointer/app.py"),
    "two-tier-read-through-cache": Path("tiered_cache/core.py"),
    "portable-command-receipt-ledger": Path("command_ledger/app.py"),
}

DIRECT_PATCHES = {
    ("transactional-release-pointer", "release_generation_cas"): (
        '''            if expected != channel.generation:\n                store.rollback(tx)\n                return _error("generation_conflict", 409)\n''',
        '',
    ),
    ("transactional-release-pointer", "release_artifact_approval"): (
        '''            if not approved:\n                store.rollback(tx)\n                return _error("artifact_not_approved", 422)\n''',
        '',
    ),
    ("transactional-release-pointer", "release_publication_completeness"): (
        '            store.stage_event(tx, event)\n',
        '',
    ),
    ("transactional-release-pointer", "release_failure_atomicity"): (
        '''    def close_error(tx: object) -> JSONResponse:\n        try:\n            store.rollback(tx)\n''',
        '''    def close_error(tx: object) -> JSONResponse:\n        try:\n            store.commit(tx)\n''',
    ),
    ("transactional-release-pointer", "release_idempotent_replay"): (
        '''            if receipt is not None:\n                if receipt.command_fingerprint != fingerprint:\n                    store.rollback(tx)\n                    return _error("request_id_conflict", 409)\n                if (\n                    receipt.request_id != request_id\n                    or receipt.status_code != 200\n                    or not isinstance(receipt.response_body, bytes)\n                ):\n                    raise StoreError("invalid receipt")\n                store.rollback(tx)\n                return Response(receipt.response_body, status_code=receipt.status_code, media_type="application/json")\n''',
        '',
    ),
    ("transactional-release-pointer", "release_split_receipt_near_miss"): (
        '            store.stage_receipt(tx, new_receipt)\n',
        '''            try:\n                store.stage_receipt(tx, new_receipt)\n            except Exception:\n                try:\n                    store.commit(tx)\n                except Exception:\n                    pass\n                return _error("storage_failure", 503)\n''',
    ),
    ("two-tier-read-through-cache", "tier_l1_short_circuit"): (
        '''        if first is not None:\n            return first\n''',
        '',
    ),
    ("two-tier-read-through-cache", "tier_l2_promotion"): (
        '''        if second is not None:\n            self._l1.put(key, second)\n            return second\n''',
        '''        if second is not None:\n            return second\n''',
    ),
    ("two-tier-read-through-cache", "tier_origin_fill"): (
        '        self._l2.put(key, loaded)\n',
        '',
    ),
    ("two-tier-read-through-cache", "tier_two_level_invalidation"): (
        '        self._l2.delete(key)\n',
        '',
    ),
    ("two-tier-read-through-cache", "tier_failure_non_admission"): (
        '        loaded = self._origin.load(key)\n',
        '''        try:\n            loaded = self._origin.load(key)\n        except OriginError:\n            self._l2.put(key, b"__origin_error__")\n            raise\n''',
    ),
    ("two-tier-read-through-cache", "tier_l2_casefold_delete_near_miss"): (
        '        self._l2.delete(key)\n',
        '        self._l2.delete(key.lower())\n',
    ),
    ("portable-command-receipt-ledger", "receipt_key_identity"): (
        '    return tenant, command, revision, key\n',
        '    return tenant, command, revision, ""\n',
    ),
    ("portable-command-receipt-ledger", "receipt_tenant_identity"): (
        '    return tenant, command, revision, key\n',
        '    return "", command, revision, key\n',
    ),
    ("portable-command-receipt-ledger", "receipt_command_identity"): (
        '    return tenant, command, revision, key\n',
        '    return tenant, "", revision, key\n',
    ),
    ("portable-command-receipt-ledger", "receipt_revision_identity"): (
        '    return tenant, command, revision, key\n',
        '    return tenant, command, 0, key\n',
    ),
    ("portable-command-receipt-ledger", "receipt_key_casefold_near_miss"): (
        '    return tenant, command, revision, key\n',
        '    return tenant, command, revision, key.lower()\n',
    ),
}


def materialize_mutant(reference: Path, task_id: str, mutant_id: str, destination: Path) -> Path:
    """Create a source-level singleton variant; no runtime mutation environment is used."""
    if task_id not in MODULES:
        raise ValueError(f"unknown task: {task_id}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(reference, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "build", "*.egg-info", ".pytest_cache"))
    module = destination / MODULES[task_id]
    source = module.read_text(encoding="utf-8")
    if (task_id, mutant_id) == ("portable-command-receipt-ledger", "receipt_process_portability"):
        start_marker = "def _run(\n"
        end_marker = "\n\ndef create_app("
        if source.count(start_marker) != 1 or source.count(end_marker) != 1:
            raise RuntimeError("portable receipt _run patch boundaries are not unique")
        start = source.index(start_marker)
        end = source.index(end_marker, start)
        replacement = '''_MEMORY: dict[tuple[str, str, int, str], bytes] = {}\n\n\ndef _run(db_path: Path, execute_once: Callable[[str, str, int, str, dict[str, Any]], str], identity: tuple[str, str, int, str], callback_identity: tuple[str, str, int, str], payload: dict[str, Any]) -> bytes:\n    existing = _MEMORY.get(identity)\n    if existing is not None:\n        return existing\n    receipt = execute_once(*callback_identity, payload)\n    if not isinstance(receipt, str) or RECEIPT.fullmatch(receipt) is None:\n        raise ValueError("invalid receipt")\n    body = _json({"receipt": receipt})\n    _MEMORY[identity] = body\n    return body\n'''
        patched = source[:start] + replacement + source[end:]
        module.write_text(patched, encoding="utf-8")
        return destination
    direct = DIRECT_PATCHES.get((task_id, mutant_id))
    if direct is not None:
        old, new = direct
        if source.count(old) != 1:
            raise RuntimeError(f"direct patch site is not unique: {task_id}/{mutant_id}")
        patched = source.replace(old, new)
        if patched == source:
            raise RuntimeError(f"direct patch did not change source: {task_id}/{mutant_id}")
        module.write_text(patched, encoding="utf-8")
        return destination
    occurrences = sum(source.count(selector) for selector in SELECTORS)
    if occurrences == 0:
        raise RuntimeError(f"reference has no private mutation selector: {task_id}")
    for selector in SELECTORS:
        source = source.replace(selector, repr(mutant_id))
    if any(selector in source for selector in SELECTORS):
        raise RuntimeError("mutation selector survived materialization")
    module.write_text(source, encoding="utf-8")
    return destination
