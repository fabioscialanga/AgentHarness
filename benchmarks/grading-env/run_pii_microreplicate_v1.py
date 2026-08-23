from __future__ import annotations

"""Freeze-first hermetic two-arm PII micro-replicate and provider-free finalizer."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
GRADING_ENV_ROOT = REPO_ROOT / "benchmarks/grading-env"
for import_root in (SRC_ROOT, GRADING_ENV_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from agentharness.benchmark_cells import (
    AGENT_INVOCATION_TIMEOUT_SECONDS,
    ClassifiedCellFailure,
    HermesCliInvoker,
    build_cell_manifest,
    compute_solution_hash,
)
from agentharness.benchmark_heldout_evaluator_v4 import evaluate_heldout
from agentharness.benchmark_review_evaluator_v4 import evaluate_review
from agentharness.efficacy_v4 import (
    CONDITIONS,
    OPAQUE_FINDING_IDS,
    canonical_hash,
    clone_pair,
    materialize_controlled_start,
    tree_fingerprint,
    validate_opaque_feedback,
)
from run_mechanism_first_v4 import (
    IntegrityFailure,
    InvocationFailure,
    SyntheticRepairInvoker,
    accounting,
    atomic_write,
    cleanup,
    contains_placeholder,
    git,
    real_usage,
    sha256_file,
    synthetic_usage,
    utc_now,
)

PILOT_ID = "pii-microreplicate-v1"
TASK_ID = "pii-redaction-pipeline"
ORDER = ("A-baseline", "B-agentharness")
TEMPLATE_PATH = REPO_ROOT / "benchmarks/grading-env/PII_MICROREPLICATE_V1_PREREG.template.json"
PLACEHOLDER = "FREEZE_REQUIRED:"


def validate_manifest_shape(manifest: Mapping[str, object]) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("pilot_id") != PILOT_ID:
        raise IntegrityFailure("micro manifest identity mismatch")
    if manifest.get("execution_mode") not in {"real", "qualification"}:
        raise IntegrityFailure("execution mode invalid")
    if manifest.get("task_id") != TASK_ID or tuple(manifest.get("condition_order", [])) != ORDER:
        raise IntegrityFailure("task or order mismatch")
    if any(
        (
            manifest.get("expected_provider_calls") != 2,
            manifest.get("expected_initial_provider_calls") != 0,
            manifest.get("maximum_provider_calls") != 2,
            manifest.get("quota_threshold_percent") != 76,
            manifest.get("general_efficacy_claim_authorized") is not False,
            manifest.get("retroactive_v4_replacement_authorized") is not False,
        )
    ):
        raise IntegrityFailure("micro protocol constants mismatch")
    if any(
        (
            manifest.get("provider") != "openai-codex",
            manifest.get("model") != "gpt-5.6-sol",
            manifest.get("toolsets") != "terminal,file",
            manifest.get("max_turns") != 40,
            manifest.get("hermes_home") != "/home/fabio/.hermes/profiles/stage2codex2",
        )
    ):
        raise IntegrityFailure("runtime constants mismatch")


def freeze_manifest(output: Path, *, execution_mode: str) -> dict[str, str]:
    if output.resolve().is_relative_to(REPO_ROOT.resolve()) or output.exists():
        raise IntegrityFailure("new external freeze path required")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise IntegrityFailure("repository must be clean before freeze")
    manifest = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    manifest.update(
        execution_mode=execution_mode,
        preregistration_status="frozen",
        frozen_at=utc_now(),
        repository_commit=git("rev-parse", "HEAD"),
    )
    for relative in manifest["frozen_file_sha256"]:
        manifest["frozen_file_sha256"][relative] = sha256_file(REPO_ROOT / relative)
    command = Path(str(manifest["hermes_command"]))
    if not command.is_file() or not os.access(command, os.X_OK):
        raise IntegrityFailure("Hermes wrapper unavailable")
    manifest["hermes_command_sha256"] = sha256_file(command)
    manifest.pop("manifest_payload_sha256", None)
    manifest["manifest_payload_sha256"] = canonical_hash(manifest)
    if contains_placeholder(manifest):
        raise IntegrityFailure("freeze left placeholders")
    atomic_write(output, manifest, exclusive=True)
    return {"path": str(output.resolve()), "sha256": sha256_file(output)}


def preflight(manifest_path: Path, run_root: Path, *, synthetic: bool) -> dict[str, str]:
    if manifest_path.resolve().is_relative_to(REPO_ROOT.resolve()) or run_root.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise IntegrityFailure("manifest and run root must be external")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    payload = dict(manifest)
    expected = payload.pop("manifest_payload_sha256", None)
    expected_mode = "qualification" if synthetic else "real"
    if any(
        (
            manifest.get("execution_mode") != expected_mode,
            manifest.get("preregistration_status") != "frozen",
            canonical_hash(payload) != expected,
            contains_placeholder(manifest),
            manifest.get("repository_commit") != git("rev-parse", "HEAD"),
        )
    ):
        raise IntegrityFailure("frozen manifest binding invalid")
    for relative, digest in manifest["frozen_file_sha256"].items():
        if sha256_file(REPO_ROOT / relative) != digest:
            raise IntegrityFailure(f"frozen file mismatch:{relative}")
    if not synthetic:
        if git("status", "--porcelain", "--untracked-files=all"):
            raise IntegrityFailure("repository must be clean")
        command = Path(str(manifest["hermes_command"]))
        if sha256_file(command) != manifest["hermes_command_sha256"] or os.environ.get("HERMES_HOME") != manifest["hermes_home"]:
            raise IntegrityFailure("runtime binding mismatch")
        if AGENT_INVOCATION_TIMEOUT_SECONDS != int(manifest["invocation_timeout_seconds"]):
            raise IntegrityFailure("timeout binding mismatch")
    return {
        "manifest_file_sha256": sha256_file(manifest_path),
        "repository_commit": str(manifest["repository_commit"]),
        "execution_mode": str(manifest["execution_mode"]),
    }


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def validate_import_audits(cell: Path, *, synthetic: bool) -> dict[str, str]:
    hashes: dict[str, str] = {}
    outputs = cell / "outputs"
    workspace = (cell / "workspace").resolve()
    guard = (REPO_ROOT / "benchmarks/grading-env/pytest_workspace_guard.py").resolve()
    guard_identity = {"path": str(guard), "sha256": sha256_file(guard)}
    for phase in ("pre-repair-pytest", "post-repair-safety-pytest"):
        path = outputs / f"{phase}.import-audit.json"
        if synthetic and not path.exists():
            atomic_write(path, {
                "schema_version": 2,
                "workspace": str(workspace),
                "project_packages": ["pii_redactor"],
                "guard_module": guard_identity,
                "import_tracker_installed": True,
                "observations": [
                    {"module": "pii_redactor", "path": str(workspace / "pii_redactor/__init__.py")},
                    {"module": "pii_redactor.redact", "path": str(workspace / "pii_redactor/redact.py")},
                ],
                "violations": [],
            }, exclusive=True)
        if not path.is_file():
            raise IntegrityFailure(f"import audit missing:{phase}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        observations = payload.get("observations") if isinstance(payload, Mapping) else None
        if any((
            payload.get("schema_version") != 2,
            payload.get("workspace") != str(workspace),
            payload.get("project_packages") != ["pii_redactor"],
            payload.get("guard_module") != guard_identity,
            payload.get("import_tracker_installed") is not True,
            payload.get("violations") != [],
            not isinstance(observations, list),
        )):
            raise IntegrityFailure(f"import isolation failed:{phase}")
        if not isinstance(observations, list):
            raise IntegrityFailure(f"import observations invalid:{phase}")
        for observation in observations:
            if not isinstance(observation, Mapping) or not isinstance(observation.get("module"), str) or not isinstance(observation.get("path"), str) or observation["module"].split(".", 1)[0] != "pii_redactor" or not _within(Path(observation["path"]), workspace):
                raise IntegrityFailure(f"import observation invalid:{phase}")
        hashes[path.name] = sha256_file(path)
    return hashes


def write_heldout_import_audit(workspace: Path, destination: Path) -> str:
    workspace = workspace.resolve(strict=True)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON") and key not in {"HOME", "OLDPWD"}}
    home = destination.parent / ".heldout-import-home"
    home.mkdir(parents=True, exist_ok=True)
    environment.update({
        "HOME": str(home.resolve()),
        "PWD": str(workspace),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONPATH": str(workspace),
        "AGENTHARNESS_WORKSPACE_ROOT": str(workspace),
    })
    script = """
