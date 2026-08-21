from __future__ import annotations

"""Freeze-first mechanism-first V3 collector and offline finalizer.

The collector performs zero initial provider calls.  It materializes one
controlled start per task, clones it into A-baseline and B-agentharness, and
uses the hardened V2 ``HermesCliInvoker.run_cloned_repair`` path for the one
repair invocation in each cell.  Collection never computes the study verdict;
``--finalize`` is a separate, provider-free operation authorized by a green
collection audit.
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from contextlib import contextmanager

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentharness.benchmark_cells import (  # noqa: E402
    AGENT_INVOCATION_TIMEOUT_SECONDS,
    AgentInvocationResult,
    ClassifiedCellFailure,
    HermesCliInvoker,
    build_cell_manifest,
    compute_solution_hash,
)
from agentharness.benchmark_heldout_evaluator_v3 import evaluate_heldout  # noqa: E402
from agentharness.benchmark_review_evaluator_v3 import evaluate_review  # noqa: E402
from agentharness.efficacy_v3 import (  # noqa: E402
    OPAQUE_FINDING_IDS,
    TASKS,
    canonical_hash,
    clone_pair,
    finalize_results,
    materialize_clean_reference,
    materialize_controlled_start,
    tree_fingerprint,
    validate_opaque_feedback,
)

PILOT_ID = "mechanism_first_controlled_start_v3"
TEMPLATE_PATH = REPO_ROOT / "benchmarks/grading-env/MECHANISM_FIRST_V3_PREREG.template.json"
REFERENCES_ROOT = REPO_ROOT / "benchmarks/grading-env/task-expansion-batch1/references"
PLACEHOLDER = "FREEZE_REQUIRED:"
STOP_INTEGRITY = 30
STOP_INVOCATION = 13
UNEXPECTED = 50

# Runtime treatment names deliberately match the hardened V2 prompt switch.
CONDITIONS = ("A-baseline", "B-agentharness")
CONDITION_ORDERS = (
    ("A-baseline", "B-agentharness"),
    ("B-agentharness", "A-baseline"),
    ("A-baseline", "B-agentharness"),
    ("B-agentharness", "A-baseline"),
)
class V3Error(RuntimeError):
    exit_code = UNEXPECTED


class IntegrityFailure(V3Error):
    exit_code = STOP_INTEGRITY


class InvocationFailure(V3Error):
    exit_code = STOP_INVOCATION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def contains_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith(PLACEHOLDER)
    if isinstance(value, Mapping):
        return any(contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_placeholder(item) for item in value)
    return False


def _runtime_condition(value: object) -> str:
    return str(value)


def validate_manifest_shape(manifest: Mapping[str, object]) -> None:
    if manifest.get("schema_version") != 3 or manifest.get("pilot_id") != PILOT_ID:
        raise IntegrityFailure("v3 manifest identity mismatch")
    if manifest.get("execution_mode") not in {"real", "qualification"}:
        raise IntegrityFailure("v3 execution mode invalid")
    manifest_tasks = manifest.get("tasks")
    if not isinstance(manifest_tasks, list) or tuple(manifest_tasks) != TASKS:
        raise IntegrityFailure("v3 task roster mismatch")
    manifest_conditions = manifest.get("conditions")
    if not isinstance(manifest_conditions, list):
        raise IntegrityFailure("v3 conditions invalid")
    raw_conditions = tuple(_runtime_condition(item) for item in manifest_conditions)
    if raw_conditions != CONDITIONS:
        raise IntegrityFailure("v3 conditions mismatch")
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != 4:
        raise IntegrityFailure("v3 block roster mismatch")
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            raise IntegrityFailure("v3 block invalid")
        raw_order = block.get("condition_order")
        if not isinstance(raw_order, list):
            raise IntegrityFailure("v3 block condition order invalid")
        order = tuple(_runtime_condition(item) for item in raw_order)
        if (
            block.get("block_id") != f"v3-{index + 1:03d}"
            or block.get("task_id") != TASKS[index]
            or order != CONDITION_ORDERS[index]
        ):
            raise IntegrityFailure("v3 AB/BA order or block identity mismatch")
    if (
        manifest.get("expected_initial_provider_calls") != 0
        or manifest.get("expected_repair_provider_calls") != 8
    ):
        raise IntegrityFailure("v3 invocation budget mismatch")


def freeze_manifest(template_path: Path, output_path: Path, *, execution_mode: str = "real") -> dict[str, str]:
    if template_path.resolve() != TEMPLATE_PATH.resolve():
        raise IntegrityFailure("normative V3 template required")
    if output_path.resolve().is_relative_to(REPO_ROOT.resolve()) or output_path.exists():
        raise IntegrityFailure("frozen preregistration must be new and external")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise IntegrityFailure("repository must be clean before freeze")
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    if execution_mode not in {"real", "qualification"}:
        raise IntegrityFailure("freeze execution mode invalid")
    manifest["execution_mode"] = execution_mode
    manifest["preregistration_status"] = "frozen"
    manifest["frozen_at"] = utc_now()
    manifest["repository_commit"] = git("rev-parse", "HEAD")
    frozen = manifest.get("frozen_file_sha256")
    if not isinstance(frozen, dict):
        raise IntegrityFailure("frozen file map missing")
    for relative in frozen:
        path = REPO_ROOT / relative
        if not path.is_file():
            raise IntegrityFailure(f"frozen file missing:{relative}")
        frozen[relative] = sha256_file(path)
    command = Path(str(manifest["hermes_command"]))
    if not command.is_file() or not os.access(command, os.X_OK):
        raise IntegrityFailure("pinned Hermes wrapper unavailable")
    manifest["hermes_command_sha256"] = sha256_file(command)
    manifest.pop("manifest_payload_sha256", None)
    manifest["manifest_payload_sha256"] = canonical_hash(manifest)
    if contains_placeholder(manifest):
        raise IntegrityFailure("freeze left placeholders")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(output_path.resolve()), "sha256": sha256_file(output_path)}


def preflight(manifest_path: Path, run_root: Path, *, synthetic: bool = False) -> dict[str, object]:
    if manifest_path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("external frozen preregistration required")
    if run_root.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("run root must be external")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    expected_mode = "qualification" if synthetic else "real"
    if manifest.get("execution_mode") != expected_mode:
        raise IntegrityFailure(f"execution mode mismatch: expected {expected_mode}")
    if manifest.get("preregistration_status") != "frozen" or contains_placeholder(manifest):
        raise IntegrityFailure("preregistration not frozen")
    payload = dict(manifest)
    expected = payload.pop("manifest_payload_sha256", None)
    if canonical_hash(payload) != expected:
        raise IntegrityFailure("manifest payload hash mismatch")
    if manifest.get("repository_commit") != git("rev-parse", "HEAD"):
        raise IntegrityFailure("repository commit mismatch")
    frozen = manifest.get("frozen_file_sha256")
    if not isinstance(frozen, Mapping):
        raise IntegrityFailure("frozen file map invalid")
    for relative, digest in frozen.items():
        path = REPO_ROOT / str(relative)
        if not path.is_file() or sha256_file(path) != digest:
            raise IntegrityFailure(f"frozen file mismatch:{relative}")
    if not synthetic:
        if git("status", "--porcelain", "--untracked-files=all"):
            raise IntegrityFailure("repository must be clean")
        command = Path(str(manifest["hermes_command"]))
        if (
            not command.is_file()
            or not os.access(command, os.X_OK)
            or sha256_file(command) != manifest["hermes_command_sha256"]
        ):
            raise IntegrityFailure("pinned Hermes wrapper binding mismatch")
        if os.environ.get("HERMES_HOME") != manifest["hermes_home"]:
            raise IntegrityFailure("HERMES_HOME mismatch")
        if AGENT_INVOCATION_TIMEOUT_SECONDS != int(manifest["invocation_timeout_seconds"]):
            raise IntegrityFailure("effective agent timeout differs from preregistration")
    return {
        "manifest_file_sha256": sha256_file(manifest_path),
        "repository_commit": manifest["repository_commit"],
        "execution_mode": manifest["execution_mode"],
    }


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IntegrityFailure("V3 runner already active") from exc
        yield


class RepairInvoker(Protocol):
    def run_cloned_repair(
        self, manifest: dict[str, object], outputs_dir: Path, workspace: Path
    ) -> AgentInvocationResult: ...


class _SyntheticResult:
    def __init__(self, *, attempts: list[dict[str, object]], treatment_delivery: dict[str, object]) -> None:
        self.attempts = attempts
        self.treatment_delivery = treatment_delivery

    def to_dict(self) -> list[dict[str, object]]:
        return self.attempts


class SyntheticRepairInvoker:
    """No-provider mock with the same run_cloned_repair interface as V2."""

    def run_cloned_repair(
        self, manifest: dict[str, object], outputs_dir: Path, workspace: Path
    ) -> _SyntheticResult:
        outputs_dir.mkdir(parents=True, exist_ok=False)
        condition, task_id = str(manifest["condition"]), str(manifest["task_id"])
        changed: list[str] = []
        if condition == "B-agentharness":
            with tempfile.TemporaryDirectory(prefix="v3-synthetic-clean-") as temporary:
                clean = Path(temporary) / "workspace"
                materialize_clean_reference(
                    task_id=task_id, references_root=REFERENCES_ROOT, destination=clean
                )
                before = {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in workspace.rglob("*")
                    if path.is_file()
                }
                shutil.rmtree(workspace)
                shutil.copytree(clean, workspace)
                after = {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in workspace.rglob("*")
                    if path.is_file()
                }
                changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        finding_id = OPAQUE_FINDING_IDS[task_id]
        findings = [] if condition == "A-baseline" else [{
            "finding_id": finding_id,
            "source": "agentharness",
            "disposition": "applied" if changed else "rejected",
            "reason": "Synthetic mock decision.",
            "changed_files": changed,
        }]
        response = {
            "schema_version": 1,
            "decision": "applied" if changed else "no_change",
            "summary": "Synthetic bounded repair completed.",
            "findings": findings,
        }
        atomic_write(outputs_dir / "repair-response.json", response)
        feedback = condition == "B-agentharness"
        return _SyntheticResult(
            attempts=[{"attempt_name": "attempt-2-repair", "exit_code": 0}],
            treatment_delivery={
                "repair_invocation_succeeded": True,
                "treatment_prompt_immutable": True,
                "feedback_delivered": feedback,
                "feedback_immutable": True if feedback else None,
                "feedback_items_accounted": True,
                "repair_response_valid": True,
                "feedback_claim_ids": [finding_id] if feedback else [],
            },
        )


QuotaGate = Callable[[str], None]


def real_quota_gate(phase: str) -> None:
    try:
        from agent.account_usage import fetch_account_usage

        usage = fetch_account_usage("openai-codex")
    except Exception as exc:
        raise InvocationFailure(f"quota telemetry unavailable:{type(exc).__name__}") from exc
    windows = list(getattr(usage, "windows", []) or []) if getattr(usage, "available", False) else []
    if len(windows) != 1 or windows[0].used_percent is None or float(windows[0].used_percent) >= 80.0:
        raise InvocationFailure(f"quota gate closed:{phase}")


def synthetic_quota_gate(_phase: str) -> None:
    return None


def cleanup_cell_sandbox(workspace: Path, command: str) -> None:
    completed = subprocess.run(
        [command, "--sandbox-cleanup"], cwd=workspace, capture_output=True, text=True,
        check=False, timeout=120,
    )
    if completed.returncode != 0:
        raise IntegrityFailure(f"sandbox cleanup failed:{workspace.parent.name}:{completed.returncode}")


def _invocation_accounting(result: object, *, condition: str, task_id: str) -> dict[str, bool]:
    attempts = getattr(result, "attempts", None)
    delivery = getattr(result, "treatment_delivery", None)
    if not isinstance(attempts, list) or len(attempts) != 1 or not isinstance(delivery, Mapping):
        raise InvocationFailure("repair invocation result contract invalid")
    common_ok = (
        delivery.get("repair_invocation_succeeded") is True
        and delivery.get("treatment_prompt_immutable") is True
        and delivery.get("repair_response_valid") is True
        and delivery.get("feedback_items_accounted") is True
    )
    if not common_ok:
        raise InvocationFailure("repair treatment delivery invalid")
    if condition == "B-agentharness":
        claims = delivery.get("feedback_claim_ids")
        feedback_ok = (
            delivery.get("feedback_delivered") is True
            and delivery.get("feedback_immutable") is True
            and claims == [OPAQUE_FINDING_IDS[task_id]]
        )
        if not feedback_ok:
            raise InvocationFailure("B feedback delivery/accounting invalid")
    return {
        "invocation_valid": True,
        "feedback_delivered": condition == "B-agentharness",
        "feedback_immutable": True,
        "feedback_accounted": True,
    }


def _validate_provider_markers(run_root: Path, *, require_success: bool) -> None:
    initial = list(run_root.rglob("provider-invocation.initial.started.json"))
    started = sorted(run_root.rglob("provider-invocation.repair.started.json"))
    completed = sorted(run_root.rglob("provider-invocation.repair.completed.json"))
    if initial or len(started) != 8 or len(completed) != 8:
        raise IntegrityFailure("provider invocation marker roster/count mismatch")
    observed: set[tuple[str, str]] = set()
    completion_ids: set[str] = set()
    for path in started:
        marker = json.loads(path.read_text(encoding="utf-8"))
        key = (str(marker.get("task_id")), str(marker.get("condition")))
        if (
            marker.get("phase") != "repair"
            or marker.get("initial_provider_call") is not False
            or key in observed
            or key not in {(task, condition) for task in TASKS for condition in CONDITIONS}
        ):
            raise IntegrityFailure("repair start marker invalid or duplicate")
        observed.add(key)
        completion_path = path.with_name("provider-invocation.repair.completed.json")
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        if completion.get("invocation_id") != marker.get("invocation_id"):
            raise IntegrityFailure("repair completion marker binding mismatch")
        invocation_id = str(completion.get("invocation_id"))
        if invocation_id in completion_ids or (require_success and completion.get("status") != "succeeded"):
            raise IntegrityFailure("repair completion marker invalid")
        completion_ids.add(invocation_id)


class V3Pilot:
    def __init__(
        self,
        manifest_path: Path,
        run_root: Path,
        *,
        invoker: RepairInvoker,
        quota_gate: QuotaGate,
        synthetic: bool = False,
    ) -> None:
        self.manifest_path, self.run_root = manifest_path.resolve(), run_root.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.invoker, self.quota_gate, self.synthetic = invoker, quota_gate, synthetic
        self.state_path = self.run_root / "campaign-state.private.json"
        self.audit_path = self.run_root / "collection-audit.final.json"

    def _markers(self) -> list[dict[str, object]]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.run_root.rglob("provider-invocation.repair.started.json"))
        ]

    def _reconcile(self) -> None:
        if not self.state_path.is_file():
            return
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("status") == "collection_complete" and self.audit_path.is_file():
            raise IntegrityFailure("collection already complete; use --finalize")
        if self._markers():
            raise IntegrityFailure("run root non-resumable after exactly-once repair marker")
        raise IntegrityFailure("incomplete V3 run root cannot be resumed")

    def _real_invoker(self) -> HermesCliInvoker:
        return HermesCliInvoker(
            hermes_command=str(self.manifest["hermes_command"]),
            toolsets=str(self.manifest["toolsets"]),
            max_retries=1,
            provider=str(self.manifest["provider"]),
            model=str(self.manifest["model"]),
            max_turns=int(self.manifest["max_turns"]),
            sandbox_cleanup_arg="--sandbox-cleanup",
        )

    def run(self) -> dict[str, object]:
        binding = preflight(self.manifest_path, self.run_root, synthetic=self.synthetic)
        with exclusive_lock(self.run_root / "pilot.lock"):
            self._reconcile()
            self.run_root.mkdir(parents=True, exist_ok=True)
            os.chmod(self.run_root, 0o700)
            atomic_write(
                self.run_root / "preregistration.frozen.json",
                json.loads(self.manifest_path.read_text(encoding="utf-8")),
            )
            state: dict[str, object] = {
                "schema_version": 3,
                "status": "collecting",
                "provider_initial_calls": 0,
                "repair_calls_started": 0,
                "repair_calls_completed": 0,
                **binding,
            }
            atomic_write(self.state_path, state)
            block_hashes: dict[str, str] = {}
            for block in self.manifest["blocks"]:
                task_id, block_id = str(block["task_id"]), str(block["block_id"])
                block_dir = self.run_root / "private-blocks" / block_id
                seed = block_dir / "controlled-start.private"
                materialization = materialize_controlled_start(
                    task_id=task_id, references_root=REFERENCES_ROOT, destination=seed
                )
                origin = {
                    "schema_version": 3,
                    "task_id": task_id,
                    "solution_hash": compute_solution_hash(seed),
                    "tree_fingerprint": tree_fingerprint(seed),
                    "provider_initial_call": False,
                }
                atomic_write(block_dir / "initial-origin.json", origin)
                origin_ref = {
                    "path": str(block_dir / "initial-origin.json"),
                    "sha256": sha256_file(block_dir / "initial-origin.json"),
                    "solution_hash": origin["solution_hash"],
                    "tree_fingerprint": origin["tree_fingerprint"],
                }
                workspaces = {
                    "A-baseline": block_dir / "cell-A" / "workspace",
                    "B-agentharness": block_dir / "cell-B" / "workspace",
                }
                clone_fingerprint = clone_pair(seed, workspaces["A-baseline"], workspaces["B-agentharness"])

                # The review evaluator's only durable/agent-visible output is in B.
                feedback = evaluate_review(seed, task_id)
                validate_opaque_feedback(feedback, task_id=task_id)
                b_feedback = block_dir / "cell-B" / "inputs" / "review-feedback.json"
                atomic_write(b_feedback, feedback)
                b_feedback_hash = sha256_file(b_feedback)

                rows: dict[str, dict[str, object]] = {}
                for raw_condition in block["condition_order"]:
                    condition = _runtime_condition(raw_condition)
                    label = "A" if condition == "A-baseline" else "B"
                    cell_dir = block_dir / f"cell-{label}"
                    inputs = cell_dir / "inputs"
                    inputs.mkdir(parents=True, exist_ok=True)
                    spec_path = inputs / "SPEC.md"
                    claims_path = inputs / "CLAIMS_CONTRACT.template.json"
                    shutil.copy2(REPO_ROOT / "benchmarks" / task_id / "SPEC.md", spec_path)
                    shutil.copy2(
                        REPO_ROOT / "benchmarks" / task_id / "CLAIMS_CONTRACT.template.json",
                        claims_path,
                    )
                    manifest = build_cell_manifest(
                        task_id=task_id,
                        condition=condition,
                        replicate_id="v3-r1",
                        cell_dir=cell_dir,
                    )
                    manifest.update({
                        "run_id": f"{PILOT_ID}_{block_id}_{label.lower()}",
                        "diagnostic_stage": PILOT_ID,
                        "spec_path": str(spec_path),
                        "claims_template_path": str(claims_path),
                        "initial_origin": origin_ref,
                    })
                    if condition == "B-agentharness":
                        manifest["review_feedback_path"] = str(b_feedback)
                    elif "review_feedback_path" in manifest:
                        raise IntegrityFailure("A manifest received review feedback")
                    atomic_write(cell_dir / "cell_manifest.json", manifest)
                    if tree_fingerprint(workspaces[condition]) != clone_fingerprint:
                        raise IntegrityFailure("cloned start changed before invocation")
                    if not self.synthetic:
                        cleanup_cell_sandbox(workspaces[condition], str(self.manifest["hermes_command"]))
                    self.quota_gate(f"repair:{block_id}:{condition}")
                    invocation_id = f"{block_id}:{condition}:repair-1"
                    started = cell_dir / "provider-invocation.repair.started.json"
                    completed = cell_dir / "provider-invocation.repair.completed.json"
                    atomic_write(started, {
                        "schema_version": 3,
                        "phase": "repair",
                        "invocation_id": invocation_id,
                        "task_id": task_id,
                        "condition": condition,
                        "initial_provider_call": False,
                        "started_at": utc_now(),
                    })
                    state["repair_calls_started"] = int(state["repair_calls_started"]) + 1
                    atomic_write(self.state_path, state)
                    status, failure = "failed", None
                    try:
                        invocation = self.invoker.run_cloned_repair(
                            manifest, cell_dir / "outputs", workspaces[condition]
                        )
                        accounting = _invocation_accounting(
                            invocation, condition=condition, task_id=task_id
                        )
                        status = "succeeded"
                    except ClassifiedCellFailure as exc:
                        failure = f"{exc.execution_status}:{exc.classification_reason}"
                        raise InvocationFailure(f"repair invocation failed:{block_id}:{condition}:{failure}") from exc
                    except Exception as exc:
                        failure = f"{type(exc).__name__}:{exc}"
                        raise
                    finally:
                        atomic_write(completed, {
                            "schema_version": 3,
                            "phase": "repair",
                            "invocation_id": invocation_id,
                            "task_id": task_id,
                            "condition": condition,
                            "status": status,
                            "failure": failure,
                            "completed_at": utc_now(),
                        })
                        state["repair_calls_completed"] = int(state["repair_calls_completed"]) + 1
                        atomic_write(self.state_path, state)
                        if not self.synthetic:
                            cleanup_cell_sandbox(workspaces[condition], str(self.manifest["hermes_command"]))
                    if condition == "B-agentharness" and sha256_file(b_feedback) != b_feedback_hash:
                        raise IntegrityFailure("B review feedback changed")
                    rows[condition] = {"task_id": task_id, "condition": condition, **accounting}

                # Strict deferred boundary: heldout starts only after both completion markers.
                for condition in CONDITIONS:
                    heldout = evaluate_heldout(workspaces[condition], task_id)
                    rows[condition].update(heldout)
                    rows[condition]["heldout_valid"] = True
                commit_path = block_dir / "block-result.commit.json"
                atomic_write(commit_path, {
                    "schema_version": 3,
                    "block_id": block_id,
                    "task_id": task_id,
                    "initial_origin_sha256": origin_ref["sha256"],
                    "initial_solution_hash": origin["solution_hash"],
                    "controlled_start": materialization,
                    "clone_fingerprint": clone_fingerprint,
                    "cells": [rows[condition] for condition in CONDITIONS],
                })
                block_hashes[block_id] = sha256_file(commit_path)

            _validate_provider_markers(self.run_root, require_success=True)
            if int(state["repair_calls_started"]) != 8 or int(state["repair_calls_completed"]) != 8:
                raise IntegrityFailure("repair accounting totals invalid")
            marker_hashes = {
                path.relative_to(self.run_root).as_posix(): sha256_file(path)
                for path in sorted(self.run_root.rglob("provider-invocation.repair.*.json"))
            }
            if len(marker_hashes) != 16:
                raise IntegrityFailure("provider marker audit roster invalid")
            audit = {
                "schema_version": 3,
                "pilot_id": PILOT_ID,
                "collection_complete": True,
                "analysis_authorized": self.manifest.get("execution_mode") == "real" and not self.synthetic,
                "execution_mode": self.manifest.get("execution_mode"),
                "provider_initial_calls": 0,
                "repair_calls_started": 8,
                "repair_calls_completed": 8,
                "manifest_file_sha256": binding["manifest_file_sha256"],
                "repository_commit": binding["repository_commit"],
                "block_commit_sha256": block_hashes,
                "provider_marker_sha256": marker_hashes,
                "completed_at": utc_now(),
            }
            atomic_write(self.audit_path, audit)
            state.update({"status": "collection_complete", "collection_completed_at": utc_now()})
            atomic_write(self.state_path, state)
            return {"status": "collection_complete", "completed_blocks": 4, "completed_cells": 8}


def _validate_block_commit(commit: Mapping[str, object], *, block_id: str, task_id: str) -> list[dict[str, object]]:
    if commit.get("schema_version") != 3 or commit.get("block_id") != block_id or commit.get("task_id") != task_id:
        raise IntegrityFailure(f"block commit identity mismatch:{block_id}")
    if not isinstance(commit.get("initial_solution_hash"), str) or not isinstance(commit.get("clone_fingerprint"), str):
        raise IntegrityFailure(f"block origin binding missing:{block_id}")
    cells = commit.get("cells")
    if not isinstance(cells, list) or len(cells) != 2 or any(not isinstance(cell, Mapping) for cell in cells):
        raise IntegrityFailure(f"block cell roster invalid:{block_id}")
    rows = [dict(cell) for cell in cells]
    if {row.get("condition") for row in rows} != set(CONDITIONS):
        raise IntegrityFailure(f"block condition pairing invalid:{block_id}")
    return rows


def finalize(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    """Provider-free finalization over audit-bound block commits only."""
    manifest_path, run_root = manifest_path.resolve(), run_root.resolve()
    if manifest_path.is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("finalizer requires external frozen preregistration")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    if manifest.get("execution_mode") != "real":
        raise IntegrityFailure("production finalizer rejects qualification artifacts")
    payload = dict(manifest)
    expected_payload_hash = payload.pop("manifest_payload_sha256", None)
    if manifest.get("preregistration_status") != "frozen" or contains_placeholder(manifest) or canonical_hash(payload) != expected_payload_hash:
        raise IntegrityFailure("finalizer manifest invalid")
    if manifest.get("repository_commit") != git("rev-parse", "HEAD"):
        raise IntegrityFailure("finalizer repository commit mismatch")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise IntegrityFailure("finalizer requires clean frozen repository")
    frozen_files = manifest.get("frozen_file_sha256")
    if not isinstance(frozen_files, Mapping):
        raise IntegrityFailure("finalizer frozen file map invalid")
    for relative, digest in frozen_files.items():
        path = REPO_ROOT / str(relative)
        if not path.is_file() or sha256_file(path) != digest:
            raise IntegrityFailure(f"finalizer frozen file mismatch:{relative}")
    frozen_copy = run_root / "preregistration.frozen.json"
    state_path = run_root / "campaign-state.private.json"
    audit_path = run_root / "collection-audit.final.json"
    if not frozen_copy.is_file() or sha256_file(frozen_copy) != sha256_file(manifest_path):
        raise IntegrityFailure("finalizer preregistration binding mismatch")
    if not state_path.is_file() or not audit_path.is_file():
        raise IntegrityFailure("green collection audit required")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(manifest_path)
    if (
        state.get("status") != "collection_complete"
        or audit.get("collection_complete") is not True
        or audit.get("analysis_authorized") is not True
        or state.get("execution_mode") != "real"
        or audit.get("execution_mode") != "real"
        or audit.get("provider_initial_calls") != 0
        or audit.get("repair_calls_started") != 8
        or audit.get("repair_calls_completed") != 8
        or state.get("manifest_file_sha256") != manifest_hash
        or audit.get("manifest_file_sha256") != manifest_hash
        or state.get("repository_commit") != manifest.get("repository_commit")
        or audit.get("repository_commit") != manifest.get("repository_commit")
    ):
        raise IntegrityFailure("collection audit is not green or not bound")
    _validate_provider_markers(run_root, require_success=True)
    expected_marker_hashes = audit.get("provider_marker_sha256")
    observed_marker_paths = sorted(run_root.rglob("provider-invocation.repair.*.json"))
    if (
        not isinstance(expected_marker_hashes, Mapping)
        or len(expected_marker_hashes) != 16
        or {
            path.relative_to(run_root).as_posix(): sha256_file(path)
            for path in observed_marker_paths
        }
        != expected_marker_hashes
    ):
        raise IntegrityFailure("provider marker audit binding mismatch")
    expected_hashes = audit.get("block_commit_sha256")
    expected_blocks = {f"v3-{index:03d}" for index in range(1, 5)}
    if not isinstance(expected_hashes, Mapping) or set(expected_hashes) != expected_blocks:
        raise IntegrityFailure("collection audit block roster mismatch")
    task_by_block = {str(block["block_id"]): str(block["task_id"]) for block in manifest["blocks"]}
    rows: list[dict[str, object]] = []
    for block_id in sorted(expected_blocks):
        commit_path = run_root / "private-blocks" / block_id / "block-result.commit.json"
        if not commit_path.is_file() or sha256_file(commit_path) != expected_hashes[block_id]:
            raise IntegrityFailure(f"block commit audit mismatch:{block_id}")
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        rows.extend(_validate_block_commit(commit, block_id=block_id, task_id=task_by_block[block_id]))
    result = finalize_results(rows)
    if result.get("verdict") == "INVALID":
        raise IntegrityFailure(str(result.get("reason")))
    result["collection_audit_sha256"] = sha256_file(audit_path)
    result_path = run_root / "MECHANISM_FIRST_V3_RESULT.json"
    if result_path.exists() or result_path.is_symlink():
        raise IntegrityFailure("result artifact already exists")
    descriptor = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mechanism-first controlled-start V3")
    parser.add_argument("--manifest", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--freeze-output", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="no-provider qualification invoker")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.freeze_output:
            mode = "qualification" if args.synthetic else "real"
            print(json.dumps(freeze_manifest(args.manifest, args.freeze_output, execution_mode=mode), indent=2, sort_keys=True))
            return 0
        if args.run_root is None:
            raise IntegrityFailure("--run-root required")
        if args.finalize:
            print(json.dumps(finalize(manifest_path=args.manifest, run_root=args.run_root), indent=2, sort_keys=True))
            return 0
        if args.preflight:
            print(json.dumps(preflight(args.manifest, args.run_root, synthetic=args.synthetic), indent=2, sort_keys=True))
            return 0
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        invoker: RepairInvoker = SyntheticRepairInvoker() if args.synthetic else HermesCliInvoker(
            hermes_command=str(manifest["hermes_command"]),
            toolsets=str(manifest["toolsets"]),
            max_retries=1,
            provider=str(manifest["provider"]),
            model=str(manifest["model"]),
            max_turns=int(manifest["max_turns"]),
            sandbox_cleanup_arg="--sandbox-cleanup",
        )
        result = V3Pilot(
            args.manifest,
            args.run_root,
            invoker=invoker,
            quota_gate=synthetic_quota_gate if args.synthetic else real_quota_gate,
            synthetic=args.synthetic,
        ).run()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except V3Error as exc:
        print(json.dumps({"verdict": "INVALID", "reason": str(exc)}), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"verdict": "INVALID", "reason": f"unexpected:{type(exc).__name__}"}), file=sys.stderr)
        return UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
