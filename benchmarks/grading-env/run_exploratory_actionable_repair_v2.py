from __future__ import annotations

"""Freeze-first collector/finalizer for exploratory actionable-repair v2.

The checked-in preregistration intentionally contains freeze placeholders.
Collection therefore fails closed until a human freezes the exact commit and
hashes.  No provider is contacted by preflight or finalization.
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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = (REPO_ROOT / "src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentharness.benchmark_cells import (  # noqa: E402
    ClassifiedCellFailure,
    HermesCliInvoker,
    build_cell_manifest,
    compute_solution_hash,
    execute_cell,
)
from agentharness.benchmark_hidden_evaluators_batch1 import evaluate_batch1_task  # noqa: E402
from agentharness.efficacy_v2 import (  # noqa: E402
    SCHEMA_GATE_ID,
    TASKS,
    TASK_PARTITIONS,
    clone_tree_identical,
    filter_evaluation_report,
    funnel,
    review_feedback_from_report,
    score_heldout_report,
    tree_fingerprint,
    validate_suite_partition,
    verify_clone_pair,
)

PILOT_ID = "exploratory_actionable_repair_v2_cloned_start"
MANIFEST_NAME = "EXPLORATORY_ACTIONABLE_REPAIR_V2_CLONED_START_PREREG.json"
MANIFEST_PATH = REPO_ROOT / "benchmarks" / "grading-env" / MANIFEST_NAME
PLACEHOLDER_PREFIX = "FREEZE_REQUIRED:"
STOP_INTEGRITY = 30
STOP_CONCURRENT = 31
STOP_QUOTA = 10
STOP_PROVIDER = 13
STOP_TREATMENT = 14
STOP_INITIAL = 15
UNEXPECTED = 50


class PilotError(RuntimeError):
    exit_code = UNEXPECTED


class IntegrityFailure(PilotError):
    exit_code = STOP_INTEGRITY


class ConcurrentRunner(PilotError):
    exit_code = STOP_CONCURRENT


class QuotaPause(PilotError):
    exit_code = STOP_QUOTA


class ProviderUnavailable(PilotError):
    exit_code = STOP_PROVIDER


class TreatmentNotDelivered(PilotError):
    exit_code = STOP_TREATMENT


class InitialGenerationInvalid(PilotError):
    exit_code = STOP_INITIAL


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_write(path: Path, value: object, *, private: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if private:
        os.chmod(path, 0o600)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConcurrentRunner("v2 collector lock already held") from exc
        yield


def structural_message(**fields: object) -> None:
    allowed = {"status", "completed_blocks", "total_blocks", "completed_cells", "total_cells", "resume_count", "invalidity", "exit_code"}
    if not set(fields).issubset(allowed):
        raise ValueError("collection progress may contain structural fields only")
    print(json.dumps(fields, sort_keys=True), flush=True)


def _contains_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith(PLACEHOLDER_PREFIX)
    if isinstance(value, Mapping):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def validate_manifest_shape(manifest: Mapping[str, object]) -> None:
    if manifest.get("pilot_id") != PILOT_ID or manifest.get("study_class") != "exploratory" or manifest.get("confirmatory") is not False:
        raise IntegrityFailure("pilot identity/classification mismatch")
    if tuple(manifest.get("tasks", [])) != TASKS:
        raise IntegrityFailure("Batch1 roster/order mismatch")
    if manifest.get("partitions") != {task: {key: list(value) for key, value in parts.items()} for task, parts in TASK_PARTITIONS.items()}:
        raise IntegrityFailure("review/heldout partitions mismatch")
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != 4 or manifest.get("expected_initial_generations") != 4 or manifest.get("expected_repair_cells") != 8:
        raise IntegrityFailure("v2 requires four initials and eight repair cells")
    starts: list[str] = []
    for index, block in enumerate(blocks, 1):
        if not isinstance(block, Mapping) or block.get("block_id") != f"p{index:03d}":
            raise IntegrityFailure("block identity/order mismatch")
        if block.get("task_id") != TASKS[index - 1]:
            raise IntegrityFailure("block task roster/order mismatch")
        order = block.get("condition_order")
        if not isinstance(order, list) or sorted(order) != ["A-baseline", "B-agentharness"]:
            raise IntegrityFailure("block condition pair mismatch")
        starts.append(str(order[0]))
    if starts != ["A-baseline", "B-agentharness", "A-baseline", "B-agentharness"]:
        raise IntegrityFailure("AB/BA counterbalance mismatch")


def require_sandbox_image(manifest: Mapping[str, object], command: Path) -> None:
    expected = str(manifest.get("sandbox_image_id") or "")
    if not expected.startswith("sha256:"):
        raise IntegrityFailure("sandbox image digest missing")
    inspected = subprocess.run(
        ["docker", "image", "inspect", expected, "--format", "{{.Id}}"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if inspected.returncode != 0 or inspected.stdout.strip() != expected:
        raise IntegrityFailure("pinned sandbox image unavailable or mismatched")
    if expected not in command.read_text(encoding="utf-8"):
        raise IntegrityFailure("sandbox wrapper/image binding mismatch")


def freeze_manifest(*, template_path: Path, output_path: Path) -> dict[str, object]:
    """Materialize an immutable external preregistration bound to clean HEAD."""
    if template_path.resolve() != MANIFEST_PATH.resolve():
        raise IntegrityFailure("normative dated v2 template required")
    if output_path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("frozen preregistration must be outside repository")
    if output_path.exists():
        raise IntegrityFailure("refusing to overwrite frozen preregistration")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise IntegrityFailure("repository must be clean before freeze")
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    manifest["preregistration_status"] = "frozen"
    manifest["frozen_at"] = utc_now()
    manifest["repository_commit"] = git("rev-parse", "HEAD")
    command = Path(str(manifest["hermes_command"]))
    if not command.is_file() or not os.access(command, os.X_OK):
        raise IntegrityFailure("pinned Hermes command unavailable at freeze")
    require_sandbox_image(manifest, command)
    manifest["hermes_command_sha256"] = sha256_file(command)
    config = Path(str(manifest["hermes_config_path"]))
    if not config.is_file():
        raise IntegrityFailure("pinned Hermes config unavailable at freeze")
    manifest["hermes_config_sha256"] = sha256_file(config)
    frozen = manifest.get("frozen_file_sha256")
    if not isinstance(frozen, dict):
        raise IntegrityFailure("frozen file map missing")
    for relative in tuple(frozen):
        path = REPO_ROOT / str(relative)
        if not path.is_file():
            raise IntegrityFailure(f"frozen file missing:{relative}")
        frozen[relative] = sha256_file(path)
    manifest.pop("manifest_payload_sha256", None)
    payload = dict(manifest)
    manifest["manifest_payload_sha256"] = canonical_hash(payload)
    if _contains_placeholder(manifest):
        raise IntegrityFailure("freeze left unresolved placeholders")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return {
        "path": str(output_path.resolve()),
        "sha256": sha256_file(output_path),
        "repository_commit": manifest["repository_commit"],
    }


def preflight(manifest_path: Path, run_root: Path) -> dict[str, object]:
    """Complete every non-destructive freeze check before touching run_root."""
    if manifest_path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("collection requires an external frozen preregistration, not the tracked template")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    if manifest.get("preregistration_status") != "frozen":
        raise IntegrityFailure("preregistration status is not frozen")
    # Explicit placeholders are normative until freeze.  Reject them rather
    # than silently deriving or inventing values at collection time.
    if _contains_placeholder(manifest):
        raise IntegrityFailure("preregistration is not frozen: replace every FREEZE_REQUIRED placeholder and recompute bindings")
    if Path(run_root).resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("run root must be outside repository")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise IntegrityFailure("repository must be clean")
    head = git("rev-parse", "HEAD")
    if head != manifest.get("repository_commit"):
        raise IntegrityFailure("repository commit freeze mismatch")
    payload = dict(manifest)
    expected_payload_hash = payload.pop("manifest_payload_sha256", None)
    if canonical_hash(payload) != expected_payload_hash:
        raise IntegrityFailure("manifest payload hash mismatch")
    frozen = manifest.get("frozen_file_sha256")
    if not isinstance(frozen, Mapping):
        raise IntegrityFailure("frozen file map missing")
    for relative, expected in frozen.items():
        path = REPO_ROOT / str(relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise IntegrityFailure(f"frozen file mismatch:{relative}")
    for task in TASKS:
        suite_path = REPO_ROOT / "benchmarks" / task / "HELDOUT_EVALUATION_SUITE.template.json"
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        validate_suite_partition(task, suite)
    command = Path(str(manifest["hermes_command"]))
    if not command.is_file() or not os.access(command, os.X_OK) or sha256_file(command) != manifest["hermes_command_sha256"]:
        raise IntegrityFailure("pinned Hermes command mismatch")
    require_sandbox_image(manifest, command)
    config = Path(str(manifest["hermes_config_path"]))
    if not config.is_file() or sha256_file(config) != manifest["hermes_config_sha256"]:
        raise IntegrityFailure("pinned Hermes config mismatch")
    if os.environ.get("HERMES_HOME") != manifest["hermes_home"]:
        raise IntegrityFailure("HERMES_HOME mismatch")
    return {"repository_commit": head, "manifest_file_sha256": sha256_file(manifest_path), "manifest_payload_sha256": expected_payload_hash}


def review_evaluation_on_temporary_clone(workspace: Path, task_id: str) -> dict[str, object]:
    """Evaluate on an ephemeral clone and return only failed review findings.

    The hidden evaluator may internally execute all checks, but the clone and
    raw result are destroyed before return.  Neither heldout IDs nor heldout
    outcomes cross this function's boundary.
    """
    with tempfile.TemporaryDirectory(prefix="agentharness-v2-review-") as temporary:
        clone = Path(temporary) / "workspace"
        clone_tree_identical(workspace, clone)
        result = evaluate_batch1_task(clone, task_id)
        raw_rows = [item.to_dict() for item in result.observations]
        raw_rows.append({"id": SCHEMA_GATE_ID, "status": "pass", "detail": "result envelope produced"})
        return review_feedback_from_report({"observations": raw_rows}, task_id=task_id)


class _RepairOnlyInvoker:
    def __init__(self, inner: HermesCliInvoker) -> None:
        self.inner = inner

    def run_cell(self, manifest: dict[str, object], outputs_dir: Path, workspace: Path):
        return self.inner.run_cloned_repair(manifest, outputs_dir, workspace)


def _quota_gate(manifest: Mapping[str, object], run_root: Path, phase: str) -> None:
    try:
        from agent.account_usage import fetch_account_usage
        usage = fetch_account_usage(str(manifest["provider"]))
    except Exception as exc:
        raise QuotaPause(f"quota telemetry unavailable:{type(exc).__name__}") from exc
    windows = list(getattr(usage, "windows", []) or []) if getattr(usage, "available", False) else []
    if len(windows) != 1:
        raise QuotaPause("one authoritative quota window required")
    used = float(windows[0].used_percent)
    with (run_root / "quota.private.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"phase": phase, "used_percent": used, "at": utc_now()}, sort_keys=True) + "\n")
    if used >= float(manifest["quota_policy"]["single_window_pause_percent"]):  # type: ignore[index]
        raise QuotaPause("quota reserve reached")


class ExploratoryClonedStartPilot:
    def __init__(self, manifest_path: Path, run_root: Path) -> None:
        self.manifest_path = manifest_path.resolve()
        self.run_root = run_root.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.state_path = self.run_root / "campaign-state.private.json"
        self.progress_path = self.run_root / "progress.structural.private.json"
        self.audit_path = self.run_root / "collection-audit.final.json"

    def _save(self, state: dict[str, object]) -> None:
        state["updated_at"] = utc_now()
        atomic_write(self.state_path, state)

    def _load(self, binding: Mapping[str, object]) -> dict[str, object]:
        self.run_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.run_root, 0o700)
        frozen_copy = self.run_root / "preregistration.frozen.json"
        if frozen_copy.is_file():
            if sha256_file(frozen_copy) != binding["manifest_file_sha256"]:
                raise IntegrityFailure("frozen preregistration copy mismatch")
        else:
            descriptor = os.open(frozen_copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(self.manifest_path.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        if not self.state_path.is_file():
            state = {"schema_version": 2, "pilot_id": PILOT_ID, "status": "ready", "resume_count": 0, "current_block": None, **binding}
            self._save(state)
            return state
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for key, value in binding.items():
            if state.get(key) != value:
                raise IntegrityFailure(f"resume binding mismatch:{key}")
        state["resume_count"] = int(state.get("resume_count", 0)) + 1
        self._save(state)
        return state

    def _block_dir(self, block_id: str) -> Path:
        return self.run_root / "private-blocks" / block_id

    def _reconcile(self, state: dict[str, object]) -> None:
        current = state.get("current_block")
        if not isinstance(current, Mapping):
            return
        block_id = str(current["block_id"])
        source = self._block_dir(block_id)
        if source.exists() and not (source / "block-result.commit.json").is_file():
            provider_markers = list(source.rglob("provider-invocation.*.started.json"))
            if provider_markers:
                raise IntegrityFailure(
                    f"incomplete block has provider invocation marker; run root is non-resumable:{block_id}"
                )
            destination = self.run_root / "quarantine" / f"{block_id}-resume-{state['resume_count']}"
            if destination.exists():
                raise IntegrityFailure("quarantine collision")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, destination)
        state["current_block"] = None
        state["status"] = "ready"
        self._save(state)

    def _invoker(self) -> HermesCliInvoker:
        return HermesCliInvoker(
            hermes_command=str(self.manifest["hermes_command"]), toolsets=str(self.manifest["toolsets"]),
            max_retries=int(self.manifest["invocation_max_retries"]), provider=str(self.manifest["provider"]),
            model=str(self.manifest["model"]), max_turns=int(self.manifest["max_turns"]),
            sandbox_cleanup_arg="--sandbox-cleanup",
        )

    def _cleanup_stale_sandboxes(self) -> None:
        command = str(self.manifest["hermes_command"])
        for block in self.manifest["blocks"]:
            block_dir = self._block_dir(str(block["block_id"]))
            workspaces = (
                block_dir / "initial-workspace",
                block_dir / "cell-A" / "workspace",
                block_dir / "cell-B" / "workspace",
            )
            for workspace in workspaces:
                if not workspace.is_dir():
                    continue
                completed = subprocess.run(
                    [command, "--sandbox-cleanup"],
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if completed.returncode != 0:
                    raise IntegrityFailure(
                        f"stale sandbox cleanup failed:{workspace}:{completed.stderr.strip()}"
                    )

    def _collect_block(self, state: dict[str, object], block: Mapping[str, object]) -> None:
        block_id, task_id = str(block["block_id"]), str(block["task_id"])
        block_dir = self._block_dir(block_id)
        state["current_block"] = {"block_id": block_id, "task_id": task_id}
        state["status"] = "running"
        self._save(state)
        inputs = block_dir / "inputs"
        initial = block_dir / "initial-workspace"
        inputs.mkdir(parents=True)
        initial.mkdir()
        task_dir = REPO_ROOT / "benchmarks" / task_id
        shutil.copy2(task_dir / "SPEC.md", inputs / "SPEC.md")
        shutil.copy2(task_dir / "CLAIMS_CONTRACT.template.json", inputs / "CLAIMS_CONTRACT.template.json")
        initial_manifest: dict[str, object] = {
            "task_id": task_id, "spec_path": str(inputs / "SPEC.md"),
            "claims_template_path": str(inputs / "CLAIMS_CONTRACT.template.json"),
        }
        invoker = self._invoker()
        _quota_gate(self.manifest, self.run_root, f"initial:{block_id}")
        atomic_write(
            block_dir / "provider-invocation.initial.started.json",
            {"schema_version": 1, "phase": "initial", "block_id": block_id, "started_at": utc_now()},
        )
        try:
            initial_result = invoker.run_initial_generation(
                initial_manifest, block_dir / "initial-invocation", initial
            )
        except ClassifiedCellFailure as exc:
            reason = str(exc.classification_reason)
            if exc.execution_status == "provider_unavailable" or reason.startswith("provider_unavailable"):
                raise ProviderUnavailable(reason) from exc
            raise InitialGenerationInvalid(f"{exc.execution_status}:{reason}") from exc
        initial_hash = compute_solution_hash(initial)
        origin = {
            "schema_version": 2, "task_id": task_id, "path": str(block_dir / "initial-invocation"),
            "solution_hash": initial_hash, "tree_fingerprint": tree_fingerprint(initial),
            "attempts": initial_result.to_dict(),
        }
        atomic_write(block_dir / "initial-origin.json", origin)
        origin_ref = {
            "schema_version": 2,
            "path": str(block_dir / "initial-origin.json"),
            "sha256": sha256_file(block_dir / "initial-origin.json"),
            "solution_hash": initial_hash,
            "tree_fingerprint": origin["tree_fingerprint"],
        }
        clone_tree_identical(initial, block_dir / "cell-A" / "workspace")
        clone_tree_identical(initial, block_dir / "cell-B" / "workspace")
        for label in ("A", "B"):
            cell_inputs = block_dir / f"cell-{label}" / "inputs"
            cell_inputs.mkdir()
            shutil.copy2(inputs / "SPEC.md", cell_inputs / "SPEC.md")
            shutil.copy2(inputs / "CLAIMS_CONTRACT.template.json", cell_inputs / "CLAIMS_CONTRACT.template.json")
        clone_fingerprint = verify_clone_pair(initial, block_dir / "cell-A" / "workspace", block_dir / "cell-B" / "workspace")
        atomic_write(block_dir / "clone-identity.json", {"fingerprint": clone_fingerprint, "verified_before_condition_operations": True})

        # Review is a frozen property of the shared seed, evaluated once on a
        # disposable third clone before either condition-specific repair.
        feedback = review_evaluation_on_temporary_clone(initial, task_id)
        feedback_master_path = block_dir / "review-feedback-B.commit.json"
        atomic_write(feedback_master_path, feedback)
        feedback_path = block_dir / "cell-B" / "inputs" / "review-feedback.json"
        shutil.copy2(feedback_master_path, feedback_path)
        if sha256_file(feedback_path) != sha256_file(feedback_master_path):
            raise IntegrityFailure("condition-B feedback copy mismatch")
        feedback_items = feedback["feedback"]["items"]  # type: ignore[index]
        review_failed_ids = [str(item["claim_id"]) for item in feedback_items]

        rows: list[dict[str, object]] = []
        for condition in block["condition_order"]:  # type: ignore[index]
            condition = str(condition)
            label = "A" if condition == "A-baseline" else "B"
            cell_dir = block_dir / f"cell-{label}"
            if label == "B":
                cell_feedback_path: Path | None = feedback_path
            else:
                cell_feedback_path = None
            manifest = build_cell_manifest(task_id=task_id, condition=condition, replicate_id="v2-r1", cell_dir=cell_dir)
            manifest.update({
                "run_id": f"{PILOT_ID}_{block_id}_{label.lower()}", "diagnostic_stage": PILOT_ID,
                "initial_origin": origin_ref,
            })
            if cell_feedback_path is not None:
                manifest["review_feedback_path"] = str(cell_feedback_path)
            atomic_write(cell_dir / "cell_manifest.json", manifest)
            _quota_gate(self.manifest, self.run_root, f"repair:{block_id}:{label}")
            if tree_fingerprint(cell_dir / "workspace") != clone_fingerprint:
                raise IntegrityFailure(f"clone changed before condition operation:{block_id}:{label}")
            atomic_write(
                cell_dir / "provider-invocation.repair.started.json",
                {"schema_version": 1, "phase": "repair", "block_id": block_id, "condition": condition, "started_at": utc_now()},
            )
            result = execute_cell(cell_dir, _RepairOnlyInvoker(invoker))
            reason = str(result.get("benchmark_classification_reason") or "")
            if reason.startswith("provider_unavailable"):
                raise ProviderUnavailable(reason)
            if result.get("treatment_delivered") is not True:
                raise TreatmentNotDelivered(reason or "repair treatment not delivered")
            if result.get("heldout_endpoint_valid") is not True:
                raise IntegrityFailure(f"heldout endpoint invalid:{block_id}:{label}")
            if result.get("benchmark_execution_status") == "harness_invalid":
                raise IntegrityFailure(f"evaluation harness invalid:{block_id}:{label}:{reason}")
            # V2 endpoint is exactly three heldout checks; schema is a gate.
            report = json.loads((cell_dir / "outputs" / "evaluation-report.json").read_text(encoding="utf-8"))
            score = score_heldout_report(report, task_id=task_id)
            post_review = filter_evaluation_report(report, task_id=task_id, partition="review")
            post_status = {str(item["case_id"]): str(item["status"]) for item in post_review["results"]}  # type: ignore[index]
            resolved_ids = [case_id for case_id in review_failed_ids if post_status.get(case_id) == "passed"]
            result["score"] = score
            result["heldout_endpoint_denominator"] = 3
            result["initial_origin"] = str(block_dir / "initial-origin.json")
            result["initial_origin_sha256"] = origin_ref["sha256"]
            result["initial_solution_hash"] = initial_hash
            result["clone_pre_repair_fingerprint"] = clone_fingerprint
            result["repair_passes_used"] = 1
            result["review_opportunity_count"] = len(review_failed_ids)
            result["review_failed_ids_pre"] = review_failed_ids
            result["review_resolved_ids_post"] = resolved_ids
            result["review_resolution_count"] = len(resolved_ids)
            atomic_write(cell_dir / "cell-result.commit.json", result)
            rows.append(result)
        commit = {
            "schema_version": 2, "block_id": block_id, "task_id": task_id,
            "initial_origin_sha256": sha256_file(block_dir / "initial-origin.json"),
            "initial_solution_hash": initial_hash,
            "clone_fingerprint": clone_fingerprint, "cells": rows,
        }
        atomic_write(block_dir / "block-result.commit.json", commit)
        state["current_block"] = None
        self._save(state)

    def _commits(self) -> list[dict[str, object]]:
        commits: list[dict[str, object]] = []
        for block in self.manifest["blocks"]:
            path = self._block_dir(str(block["block_id"])) / "block-result.commit.json"
            if path.is_file():
                commits.append(json.loads(path.read_text(encoding="utf-8")))
        return commits

    def run(self) -> int:
        binding = preflight(self.manifest_path, self.run_root)
        with exclusive_lock(self.run_root / "pilot.lock"):
            state = self._load(binding)
            self._cleanup_stale_sandboxes()
            self._reconcile(state)
            for block in self.manifest["blocks"]:
                if not (self._block_dir(str(block["block_id"])) / "block-result.commit.json").is_file():
                    self._collect_block(state, block)
                complete = len(self._commits())
                progress = {"schema_version": 2, "completed_blocks": complete, "total_blocks": 4, "completed_cells": complete * 2, "total_cells": 8}
                atomic_write(self.progress_path, progress)
                structural_message(status="collecting", **{key: progress[key] for key in ("completed_blocks", "total_blocks", "completed_cells", "total_cells")}, resume_count=state["resume_count"])
            commits = self._commits()
            if len(commits) != 4:
                raise IntegrityFailure("collection incomplete")
            commit_hashes = {str(item["block_id"]): sha256_file(self._block_dir(str(item["block_id"])) / "block-result.commit.json") for item in commits}
            audit = {
                "schema_version": 2, "pilot_id": PILOT_ID, "collection_complete": True,
                "analysis_authorized": True, "manifest_file_sha256": binding["manifest_file_sha256"],
                "repository_commit": binding["repository_commit"], "block_commit_sha256": commit_hashes,
                "progress_sha256": sha256_file(self.progress_path), "completed_at": utc_now(),
            }
            atomic_write(self.audit_path, audit)
            state["status"] = "complete"
            self._save(state)
        structural_message(status="complete", completed_blocks=4, total_blocks=4, completed_cells=8, total_cells=8, resume_count=state["resume_count"])
        return 0


def validate_block_commit(
    commit: Mapping[str, object], *, block_id: str, expected_task: str
) -> list[dict[str, object]]:
    if commit.get("block_id") != block_id or commit.get("task_id") != expected_task:
        raise IntegrityFailure(f"block commit identity mismatch:{block_id}")
    origin_sha = commit.get("initial_origin_sha256")
    initial_solution_hash = commit.get("initial_solution_hash")
    clone_fingerprint = commit.get("clone_fingerprint")
    if not all(isinstance(value, str) and value for value in (origin_sha, initial_solution_hash, clone_fingerprint)):
        raise IntegrityFailure(f"block clone binding missing:{block_id}")
    cells = commit.get("cells")
    if not isinstance(cells, list) or len(cells) != 2 or any(not isinstance(cell, dict) for cell in cells):
        raise IntegrityFailure("exactly two object cells per block required")
    typed_cells = [dict(cell) for cell in cells]
    if {str(cell.get("condition")) for cell in typed_cells} != {"A-baseline", "B-agentharness"}:
        raise IntegrityFailure(f"block condition pairing mismatch:{block_id}")
    for cell in typed_cells:
        if (
            cell.get("task_id") != expected_task
            or cell.get("initial_origin_sha256") != origin_sha
            or cell.get("initial_solution_hash") != initial_solution_hash
            or cell.get("clone_pre_repair_fingerprint") != clone_fingerprint
        ):
            raise IntegrityFailure(f"pair initial origin mismatch:{block_id}")
        if cell.get("repair_passes_used") != 1 or cell.get("attempt_count") != 1:
            raise IntegrityFailure(f"unexpected local invocation count:{block_id}")
        if not isinstance(cell.get("score"), (int, float)) or not 0.0 <= float(cell["score"]) <= 1.0:
            raise IntegrityFailure(f"invalid heldout score:{block_id}")
    return typed_cells


def finalize(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    if manifest_path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("finalizer requires the external frozen preregistration")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    if manifest.get("preregistration_status") != "frozen":
        raise IntegrityFailure("preregistration status is not frozen")
    if _contains_placeholder(manifest):
        raise IntegrityFailure("frozen preregistration contains placeholders")
    payload = dict(manifest)
    expected_payload_hash = payload.pop("manifest_payload_sha256", None)
    if canonical_hash(payload) != expected_payload_hash:
        raise IntegrityFailure("manifest payload hash mismatch")
    frozen_copy = run_root / "preregistration.frozen.json"
    if not frozen_copy.is_file() or sha256_file(frozen_copy) != sha256_file(manifest_path):
        raise IntegrityFailure("finalizer preregistration binding mismatch")
    state_path, audit_path = run_root / "campaign-state.private.json", run_root / "collection-audit.final.json"
    if not state_path.is_file() or not audit_path.is_file():
        raise IntegrityFailure("authorized complete collection audit required")
    state, audit = json.loads(state_path.read_text()), json.loads(audit_path.read_text())
    if state.get("status") != "complete" or audit.get("collection_complete") is not True or audit.get("analysis_authorized") is not True:
        raise IntegrityFailure("analysis is not authorized")
    if state.get("repository_commit") != manifest.get("repository_commit") or audit.get("repository_commit") != manifest.get("repository_commit"):
        raise IntegrityFailure("finalizer repository binding mismatch")
    manifest_hash = sha256_file(manifest_path)
    if state.get("manifest_file_sha256") != manifest_hash or audit.get("manifest_file_sha256") != manifest_hash:
        raise IntegrityFailure("finalizer manifest binding mismatch")
    expected_hashes = audit.get("block_commit_sha256")
    if not isinstance(expected_hashes, Mapping) or set(expected_hashes) != {f"p{i:03d}" for i in range(1, 5)}:
        raise IntegrityFailure("collection audit block roster mismatch")
    blocks_root = run_root / "private-blocks"
    expected_markers = {
        *(blocks_root / f"p{i:03d}" / "provider-invocation.initial.started.json" for i in range(1, 5)),
        *(blocks_root / f"p{i:03d}" / f"cell-{label}" / "provider-invocation.repair.started.json" for i in range(1, 5) for label in ("A", "B")),
    }
    observed_markers = set(run_root.rglob("provider-invocation.*.started.json"))
    if observed_markers != expected_markers:
        raise IntegrityFailure("provider invocation marker roster mismatch")
    rows: list[dict[str, object]] = []
    task_by_block = {str(block["block_id"]): str(block["task_id"]) for block in manifest["blocks"]}
    for block_id, expected in expected_hashes.items():
        path = run_root / "private-blocks" / str(block_id) / "block-result.commit.json"
        if not path.is_file() or sha256_file(path) != expected:
            raise IntegrityFailure(f"block commit audit mismatch:{block_id}")
        commit = json.loads(path.read_text())
        origin_path = path.parent / "initial-origin.json"
        if not origin_path.is_file() or sha256_file(origin_path) != commit.get("initial_origin_sha256"):
            raise IntegrityFailure(f"initial origin artifact mismatch:{block_id}")
        origin = json.loads(origin_path.read_text(encoding="utf-8"))
        origin_attempts = origin.get("attempts")
        if not isinstance(origin_attempts, list) or len(origin_attempts) != 1:
            raise IntegrityFailure(f"initial invocation count mismatch:{block_id}")
        rows.extend(validate_block_commit(commit, block_id=str(block_id), expected_task=task_by_block[str(block_id)]))
    by_task: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        by_task.setdefault(str(row["task_id"]), {})[str(row["condition"])] = row
    if set(by_task) != set(TASKS) or any(set(pair) != {"A-baseline", "B-agentharness"} for pair in by_task.values()):
        raise IntegrityFailure("finalizer A/B pairing mismatch")
    paired = []
    for task in TASKS:
        a, b = by_task[task]["A-baseline"], by_task[task]["B-agentharness"]
        delta = float(b["score"]) - float(a["score"])
        paired.append({
            "task_id": task,
            "score_a": a["score"], "score_b": b["score"], "difference_b_minus_a": delta,
            "review_opportunity_count": b.get("review_opportunity_count", 0),
            "review_resolution_a": a.get("review_resolution_count", 0),
            "review_resolution_b": b.get("review_resolution_count", 0),
        })
    deltas = [float(item["difference_b_minus_a"]) for item in paired]
    positive = sum(value > 0 for value in deltas)
    non_positive = sum(value <= 0 for value in deltas)
    mean_delta = sum(deltas) / 4
    if positive >= 3 and mean_delta > 0:
        verdict = "directional_signal_positive"
    elif non_positive >= 3 and mean_delta <= 0:
        verdict = "no_directional_signal"
    else:
        verdict = "mixed_or_inconclusive"
    result = {
        "schema_version": 2, "pilot_id": PILOT_ID, "study_class": "exploratory", "confirmatory": False,
        "warning": "Exploratory n=4 directional evidence only; no confirmatory inference.",
        "paired_heldout_scores": paired, "mean_difference_b_minus_a": mean_delta,
        "verdict": verdict,
        "funnel": funnel(rows),
        "review_opportunity_funnel": {
            "review_checks_total": len(TASKS) * 2,
            "review_checks_failed_pre": sum(int(pair["review_opportunity_count"]) for pair in paired),
            "tasks_with_actionable_opportunity": sum(int(pair["review_opportunity_count"]) > 0 for pair in paired),
            "resolved_by_a": sum(int(pair["review_resolution_a"]) for pair in paired),
            "resolved_by_b": sum(int(pair["review_resolution_b"]) for pair in paired),
        },
    }
    atomic_write(run_root / "EXPLORATORY_ACTIONABLE_REPAIR_V2_RESULT.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--freeze-output", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.freeze_output:
            print(json.dumps(freeze_manifest(template_path=args.manifest, output_path=args.freeze_output), indent=2, sort_keys=True))
            return 0
        if args.run_root is None:
            raise IntegrityFailure("--run-root is required for preflight, collection, and finalization")
        if args.finalize:
            print(json.dumps(finalize(manifest_path=args.manifest, run_root=args.run_root), indent=2, sort_keys=True))
            return 0
        if args.preflight:
            preflight(args.manifest, args.run_root)
            structural_message(status="preflight_ok", completed_blocks=0, total_blocks=4, completed_cells=0, total_cells=8)
            return 0
        return ExploratoryClonedStartPilot(args.manifest, args.run_root).run()
    except PilotError as exc:
        structural_message(status="failed", completed_blocks=0, total_blocks=4, completed_cells=0, total_cells=8, invalidity=type(exc).__name__, exit_code=exc.exit_code)
        return exc.exit_code
    except Exception as exc:
        structural_message(status="failed", completed_blocks=0, total_blocks=4, completed_cells=0, total_cells=8, invalidity=type(exc).__name__, exit_code=UNEXPECTED)
        return UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
