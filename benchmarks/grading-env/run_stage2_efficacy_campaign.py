from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agentharness.benchmark_cells import (
    HermesCliInvoker,
    execute_cell,
    prepare_fresh_cell,
    replay_uncommitted_successful_invocations,
)
from agentharness.stage2_analysis import build_dataset_from_progress, validate_campaign_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]

NORMATIVE_MANIFEST_RELATIVE = "benchmarks/grading-env/STAGE2_EFFICACY_FREEZE_2026-07-17.json"

REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "provider",
        "model",
        "toolsets",
        "max_turns",
        "codex_sse_idle_seconds",
        "invocation_max_retries",
        "retry_backoff_seconds",
        "tasks",
        "conditions",
        "replicates",
        "expected_cells",
        "expected_blocks",
        "blocks",
        "mme",
        "rerun_policy",
        "quota_policy",
        "analysis_parameters",
        "frozen_file_sha256",
        "manifest_payload_sha256",
    }
)

REQUIRED_FROZEN_FILE_KEYS = frozenset(
    {
        "benchmarks/grading-env/run_stage2_efficacy_campaign.py",
        "benchmarks/grading-env/finalize_stage2_efficacy.py",
        "benchmarks/grading-env/stage2_run_analysis.py",
        "benchmarks/grading-env/stage2-analysis-requirements.txt",
        "src/agentharness/benchmark_cells.py",
        "src/agentharness/evaluation.py",
        "src/agentharness/stage2_analysis.py",
    }
)

STATE_SCHEMA_VERSION = 2

PAUSE_QUOTA = 10
PAUSE_USAGE_UNAVAILABLE = 11
PAUSE_PROVENANCE = 12
PAUSE_PROVIDER = 13
PAUSE_ADJUDICATION = 20
INTEGRITY_FAILURE = 30
CONCURRENT_RUNNER = 31
UNEXPECTED_FAILURE = 50


class CampaignError(RuntimeError):
    exit_code = UNEXPECTED_FAILURE


class QuotaPause(CampaignError):
    exit_code = PAUSE_QUOTA


class UsageUnavailable(QuotaPause):
    exit_code = PAUSE_USAGE_UNAVAILABLE


class ProvenanceMismatch(CampaignError):
    exit_code = PAUSE_PROVENANCE


class ProviderPause(CampaignError):
    exit_code = PAUSE_PROVIDER


class AdjudicationRequired(CampaignError):
    exit_code = PAUSE_ADJUDICATION


class IntegrityFailure(CampaignError):
    exit_code = INTEGRITY_FAILURE


