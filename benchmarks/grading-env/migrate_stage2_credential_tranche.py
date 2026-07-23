from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = Path("/home/fabio/agentharness-stage2-efficacy-20260718-workspace-isolated")
OLD_MANIFEST_RELATIVE = "benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-17.json"
NEW_MANIFEST_RELATIVE = "benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-18_ACCOUNT2.json"
AUTHORIZATION_RELATIVE = "benchmarks/grading-env/STAGE2_CREDENTIAL_TRANCHE_AUTHORIZATION_2026-07-18.json"
AMENDMENT_RELATIVE = "benchmarks/PREREGISTRATION.md"
AMENDED_FREEZE_TAG = "stage2-account2-freeze-20260718-v1"
OLD_MANIFEST_PAYLOAD_SHA256 = "1e2c313573aede67848aeaba07917a914e6393ad4283e0ae0f99607db8c26159"
OLD_MANIFEST_FILE_SHA256 = "4979150ebd6762fe39410a027007bd0cc052b0c7a659c23beb4fb475a8372b38"
OLD_REPOSITORY_COMMIT = "85b0447ddceab856ff8e92631b8fbe09d7456073"
EXPECTED_CAMPAIGN_ID = "stage2-efficacy-20x3-20260717"
EXPECTED_COMPLETED_BLOCKS = [f"b{i:03d}" for i in range(1, 19)]
BOUNDARY_BLOCK = "b019"
PROFILE_HOME = Path("/home/fabio/.hermes/profiles/stage2codex2")
DEFAULT_HOME = Path("/home/fabio/.hermes")
TRANSACTION_NAME = "credential-tranche-migration.transaction.json"
AUDIT_NAME = "credential-tranche-amendment.json"


class MigrationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: object, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with tmp.open("wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    os.chmod(path, mode)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MigrationError("Campaign or migration lock is held") from exc
        yield


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


def account_fingerprint(auth_path: Path) -> str:
    data = json.loads(auth_path.read_text(encoding="utf-8"))
    pool = data.get("credential_pool", {}).get("openai-codex")
    if pool is not None:
        if not isinstance(pool, list) or len(pool) != 1 or not isinstance(pool[0], dict):
            raise MigrationError(
                f"Codex credential pool must contain exactly one credential in {auth_path}"
            )
        tokens = pool[0]
    else:
        state = data.get("providers", {}).get("openai-codex", {})
        tokens = state.get("tokens", {})
    account_id = str(tokens.get("account_id") or "").strip()
    if not account_id:
        token = str(tokens.get("access_token") or "")
        parts = token.split(".")
        if len(parts) >= 2:
            raw = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(raw))
            auth_claim = claims.get("https://api.openai.com/auth", {})
            account_id = str(
                auth_claim.get("chatgpt_account_id") or claims.get("account_id") or ""
            ).strip()
    if not account_id:
        raise MigrationError(f"No Codex account identity in {auth_path}")
    return sha256_bytes(f"stage2-credential-tranche-v1:{account_id}".encode("utf-8"))


