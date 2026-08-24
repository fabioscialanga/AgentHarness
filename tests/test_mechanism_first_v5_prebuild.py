from __future__ import annotations

import copy
import concurrent.futures
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "benchmarks" / "grading-env" / "build_mechanism_first_v5_prebuild.py"
VALIDATOR = REPO / "benchmarks" / "grading-env" / "validate_mechanism_first_v5_prebuild.py"
OUT = REPO / "benchmarks" / "grading-env" / "mechanism-first-v5"
LEDGER = OUT / "V5_PREBUILD_LEDGER.json"
RENDERING = OUT / "V5_PREBUILD_LEDGER.md"
MANIFEST = OUT / "V5_PREBUILD_CURRENT.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v5_prebuild_generator_is_byte_stable_and_validator_is_read_only(tmp_path: Path) -> None:
    before_json = LEDGER.read_bytes()
    before_md = RENDERING.read_bytes()
    before_manifest = MANIFEST.read_bytes()
    done = subprocess.run([sys.executable, str(GENERATOR)], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert LEDGER.read_bytes() == before_json
    assert RENDERING.read_bytes() == before_md
    assert MANIFEST.read_bytes() == before_manifest

    done = subprocess.run([sys.executable, str(VALIDATOR), "--json"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    result = json.loads(done.stdout)
    assert result == {
        "all_prior_rows": 480,
        "candidates": 24,
        "checks": 120,
        "efficacy_cells": 0,
        "families": 6,
        "ledger_sha256": hashlib.sha256(before_json).hexdigest(),
        "ok": True,
        "pairwise_rows": 276,
        "planned_mutants": 120,
        "target_model_calls": 0,
    }
    assert LEDGER.read_bytes() == before_json
    assert RENDERING.read_bytes() == before_md
    assert MANIFEST.read_bytes() == before_manifest


def test_v5_prebuild_exact_family_check_and_selection_shape() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert payload["efficacy_cells_collected"] == 0
    assert payload["target_model_calls_before_freeze"] == 0
    assert len(payload["families"]) == 6
    assert len(payload["candidates"]) == 24
    assert all(len(family["candidate_ids"]) == 4 for family in payload["families"])
    assert all(len(row["checks"]) == 5 for row in payload["candidates"])
    assert all(row["checks"][0]["id"] == row["target_check_id"] for row in payload["candidates"])
    assert len(payload["all_prior_overlap_matrix"]) == 480
    assert len(payload["candidate_pairwise_matrix"]) == 276
    assert len(payload["seeded_candidate_order"]) == len(set(payload["seeded_candidate_order"])) == 24
    assert set(payload["seeded_family_orders"]) == {family["family_id"] for family in payload["families"]}
    assert all(len(order) == 4 for order in payload["seeded_family_orders"].values())
    assert payload["planned_campaign_rule"]["status"] == "not_yet_frozen"
    assert "go_requires" not in payload["planned_campaign_rule"]


def test_v5_prebuild_all_mutants_are_singleton_plans() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    total = 0
    for row in payload["candidates"]:
        check_ids = [item["id"] for item in row["checks"]]
        for item in row["checks"]:
            total += 1
            assert item["expected_mutant_failed_checks"] == [item["id"]]
            assert item["expected_mutant_passed_checks"] == [check_id for check_id in check_ids if check_id != item["id"]]
    assert total == 120


def test_v5_prebuild_validator_rejects_outcome_token() -> None:
    validator = load_module(VALIDATOR, "v5_prebuild_validator_test")
    try:
        validator.reject_outcome_tokens("neutral prose then delta_B_minus_A then more prose")
    except ValueError as exc:
        assert "outcome-derived token" in str(exc)
    else:
        raise AssertionError("outcome-derived token was not rejected")


def test_v5_prebuild_high_overlap_pairs_have_manual_discriminants() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    manual = [row for row in payload["candidate_pairwise_matrix"] if row["high_overlap_manual_discriminant"] is not None]
    assert len(manual) == 6
    assert all(len(row["high_overlap_manual_discriminant"]) >= 80 for row in manual)


def validate_mutated_payload(module: Any, payload: dict[str, object], tmp_path: Path, markdown_override: str | None = None) -> None:
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    markdown = markdown_override if markdown_override is not None else module.independent_render(payload, digest)
    markdown_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": 1,
        "base_commit": payload["base_commit"],
        "json_file": f"V5_PREBUILD_LEDGER.{digest}.json",
        "json_sha256": digest,
        "markdown_file": f"V5_PREBUILD_LEDGER.{markdown_digest}.md",
        "markdown_sha256": markdown_digest,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    original_manifest = module.MANIFEST
    module.MANIFEST = manifest_path
    try:
        module.validate(payload, raw, markdown)
    finally:
        module.MANIFEST = original_manifest


@pytest.mark.parametrize("mutation", ["missing_contract", "prior_roster", "generic_pair", "missing_probe", "valid_different_contract", "valid_different_mutant"])
def test_v5_independent_validator_rejects_semantic_mutations(tmp_path: Path, mutation: str) -> None:
    module = load_module(VALIDATOR, f"v5_validator_mutation_{mutation}")
    payload = copy.deepcopy(json.loads(LEDGER.read_text(encoding="utf-8")))
    if mutation == "missing_contract":
        del payload["candidates"][0]["normative_profile"]
    elif mutation == "prior_roster":
        payload["all_prior_overlap_matrix"][0]["prior_task"] = "invented-prior-task"
    elif mutation == "generic_pair":
        row = payload["candidate_pairwise_matrix"][0]
        row["substantive_difference"] = f"{row['left']} and {row['right']} are different tasks with distinct behavior."
    elif mutation == "missing_probe":
        del payload["candidates"][0]["checks"][0]["planned_probe"]
    elif mutation == "valid_different_contract":
        payload["candidates"][0]["checks"][0]["public_contract"] = "A claimant may complete any visible item when the worker identifier matches the stored worker identifier."
    else:
        payload["candidates"][0]["checks"][0]["planned_mutant"] = "sorts available queue items in descending lexical order before returning the first claim"
    with pytest.raises((ValueError, KeyError)):
        validate_mutated_payload(module, payload, tmp_path)


def test_v5_independent_validator_rejects_markdown_omission(tmp_path: Path) -> None:
    module = load_module(VALIDATOR, "v5_validator_markdown_mutation")
    payload = copy.deepcopy(json.loads(LEDGER.read_text(encoding="utf-8")))
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    markdown = module.independent_render(payload, hashlib.sha256(raw).hexdigest()).replace("Efficacy cells: `0`\n", "")
    with pytest.raises(ValueError):
        validate_mutated_payload(module, payload, tmp_path, markdown)


def test_v5_content_addressed_publication_survives_concurrent_generators() -> None:
    def run_generator(_: int) -> int:
        return subprocess.run([sys.executable, str(GENERATOR)], cwd=REPO, capture_output=True, text=True).returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(run_generator, range(12))) == [0] * 12
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    json_bytes = (OUT / manifest["json_file"]).read_bytes()
    markdown_bytes = (OUT / manifest["markdown_file"]).read_bytes()
    assert hashlib.sha256(json_bytes).hexdigest() == manifest["json_sha256"]
    assert hashlib.sha256(markdown_bytes).hexdigest() == manifest["markdown_sha256"]
    assert LEDGER.read_bytes() == json_bytes
    assert RENDERING.read_bytes() == markdown_bytes
