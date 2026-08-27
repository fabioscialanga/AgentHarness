from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADING = ROOT / "benchmarks/grading-env"
_spec = importlib.util.spec_from_file_location("materialize_v5_crypto_mutants", GRADING / "materialize_v5_crypto_mutants.py")
assert _spec is not None and _spec.loader is not None
_materializer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_materializer)
materialize_mutant = _materializer.materialize_mutant
OUT = GRADING / "mechanism-first-v5"
TASKS = {
    "rotating-key-token-verifier": {
        "script": GRADING / "qualify_v5_rotating_token.py",
        "reference": OUT / "references/rotating-key-token-verifier",
        "env": "V5_ROTATING_TOKEN_REFERENCE",
        "checks": ["token_rotation_window", "token_issuer_audience", "token_algorithm_pin", "token_time_claims", "token_canonical_encoding"],
        "probe_counts": {"token_rotation_window": 8, "token_issuer_audience": 6, "token_algorithm_pin": 3, "token_time_claims": 9, "token_canonical_encoding": 8},
        "package": "rotating_token",
        "module": "verify.py",
    },
    "envelope-context-decryptor": {
        "script": GRADING / "qualify_v5_envelope_crypto.py",
        "reference": OUT / "references/envelope-context-decryptor",
        "env": "V5_ENVELOPE_REFERENCE",
        "checks": ["envelope_context_binding", "envelope_key_version", "envelope_nonce_tag", "envelope_schema", "envelope_output_atomicity"],
        "probe_counts": {"envelope_context_binding": 5, "envelope_key_version": 7, "envelope_nonce_tag": 9, "envelope_schema": 14, "envelope_output_atomicity": 4},
        "package": "envelope_crypto",
        "module": "decrypt.py",
    },
    "attenuated-capability-verifier": {
        "script": GRADING / "qualify_v5_capability.py",
        "reference": OUT / "references/attenuated-capability-verifier",
        "env": "V5_CAPABILITY_REFERENCE",
        "checks": ["capability_attenuation", "capability_chain_signatures", "capability_request_match", "capability_time_intersection", "capability_depth"],
        "probe_counts": {"capability_attenuation": 5, "capability_chain_signatures": 7, "capability_request_match": 7, "capability_time_intersection": 8, "capability_depth": 6},
        "package": "capability",
        "module": "verify.py",
    },
    "atomic-batch-state-machine": {
        "script": GRADING / "qualify_v5_atomic_batch.py",
        "reference": OUT / "references/atomic-batch-state-machine",
        "env": "V5_ATOMIC_BATCH_REFERENCE",
        "checks": ["batch_all_or_none", "batch_duplicate_entity", "batch_error_index", "batch_idempotent_replay", "batch_response_order"],
        "probe_counts": {"batch_all_or_none": 6, "batch_duplicate_entity": 5, "batch_error_index": 19, "batch_idempotent_replay": 7, "batch_response_order": 5},
        "package": "batch_state_api",
        "module": "main.py",
    },
    "ack-token-work-queue": {
        "script": GRADING / "qualify_v5_ack_queue.py",
        "reference": OUT / "references/ack-token-work-queue",
        "env": "V5_ACK_QUEUE_REFERENCE",
        "checks": ["ack_stale_worker_rejected", "ack_single_claim", "ack_visibility_timeout", "ack_nack_requeues", "ack_attempt_accounting"],
        "probe_counts": {"ack_stale_worker_rejected": 24, "ack_single_claim": 6, "ack_visibility_timeout": 6, "ack_nack_requeues": 7, "ack_attempt_accounting": 6},
        "admission_mutants": {"ack_stale_toctou": ["ack_stale_worker_rejected"]},
        "package": "ack_queue",
        "module": "cli.py",
    },
}


def run(script: Path, env: dict[str, str] | None = None, args: list[str] | None = None) -> dict:
    completed = subprocess.run([sys.executable, str(script), *(args or [])], cwd="/tmp", env=env, capture_output=True, text=True, timeout=300, check=False)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    return json.loads(completed.stdout)


def semantic(payload: dict) -> dict:
    return {"ok": payload["ok"], "task_id": payload["task_id"], "matrix": payload["matrix"], "target_model_calls": payload["target_model_calls"], "efficacy_cells": payload["efficacy_cells"]}