def tree_hash(root: Path) -> str:
    if not root.is_dir():
        raise MigrationError(f"Missing directory: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        entries.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return sha256_bytes(canonical_json(entries))


def _load_and_validate_manifest_payload(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    copy = dict(manifest)
    expected = str(copy.pop("manifest_payload_sha256"))
    if sha256_bytes(canonical_json(copy)) != expected:
        raise MigrationError(f"Manifest payload hash mismatch: {path.name}")
    return manifest


def git_file_bytes(commit: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise MigrationError(f"Missing frozen Git object: {commit}:{relative}")
    return result.stdout


def validate_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_and_validate_manifest_payload(path)
    for relative, frozen_sha in manifest["frozen_file_sha256"].items():
        frozen_path = REPO_ROOT / relative
        if not frozen_path.is_file() or sha256_file(frozen_path) != frozen_sha:
            raise MigrationError(f"Frozen file mismatch: {relative}")
    return manifest


def validate_manifest_at_commit(path: Path, commit: str) -> dict[str, Any]:
    manifest = _load_and_validate_manifest_payload(path)
    for relative, frozen_sha in manifest["frozen_file_sha256"].items():
        if sha256_bytes(git_file_bytes(commit, relative)) != frozen_sha:
            raise MigrationError(f"Frozen Git object mismatch: {commit}:{relative}")
    return manifest


def validate_repository_and_authorization() -> tuple[dict[str, Any], dict[str, Any], str]:
    if git("status", "--porcelain"):
        raise MigrationError("Repository must be clean")
    head = git("rev-parse", "HEAD")
    if head != git("rev-parse", "origin/main"):
        raise MigrationError("HEAD must equal origin/main")
    tagged = git("rev-parse", f"refs/tags/{AMENDED_FREEZE_TAG}^{{commit}}")
    if tagged != head:
        raise MigrationError("HEAD is not the exact amended freeze tag commit")
    git("ls-files", "--error-unmatch", AUTHORIZATION_RELATIVE)

    old_path = REPO_ROOT / OLD_MANIFEST_RELATIVE
    new_path = REPO_ROOT / NEW_MANIFEST_RELATIVE
    if sha256_file(old_path) != OLD_MANIFEST_FILE_SHA256:
        raise MigrationError("Old manifest file hash mismatch")
    old_manifest = validate_manifest_at_commit(old_path, OLD_REPOSITORY_COMMIT)
    new_manifest = validate_manifest(new_path)
    if old_manifest["manifest_payload_sha256"] != OLD_MANIFEST_PAYLOAD_SHA256:
        raise MigrationError("Old manifest payload hash mismatch")
    authorization = json.loads((REPO_ROOT / AUTHORIZATION_RELATIVE).read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "run_root",
        "old_manifest_payload_sha256",
        "old_manifest_file_sha256",
        "old_repository_commit",
        "new_manifest_payload_sha256",
        "new_manifest_file_sha256",
        "freeze_tag",
        "boundary_block",
        "authorized_completed_blocks",
        "account_fingerprints_sha256",
    }
    if set(authorization) != expected_keys:
        raise MigrationError("Authorization keys are not the exact allowlist")
    expected_authorization = {
        "schema_version": 1,
        "run_root": str(RUN_ROOT),
        "old_manifest_payload_sha256": OLD_MANIFEST_PAYLOAD_SHA256,
        "old_manifest_file_sha256": OLD_MANIFEST_FILE_SHA256,
        "old_repository_commit": OLD_REPOSITORY_COMMIT,
        "new_manifest_payload_sha256": new_manifest["manifest_payload_sha256"],
        "new_manifest_file_sha256": sha256_file(new_path),
        "freeze_tag": AMENDED_FREEZE_TAG,
        "boundary_block": BOUNDARY_BLOCK,
        "authorized_completed_blocks": EXPECTED_COMPLETED_BLOCKS,
        "account_fingerprints_sha256": {
            "codex-account-tranche-1": account_fingerprint(DEFAULT_HOME / "auth.json"),
            "codex-account-tranche-2": account_fingerprint(PROFILE_HOME / "auth.json"),
        },
    }
    if expected_authorization["account_fingerprints_sha256"]["codex-account-tranche-1"] == expected_authorization["account_fingerprints_sha256"]["codex-account-tranche-2"]:
        raise MigrationError("Second credential resolves to the same Codex account")
    if authorization != expected_authorization:
        raise MigrationError("Tracked authorization does not match the exact migration boundary")
    return old_manifest, new_manifest, head


def validate_row_identity(
    row: dict[str, Any], block: dict[str, Any], *, slot: int, condition: str
) -> None:
    block_id = str(block["block_id"])
    expected = {
        "block_id": block_id,
        "task_id": str(block["task_id"]),
        "replicate_id": str(block["replicate_id"]),
        "condition": condition,
        "slot": slot,
        "campaign_cell_id": f"{block_id}-s{slot}",
    }
    for key, value in expected.items():
        if row.get(key) != value:
            raise MigrationError(f"Journal row identity mismatch in {block_id}: {key}")


def validate_old_frontier(
    old_manifest: dict[str, Any],
    state: dict[str, Any],
    *,
    require_boundary_sources: bool = True,
) -> None:
    if state.get("campaign_id") != EXPECTED_CAMPAIGN_ID:
        raise MigrationError("Campaign id mismatch")
    if state.get("schema_version") != 2:
        raise MigrationError("Old state schema mismatch")
    if state.get("manifest_sha256") != OLD_MANIFEST_PAYLOAD_SHA256:
        raise MigrationError("Old state manifest payload mismatch")
    if state.get("manifest_file_sha256") != OLD_MANIFEST_FILE_SHA256:
        raise MigrationError("Old state manifest file mismatch")
    if state.get("repository_commit") != OLD_REPOSITORY_COMMIT:
        raise MigrationError("Old state repository commit mismatch")
    if state.get("status") != "paused_quota":
        raise MigrationError("Campaign is not paused_quota")

    block_map = {str(block["block_id"]): block for block in old_manifest["blocks"]}
    current = state.get("current_cell")
    boundary = block_map[BOUNDARY_BLOCK]
    expected_current = {
        "cell_id": "b019-s2",
        "block_id": BOUNDARY_BLOCK,
        "task_id": str(boundary["task_id"]),
        "replicate_id": str(boundary["replicate_id"]),
        "condition": str(boundary["condition_order"][1]),
        "slot": 2,
        "attempt_no": 1,
    }
    if not isinstance(current, dict):
        raise MigrationError("Current cell is not an object")
    for key, value in expected_current.items():
        if current.get(key) != value:
            raise MigrationError(f"Current boundary cell mismatch: {key}")

    journal_paths = sorted((RUN_ROOT / "block-journals").glob("*.commit.json"))
    journal_ids = [path.name.removesuffix(".commit.json") for path in journal_paths]
    if journal_ids != EXPECTED_COMPLETED_BLOCKS:
        raise MigrationError("Committed-block frontier is not exactly b001..b018")
    rebuilt_progress: list[dict[str, Any]] = []
    for block_id in EXPECTED_COMPLETED_BLOCKS:
        block = block_map[block_id]
        payload = json.loads((RUN_ROOT / "block-journals" / f"{block_id}.commit.json").read_text(encoding="utf-8"))
        rows = payload.get("rows")
        if payload.get("block_id") != block_id or not isinstance(rows, list) or len(rows) != 2:
            raise MigrationError(f"Invalid pair journal: {block_id}")
        ordered: list[dict[str, Any]] = []
        for slot, condition in enumerate(block["condition_order"], start=1):
            row = next((item for item in rows if item.get("condition") == condition), None)
            if not isinstance(row, dict):
                raise MigrationError(f"Missing condition in pair journal: {block_id}")
            validate_row_identity(row, block, slot=slot, condition=str(condition))
            ordered.append(row)
        for row in ordered:
            rebuilt_progress.append(
                {
                    "task_id": row["task_id"],
                    "condition": row["condition"],
                    "replicate_id": row["replicate_id"],
                    "block_id": block_id,
                    "campaign_cell_id": row["campaign_cell_id"],
                    "final": row,
                }
            )
    progress = json.loads((RUN_ROOT / "progress.private.json").read_text(encoding="utf-8"))
    if canonical_json(progress) != canonical_json(rebuilt_progress):
        raise MigrationError("Progress is not canonically identical to committed pair journals")

    counters = state.get("counters")
    if not isinstance(counters, dict):
        raise MigrationError("State counters missing")
    physical = counters.get("physical_cell_attempts")
    if not isinstance(physical, dict):
        raise MigrationError("Physical-attempt counters missing")
    if physical.get("b019-s1") != 1 or physical.get("b019-s2") != 1:
        raise MigrationError("Boundary physical-attempt counters mismatch")
    if require_boundary_sources:
        s1 = RUN_ROOT / "private-cells" / "b019-s1"
        s2 = RUN_ROOT / "private-cells" / "b019-s2"
        if not (s1 / "cell-result.commit.json").is_file():
            raise MigrationError("Boundary slot 1 private commit is missing")
        if (s2 / "cell-result.commit.json").exists():
            raise MigrationError("Boundary slot 2 unexpectedly has a private commit")


def frontier_hashes() -> dict[str, Any]:
    progress_sha = sha256_file(RUN_ROOT / "progress.private.json")
    journals = {
        block_id: sha256_file(RUN_ROOT / "block-journals" / f"{block_id}.commit.json")
        for block_id in EXPECTED_COMPLETED_BLOCKS
    }
    aggregate = sha256_bytes(
        canonical_json(
            {
                "progress_sha256": progress_sha,
                "block_journal_sha256": journals,
            }
        )
    )
    return {
        "progress_sha256": progress_sha,
        "block_journal_sha256": journals,
        "aggregate_sha256": aggregate,
    }


def _validate_transaction(
    transaction: dict[str, Any],
    *,
    state_path: Path,
    expected_new_payload: str,
    expected_new_file: str,
    head: str,
) -> None:
    required = {
        "schema_version",
        "phase",
        "prepared_at",
        "run_root",
        "old_state_sha256",
        "frontier_sha256",
        "source_tree_sha256",
        "new_manifest_payload_sha256",
        "new_manifest_file_sha256",
        "new_repository_commit",
        "freeze_tag",
    }
    if not required.issubset(transaction):
        raise MigrationError("Transaction journal is missing required keys")
    if transaction["schema_version"] != 1:
        raise MigrationError("Transaction schema mismatch")
    if transaction["phase"] not in {"prepared", "archives_complete", "complete"}:
        raise MigrationError("Transaction phase mismatch")
    if transaction["run_root"] != str(RUN_ROOT):
        raise MigrationError("Transaction run root mismatch")
    if transaction["new_manifest_payload_sha256"] != expected_new_payload:
        raise MigrationError("Transaction manifest payload mismatch")
    if transaction["new_manifest_file_sha256"] != expected_new_file:
        raise MigrationError("Transaction manifest file mismatch")
    if transaction["new_repository_commit"] != head:
        raise MigrationError("Transaction repository commit mismatch")
    if transaction["freeze_tag"] != AMENDED_FREEZE_TAG:
        raise MigrationError("Transaction freeze tag mismatch")
    observed_frontier = frontier_hashes()
    if transaction["frontier_sha256"] != observed_frontier:
        raise MigrationError("Committed frontier changed after transaction preparation")
    source_hashes = transaction["source_tree_sha256"]
    if not isinstance(source_hashes, dict) or set(source_hashes) != {"b019-s1", "b019-s2"}:
        raise MigrationError("Transaction source-tree allowlist mismatch")
    if any(not isinstance(value, str) or len(value) != 64 for value in source_hashes.values()):
        raise MigrationError("Transaction source-tree hash malformed")
    if transaction["phase"] == "prepared" and sha256_file(state_path) != transaction["old_state_sha256"]:
        raise MigrationError("Old state changed after transaction preparation")


def _archive_boundary(transaction: dict[str, Any]) -> list[dict[str, Any]]:
    archives: list[dict[str, Any]] = []
    for cell_id in ("b019-s1", "b019-s2"):
        source = RUN_ROOT / "private-cells" / cell_id
        destination = RUN_ROOT / "quarantine" / cell_id / "attempt-01-account_tranche_boundary"
        expected_hash = str(transaction["source_tree_sha256"][cell_id])
        if source.exists() and destination.exists():
            raise MigrationError(f"Both source and archive exist for {cell_id}")
        if source.exists():
            if tree_hash(source) != expected_hash:
                raise MigrationError(f"Boundary source tree changed for {cell_id}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(destination.parent, 0o700)
            shutil.move(str(source), str(destination))
            os.chmod(destination, 0o700)
        if not destination.exists() or tree_hash(destination) != expected_hash:
            raise MigrationError(f"Boundary archive verification failed for {cell_id}")
        archives.append(
            {
                "cell_id": cell_id,
                "attempt_no": 1,
                "archive": str(destination),
                "tree_sha256": expected_hash,
            }
        )
    return archives


def migrate() -> dict[str, Any]:
    transaction_path = RUN_ROOT / TRANSACTION_NAME
    audit_path = RUN_ROOT / AUDIT_NAME
    state_path = RUN_ROOT / "campaign-state.private.json"
    with exclusive_lock(RUN_ROOT / "campaign.lock"):
        old_manifest, new_manifest, head = validate_repository_and_authorization()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        expected_new_payload = str(new_manifest["manifest_payload_sha256"])
        expected_new_file = sha256_file(REPO_ROOT / NEW_MANIFEST_RELATIVE)
        state_was_ready = (
            state.get("status") == "ready"
            and state.get("manifest_sha256") == expected_new_payload
            and state.get("manifest_file_sha256") == expected_new_file
            and state.get("repository_commit") == head
        )

        if not transaction_path.exists():
            if state_was_ready:
                raise MigrationError("Migrated state exists without transaction journal")
            validate_old_frontier(old_manifest, state)
            transaction = {
                "schema_version": 1,
                "phase": "prepared",
                "prepared_at": utc_now(),
                "run_root": str(RUN_ROOT),
                "old_state_sha256": sha256_file(state_path),
                "frontier_sha256": frontier_hashes(),
                "source_tree_sha256": {
                    cell_id: tree_hash(RUN_ROOT / "private-cells" / cell_id)
                    for cell_id in ("b019-s1", "b019-s2")
                },
                "new_manifest_payload_sha256": expected_new_payload,
                "new_manifest_file_sha256": expected_new_file,
                "new_repository_commit": head,
                "freeze_tag": AMENDED_FREEZE_TAG,
            }
            atomic_write(transaction_path, transaction)
        else:
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))

        _validate_transaction(
            transaction,
            state_path=state_path,
            expected_new_payload=expected_new_payload,
            expected_new_file=expected_new_file,
            head=head,
        )
        if not state_was_ready:
            validate_old_frontier(old_manifest, state, require_boundary_sources=False)
            if sha256_file(state_path) != transaction["old_state_sha256"]:
                raise MigrationError("Old state changed during resumable migration")
        else:
            if state.get("current_cell") is not None:
                raise MigrationError("Migrated ready state retains a current cell")
            reconstructed = dict(state)
            reconstructed.update(
                {
                    "status": "paused_quota",
                    "manifest_sha256": OLD_MANIFEST_PAYLOAD_SHA256,
                    "manifest_file_sha256": OLD_MANIFEST_FILE_SHA256,
                    "repository_commit": OLD_REPOSITORY_COMMIT,
                }
            )
            boundary = old_manifest["blocks"][18]
            reconstructed["current_cell"] = {
                "cell_id": "b019-s2",
                "block_id": "b019",
                "task_id": str(boundary["task_id"]),
                "replicate_id": str(boundary["replicate_id"]),
                "condition": str(boundary["condition_order"][1]),
                "slot": 2,
                "attempt_no": 1,
            }
            validate_old_frontier(old_manifest, reconstructed, require_boundary_sources=False)

        archives = _archive_boundary(transaction)
        if transaction["phase"] == "prepared":
            transaction["phase"] = "archives_complete"
            transaction["archives_completed_at"] = utc_now()
            transaction["archives"] = archives
            atomic_write(transaction_path, transaction)
        else:
            if transaction.get("archives") != archives:
                raise MigrationError("Transaction archive evidence mismatch")

        archive_evidence_sha = sha256_bytes(
            canonical_json(
                {
                    "source_tree_sha256": transaction["source_tree_sha256"],
                    "frontier_aggregate_sha256": transaction["frontier_sha256"][
                        "aggregate_sha256"
                    ],
                    "archives": archives,
                    "boundary_block": BOUNDARY_BLOCK,
                    "new_manifest_payload_sha256": expected_new_payload,
                    "new_repository_commit": head,
                }
            )
        )
        authorization = json.loads((REPO_ROOT / AUTHORIZATION_RELATIVE).read_text(encoding="utf-8"))
        existing_audit = (
            json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
        )
        audit = {
            "schema_version": 1,
            "amendment": "17.36-credential-tranche-continuation",
            "applied_at": existing_audit["applied_at"] if existing_audit else utc_now(),
            "outcome_blind": True,
            "migration_complete": True,
            "run_root": str(RUN_ROOT),
            "old_manifest_payload_sha256": OLD_MANIFEST_PAYLOAD_SHA256,
            "old_manifest_file_sha256": OLD_MANIFEST_FILE_SHA256,
            "old_repository_commit": OLD_REPOSITORY_COMMIT,
            "new_manifest_payload_sha256": expected_new_payload,
            "new_manifest_file_sha256": expected_new_file,
            "new_repository_commit": head,
            "freeze_tag": AMENDED_FREEZE_TAG,
            "authorization_file_sha256": sha256_file(REPO_ROOT / AUTHORIZATION_RELATIVE),
            "amendment_file_sha256": sha256_file(REPO_ROOT / AMENDMENT_RELATIVE),
            "preserved_pair_complete_blocks": EXPECTED_COMPLETED_BLOCKS,
            "boundary_block_restarted": BOUNDARY_BLOCK,
            "credential_tranche_by_block": {
                "codex-account-tranche-1": "b001-b018",
                "codex-account-tranche-2": "b019-b060",
            },
            "account_fingerprints_sha256": authorization["account_fingerprints_sha256"],
            "quarantined_boundary_attempts": archives,
            "frontier_sha256": transaction["frontier_sha256"],
            "archive_evidence_sha256": archive_evidence_sha,
            "new_invocations_performed": False,
            "analysis_authorized": False,
        }
        if existing_audit is not None:
            if existing_audit != audit:
                raise MigrationError("Existing amendment audit differs from resumable transaction")
        else:
            atomic_write(audit_path, audit)
        audit_sha = sha256_file(audit_path)

        if not state_was_ready:
            state["manifest_sha256"] = expected_new_payload
            state["manifest_file_sha256"] = expected_new_file
            state["repository_commit"] = head
            state["status"] = "ready"
            state["current_cell"] = None
            state["updated_at"] = utc_now()
            state["credential_tranche_amendment_sha256"] = audit_sha
            state["credential_tranches"] = [
                {
                    "tranche": "codex-account-tranche-1",
                    "account_fingerprint_sha256": authorization["account_fingerprints_sha256"]["codex-account-tranche-1"],
                    "blocks": "b001-b018",
                },
                {
                    "tranche": "codex-account-tranche-2",
                    "account_fingerprint_sha256": authorization["account_fingerprints_sha256"]["codex-account-tranche-2"],
                    "blocks": "b019-b060",
                },
            ]
            amendments = state.setdefault("amendments", [])
            if not any(item.get("id") == "17.36-credential-tranche-continuation" for item in amendments):
                amendments.append(
                    {
                        "id": "17.36-credential-tranche-continuation",
                        "applied_at": utc_now(),
                        "repository_commit": head,
                        "manifest_sha256": expected_new_payload,
                        "audit_sha256": audit_sha,
                    }
                )
            atomic_write(state_path, state)
        elif state.get("credential_tranche_amendment_sha256") != audit_sha:
            raise MigrationError("Ready state amendment audit hash mismatch")

        if transaction["phase"] != "complete":
            transaction["phase"] = "complete"
            transaction["completed_at"] = utc_now()
            transaction["audit_sha256"] = audit_sha
            atomic_write(transaction_path, transaction)
        elif transaction.get("audit_sha256") != audit_sha:
            raise MigrationError("Completed transaction audit hash mismatch")

        return {
            "status": "already_migrated" if state_was_ready else "migrated",
            "completed_blocks_preserved": 18,
            "boundary_block_restarted": BOUNDARY_BLOCK,
            "new_invocations_performed": False,
            "analysis_authorized": False,
            "audit_sha256": audit_sha,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply the one-time Stage 2 credential-tranche amendment"
    )
    parser.add_argument("--apply", action="store_true", help="Apply the exact tagged migration")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.apply:
        print(json.dumps({"status": "rejected", "reason": "--apply is required"}, sort_keys=True))
        raise SystemExit(30)
    try:
        print(json.dumps(migrate(), sort_keys=True))
    except (MigrationError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(
            json.dumps(
                {"status": "rejected", "reason": f"{type(exc).__name__}: {exc}"},
                sort_keys=True,
            )
        )
        raise SystemExit(30)