class ConcurrentRunner(CampaignError):
    exit_code = CONCURRENT_RUNNER


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: object, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    if mode is not None:
        os.chmod(path, mode)
    directory_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def append_event(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConcurrentRunner(f"Campaign lock is already held: {path}") from exc
        yield


class CodexQuotaGate:
    def __init__(
        self,
        *,
        run_root: Path,
        weekly_limit: float,
        session_limit: float,
        single_window_limit: float,
        allow_single_authoritative_window: bool,
    ) -> None:
        self.run_root = run_root
        self.weekly_limit = weekly_limit
        self.session_limit = session_limit
        self.single_window_limit = single_window_limit
        self.allow_single_authoritative_window = allow_single_authoritative_window
        self.last_snapshot: dict[str, object] | None = None

    def snapshot(self, *, phase: str) -> dict[str, object]:
        try:
            from agent.account_usage import fetch_account_usage

            usage = fetch_account_usage("openai-codex")
        except Exception as exc:
            raise UsageUnavailable(f"Codex usage lookup failed: {type(exc).__name__}") from exc
        if usage is None or not usage.available:
            raise UsageUnavailable("Codex usage is unavailable")
        windows: dict[str, dict[str, Any]] = {}
        for window in usage.windows:
            if window.used_percent is None or window.reset_at is None:
                continue
            windows[window.label.lower()] = {
                "used_percent": float(window.used_percent),
                "remaining_percent": max(0.0, 100.0 - float(window.used_percent)),
                "reset_at": window.reset_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        if "session" not in windows and "weekly" not in windows:
            raise UsageUnavailable("At least one authoritative Codex usage window is required")
        if len(windows) == 1 and not self.allow_single_authoritative_window:
            raise UsageUnavailable("Both Codex Session and Weekly windows are required")
        credit_risk = any("credit" in detail.lower() for detail in usage.details)
        snapshot: dict[str, object] = {
            "observed_at": utc_now(),
            "source": usage.source,
            "provider": usage.provider,
            "phase": phase,
            "windows": windows,
            "credit_risk": credit_risk,
        }
        snapshot["snapshot_sha256"] = sha256_bytes(canonical_json(snapshot))
        append_event(self.run_root / "quota-events.jsonl", snapshot)
        self.last_snapshot = snapshot
        if credit_risk:
            raise QuotaPause("Purchased-credit risk detected; campaign remains paused")
        if len(windows) == 1:
            label, only_window = next(iter(windows.items()))
            used = float(only_window["used_percent"])
            conservative_limit = self.single_window_limit
            if used >= conservative_limit:
                raise QuotaPause(
                    f"Quota reserve reached: {label}={used:.1f}% limit={conservative_limit:.1f}%"
                )
        else:
            weekly = float(windows["weekly"]["used_percent"])
            session = float(windows["session"]["used_percent"])
            if weekly >= self.weekly_limit or session >= self.session_limit:
                raise QuotaPause(
                    f"Quota reserve reached: weekly={weekly:.1f}% session={session:.1f}%"
                )
        return snapshot

    def admission_hook(self, attempt_name: str, retry_index: int) -> None:
        self.snapshot(phase=f"before:{attempt_name}:try{retry_index}")


class Stage2Campaign:
    def __init__(self, *, manifest_path: Path, run_root: Path) -> None:
        self.manifest_path = manifest_path.resolve()
        self.run_root = run_root.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        quota = self.manifest["quota_policy"]
        self.quota = CodexQuotaGate(
            run_root=self.run_root,
            weekly_limit=float(quota["weekly_used_pause_percent"]),
            session_limit=float(quota["session_used_pause_percent"]),
            single_window_limit=float(quota["single_window_pause_percent"]),
            allow_single_authoritative_window=bool(
                quota.get("allow_single_authoritative_window", False)
            ),
        )
        self.state_path = self.run_root / "campaign-state.private.json"
        self.progress_path = self.run_root / "progress.private.json"
        self.milestone_path = self.run_root / "milestones.json"

    # ------------------------------------------------------------------
    # Preflight / manifest binding
    # ------------------------------------------------------------------

    def preflight(self) -> dict[str, object]:
        expected_sse_idle = str(self.manifest["codex_sse_idle_seconds"])
        configured_sse_idle = os.environ.get("HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS")
        if configured_sse_idle not in {None, expected_sse_idle}:
            raise ProvenanceMismatch("Conflicting Codex SSE-idle watchdog override")
        os.environ["HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS"] = expected_sse_idle

        if _is_within(self.run_root, REPO_ROOT):
            raise IntegrityFailure("run_root must be outside the repository")

        expected_manifest_path = (REPO_ROOT / NORMATIVE_MANIFEST_RELATIVE).resolve()
        if self.manifest_path != expected_manifest_path:
            raise ProvenanceMismatch(
                f"Manifest must be the frozen normative file: {NORMATIVE_MANIFEST_RELATIVE}"
            )
        try:
            git("ls-files", "--error-unmatch", NORMATIVE_MANIFEST_RELATIVE)
        except subprocess.CalledProcessError as exc:
            raise ProvenanceMismatch("Normative manifest is not tracked in git") from exc

        missing_keys = sorted(REQUIRED_MANIFEST_KEYS - self.manifest.keys())
        if missing_keys:
            raise IntegrityFailure(f"Manifest missing required keys: {missing_keys}")

        expected_manifest_hash = str(self.manifest["manifest_payload_sha256"])
        manifest_copy = dict(self.manifest)
        manifest_copy.pop("manifest_payload_sha256", None)
        actual_manifest_hash = sha256_bytes(canonical_json(manifest_copy))
        if actual_manifest_hash != expected_manifest_hash:
            raise IntegrityFailure("Campaign manifest payload hash mismatch")
        manifest_file_hash = sha256_file(self.manifest_path)

        if self.manifest["provider"] != "openai-codex" or self.manifest["model"] != "gpt-5.6-sol":
            raise ProvenanceMismatch("Frozen provider/model mismatch")

        tasks = list(self.manifest["tasks"])
        blocks = list(self.manifest["blocks"])
        replicates = list(self.manifest["replicates"])
        if len(tasks) != 20 or replicates != ["r1", "r2", "r3"] or len(blocks) != 60:
            raise IntegrityFailure("Frozen campaign shape is not 20 tasks x 3 replicate blocks")

        expected_block_ids = {f"b{index:03d}" for index in range(1, 61)}
        observed_block_ids = {str(row["block_id"]) for row in blocks}
        if observed_block_ids != expected_block_ids:
            raise IntegrityFailure("Block ID roster mismatch: expected b001..b060")

        expected_pairs = {(task, rep) for task in tasks for rep in replicates}
        observed_pairs = {(str(row["task_id"]), str(row["replicate_id"])) for row in blocks}
        if observed_pairs != expected_pairs:
            raise IntegrityFailure("Block roster mismatch")

        cell_ids: set[str] = set()
        for row in blocks:
            if sorted(row["condition_order"]) != ["A-baseline", "B-agentharness"]:
                raise IntegrityFailure(f"Invalid condition order in {row['block_id']}")
            for slot in (1, 2):
                cell_ids.add(f"{row['block_id']}-s{slot}")
        if len(cell_ids) != 120:
            raise IntegrityFailure("Cell ID roster is not unique/complete")

        if int(self.manifest["expected_cells"]) != 120:
            raise IntegrityFailure("Expected-cell count mismatch")

        required_frozen_keys = set(REQUIRED_FROZEN_FILE_KEYS)
        for task in tasks:
            required_frozen_keys.add(f"benchmarks/{task}/SPEC.md")
            required_frozen_keys.add(f"benchmarks/{task}/CLAIMS_CONTRACT.template.json")
        frozen_hashes = self.manifest["frozen_file_sha256"]
        missing_frozen_keys = sorted(required_frozen_keys - frozen_hashes.keys())
        if missing_frozen_keys:
            raise IntegrityFailure(f"Manifest frozen_file_sha256 missing required keys: {missing_frozen_keys}")
        for relative, expected in frozen_hashes.items():
            path = REPO_ROOT / relative
            if not path.is_file() or sha256_file(path) != expected:
                raise IntegrityFailure(f"Frozen file hash mismatch: {relative}")

        if git("status", "--porcelain"):
            raise ProvenanceMismatch("Repository must be clean before campaign execution")
        head = git("rev-parse", "HEAD")
        origin = git("rev-parse", "origin/main")
        if head != origin:
            raise ProvenanceMismatch("HEAD must equal origin/main")

        return {
            "ok": True,
            "campaign_id": self.manifest["campaign_id"],
            "manifest_sha256": expected_manifest_hash,
            "manifest_file_sha256": manifest_file_hash,
            "repository_commit": head,
            "task_count": len(tasks),
            "block_count": len(blocks),
            "cell_count": int(self.manifest["expected_cells"]),
        }

    # ------------------------------------------------------------------
    # State lifecycle
    # ------------------------------------------------------------------

    def _initial_state(self, preflight: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "campaign_id": self.manifest["campaign_id"],
            "manifest_sha256": preflight["manifest_sha256"],
            "manifest_file_sha256": preflight["manifest_file_sha256"],
            "repository_commit": preflight["repository_commit"],
            "status": "ready",
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "current_cell": None,
            "counters": {
                "quota_pauses": 0,
                "provider_failures": {},
                "crash_recoveries": {},
                "physical_cell_attempts": {},
                "harness_reruns": {},
            },
            "resume_count": 0,
        }

    def _validate_current_cell(self, current: object) -> None:
        if not isinstance(current, dict):
            raise IntegrityFailure("Recovered current_cell is not an object")
        block_id = str(current.get("block_id"))
        block = next(
            (row for row in self.manifest["blocks"] if str(row["block_id"]) == block_id), None
        )
        if block is None:
            raise IntegrityFailure(f"Recovered current_cell references unknown block {block_id}")
        slot = current.get("slot")
        if slot not in (1, 2):
            raise IntegrityFailure("Recovered current_cell has an invalid slot")
        expected_condition = str(block["condition_order"][slot - 1])
        expected = {
            "cell_id": f"{block_id}-s{slot}",
            "condition": expected_condition,
            "task_id": str(block["task_id"]),
            "replicate_id": str(block["replicate_id"]),
        }
        for key, expected_value in expected.items():
            if str(current.get(key)) != expected_value:
                raise IntegrityFailure(
                    f"Recovered current_cell {key} mismatch: {current.get(key)!r} != {expected_value!r}"
                )

    def _load_or_initialize(self, preflight: dict[str, object]) -> dict[str, object]:
        self.run_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.run_root, 0o700)
        if self.state_path.is_file():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if int(state.get("schema_version", 0)) != STATE_SCHEMA_VERSION:
                raise IntegrityFailure("Unsupported campaign state schema version")
            if state.get("manifest_sha256") != preflight["manifest_sha256"]:
                raise IntegrityFailure("Resume manifest payload differs from frozen state")
            if state.get("manifest_file_sha256") != preflight["manifest_file_sha256"]:
                raise IntegrityFailure("Resume manifest file differs from frozen state")
            if state.get("repository_commit") != preflight["repository_commit"]:
                raise ProvenanceMismatch("Resume repository commit differs from launch commit")
            current = state.get("current_cell")
            if current is not None:
                self._validate_current_cell(current)
            state["resume_count"] = int(state.get("resume_count", 0)) + 1
            self._save_state(state)
            return state
        state = self._initial_state(preflight)
        atomic_write(self.state_path, state, mode=0o600)
        provenance = {
            **preflight,
            "created_at": utc_now(),
            "python": sys.version,
            "platform": platform.platform(),
            "hermes_version": subprocess.run(
                ["hermes", "--version"], text=True, capture_output=True, check=True
            ).stdout.strip(),
            "manifest_path": str(self.manifest_path),
            "manifest_file_sha256": preflight["manifest_file_sha256"],
            "fallback_disabled": True,
            "credential_rotation_disabled": True,
            "auth_reset_forbidden": True,
            "purchased_credits_forbidden": True,
            "codex_sse_idle_seconds": self.manifest["codex_sse_idle_seconds"],
        }
        atomic_write(self.run_root / "run-provenance.json", provenance, mode=0o600)
        atomic_write(self.progress_path, [], mode=0o600)
        return state

    def _save_state(self, state: dict[str, object]) -> None:
        state["updated_at"] = utc_now()
        atomic_write(self.state_path, state, mode=0o600)

    def _note_quota_pause(self, state: dict[str, object]) -> None:
        counters = state["counters"]
        assert isinstance(counters, dict)
        counters["quota_pauses"] = int(counters.get("quota_pauses", 0)) + 1
        state["status"] = "paused_quota"
        self._save_state(state)

    # ------------------------------------------------------------------
    # Cell-level filesystem helpers
    # ------------------------------------------------------------------

    def _cell_dir(self, cell_id: str) -> Path:
        return self.run_root / "private-cells" / cell_id

    def _read_commit(self, cell_id: str) -> dict[str, object] | None:
        path = self._cell_dir(cell_id) / "cell-result.commit.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate_cell_identity(
        self,
        result: dict[str, object],
        *,
        block: dict[str, object],
        condition: str,
        slot: int,
        cell_id: str,
    ) -> None:
        expected = {
            "block_id": str(block["block_id"]),
            "task_id": str(block["task_id"]),
            "replicate_id": str(block["replicate_id"]),
            "condition": condition,
            "slot": slot,
            "campaign_cell_id": cell_id,
        }
        for key, expected_value in expected.items():
            if result.get(key) != expected_value:
                raise IntegrityFailure(f"Recovered cell identity mismatch for {cell_id}: {key}")

    def _archive_attempt(self, cell_id: str, cell_dir: Path, attempt_no: int, *, reason: str) -> None:
        if not cell_dir.exists():
            return
        quarantine_root = self.run_root / "quarantine" / cell_id
        quarantine_root.mkdir(parents=True, exist_ok=True)
        os.chmod(quarantine_root, 0o700)
        archive = quarantine_root / f"attempt-{attempt_no:02d}-{reason}"
        if archive.exists():
            raise IntegrityFailure(f"Quarantine destination already exists: {archive}")
        shutil.move(str(cell_dir), str(archive))
        os.chmod(archive, 0o700)

    def _reconcile_crashed_attempts(self, state: dict[str, object]) -> None:
        current = state.get("current_cell")
        private_cells_dir = self.run_root / "private-cells"
        counters = state["counters"]
        assert isinstance(counters, dict)
        crash_recoveries = counters.setdefault("crash_recoveries", {})
        harness_reruns = counters.setdefault("harness_reruns", {})
        physical_attempts = counters.setdefault("physical_cell_attempts", {})
        assert isinstance(crash_recoveries, dict) and isinstance(harness_reruns, dict) and isinstance(physical_attempts, dict)
        reconciled = False
        if private_cells_dir.is_dir():
            os.chmod(private_cells_dir, 0o700)
            for block in self.manifest["blocks"]:
                for slot in (1, 2):
                    cell_id = f"{block['block_id']}-s{slot}"
                    cell_dir = private_cells_dir / cell_id
                    if not cell_dir.exists():
                        continue
                    if (cell_dir / "cell-result.commit.json").is_file():
                        os.chmod(cell_dir, 0o700)
                        continue
                    if isinstance(current, dict) and str(current.get("cell_id")) == cell_id:
                        attempt_no = int(current.get("attempt_no", 1))
                    else:
                        attempt_no = int(physical_attempts.get(cell_id, 0)) or 1
                    invocation_meta = list(
                        (cell_dir / "outputs" / "agent-invocations").glob("attempt-*.meta.json")
                    )
                    if len(invocation_meta) >= 2:
                        used = int(harness_reruns.get(cell_id, 0))
                        allowed = int(self.manifest["rerun_policy"]["harness_invalid_fresh_reruns"])
                        if used >= allowed:
                            condition = str(block["condition_order"][slot - 1])
                            if condition != "A-baseline":
                                raise AdjudicationRequired(
                                    f"Completed-invocation recovery exhausted harness rerun allowance for {cell_id}"
                                )
                            try:
                                recovered = replay_uncommitted_successful_invocations(cell_dir)
                            except ValueError as exc:
                                raise AdjudicationRequired(
                                    f"Persisted-invocation replay rejected {cell_id}: {exc}"
                                ) from exc
                            enriched = self._finalize_cell_result(recovered, cell_dir, cell_id)
                            enriched.update(
                                {
                                    "campaign_cell_id": cell_id,
                                    "block_id": str(block["block_id"]),
                                    "slot": slot,
                                    "execution_attempt_no": attempt_no,
                                    "recovered_without_agent_reinvocation": True,
                                }
                            )
                            atomic_write(cell_dir / "cell-result.commit.json", enriched, mode=0o600)
                        else:
                            self._archive_attempt(
                                cell_id, cell_dir, attempt_no, reason="harness_invalid_recovery"
                            )
                            harness_reruns[cell_id] = used + 1
                    else:
                        self._archive_attempt(cell_id, cell_dir, attempt_no, reason="crash_recovery")
                        crash_recoveries[cell_id] = int(crash_recoveries.get(cell_id, 0)) + 1
                    reconciled = True
        if current is not None:
            state["current_cell"] = None
            reconciled = True
        if reconciled:
            state["status"] = "ready"
            self._save_state(state)

    # ------------------------------------------------------------------
    # Block journals (pair-atomicity source of truth)
    # ------------------------------------------------------------------

    def _journal_path(self, block_id: str) -> Path:
        return self.run_root / "block-journals" / f"{block_id}.commit.json"

    def _load_committed_blocks(self) -> dict[str, list[dict[str, object]]]:
        out: dict[str, list[dict[str, object]]] = {}
        for block in self.manifest["blocks"]:
            block_id = str(block["block_id"])
            path = self._journal_path(block_id)
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("rows")
            if payload.get("block_id") != block_id or not isinstance(rows, list) or len(rows) != 2:
                raise IntegrityFailure(f"Corrupt block journal for {block_id}")
            observed_conditions = {str(row.get("condition")) for row in rows}
            if observed_conditions != set(block["condition_order"]):
                raise IntegrityFailure(f"Block journal condition mismatch for {block_id}")
            for slot, condition in enumerate(block["condition_order"], start=1):
                row = next((r for r in rows if str(r.get("condition")) == str(condition)), None)
                if row is None:
                    raise IntegrityFailure(f"Block journal missing condition {condition} for {block_id}")
                self._validate_cell_identity(
                    row, block=block, condition=str(condition), slot=slot, cell_id=f"{block_id}-s{slot}"
                )
            out[block_id] = rows
        return out

    def _rebuild_progress(self, committed: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for block in self.manifest["blocks"]:
            block_id = str(block["block_id"])
            block_rows = committed.get(block_id)
            if block_rows is None:
                continue
            ordered = sorted(block_rows, key=lambda row: int(row["slot"]))
            for final in ordered:
                rows.append(
                    {
                        "task_id": final["task_id"],
                        "condition": final["condition"],
                        "replicate_id": final["replicate_id"],
                        "block_id": block_id,
                        "campaign_cell_id": final["campaign_cell_id"],
                        "final": final,
                    }
                )
        return rows

    def _commit_block(
        self, block: dict[str, object], slot_results: dict[int, dict[str, object]]
    ) -> list[dict[str, object]]:
        block_id = str(block["block_id"])
        if set(slot_results.keys()) != {1, 2}:
            raise IntegrityFailure(f"Block {block_id} is not pair-complete")
        rows = [slot_results[1], slot_results[2]]
        observed_conditions = {str(row["condition"]) for row in rows}
        if observed_conditions != set(block["condition_order"]):
            raise IntegrityFailure(f"Block {block_id} condition pair mismatch")
        journal_path = self._journal_path(block_id)
        if journal_path.is_file():
            raise IntegrityFailure(f"Block {block_id} already committed")
        payload = {
            "block_id": block_id,
            "task_id": str(block["task_id"]),
            "replicate_id": str(block["replicate_id"]),
            "committed_at": utc_now(),
            "rows": rows,
        }
        atomic_write(journal_path, payload, mode=0o600)
        os.chmod(journal_path.parent, 0o700)
        return rows

    # ------------------------------------------------------------------
    # Cost aggregation (requirement: include quarantined physical attempts)
    # ------------------------------------------------------------------

    def _aggregate_cell_cost(self, cell_id: str, final_cell_dir: Path) -> dict[str, object]:
        meta_files: list[Path] = []
        quarantine_dir = self.run_root / "quarantine" / cell_id
        if quarantine_dir.is_dir():
            for attempt_dir in sorted(quarantine_dir.iterdir()):
                meta_files.extend(sorted((attempt_dir / "outputs" / "agent-invocations").glob("*.meta.json")))
        meta_files.extend(sorted((final_cell_dir / "outputs" / "agent-invocations").glob("*.meta.json")))
        included_attempt_ids: list[str] = []
        seen: set[str] = set()
        total_duration = 0.0
        for meta_path in meta_files:
            attempt_id = str(meta_path.relative_to(self.run_root))
            if attempt_id in seen:
                continue
            seen.add(attempt_id)
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            total_duration += float(payload.get("duration_seconds", 0.0))
            included_attempt_ids.append(attempt_id)
        return {
            "agent_invocation_count": len(included_attempt_ids),
            "agent_duration_seconds": total_duration,
            "agent_invocation_attempt_ids": included_attempt_ids,
        }

    def _finalize_cell_result(
        self, result: dict[str, object], cell_dir: Path, cell_id: str
    ) -> dict[str, object]:
        enriched = dict(result)
        provenance_path = cell_dir / "provenance.json"
        if provenance_path.is_file():
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            enriched["treatment_delivery"] = provenance.get("treatment_delivery")
        cost = self._aggregate_cell_cost(cell_id, cell_dir)
        enriched["agent_invocation_count"] = cost["agent_invocation_count"]
        enriched["agent_duration_seconds"] = cost["agent_duration_seconds"]
        enriched["agent_invocation_attempt_ids"] = cost["agent_invocation_attempt_ids"]
        return enriched

    # ------------------------------------------------------------------
    # Cell execution
    # ------------------------------------------------------------------

    def _execute_planned_cell(
        self,
        *,
        state: dict[str, object],
        block: dict[str, object],
        condition: str,
        slot: int,
        cell_id: str,
    ) -> dict[str, object]:
        cell_dir = self._cell_dir(cell_id)
        counters = state["counters"]
        assert isinstance(counters, dict)
        physical_attempts = counters["physical_cell_attempts"]
        provider_failures = counters["provider_failures"]
        harness_reruns = counters["harness_reruns"]
        assert isinstance(physical_attempts, dict) and isinstance(provider_failures, dict) and isinstance(harness_reruns, dict)

        while True:
            if cell_dir.exists():
                raise IntegrityFailure(f"Unexpected residual cell directory before attempt: {cell_dir}")
            attempt_no = int(physical_attempts.get(cell_id, 0)) + 1
            physical_attempts[cell_id] = attempt_no
            state["current_cell"] = {
                "cell_id": cell_id,
                "block_id": str(block["block_id"]),
                "task_id": str(block["task_id"]),
                "replicate_id": str(block["replicate_id"]),
                "condition": condition,
                "slot": slot,
                "attempt_no": attempt_no,
                "started_at": utc_now(),
            }
            state["status"] = "running"
            self._save_state(state)

            manifest = prepare_fresh_cell(
                task_id=str(block["task_id"]),
                condition=condition,
                replicate_id=str(block["replicate_id"]),
                cell_dir=cell_dir,
            )
            os.chmod(self.run_root / "private-cells", 0o700)
            os.chmod(cell_dir, 0o700)
            manifest["run_id"] = f"{self.manifest['campaign_id']}_{safe_slug(cell_id)}_a{attempt_no}"
            manifest["diagnostic_stage"] = "stage2_efficacy"
            atomic_write(cell_dir / "cell_manifest.json", manifest, mode=0o600)

            invoker = HermesCliInvoker(
                toolsets=str(self.manifest["toolsets"]),
                max_retries=int(self.manifest["invocation_max_retries"]),
                retry_backoff_seconds=float(self.manifest["retry_backoff_seconds"]),
                provider=str(self.manifest["provider"]),
                model=str(self.manifest["model"]),
                max_turns=int(self.manifest["max_turns"]),
                admission_hook=self.quota.admission_hook,
            )
            try:
                result = execute_cell(cell_dir, invoker)
            except QuotaPause:
                self._note_quota_pause(state)
                raise

            reason = str(result.get("benchmark_classification_reason") or "")
            if reason.startswith("provider_unavailable"):
                self._archive_attempt(cell_id, cell_dir, attempt_no, reason="provider_unavailable")
                provider_failures[cell_id] = int(provider_failures.get(cell_id, 0)) + 1
                state["current_cell"] = None
                state["status"] = "paused_provider"
                self._save_state(state)
                if int(provider_failures[cell_id]) >= int(self.manifest["rerun_policy"]["max_provider_attempts"]):
                    raise AdjudicationRequired(
                        f"Provider failure limit reached for {cell_id}; adjudication required"
                    )
                raise ProviderPause(f"Provider unavailable in {cell_id}; resume after verified reset")

            if result.get("benchmark_execution_status") == "harness_invalid":
                used = int(harness_reruns.get(cell_id, 0))
                allowed = int(self.manifest["rerun_policy"]["harness_invalid_fresh_reruns"])
                if used < allowed:
                    harness_reruns[cell_id] = used + 1
                    self._archive_attempt(cell_id, cell_dir, attempt_no, reason="harness_invalid_rerun")
                    state["current_cell"] = None
                    self._save_state(state)
                    continue

            enriched = self._finalize_cell_result(result, cell_dir, cell_id)
            enriched.update(
                {
                    "campaign_cell_id": cell_id,
                    "block_id": str(block["block_id"]),
                    "slot": slot,
                    "execution_attempt_no": attempt_no,
                }
            )
            atomic_write(cell_dir / "cell-result.commit.json", enriched, mode=0o600)
            state["current_cell"] = None
            self._save_state(state)
            return enriched

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------

    def _write_milestone(
        self,
        state: dict[str, object],
        committed: dict[str, list[dict[str, object]]],
        progress: list[dict[str, object]],
        *,
        dataset_sha256: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "campaign_id": self.manifest["campaign_id"],
            "updated_at": utc_now(),
            "completed_blocks": len(committed),
            "total_blocks": len(self.manifest["blocks"]),
            "completed_cells": len(progress),
            "total_cells": int(self.manifest["expected_cells"]),
            "status": state["status"],
            "quota_snapshot": self.quota.last_snapshot,
        }
        if dataset_sha256 is not None:
            payload["dataset_sha256"] = dataset_sha256
        atomic_write(self.milestone_path, payload)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        preflight = self.preflight()
        with exclusive_lock(self.run_root / "campaign.lock"):
            state = self._load_or_initialize(preflight)
            if state["status"] == "complete":
                return 0
            self._reconcile_crashed_attempts(state)

            committed = self._load_committed_blocks()
            progress = self._rebuild_progress(committed)
            atomic_write(self.progress_path, progress, mode=0o600)

            for block in self.manifest["blocks"]:
                block_id = str(block["block_id"])
                if block_id in committed:
                    continue
                slot_results: dict[int, dict[str, object]] = {}
                for slot, condition in enumerate(block["condition_order"], start=1):
                    cell_id = f"{block_id}-s{slot}"
                    existing = self._read_commit(cell_id)
                    if existing is not None:
                        self._validate_cell_identity(
                            existing, block=block, condition=str(condition), slot=slot, cell_id=cell_id
                        )
                        slot_results[slot] = existing
                        continue
                    try:
                        self.quota.snapshot(phase=f"before_cell:{block_id}:slot{slot}")
                    except QuotaPause:
                        self._note_quota_pause(state)
                        raise
                    slot_results[slot] = self._execute_planned_cell(
                        state=state, block=block, condition=str(condition), slot=slot, cell_id=cell_id
                    )
                rows = self._commit_block(block, slot_results)
                committed[block_id] = rows
                progress = self._rebuild_progress(committed)
                atomic_write(self.progress_path, progress, mode=0o600)
                state["status"] = "running"
                self._save_state(state)
                self._write_milestone(state, committed, progress)

            validate_campaign_dataset(
                build_dataset_from_progress(self.progress_path),
                expected_task_ids=list(self.manifest["tasks"]),
                expected_replicates_per_condition=3,
            )
            if len(progress) != int(self.manifest["expected_cells"]):
                raise IntegrityFailure("Final progress row count mismatch")

            rows = build_dataset_from_progress(self.progress_path)
            dataset_path = self.run_root / "analysis-dataset.sealed.json"
            atomic_write(dataset_path, rows, mode=0o600)
            seal = {
                "campaign_id": self.manifest["campaign_id"],
                "manifest_file_sha256": preflight["manifest_file_sha256"],
                "repository_commit": preflight["repository_commit"],
                "sealed_at": utc_now(),
                "progress_sha256": sha256_file(self.progress_path),
                "dataset_sha256": sha256_file(dataset_path),
                "rows": len(rows),
                "blocks": len(committed),
                "analysis_authorized": True,
            }
            atomic_write(self.run_root / "dataset-seal.json", seal, mode=0o600)
            state["status"] = "complete"
            state["completed_at"] = utc_now()
            self._save_state(state)
            self._write_milestone(state, committed, progress, dataset_sha256=seal["dataset_sha256"])
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen Stage 2 AgentHarness efficacy campaign")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    campaign = Stage2Campaign(manifest_path=args.manifest, run_root=args.run_root)
    try:
        result = campaign.preflight()
        if args.preflight:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        return campaign.run()
    except CampaignError as exc:
        print(json.dumps({"status": "paused_or_failed", "reason": str(exc), "exit_code": exc.exit_code}))
        return exc.exit_code
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "unexpected_failure",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "exit_code": UNEXPECTED_FAILURE,
                }
            )
        )
        return UNEXPECTED_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