def test_v5_crypto_reference_and_singleton_mutation_matrices_are_exact() -> None:
    for task_id, task in TASKS.items():
        payload = run(task["script"])
        assert payload["ok"] is True
        assert payload["target_model_calls"] == payload["efficacy_cells"] == 0
        assert payload["probe_counts"] == task["probe_counts"]
        assert payload["total_probes_per_implementation"] == sum(task["probe_counts"].values())
        assert payload["matrix"][0]["implementation"] == "reference"
        assert payload["matrix"][0]["failed"] == []
        assert payload["matrix"][0]["passed"] == task["checks"]
        assert payload["matrix"][0]["executed_probes"] == task["probe_counts"]
        planned = payload["matrix"][1:1 + len(task["checks"])]
        for row, check in zip(planned, task["checks"], strict=True):
            assert row["implementation"] == check
            assert row["failed"] == [check]
            assert row["passed"] == [name for name in task["checks"] if name != check]
        admission = task.get("admission_mutants", {})
        admission_rows = payload["matrix"][1 + len(task["checks"]):]
        assert [row["implementation"] for row in admission_rows] == list(admission)
        for row in admission_rows:
            assert row["failed"] == admission[row["implementation"]]
            assert row["passed"] == [name for name in task["checks"] if name not in row["failed"]]


def test_v5_crypto_qualification_is_deterministic() -> None:
    for task in TASKS.values():
        first = semantic(run(task["script"]))
        second = semantic(run(task["script"]))
        assert first == second


def test_v5_crypto_clean_room_reference_copies(tmp_path: Path) -> None:
    for task_id, task in TASKS.items():
        copied = tmp_path / task_id
        shutil.copytree(task["reference"], copied)
        env = dict(os.environ)
        env[task["env"]] = str(copied)
        payload = run(task["script"], env)
        assert payload["ok"] is True
        assert all(not row["failed"] for row in payload["matrix"][:1])


def test_v5_crypto_candidate_mode_exercises_arbitrary_workspace_without_mutants() -> None:
    for task in TASKS.values():
        payload = run(task["script"], args=["--workspace", str(task["reference"])])
        assert payload["ok"] is True
        assert payload["mutant_runs"] == 0
        assert len(payload["matrix"]) == 1
        assert payload["matrix"][0]["failed"] == []


def test_v5_crypto_source_mutants_are_distinct_and_have_no_runtime_selector(tmp_path: Path) -> None:
    for task_id, task in TASKS.items():
        digests = set()
        private_mutants = [*task["checks"], *task.get("admission_mutants", {})]
        for mutant in private_mutants:
            destination = tmp_path / task_id / mutant
            materialize_mutant(task["reference"], task_id, mutant, destination)
            source = (destination / task["package"] / task["module"]).read_bytes()
            assert b'os.environ.get("AGENTHARNESS_MUTANT"' not in source
            digests.add(hashlib.sha256(source).hexdigest())
        assert len(digests) == len(private_mutants)


def test_v5_crypto_visible_allowlist_and_private_ids_absent() -> None:
    for task_id, task in TASKS.items():
        root = ROOT / "benchmarks" / task_id
        actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        expected = {"SPEC.md", "README.md", "pyproject.toml", "CLAIMS_CONTRACT.template.json", f"{task['package']}/__init__.py", f"{task['package']}/{task['module']}"}
        assert actual == expected
        visible = (root / "SPEC.md").read_text(encoding="utf-8") + (root / task["package"] / task["module"]).read_text(encoding="utf-8")
        assert "AGENTHARNESS_MUTANT" not in visible
        for private_id in [*task["checks"], *task.get("admission_mutants", {})]:
            assert private_id not in visible


def test_v5_crypto_dependency_is_in_frozen_wheelhouse() -> None:
    manifest = json.loads((GRADING / "wheelhouse-manifest.json").read_text(encoding="utf-8"))
    filenames = {row["filename"] for row in manifest["files"]}
    assert "cryptography" in manifest["allowed_top_level"]["cli-solution"]
    crypto = [name for name in filenames if name.lower().startswith("cryptography-49.0.0-")]
    assert len(crypto) == 1
    constraints = (GRADING / "constraints-py312.txt").read_text(encoding="utf-8").splitlines()
    assert "cryptography==49.0.0" in constraints
