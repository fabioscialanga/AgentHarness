from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = (REPO_ROOT / "src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import agentharness
from agentharness.benchmark_cells import (
    EXPECTED_HELDOUT_CASES,
    HermesCliInvoker,
    execute_cell,
    heldout_suite_template_path,
    prepare_fresh_cell,
)
from agentharness.benchmarking import render_json_template
from agentharness.evaluation import validate_evaluation_suite_payload

if not Path(agentharness.__file__).resolve().is_relative_to(SRC_ROOT):
    raise ImportError("agentharness must be loaded from this repository")

MANIFEST_RELATIVE = "benchmarks/grading-env/EXPLORATORY_ACTIONABLE_REPAIR_V1_2026-07-27.json"
PILOT_ID = "exploratory_actionable_repair_v1"
STATE_SCHEMA_VERSION = 1
STOP_PROVIDER = 13
STOP_TREATMENT = 14
STOP_QUOTA = 10
INTEGRITY_FAILURE = 30
CONCURRENT_RUNNER = 31
UNEXPECTED_FAILURE = 50


class PilotError(RuntimeError):
    exit_code = UNEXPECTED_FAILURE


class IntegrityFailure(PilotError):
    exit_code = INTEGRITY_FAILURE


class ProviderUnavailable(PilotError):
    exit_code = STOP_PROVIDER


class TreatmentNotDelivered(PilotError):
    exit_code = STOP_TREATMENT


class QuotaPause(PilotError):
    exit_code = STOP_QUOTA


class ConcurrentRunner(PilotError):
    exit_code = CONCURRENT_RUNNER


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, payload: object, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with tmp.open("wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    if private:
        os.chmod(path, 0o600)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConcurrentRunner("pilot runner lock already held") from exc
        yield


def manifest_payload_hash(manifest: dict[str, object]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_payload_sha256", None)
    return sha256_bytes(canonical_json(payload))


def structural_message(**values: object) -> None:
    """The only collection-time stdout path; callers must not pass outcome values."""
    allowed = {
        "status", "completed_blocks", "total_blocks", "completed_cells", "total_cells",
        "invalidity", "exit_code", "resume_count",
    }
    if not set(values).issubset(allowed):
        raise ValueError("non-structural console field")
    print(json.dumps(values, sort_keys=True), flush=True)


def validate_suite_executability(tasks: list[str]) -> dict[str, str]:
    """Validate every envelope and both evaluation command entry points without scoring a cell."""
    hashes: dict[str, str] = {}
    for task in tasks:
        path = heldout_suite_template_path(task)
        run_id = f"{PILOT_ID}_preflight_{task}"
        payload = render_json_template(path, run_id=run_id)
        errors = validate_evaluation_suite_payload(
            payload, run_id=run_id, expected_case_count=EXPECTED_HELDOUT_CASES
        )
        if errors:
            raise IntegrityFailure(f"heldout suite invalid for {task}: {'|'.join(errors)}")
        hashes[task] = sha256_file(path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for command in ("evaluate", "benchmark-evaluate-task"):
        completed = subprocess.run(
            [sys.executable, "-m", "agentharness", command, "--help"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        if completed.returncode != 0:
            raise IntegrityFailure(f"heldout command is not executable: {command}")
    return hashes


def fetch_usage(provider: str) -> object:
    from agent.account_usage import fetch_account_usage

    return fetch_account_usage(provider)


class ExploratoryPilot:
    def __init__(self, *, manifest_path: Path, run_root: Path) -> None:
        self.manifest_path = manifest_path.resolve()
        self.run_root = run_root.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.state_path = self.run_root / "campaign-state.private.json"
        self.progress_path = self.run_root / "progress.private.json"
        self.audit_path = self.run_root / "collection-audit.final.json"

    def preflight(self) -> dict[str, object]:
        if self.manifest_path != (REPO_ROOT / MANIFEST_RELATIVE).resolve():
            raise IntegrityFailure("manifest must be the dated normative pilot manifest")
        if within(self.run_root, REPO_ROOT):
            raise IntegrityFailure("run root must be outside the repository")
        m = self.manifest
        if m.get("pilot_id") != PILOT_ID or m.get("study_class") != "exploratory" or m.get("confirmatory") is not False:
            raise IntegrityFailure("pilot identity/classification mismatch")
        if manifest_payload_hash(m) != m.get("manifest_payload_sha256"):
            raise IntegrityFailure("manifest payload hash mismatch")
        tasks = [str(value) for value in m.get("tasks", [])]
        expected_tasks = [
            "pii-redaction-pipeline", "lease-coordination-api",
            "double-entry-ledger-api", "signed-artifact-verifier",
        ]
        if tasks != expected_tasks:
            raise IntegrityFailure("task roster/order mismatch")
        blocks = m.get("blocks")
        if not isinstance(blocks, list) or len(blocks) != 4 or m.get("expected_cells") != 8:
            raise IntegrityFailure("pilot must contain four paired blocks and eight cells")
        starts: list[str] = []
        seen_tasks: set[str] = set()
        for index, block in enumerate(blocks, 1):
            if not isinstance(block, dict):
                raise IntegrityFailure("block is not an object")
            order = block.get("condition_order")
            if sorted(order or []) != ["A-baseline", "B-agentharness"]:
                raise IntegrityFailure("each block must contain exactly one A and one B")
            if block.get("block_id") != f"p{index:03d}":
                raise IntegrityFailure("block order/id mismatch")
            seen_tasks.add(str(block.get("task_id")))
            starts.append(str(order[0]))
        if seen_tasks != set(tasks) or starts.count("A-baseline") != 2 or starts.count("B-agentharness") != 2:
            raise IntegrityFailure("counterbalancing/task pairing mismatch")
        frozen = m.get("frozen_file_sha256")
        if not isinstance(frozen, dict):
            raise IntegrityFailure("frozen hashes missing")
        for relative, expected in frozen.items():
            path = REPO_ROOT / str(relative)
            if not path.is_file() or sha256_file(path) != expected:
                raise IntegrityFailure(f"frozen file hash mismatch: {relative}")
        expected_runtime = {
            "provider": "openai-codex", "model": "gpt-5.6-sol",
            "hermes_command": "/home/fabio/.local/bin/stage2codex2",
            "hermes_home": "/home/fabio/.hermes/profiles/stage2codex2",
            "toolsets": "terminal,file", "max_turns": 40,
        }
        for key, expected in expected_runtime.items():
            if m.get(key) != expected:
                raise IntegrityFailure(f"runtime pin mismatch: {key}")
        command = Path(str(m["hermes_command"]))
        if not command.is_file() or not os.access(command, os.X_OK) or sha256_file(command) != m.get("hermes_command_sha256"):
            raise IntegrityFailure("Hermes command missing, non-executable, or hash-mismatched")
        if os.environ.get("HERMES_HOME") != m["hermes_home"]:
            raise IntegrityFailure("HERMES_HOME is not pinned to the manifest")

        # All non-destructive checks, including every heldout suite, precede any
        # reconciliation or prepare_fresh_cell call that can remove a directory.
        suite_hashes = validate_suite_executability(tasks)
        if git("status", "--porcelain", "--untracked-files=all"):
            raise IntegrityFailure("repository must be clean")
        head = git("rev-parse", "HEAD")
        published = git("rev-parse", str(m["published_ref"]))
        if head != published:
            raise IntegrityFailure("HEAD must exactly equal the published ref")
        return {
            "ok": True, "repository_commit": head,
            "manifest_file_sha256": sha256_file(self.manifest_path),
            "manifest_payload_sha256": m["manifest_payload_sha256"],
            "suite_sha256": suite_hashes, "blocks": 4, "cells": 8,
        }

    def _initial_state(self, preflight: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": STATE_SCHEMA_VERSION, "pilot_id": PILOT_ID,
            "status": "ready", "started_at": utc_now(), "updated_at": utc_now(),
            "repository_commit": preflight["repository_commit"],
            "manifest_file_sha256": preflight["manifest_file_sha256"],
            "manifest_payload_sha256": preflight["manifest_payload_sha256"],
            "current_cell": None, "resume_count": 0,
            "counters": {"invalidities": {}, "physical_attempts": {}},
        }

    def _save_state(self, state: dict[str, object]) -> None:
        state["updated_at"] = utc_now()
        atomic_write(self.state_path, state, private=True)

    def _load_state(self, preflight: dict[str, object]) -> dict[str, object]:
        self.run_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.run_root, 0o700)
        if not self.state_path.is_file():
            state = self._initial_state(preflight)
            self._save_state(state)
            return state
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for key in ("repository_commit", "manifest_file_sha256", "manifest_payload_sha256"):
            if state.get(key) != preflight[key]:
                raise IntegrityFailure(f"resume binding mismatch: {key}")
        state["resume_count"] = int(state.get("resume_count", 0)) + 1
        self._save_state(state)
        return state

    def _cell_dir(self, block_id: str, slot: int) -> Path:
        return self.run_root / "private-cells" / f"{block_id}-s{slot}"

    def _quota_gate(self, *, phase: str) -> None:
        """Fail closed before every model invocation using the pinned account path."""
        try:
            usage = fetch_usage(str(self.manifest["provider"]))
        except Exception as exc:
            raise QuotaPause(f"quota telemetry unavailable: {type(exc).__name__}") from exc
        windows = list(getattr(usage, "windows", []) or []) if usage is not None else []
        if not getattr(usage, "available", False) or len(windows) != 1:
            raise QuotaPause("exactly one authoritative usage window is required")
        used_percent = float(windows[0].used_percent)
        reset_at = getattr(windows[0], "reset_at", None)
        snapshots = self.run_root / "quota-snapshots.private.jsonl"
        snapshots.parent.mkdir(parents=True, exist_ok=True)
        with snapshots.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "phase": phase,
                "fetched_at": str(getattr(usage, "fetched_at", utc_now())),
                "used_percent": used_percent,
                "reset_at": str(reset_at) if reset_at is not None else None,
            }, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(snapshots, 0o600)
        limit = float(self.manifest["quota_policy"]["single_window_pause_percent"])
        if used_percent >= limit:
            raise QuotaPause(f"quota reserve reached: {used_percent} >= {limit}")

    def _reconcile_interrupted(self, state: dict[str, object]) -> None:
        current = state.get("current_cell")
        if not isinstance(current, dict):
            return
        cell_id = str(current["cell_id"])
        cell_dir = self.run_root / "private-cells" / cell_id
        if cell_dir.exists() and not (cell_dir / "cell-result.commit.json").is_file():
            attempt = int(current.get("attempt", 1))
            target = self.run_root / "quarantine" / cell_id / f"attempt-{attempt:02d}-interrupted"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise IntegrityFailure("interrupted-attempt quarantine collision")
            shutil.move(str(cell_dir), str(target))
        state["current_cell"] = None
        state["status"] = "ready"
        self._save_state(state)

    def _read_committed(self, block_id: str, slot: int) -> dict[str, object] | None:
        path = self._cell_dir(block_id, slot) / "cell-result.commit.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _private_progress(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for block in self.manifest["blocks"]:
            block_id = str(block["block_id"])
            pair = [self._read_committed(block_id, slot) for slot in (1, 2)]
            if all(row is not None for row in pair):
                rows.extend(row for row in pair if row is not None)
        return rows

    @staticmethod
    def _stop_invalidity(result: dict[str, object]) -> str | None:
        reason = str(result.get("benchmark_classification_reason") or "")
        if reason.startswith("provider_unavailable"):
            return "provider_unavailable"
        if reason.startswith("treatment_not_delivered") or result.get("treatment_delivered") is not True:
            return "treatment_not_delivered"
        return None

    def _execute(self, state: dict[str, object], block: dict[str, object], slot: int, condition: str) -> dict[str, object]:
        block_id = str(block["block_id"])
        cell_id = f"{block_id}-s{slot}"
        counters = state["counters"]
        assert isinstance(counters, dict)
        attempts = counters["physical_attempts"]
        assert isinstance(attempts, dict)
        attempt = int(attempts.get(cell_id, 0)) + 1
        attempts[cell_id] = attempt
        state["current_cell"] = {
            "cell_id": cell_id, "block_id": block_id, "slot": slot,
            "task_id": block["task_id"], "condition": condition, "attempt": attempt,
        }
        state["status"] = "running"
        self._save_state(state)
        cell_dir = self._cell_dir(block_id, slot)
        manifest = prepare_fresh_cell(
            task_id=str(block["task_id"]), condition=condition,
            replicate_id=str(block["replicate_id"]), cell_dir=cell_dir,
        )
        manifest["run_id"] = f"{PILOT_ID}_{cell_id}_a{attempt}"
        manifest["diagnostic_stage"] = PILOT_ID
        atomic_write(cell_dir / "cell_manifest.json", manifest, private=True)
        invoker = HermesCliInvoker(
            hermes_command=str(self.manifest["hermes_command"]),
            toolsets=str(self.manifest["toolsets"]),
            max_retries=int(self.manifest["invocation_max_retries"]),
            provider=str(self.manifest["provider"]), model=str(self.manifest["model"]),
            max_turns=int(self.manifest["max_turns"]),
        )
        try:
            self._quota_gate(phase=f"before:{cell_id}")
        except QuotaPause:
            state["status"] = "paused_quota"
            self._save_state(state)
            progress = self._private_progress()
            structural_message(
                status="paused", completed_blocks=len(progress) // 2,
                total_blocks=4, completed_cells=len(progress), total_cells=8,
                invalidity="quota_pause", exit_code=STOP_QUOTA,
            )
            raise
        result = execute_cell(cell_dir, invoker)
        invalidity = self._stop_invalidity(result)
        if invalidity:
            invalidities = counters["invalidities"]
            assert isinstance(invalidities, dict)
            invalidities[invalidity] = int(invalidities.get(invalidity, 0)) + 1
            state["status"] = f"paused_{invalidity}"
            self._save_state(state)
            structural_message(
                status="paused", completed_blocks=len(self._private_progress()) // 2,
                total_blocks=4, completed_cells=len(self._private_progress()), total_cells=8,
                invalidity=invalidity,
                exit_code=STOP_PROVIDER if invalidity == "provider_unavailable" else STOP_TREATMENT,
            )
            if invalidity == "provider_unavailable":
                raise ProviderUnavailable(invalidity)
            raise TreatmentNotDelivered(invalidity)
        enriched = dict(result)
        enriched.update({"pilot_cell_id": cell_id, "block_id": block_id, "slot": slot, "attempt": attempt})
        atomic_write(cell_dir / "cell-result.commit.json", enriched, private=True)
        state["current_cell"] = None
        self._save_state(state)
        return enriched

    def _write_final_audit(self, state: dict[str, object], progress: list[dict[str, object]]) -> None:
        audit = {
            "schema_version": 1, "pilot_id": PILOT_ID, "collection_complete": True,
            "analysis_authorized": True, "completed_at": utc_now(),
            "repository_commit": state["repository_commit"],
            "manifest_file_sha256": state["manifest_file_sha256"],
            "progress_sha256": sha256_file(self.progress_path),
            "completed_blocks": 4, "completed_cells": len(progress),
            "pair_complete": True,
        }
        atomic_write(self.audit_path, audit, private=True)

    def run(self) -> int:
        preflight = self.preflight()
        with exclusive_lock(self.run_root / "pilot.lock"):
            state = self._load_state(preflight)
            if state.get("status") == "complete":
                structural_message(status="complete", completed_blocks=4, total_blocks=4, completed_cells=8, total_cells=8, resume_count=state["resume_count"])
                return 0
            self._reconcile_interrupted(state)
            for block in self.manifest["blocks"]:
                block_id = str(block["block_id"])
                for slot, condition in enumerate(block["condition_order"], 1):
                    if self._read_committed(block_id, slot) is None:
                        self._execute(state, block, slot, str(condition))
                progress = self._private_progress()
                atomic_write(self.progress_path, progress, private=True)
                structural_message(status="collecting", completed_blocks=len(progress) // 2, total_blocks=4, completed_cells=len(progress), total_cells=8, resume_count=state["resume_count"])
            progress = self._private_progress()
            if len(progress) != 8:
                raise IntegrityFailure("collection did not reach four complete pairs")
            conditions_by_task: dict[str, set[str]] = {}
            for row in progress:
                conditions_by_task.setdefault(str(row["task_id"]), set()).add(str(row["condition"]))
            if any(value != {"A-baseline", "B-agentharness"} for value in conditions_by_task.values()):
                raise IntegrityFailure("A/B symmetry check failed")
            state["status"] = "complete"
            state["completed_at"] = utc_now()
            self._save_state(state)
            self._write_final_audit(state, progress)
            structural_message(status="complete", completed_blocks=4, total_blocks=4, completed_cells=8, total_cells=8, resume_count=state["resume_count"])
        return 0


def _cost_for_cell(run_root: Path, cell_id: str) -> dict[str, object]:
    paths = list((run_root / "private-cells" / cell_id / "outputs" / "agent-invocations").glob("*.meta.json"))
    paths += list((run_root / "quarantine" / cell_id).glob("*/outputs/agent-invocations/*.meta.json"))
    duration = 0.0
    unique: set[str] = set()
    for path in paths:
        identity = str(path.resolve())
        if identity in unique:
            continue
        unique.add(identity)
        duration += float(json.loads(path.read_text(encoding="utf-8")).get("duration_seconds", 0.0))
    return {"invocation_count_cost_proxy": len(unique), "duration_seconds": duration}


def finalize(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    if manifest_path.resolve() != (REPO_ROOT / MANIFEST_RELATIVE).resolve():
        raise IntegrityFailure("finalizer requires the normative dated manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest_payload_hash(manifest) != manifest.get("manifest_payload_sha256"):
        raise IntegrityFailure("finalizer manifest payload hash mismatch")
    state_path = run_root / "campaign-state.private.json"
    progress_path = run_root / "progress.private.json"
    audit_path = run_root / "collection-audit.final.json"
    if not state_path.is_file() or not progress_path.is_file() or not audit_path.is_file():
        raise IntegrityFailure("complete collection state/progress/audit required")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    rows = json.loads(progress_path.read_text(encoding="utf-8"))
    if state.get("status") != "complete" or audit.get("analysis_authorized") is not True or len(rows) != 8:
        raise IntegrityFailure("contrast remains blinded until complete eight-cell collection")
    if audit.get("progress_sha256") != sha256_file(progress_path):
        raise IntegrityFailure("private progress hash mismatch")
    expected_manifest_file_hash = sha256_file(manifest_path)
    if (
        state.get("manifest_file_sha256") != expected_manifest_file_hash
        or audit.get("manifest_file_sha256") != expected_manifest_file_hash
    ):
        raise IntegrityFailure("collection/finalizer manifest binding mismatch")
    by_task: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        by_task.setdefault(str(row["task_id"]), {})[str(row["condition"])] = row
    if set(by_task) != set(manifest["tasks"]) or any(set(pair) != {"A-baseline", "B-agentharness"} for pair in by_task.values()):
        raise IntegrityFailure("finalizer requires four exact A/B pairs")
    paired: list[dict[str, object]] = []
    for task in manifest["tasks"]:
        a, b = by_task[task]["A-baseline"], by_task[task]["B-agentharness"]
        if a.get("heldout_endpoint_valid") is not True or b.get("heldout_endpoint_valid") is not True:
            raise IntegrityFailure("all paired heldout endpoints must be valid")
        delta = float(b["score"]) - float(a["score"])
        paired.append({"task_id": task, "score_a": a["score"], "score_b": b["score"], "paired_difference_b_minus_a": delta})
    deltas = [float(row["paired_difference_b_minus_a"]) for row in paired]
    mean = sum(deltas) / 4
    positive = sum(value > 0 for value in deltas)
    nonpositive = sum(value <= 0 for value in deltas)
    if positive >= 3 and mean > 0:
        verdict = "directional_signal_positive"
    elif nonpositive >= 3 and mean <= 0:
        verdict = "no_directional_signal"
    else:
        verdict = "mixed_or_inconclusive"
    b_rows = [by_task[task]["B-agentharness"] for task in manifest["tasks"]]
    all_rows = [row for pair in by_task.values() for row in pair.values()]
    costs = {str(row["pilot_cell_id"]): _cost_for_cell(run_root, str(row["pilot_cell_id"])) for row in all_rows}
    result = {
        "schema_version": 1, "pilot_id": PILOT_ID, "study_class": "exploratory",
        "confirmatory": False, "n_paired_tasks": 4,
        "warning": "Exploratory n=4 directional evidence only; no strong or confirmatory inference.",
        "verdict": verdict, "verdict_rule": manifest["directional_verdict_rule"],
        "paired_heldout_scores": paired, "mean_paired_difference_b_minus_a": mean,
        "b_adoption_accounting": {
            "repair_response_valid": sum(row.get("repair_response_valid") is True for row in b_rows),
            "feedback_items_accounted": sum(row.get("feedback_items_accounted") is True for row in b_rows),
            "denominator": 4,
        },
        "b_resolution": {
            "supported": sum(int(row.get("feedback_postverify_supported") or 0) for row in b_rows),
            "unresolved": sum(int(row.get("feedback_postverify_unresolved") or 0) for row in b_rows),
        },
        "repair_retention_rollback": {
            "retained": sum(row.get("repair_change_retained") is True for row in all_rows),
            "rolled_back": sum(row.get("repair_rollback_performed") is True for row in all_rows),
            "cells": 8,
        },
        "invocation_cost_proxy_by_cell": costs,
        "total_invocation_count_cost_proxy": sum(int(value["invocation_count_cost_proxy"]) for value in costs.values()),
        "total_invocation_duration_seconds": sum(float(value["duration_seconds"]) for value in costs.values()),
    }
    output = run_root / "EXPLORATORY_ACTIONABLE_REPAIR_V1_RESULT.json"
    atomic_write(output, result, private=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run/finalize the pre-data actionable-repair mini-pilot")
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / MANIFEST_RELATIVE)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--finalize", action="store_true", help="explicitly unblind and compute contrasts after completion")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.finalize:
            result = finalize(manifest_path=args.manifest.resolve(), run_root=args.run_root.resolve())
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        pilot = ExploratoryPilot(manifest_path=args.manifest, run_root=args.run_root)
        if args.preflight:
            result = pilot.preflight()
            structural_message(status="preflight_ok", completed_blocks=0, total_blocks=int(result["blocks"]), completed_cells=0, total_cells=int(result["cells"]))
            return 0
        return pilot.run()
    except PilotError as exc:
        if not isinstance(exc, (QuotaPause, ProviderUnavailable, TreatmentNotDelivered)):
            structural_message(status="failed", completed_blocks=0, total_blocks=4, completed_cells=0, total_cells=8, invalidity=type(exc).__name__, exit_code=exc.exit_code)
        return exc.exit_code
    except Exception as exc:
        structural_message(status="failed", completed_blocks=0, total_blocks=4, completed_cells=0, total_cells=8, invalidity=type(exc).__name__, exit_code=UNEXPECTED_FAILURE)
        return UNEXPECTED_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