import json, os, sys
from pathlib import Path
workspace = Path(os.environ['AGENTHARNESS_WORKSPACE_ROOT']).resolve(strict=True)
allowed = (workspace, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
initial = list(sys.path)
kept = []
removed = []
for entry in sys.path:
    candidate = Path(entry or os.getcwd()).resolve(strict=False)
    if any(candidate == root or root in candidate.parents for root in allowed):
        kept.append(entry)
    else:
        removed.append(entry)
sys.path[:] = kept
import pii_redactor
import pii_redactor.redact as redact
print(json.dumps({
    'origins': {'pii_redactor': pii_redactor.__file__, 'pii_redactor.redact': redact.__file__},
    'runtime': {'cwd': os.getcwd(), 'pwd': os.environ.get('PWD'), 'safe_path': bool(sys.flags.safe_path), 'initial_sys_path': initial, 'removed_sys_path': removed, 'sys_path': list(sys.path)},
}, sort_keys=True))
"""
    completed = subprocess.run([sys.executable, "-P", "-c", script], cwd=workspace, env=environment, capture_output=True, text=True, check=False, timeout=60)
    if completed.returncode != 0:
        raise IntegrityFailure("heldout import probe failed")
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise IntegrityFailure("heldout import probe payload invalid") from exc
    origins = probe.get("origins") if isinstance(probe, Mapping) else None
    runtime = probe.get("runtime") if isinstance(probe, Mapping) else None
    expected = {"pii_redactor", "pii_redactor.redact"}
    if (
        not isinstance(origins, Mapping)
        or set(origins) != expected
        or any(not isinstance(path, str) or not _within(Path(path), workspace) for path in origins.values())
        or not isinstance(runtime, Mapping)
        or runtime.get("cwd") != str(workspace)
        or runtime.get("pwd") != str(workspace)
        or runtime.get("safe_path") is not True
        or not isinstance(runtime.get("initial_sys_path"), list)
        or not isinstance(runtime.get("removed_sys_path"), list)
        or not isinstance(runtime.get("sys_path"), list)
    ):
        raise IntegrityFailure("heldout import origin escaped workspace")
    payload = {"schema_version": 2, "workspace": str(workspace), "environment": {"PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1", "PYTHONPATH": str(workspace), "PWD": str(workspace)}, "runtime": dict(runtime), "origins": dict(origins), "violations": []}
    atomic_write(destination, payload, exclusive=True)
    return sha256_file(destination)


def validate_provider_markers(run_root: Path) -> dict[str, str]:
    if list(run_root.rglob("provider-invocation.initial.*.json")):
        raise IntegrityFailure("unexpected initial provider marker")
    started = sorted(run_root.rglob("provider-invocation.repair.started.json"))
    completed = sorted(run_root.rglob("provider-invocation.repair.completed.json"))
    if len(started) != 2 or len(completed) != 2:
        raise IntegrityFailure("provider marker count mismatch")
    starts = {json.loads(path.read_text())["invocation_id"]: json.loads(path.read_text()) for path in started}
    ends = {json.loads(path.read_text())["invocation_id"]: json.loads(path.read_text()) for path in completed}
    if len(starts) != 2 or set(starts) != set(ends):
        raise IntegrityFailure("provider marker identity mismatch")
    for identity, start in starts.items():
        end = ends[identity]
        if end.get("status") != "succeeded" or end.get("failure") is not None:
            raise IntegrityFailure("provider invocation unsuccessful")
        for key in ("invocation_id", "task_id", "condition", "phase"):
            if start.get(key) != end.get(key):
                raise IntegrityFailure("provider marker pairing mismatch")
    return {path.relative_to(run_root).as_posix(): sha256_file(path) for path in started + completed}


class MicroPilot:
    def __init__(self, manifest_path: Path, run_root: Path, *, invoker: object, usage: object, synthetic: bool) -> None:
        self.manifest_path = manifest_path.resolve()
        self.run_root = run_root.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.invoker = invoker
        self.usage = usage
        self.synthetic = synthetic
        self.state_path = self.run_root / "campaign-state.private.json"

    def invoke(self, block: Path, condition: str, workspace: Path, feedback: Path | None, origin_ref: dict[str, object], state: dict[str, object]) -> dict[str, object]:
        label = "A" if condition == "A-baseline" else "B"
        cell = block / f"cell-{label}"
        inputs = cell / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        spec = inputs / "SPEC.md"
        claims = inputs / "CLAIMS_CONTRACT.template.json"
        shutil.copy2(REPO_ROOT / "benchmarks" / TASK_ID / "SPEC.md", spec)
        shutil.copy2(REPO_ROOT / "benchmarks" / TASK_ID / "CLAIMS_CONTRACT.template.json", claims)
        manifest = build_cell_manifest(task_id=TASK_ID, condition=condition, replicate_id="pii-micro-r1", cell_dir=cell)
        manifest.update({
            "run_id": f"{PILOT_ID}-{label}",
            "diagnostic_stage": PILOT_ID,
            "spec_path": str(spec),
            "claims_template_path": str(claims),
            "initial_origin": origin_ref,
        })
        if feedback is not None:
            manifest["review_feedback_path"] = str(feedback)
        atomic_write(cell / "cell_manifest.json", manifest, exclusive=True)
        if not self.synthetic:
            cleanup(workspace, str(self.manifest["hermes_command"]))
        identity = f"pii-micro:{condition}:repair-1"
        start = cell / "provider-invocation.repair.started.json"
        end = cell / "provider-invocation.repair.completed.json"
        atomic_write(start, {"schema_version": 1, "phase": "repair", "invocation_id": identity, "task_id": TASK_ID, "condition": condition, "initial_provider_call": False, "started_at": utc_now()}, exclusive=True)
        state["repair_calls_started"] = int(state["repair_calls_started"]) + 1
        atomic_write(self.state_path, state)
        status = "failed"
        failure = None
        try:
            result = self.invoker.run_cloned_repair(manifest, cell / "outputs", workspace)
            row = accounting(result, condition, TASK_ID)
            row["import_audit_sha256"] = validate_import_audits(cell, synthetic=self.synthetic)
            status = "succeeded"
            return row
        except ClassifiedCellFailure as exc:
            failure = f"{exc.execution_status}:{exc.classification_reason}"
            raise InvocationFailure(failure) from exc
        except Exception as exc:
            failure = f"{type(exc).__name__}:{exc}"
            raise
        finally:
            atomic_write(end, {"schema_version": 1, "phase": "repair", "invocation_id": identity, "task_id": TASK_ID, "condition": condition, "status": status, "failure": failure, "completed_at": utc_now()}, exclusive=True)
            state["repair_calls_completed"] = int(state["repair_calls_completed"]) + 1
            atomic_write(self.state_path, state)
            if not self.synthetic:
                cleanup(workspace, str(self.manifest["hermes_command"]))

    def run(self) -> dict[str, object]:
        binding = preflight(self.manifest_path, self.run_root, synthetic=self.synthetic)
        if self.run_root.exists():
            raise IntegrityFailure("fresh run root required")
        self.run_root.mkdir(parents=True)
        os.chmod(self.run_root, 0o700)
        atomic_write(self.run_root / "preregistration.frozen.json", self.manifest, exclusive=True)
        state: dict[str, object] = {"schema_version": 1, "status": "collecting", "provider_initial_calls": 0, "repair_calls_started": 0, "repair_calls_completed": 0, **binding}
        atomic_write(self.state_path, state)
        block = self.run_root / "private-block"
        seed = block / "controlled-start.private"
        materialization = materialize_controlled_start(task_id=TASK_ID, repo_root=REPO_ROOT, destination=seed)
        origin = {"schema_version": 1, "task_id": TASK_ID, "solution_hash": compute_solution_hash(seed), "tree_fingerprint": tree_fingerprint(seed), "provider_initial_call": False}
        origin_path = block / "initial-origin.json"
        atomic_write(origin_path, origin, exclusive=True)
        origin_ref = {"path": str(origin_path), "sha256": sha256_file(origin_path), "solution_hash": origin["solution_hash"], "tree_fingerprint": origin["tree_fingerprint"]}
        workspaces = {"A-baseline": block / "cell-A" / "workspace", "B-agentharness": block / "cell-B" / "workspace"}
        fingerprint = clone_pair(seed, workspaces["A-baseline"], workspaces["B-agentharness"])
        feedback_payload = evaluate_review(seed, TASK_ID)
        validate_opaque_feedback(feedback_payload, task_id=TASK_ID)
        feedback = block / "cell-B" / "inputs" / "review-feedback.json"
        atomic_write(feedback, feedback_payload, exclusive=True)
        feedback_hash = sha256_file(feedback)
        rows: dict[str, dict[str, object]] = {}
        quota_snapshots: list[dict[str, object]] = []
        for condition in ORDER:
            if tree_fingerprint(workspaces[condition]) != fingerprint:
                raise IntegrityFailure("clone changed before invocation")
            used = float(self.usage(f"micro:{condition}:before"))
            quota_snapshots.append({"condition": condition, "used_percent": used, "captured_at": utc_now()})
            atomic_write(self.run_root / "quota-snapshots.private.json", quota_snapshots)
            if not self.synthetic and used >= 76:
                raise InvocationFailure("quota threshold reached")
            rows[condition] = {"task_id": TASK_ID, "condition": condition, **self.invoke(block, condition, workspaces[condition], feedback if condition == "B-agentharness" else None, origin_ref, state)}
            if sha256_file(feedback) != feedback_hash:
                raise IntegrityFailure("feedback changed")
        for condition in CONDITIONS:
            label = "A" if condition == "A-baseline" else "B"
            heldout_audit_path = block / f"cell-{label}/heldout-import-audit.json"
            rows[condition]["heldout_import_audit_sha256"] = write_heldout_import_audit(workspaces[condition], heldout_audit_path)
            rows[condition].update(evaluate_heldout(workspaces[condition], TASK_ID))
            rows[condition]["heldout_valid"] = True
        commit = {
            "schema_version": 1,
            "pilot_id": PILOT_ID,
            "task_id": TASK_ID,
            "condition_order": list(ORDER),
            "initial_origin_sha256": origin_ref["sha256"],
            "initial_solution_hash": origin["solution_hash"],
            "controlled_start": materialization,
            "clone_fingerprint": fingerprint,
            "cells": [rows[condition] for condition in CONDITIONS],
        }
        commit_path = block / "block-result.commit.json"
        atomic_write(commit_path, commit, exclusive=True)
        marker_hashes = validate_provider_markers(self.run_root)
        state.update(status="collection_complete")
        atomic_write(self.state_path, state)
        audit = {
            "schema_version": 1,
            "pilot_id": PILOT_ID,
            "collection_complete": True,
            "analysis_authorized": self.manifest["execution_mode"] == "real" and not self.synthetic,
            "execution_mode": self.manifest["execution_mode"],
            "provider_initial_calls": 0,
            "repair_calls_started": 2,
            "repair_calls_completed": 2,
            "block_commit_sha256": sha256_file(commit_path),
            "provider_marker_sha256": marker_hashes,
            "quota_snapshots_sha256": sha256_file(self.run_root / "quota-snapshots.private.json"),
            **binding,
        }
        atomic_write(self.run_root / "collection-audit.final.json", audit, exclusive=True)
        return {"status": "collection_complete", "provider_calls": 2}


def interpret_pair(*, a_target: bool, a_guards: bool, b_target: bool, b_guards: bool) -> tuple[int, int, str]:
    a = int(a_target and a_guards)
    b = int(b_target and b_guards)
    interpretation = "localized_incremental_benefit" if (a, b) == (0, 1) else "baseline_ceiling" if (a, b) == (1, 1) else "treatment_not_repaired" if b == 0 else "unexpected_pair_shape"
    return a, b, interpretation


def finalize(manifest_path: Path, run_root: Path) -> dict[str, object]:
    manifest_path = manifest_path.resolve()
    run_root = run_root.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)
    if manifest.get("execution_mode") != "real":
        raise IntegrityFailure("production finalizer rejects qualification artifacts")
    payload = dict(manifest)
    expected = payload.pop("manifest_payload_sha256", None)
    if canonical_hash(payload) != expected or manifest.get("repository_commit") != git("rev-parse", "HEAD") or git("status", "--porcelain", "--untracked-files=all"):
        raise IntegrityFailure("clean bound HEAD required")
    for relative, digest in manifest["frozen_file_sha256"].items():
        if sha256_file(REPO_ROOT / relative) != digest:
            raise IntegrityFailure(f"frozen file mismatch:{relative}")
    frozen = run_root / "preregistration.frozen.json"
    audit_path = run_root / "collection-audit.final.json"
    state_path = run_root / "campaign-state.private.json"
    commit_path = run_root / "private-block/block-result.commit.json"
    if not all(path.is_file() for path in (frozen, audit_path, state_path, commit_path)) or sha256_file(frozen) != sha256_file(manifest_path):
        raise IntegrityFailure("collection binding missing")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if any((audit.get("analysis_authorized") is not True, audit.get("collection_complete") is not True, audit.get("execution_mode") != "real", audit.get("repair_calls_started") != 2, audit.get("repair_calls_completed") != 2, audit.get("manifest_file_sha256") != sha256_file(manifest_path), state.get("status") != "collection_complete")):
        raise IntegrityFailure("green production audit required")
    markers = validate_provider_markers(run_root)
    if markers != audit.get("provider_marker_sha256") or sha256_file(commit_path) != audit.get("block_commit_sha256") or sha256_file(run_root / "quota-snapshots.private.json") != audit.get("quota_snapshots_sha256"):
        raise IntegrityFailure("audit hash mismatch")
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    quota_snapshots = json.loads((run_root / "quota-snapshots.private.json").read_text(encoding="utf-8"))
    if (
        not isinstance(quota_snapshots, list)
        or len(quota_snapshots) != 2
        or [item.get("condition") for item in quota_snapshots if isinstance(item, Mapping)] != list(ORDER)
        or any(type(item.get("used_percent")) not in (int, float) or not 0 <= item["used_percent"] < 76 for item in quota_snapshots if isinstance(item, Mapping))
    ):
        raise IntegrityFailure("quota snapshot semantics invalid")
    cells = commit.get("cells")
    seed = run_root / "private-block/controlled-start.private"
    origin_path = run_root / "private-block/initial-origin.json"
    materialization = commit.get("controlled_start")
    if any((commit.get("schema_version") != 1, commit.get("pilot_id") != PILOT_ID, commit.get("task_id") != TASK_ID, tuple(commit.get("condition_order", [])) != ORDER, not isinstance(cells, list), len(cells or []) != 2, not isinstance(materialization, Mapping), materialization.get("agent_visible_leakage") != [], tree_fingerprint(seed) != materialization.get("controlled_fingerprint"), commit.get("clone_fingerprint") != materialization.get("controlled_fingerprint"), compute_solution_hash(seed) != commit.get("initial_solution_hash"), sha256_file(origin_path) != commit.get("initial_origin_sha256"))):
        raise IntegrityFailure("block semantic binding invalid")
    by_condition = {cell.get("condition"): cell for cell in cells if isinstance(cell, Mapping)}
    if set(by_condition) != set(CONDITIONS):
        raise IntegrityFailure("condition roster invalid")
    for condition, cell in by_condition.items():
        if any(cell.get(key) is not True for key in ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated")):
            raise IntegrityFailure("cell validity invalid")
        if not isinstance(cell.get("target_passed"), bool) or not isinstance(cell.get("guards_passed"), bool):
            raise IntegrityFailure("endpoint type invalid")
        if condition == "B-agentharness" and any(cell.get(key) is not True for key in ("feedback_delivered", "feedback_immutable", "feedback_accounted")):
            raise IntegrityFailure("B treatment invalid")
        if condition == "A-baseline" and cell.get("feedback_delivered") is not False:
            raise IntegrityFailure("A treatment contamination")
        label = "A" if condition == "A-baseline" else "B"
        expected_audits = cell.get("import_audit_sha256")
        if not isinstance(expected_audits, Mapping) or set(expected_audits) != {"pre-repair-pytest.import-audit.json", "post-repair-safety-pytest.import-audit.json"}:
            raise IntegrityFailure("import audit roster invalid")
        cell_root = run_root / f"private-block/cell-{label}"
        validate_import_audits(cell_root, synthetic=False)
        for name, digest in expected_audits.items():
            path = cell_root / f"outputs/{name}"
            if sha256_file(path) != digest:
                raise IntegrityFailure("import audit binding invalid")
        heldout_path = cell_root / "heldout-import-audit.json"
        heldout_payload = json.loads(heldout_path.read_text(encoding="utf-8"))
        origins = heldout_payload.get("origins") if isinstance(heldout_payload, Mapping) else None
        workspace = (cell_root / "workspace").resolve()
        heldout_runtime = heldout_payload.get("runtime") if isinstance(heldout_payload, Mapping) else None
        if (
            sha256_file(heldout_path) != cell.get("heldout_import_audit_sha256")
            or heldout_payload.get("schema_version") != 2
            or heldout_payload.get("workspace") != str(workspace)
            or heldout_payload.get("violations") != []
            or not isinstance(origins, Mapping)
            or set(origins) != {"pii_redactor", "pii_redactor.redact"}
            or any(not isinstance(path, str) or not _within(Path(path), workspace) for path in origins.values())
            or not isinstance(heldout_runtime, Mapping)
            or heldout_runtime.get("cwd") != str(workspace)
            or heldout_runtime.get("pwd") != str(workspace)
            or heldout_runtime.get("safe_path") is not True
            or not isinstance(heldout_runtime.get("removed_sys_path"), list)
            or not isinstance(heldout_runtime.get("sys_path"), list)
        ):
            raise IntegrityFailure("heldout import audit binding invalid")
    a_target = bool(by_condition["A-baseline"]["target_passed"])
    b_target = bool(by_condition["B-agentharness"]["target_passed"])
    a_guards = bool(by_condition["A-baseline"]["guards_passed"])
    b_guards = bool(by_condition["B-agentharness"]["guards_passed"])
    a, b, interpretation = interpret_pair(
        a_target=a_target,
        a_guards=a_guards,
        b_target=b_target,
        b_guards=b_guards,
    )
    result = {
        "schema_version": 1,
        "pilot_id": PILOT_ID,
        "verdict": "VALID",
        "A_target": int(a_target),
        "B_target": int(b_target),
        "A_binary_endpoint": a,
        "B_binary_endpoint": b,
        "delta_B_minus_A": b - a,
        "A_guards": a_guards,
        "B_guards": b_guards,
        "interpretation": interpretation,
        "general_efficacy_claim_authorized": False,
        "retroactive_v4_replacement_authorized": False,
        "collection_audit_sha256": sha256_file(audit_path),
    }
    atomic_write(run_root / "PII_MICROREPLICATE_V1_RESULT.json", result, exclusive=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--freeze-output", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    try:
        if args.freeze_output:
            print(json.dumps(freeze_manifest(args.freeze_output, execution_mode="qualification" if args.synthetic else "real"), indent=2))
            return 0
        if not args.run_root:
            raise IntegrityFailure("--run-root required")
        if args.preflight:
            print(json.dumps(preflight(args.manifest, args.run_root, synthetic=args.synthetic), indent=2))
            return 0
        if args.finalize:
            print(json.dumps(finalize(args.manifest, args.run_root), indent=2))
            return 0
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        invoker = SyntheticRepairInvoker() if args.synthetic else HermesCliInvoker(
            hermes_command=manifest["hermes_command"],
            toolsets=manifest["toolsets"],
            max_retries=1,
            provider=manifest["provider"],
            model=manifest["model"],
            max_turns=int(manifest["max_turns"]),
            sandbox_cleanup_arg="--sandbox-cleanup",
        )
        pilot = MicroPilot(args.manifest, args.run_root, invoker=invoker, usage=synthetic_usage if args.synthetic else real_usage, synthetic=args.synthetic)
        print(json.dumps(pilot.run(), indent=2))
        return 0
    except (IntegrityFailure, InvocationFailure) as exc:
        print(json.dumps({"verdict": "INVALID", "reason": str(exc)}), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        traceback.print_exc()
        print(json.dumps({"verdict": "INVALID", "reason": f"unexpected:{type(exc).__name__}"}), file=sys.stderr)
        return 50


if __name__ == "__main__":
    raise SystemExit(main())
