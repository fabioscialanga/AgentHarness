from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "benchmarks" / "grading-env" / "migrate_stage2_credential_tranche.py"
OLD_FREEZE = REPO_ROOT / "benchmarks" / "grading-env" / "STAGE2_EFFICACY_FREEZE_2026-07-17.json"
NEW_FREEZE = REPO_ROOT / "benchmarks" / "grading-env" / "STAGE2_EFFICACY_FREEZE_2026-07-18_ACCOUNT2.json"
SPEC = importlib.util.spec_from_file_location("stage2_credential_migration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class Stage2CredentialMigrationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, dict, dict]:
        run_root = root / "run"
        fake_repo = root / "repo"
        fake_repo.mkdir()
        old_manifest = json.loads(OLD_FREEZE.read_text())
        new_manifest = json.loads(NEW_FREEZE.read_text())
        fake_new = fake_repo / "new-freeze.json"
        fake_new.write_text(NEW_FREEZE.read_text())
        (fake_repo / "amendment.md").write_text("amendment\n")
        fingerprints = {
            "codex-account-tranche-1": "1" * 64,
            "codex-account-tranche-2": "2" * 64,
        }
        authorization = {"account_fingerprints_sha256": fingerprints}
        (fake_repo / "authorization.json").write_text(json.dumps(authorization) + "\n")

        (run_root / "block-journals").mkdir(parents=True)
        (run_root / "private-cells" / "b019-s1").mkdir(parents=True)
        (run_root / "private-cells" / "b019-s2").mkdir(parents=True)
        (run_root / "private-cells" / "b019-s1" / "cell-result.commit.json").write_text("{}\n")
        (run_root / "private-cells" / "b019-s2" / "partial.txt").write_text("partial\n")

        progress = []
        for block in old_manifest["blocks"][:18]:
            block_id = str(block["block_id"])
            rows = []
            for slot, condition in enumerate(block["condition_order"], start=1):
                row = {
                    "block_id": block_id,
                    "task_id": str(block["task_id"]),
                    "replicate_id": str(block["replicate_id"]),
                    "condition": str(condition),
                    "slot": slot,
                    "campaign_cell_id": f"{block_id}-s{slot}",
                }
                rows.append(row)
                progress.append(
                    {
                        "task_id": row["task_id"],
                        "condition": row["condition"],
                        "replicate_id": row["replicate_id"],
                        "block_id": block_id,
                        "campaign_cell_id": row["campaign_cell_id"],
                        "final": row,
                    }
                )
            journal = {"block_id": block_id, "rows": rows}
            (run_root / "block-journals" / f"{block_id}.commit.json").write_text(
                json.dumps(journal) + "\n"
            )
        (run_root / "progress.private.json").write_text(json.dumps(progress) + "\n")

        boundary = old_manifest["blocks"][18]
        state = {
            "schema_version": 2,
            "campaign_id": migration.EXPECTED_CAMPAIGN_ID,
            "status": "paused_quota",
            "manifest_sha256": migration.OLD_MANIFEST_PAYLOAD_SHA256,
            "manifest_file_sha256": migration.OLD_MANIFEST_FILE_SHA256,
            "repository_commit": migration.OLD_REPOSITORY_COMMIT,
            "current_cell": {
                "cell_id": "b019-s2",
                "block_id": "b019",
                "task_id": str(boundary["task_id"]),
                "replicate_id": str(boundary["replicate_id"]),
                "condition": str(boundary["condition_order"][1]),
                "slot": 2,
                "attempt_no": 1,
            },
            "counters": {
                "physical_cell_attempts": {"b019-s1": 1, "b019-s2": 1},
            },
            "amendments": [],
        }
        (run_root / "campaign-state.private.json").write_text(json.dumps(state) + "\n")
        return run_root, fake_repo, old_manifest, new_manifest

    def test_pair_atomic_migration_recovers_after_first_archive_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root, fake_repo, old_manifest, new_manifest = self._fixture(root)
            real_move = shutil.move
            calls = 0

            def fail_second_move(source: str, destination: str) -> str:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected crash after first archive")
                return real_move(source, destination)

            patches = (
                mock.patch.object(migration, "RUN_ROOT", run_root),
                mock.patch.object(migration, "REPO_ROOT", fake_repo),
                mock.patch.object(migration, "NEW_MANIFEST_RELATIVE", "new-freeze.json"),
                mock.patch.object(migration, "AUTHORIZATION_RELATIVE", "authorization.json"),
                mock.patch.object(migration, "AMENDMENT_RELATIVE", "amendment.md"),
                mock.patch.object(
                    migration,
                    "validate_repository_and_authorization",
                    return_value=(old_manifest, new_manifest, "frozen-commit"),
                ),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with mock.patch.object(migration.shutil, "move", side_effect=fail_second_move):
                    with self.assertRaises(OSError):
                        migration.migrate()
                state_after_crash = json.loads(
                    (run_root / "campaign-state.private.json").read_text()
                )
                self.assertEqual(state_after_crash["status"], "paused_quota")
                self.assertFalse((run_root / migration.AUDIT_NAME).exists())
                result = migration.migrate()
                again = migration.migrate()

            self.assertEqual(result["status"], "migrated")
            self.assertEqual(again["status"], "already_migrated")
            self.assertFalse(result["new_invocations_performed"])
            self.assertFalse(result["analysis_authorized"])
            migrated = json.loads((run_root / "campaign-state.private.json").read_text())
            self.assertEqual(migrated["status"], "ready")
            self.assertIsNone(migrated["current_cell"])
            for cell_id in ("b019-s1", "b019-s2"):
                self.assertFalse((run_root / "private-cells" / cell_id).exists())
                self.assertTrue(
                    (run_root / "quarantine" / cell_id / "attempt-01-account_tranche_boundary").is_dir()
                )
            audit = json.loads((run_root / migration.AUDIT_NAME).read_text())
            self.assertTrue(audit["migration_complete"])
            self.assertTrue(audit["outcome_blind"])
            self.assertFalse(audit["analysis_authorized"])
            transaction = json.loads((run_root / migration.TRANSACTION_NAME).read_text())
            self.assertEqual(transaction["phase"], "complete")

    def test_migration_recovers_from_every_durable_write_boundary(self) -> None:
        cases = (
            "transaction_prepared",
            "transaction_archives_complete",
            "audit_written",
            "state_ready",
            "transaction_complete",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run_root, fake_repo, old_manifest, new_manifest = self._fixture(root)
                real_atomic_write = migration.atomic_write
                injected = False

                def crash_after_write(path: Path, payload: object, mode: int = 0o600) -> None:
                    nonlocal injected
                    real_atomic_write(path, payload, mode)
                    if injected or not isinstance(payload, dict):
                        return
                    matches = (
                        case == "transaction_prepared"
                        and path.name == migration.TRANSACTION_NAME
                        and payload.get("phase") == "prepared"
                    ) or (
                        case == "transaction_archives_complete"
                        and path.name == migration.TRANSACTION_NAME
                        and payload.get("phase") == "archives_complete"
                    ) or (
                        case == "audit_written" and path.name == migration.AUDIT_NAME
                    ) or (
                        case == "state_ready"
                        and path.name == "campaign-state.private.json"
                        and payload.get("status") == "ready"
                    ) or (
                        case == "transaction_complete"
                        and path.name == migration.TRANSACTION_NAME
                        and payload.get("phase") == "complete"
                    )
                    if matches:
                        injected = True
                        raise OSError(f"injected crash at {case}")

                patches = (
                    mock.patch.object(migration, "RUN_ROOT", run_root),
                    mock.patch.object(migration, "REPO_ROOT", fake_repo),
                    mock.patch.object(migration, "NEW_MANIFEST_RELATIVE", "new-freeze.json"),
                    mock.patch.object(migration, "AUTHORIZATION_RELATIVE", "authorization.json"),
                    mock.patch.object(migration, "AMENDMENT_RELATIVE", "amendment.md"),
                    mock.patch.object(
                        migration,
                        "validate_repository_and_authorization",
                        return_value=(old_manifest, new_manifest, "frozen-commit"),
                    ),
                )
                with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                    with mock.patch.object(migration, "atomic_write", side_effect=crash_after_write):
                        with self.assertRaises(OSError):
                            migration.migrate()
                    result = migration.migrate()
                    again = migration.migrate()
                self.assertTrue(injected)
                self.assertIn(result["status"], {"migrated", "already_migrated"})
                self.assertEqual(again["status"], "already_migrated")
                state = json.loads((run_root / "campaign-state.private.json").read_text())
                self.assertEqual(state["status"], "ready")
                transaction = json.loads((run_root / migration.TRANSACTION_NAME).read_text())
                self.assertEqual(transaction["phase"], "complete")

    def test_ready_resume_rejects_coordinated_frontier_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root, fake_repo, old_manifest, new_manifest = self._fixture(root)
            real_atomic_write = migration.atomic_write
            injected = False

            def crash_after_ready(path: Path, payload: object, mode: int = 0o600) -> None:
                nonlocal injected
                real_atomic_write(path, payload, mode)
                if (
                    not injected
                    and path.name == "campaign-state.private.json"
                    and isinstance(payload, dict)
                    and payload.get("status") == "ready"
                ):
                    injected = True
                    raise OSError("injected crash after ready state")

            patches = (
                mock.patch.object(migration, "RUN_ROOT", run_root),
                mock.patch.object(migration, "REPO_ROOT", fake_repo),
                mock.patch.object(migration, "NEW_MANIFEST_RELATIVE", "new-freeze.json"),
                mock.patch.object(migration, "AUTHORIZATION_RELATIVE", "authorization.json"),
                mock.patch.object(migration, "AMENDMENT_RELATIVE", "amendment.md"),
                mock.patch.object(
                    migration,
                    "validate_repository_and_authorization",
                    return_value=(old_manifest, new_manifest, "frozen-commit"),
                ),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with mock.patch.object(migration, "atomic_write", side_effect=crash_after_ready):
                    with self.assertRaises(OSError):
                        migration.migrate()
                journal_path = run_root / "block-journals" / "b001.commit.json"
                progress_path = run_root / "progress.private.json"
                journal = json.loads(journal_path.read_text())
                progress = json.loads(progress_path.read_text())
                journal["rows"][0]["score"] = 0.987654321
                progress[0]["final"]["score"] = 0.987654321
                migration.atomic_write(journal_path, journal)
                migration.atomic_write(progress_path, progress)
                with self.assertRaisesRegex(
                    migration.MigrationError,
                    "Committed frontier changed after transaction preparation",
                ):
                    migration.migrate()

    def test_frontier_validation_rejects_noncanonical_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root, _, old_manifest, _ = self._fixture(root)
            progress_path = run_root / "progress.private.json"
            progress = json.loads(progress_path.read_text())
            progress.reverse()
            progress_path.write_text(json.dumps(progress) + "\n")
            state = json.loads((run_root / "campaign-state.private.json").read_text())
            with mock.patch.object(migration, "RUN_ROOT", run_root):
                with self.assertRaises(migration.MigrationError):
                    migration.validate_old_frontier(old_manifest, state)


    def test_account_fingerprint_accepts_single_pool_and_rejects_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "credential_pool": {
                            "openai-codex": [{"account_id": "account-two"}]
                        }
                    }
                )
                + "\n"
            )
            self.assertEqual(
                migration.account_fingerprint(auth_path),
                migration.sha256_bytes(
                    b"stage2-credential-tranche-v1:account-two"
                ),
            )
            auth_path.write_text(
                json.dumps(
                    {
                        "credential_pool": {
                            "openai-codex": [
                                {"account_id": "account-one"},
                                {"account_id": "account-two"},
                            ]
                        }
                    }
                )
                + "\n"
            )
            with self.assertRaisesRegex(
                migration.MigrationError, "exactly one credential"
            ):
                migration.account_fingerprint(auth_path)

    def test_old_manifest_validation_reads_frozen_git_commit_not_current_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old-freeze.json"
            frozen_bytes = b"old-frozen-content\n"
            payload = {
                "frozen_file_sha256": {
                    "benchmarks/example.txt": migration.sha256_bytes(frozen_bytes)
                }
            }
            payload["manifest_payload_sha256"] = migration.sha256_bytes(
                migration.canonical_json(payload)
            )
            path.write_text(json.dumps(payload) + "\n")

            with mock.patch.object(
                migration, "git_file_bytes", return_value=frozen_bytes
            ) as git_bytes:
                observed = migration.validate_manifest_at_commit(path, "old-commit")
            self.assertEqual(observed, payload)
            git_bytes.assert_called_once_with("old-commit", "benchmarks/example.txt")

            with mock.patch.object(
                migration, "git_file_bytes", return_value=b"current-tree-content\n"
            ):
                with self.assertRaisesRegex(
                    migration.MigrationError, "Frozen Git object mismatch"
                ):
                    migration.validate_manifest_at_commit(path, "old-commit")


if __name__ == "__main__":
    unittest.main()
