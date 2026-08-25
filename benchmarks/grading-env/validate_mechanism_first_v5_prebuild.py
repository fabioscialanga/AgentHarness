from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "grading-env" / "mechanism-first-v5"
LEDGER = OUT / "V5_PREBUILD_LEDGER.json"
RENDERING = OUT / "V5_PREBUILD_LEDGER.md"
MANIFEST = OUT / "V5_PREBUILD_CURRENT.json"

EXPECTED_FAMILIES = {
    "concurrency-ownership": {"ack-token-work-queue", "semaphore-permit-registry", "epoch-guarded-leader-heartbeat", "atomic-snapshot-publisher"},
    "transactional-transitions": {"transactional-outbox-order", "saga-compensation-engine", "atomic-batch-state-machine", "durable-retry-scheduler"},
    "cryptographic-binding": {"canonical-query-signature", "envelope-context-decryptor", "rotating-key-token-verifier", "merkle-batch-proof-verifier"},
    "authorization-isolation": {"tenant-scoped-resource-api", "attenuated-capability-verifier", "field-projection-authorization", "atomic-authorized-batch"},
    "cache-idempotency": {"version-fenced-read-cache", "canonical-idempotent-command", "negative-cache-invalidation", "singleflight-scope-key"},
    "streaming-parser-boundaries": {"incremental-utf8-decoder", "length-prefixed-frame-parser", "ndjson-transactional-ingest", "streaming-csv-quoted-records"},
}

OUTCOME_TOKENS = ("a_target", "b_target", "delta_b_minus_a", "baseline_ceiling", "pii_microreplicate_v1_result")
EXPECTED_BASE_COMMIT = "95649a6ae0cbbbaf770f7f1363fbe6cc35d79f77"
EXPECTED_SELECTION_SEED = "agentharness-mechanism-first-v5-admission-v1"
EXPECTED_FREEZE_DATE = "2026-08-24"
EXPECTED_LEDGER_SHA256 = "01a331c23895b764f84952d266350fa50e581007e9950039973e8ea3c42e816c"
EXPECTED_PRIOR_IDS = {
    "support-ticket-api", "csv-member-import", "incident-escalation-api", "inventory-adjustment-api",
    "leave-request-api", "refund-approval-api", "report-export-job", "webhook-ingestion-service",
    "appointment-booking-api", "shipment-event-api", "jsonl-event-aggregation", "invoice-payment-reconciliation",
    "dependency-impact-planner", "access-policy-evaluator", "versioned-document-api", "safe-archive-extraction",
    "signed-artifact-verifier", "pii-redaction-pipeline", "lease-coordination-api", "double-entry-ledger-api",
}


def reject_outcome_tokens(text: str) -> None:
    lowered = text.lower()
    for forbidden in OUTCOME_TOKENS:
        require(forbidden not in lowered, f"outcome-derived token present: {forbidden}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nonplaceholder(value: object, field: str) -> str:
    require(isinstance(value, str) and len(value.strip()) >= 3, f"{field} is missing or placeholder")
    assert isinstance(value, str)
    lowered = value.lower()
    require(not any(token in lowered for token in ("todo", "tbd", "placeholder", "fill me")), f"{field} contains placeholder text")
    return value


def independent_render(payload: dict[str, Any], digest: str) -> str:
    lines = [
        "# AgentHarness mechanism-first V5 pre-build ledger", "",
        f"Freeze date: {EXPECTED_FREEZE_DATE}",
        f"Base commit before this amendment: `{EXPECTED_BASE_COMMIT}`",
        f"Normative JSON SHA-256: `{digest}`",
        "Target-model calls: `0`", "Efficacy cells: `0`", "",
        "## Authorization boundary", "", str(payload["authorization"]), "",
        f"Prohibited: {payload['campaign_boundary']}.", "", "## Frozen families and candidates", "",
    ]
    for family in payload["families"]:
        lines.extend([f"### `{family['family_id']}`", "", str(family["definition"]), ""])
        for row in [item for item in payload["candidates"] if item["family_id"] == family["family_id"]]:
            lines.extend([
                f"#### `{row['candidate_id']}`", "", str(row["construct"]), "",
                f"Interface: `{row['public_interface']['entrypoint']}`",
                f"Designated target: `{row['target_check_id']}`",
                f"Finding concept: {row['finding_concept']}", "", "Planned checks:",
            ])
            for check in row["checks"]:
                marker = "target" if check["id"] == row["target_check_id"] else "guard"
                lines.append(f"- `{check['id']}` ({marker}): {check['public_contract']}")
            lines.append("")
    counts = payload["expected_counts"]
    lines.extend([
        "## Preventive evidence shape", "",
        f"- {counts['candidates']} candidates across {counts['families']} families",
        f"- {counts['planned_mutants']} planned singleton mutants",
        f"- {counts['all_prior_rows']} candidate-versus-prior comparisons",
        f"- {counts['pairwise_rows']} within-bank pair comparisons",
        "- Selection is seeded and mechanical; no target-model screening is authorized",
        "- Fewer than 12 qualified candidates means no V5 launch", "", "## Next gate", "",
        "Independent read-only review must return GO before visible bundles, references, hidden evaluators, or mutants are implemented. This artifact does not authorize provider calls.", "",
    ])
    return "\n".join(lines)


def validate(payload: dict[str, Any], raw: bytes, markdown: str) -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    json_digest = hashlib.sha256(raw).hexdigest()
    markdown_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    require(manifest == {
        "schema_version": 1,
        "base_commit": payload.get("base_commit"),
        "json_file": f"V5_PREBUILD_LEDGER.{json_digest}.json",
        "json_sha256": json_digest,
        "markdown_file": f"V5_PREBUILD_LEDGER.{markdown_digest}.md",
        "markdown_sha256": markdown_digest,
    }, "published bundle manifest does not bind the exact JSON and Markdown bytes")
    require(payload.get("schema_version") == 1, "schema_version must be 1")
    require(payload.get("base_commit") == EXPECTED_BASE_COMMIT, "base commit differs from independent freeze")
    require(payload.get("selection_seed") == EXPECTED_SELECTION_SEED, "selection seed differs from independent freeze")
    require(payload.get("freeze_date") == EXPECTED_FREEZE_DATE, "freeze date differs from independent freeze")
    require(json_digest == EXPECTED_LEDGER_SHA256, "ledger bytes differ from the independently reviewed semantic freeze")
    require(payload.get("efficacy_cells_collected") == 0, "efficacy cells must be zero")
    require(payload.get("target_model_calls_before_freeze") == 0, "target-model calls must be zero")
    require("no target-model repair pilot" in payload.get("campaign_boundary", ""), "campaign boundary is not fail-closed")
    global_contracts = payload.get("global_contracts")
    require(isinstance(global_contracts, dict) and len(global_contracts) == 8, "global contract roster is incomplete")
    assert isinstance(global_contracts, dict)
    for key, value in global_contracts.items():
        nonplaceholder(value, f"global_contracts.{key}")
    campaign_rule = payload.get("planned_campaign_rule")
    require(isinstance(campaign_rule, dict) and campaign_rule.get("status") == "not_yet_frozen", "campaign threshold must remain unfrozen at prebuild")
    assert isinstance(campaign_rule, dict)
    require("go_requires" not in campaign_rule, "uncalibrated GO threshold is forbidden")

    families = payload.get("families")
    candidates = payload.get("candidates")
    require(isinstance(families, list) and len(families) == 6, "exactly six families required")
    require(isinstance(candidates, list) and len(candidates) == 24, "exactly 24 candidates required")
    assert isinstance(families, list)
    assert isinstance(candidates, list)

    family_ids = [row.get("family_id") for row in families]
    require(len(set(family_ids)) == 6, "family IDs must be unique")
    require(set(family_ids) == set(EXPECTED_FAMILIES), "family roster differs from independent freeze")
    candidate_ids = [row.get("candidate_id") for row in candidates]
    require(all(isinstance(item, str) for item in candidate_ids), "candidate IDs must be strings")
    require(len(set(candidate_ids)) == 24, "candidate IDs must be unique")

    expected_order = sorted(
        candidate_ids,
        key=lambda candidate_id: hashlib.sha256(f"{payload['selection_seed']}{candidate_id}".encode("utf-8")).hexdigest(),
    )
    require(payload.get("seeded_candidate_order") == expected_order, "seeded candidate order mismatch")
    expected_family_orders = {
        family_id: [candidate_id for candidate_id in expected_order if candidate_id in members]
        for family_id, members in EXPECTED_FAMILIES.items()
    }
    require(payload.get("seeded_family_orders") == expected_family_orders, "seeded family orders mismatch")

    check_count = 0
    mutant_count = 0
    for family in families:
        family_id = family["family_id"]
        members = [row for row in candidates if row.get("family_id") == family_id]
        require(len(members) == 4, f"family {family_id} must contain four candidates")
        require({row["candidate_id"] for row in members} == EXPECTED_FAMILIES[family_id], f"family {family_id} candidate roster differs from independent freeze")
        require(family.get("candidate_ids") == [row["candidate_id"] for row in members], f"family {family_id} roster mismatch")
        nonplaceholder(family.get("definition"), f"family {family_id} definition")
        nonplaceholder(family.get("inclusion_rule"), f"family {family_id} inclusion_rule")
        nonplaceholder(family.get("exclusion_rule"), f"family {family_id} exclusion_rule")

    for row in candidates:
        candidate_id = row["candidate_id"]
        require(row.get("admission_status") == "candidate", f"{candidate_id} has outcome-derived admission status")
        nonplaceholder(row.get("construct"), f"{candidate_id}.construct")
        nonplaceholder(row.get("interface_kind"), f"{candidate_id}.interface_kind")
        require(isinstance(row.get("normative_profile"), str) and len(row["normative_profile"]) >= 160, f"{candidate_id} normative profile is not implementation-complete")
        require(isinstance(row.get("qualification_control"), str) and len(row["qualification_control"]) >= 120, f"{candidate_id} qualification control is underspecified")
        public = row.get("public_interface")
        require(isinstance(public, dict), f"{candidate_id} public interface missing")
        assert isinstance(public, dict)
        for key in ("entrypoint", "input_contract", "state_or_output_boundary", "failure_contract"):
            nonplaceholder(public.get(key), f"{candidate_id}.public_interface.{key}")

        checks = row.get("checks")
        require(isinstance(checks, list) and len(checks) == 5, f"{candidate_id} must have five checks")
        assert isinstance(checks, list)
        check_ids = [item.get("id") for item in checks]
        require(len(set(check_ids)) == 5, f"{candidate_id} check IDs must be unique")
        require(row.get("target_check_id") in check_ids, f"{candidate_id} target not in roster")
        require(check_ids[0] == row.get("target_check_id"), f"{candidate_id} target must be first and explicit")
        check_count += len(checks)
        for item in checks:
            check_id = item["id"]
            for key in ("public_contract", "planned_probe", "planned_mutant", "failure_atomicity"):
                nonplaceholder(item.get(key), f"{candidate_id}.{check_id}.{key}")
            require(item.get("expected_mutant_failed_checks") == [check_id], f"{candidate_id}.{check_id} failed set is not singleton")
            require(item.get("expected_mutant_passed_checks") == [other for other in check_ids if other != check_id], f"{candidate_id}.{check_id} passed set mismatch")
            mutant_count += 1

        finding = nonplaceholder(row.get("finding_concept"), f"{candidate_id}.finding_concept")
        require(finding.startswith("Observed behavior:") and ". Violated invariant:" in finding, f"{candidate_id} finding must be descriptive evidence plus invariant")
        require(str(row["target_check_id"]).lower() not in finding.lower(), f"{candidate_id} finding leaks private check ID")
        require(not any(token in finding.lower() for token in ("heldout", "fixture", "expected output", "test_")), f"{candidate_id} finding leaks evaluator language")
        steps = row.get("private_static_reasoning_rubric")
        require(isinstance(steps, list) and len(steps) >= 2, f"{candidate_id} needs at least two reasoning steps")
        assert isinstance(steps, list)
        for index, step in enumerate(steps):
            nonplaceholder(step, f"{candidate_id}.repair_reasoning_steps[{index}]")
        nonplaceholder(row.get("independent_near_miss"), f"{candidate_id}.independent_near_miss")
        for key in ("latent_invariant", "adversarial_axis", "repair_mechanism_class", "discriminating_counterexample"):
            nonplaceholder(row.get(key), f"{candidate_id}.{key}")

    prior_rows = payload.get("all_prior_overlap_matrix")
    require(isinstance(prior_rows, list) and len(prior_rows) == 480, "all-prior matrix must have 480 rows")
    assert isinstance(prior_rows, list)
    expected_prior_pairs = {(candidate_id, prior_id) for candidate_id in candidate_ids for prior_id in EXPECTED_PRIOR_IDS}
    actual_prior_pairs = {(row.get("candidate_id"), row.get("prior_task")) for row in prior_rows}
    require(actual_prior_pairs == expected_prior_pairs, "all-prior matrix is incomplete or duplicated")
    for row in prior_rows:
        for key in ("shared_shell_or_surface", "substantive_difference", "non_implication"):
            nonplaceholder(row.get(key), f"prior matrix {row.get('candidate_id')}/{row.get('prior_task')} {key}")
        require(str(row["candidate_id"]) in row["substantive_difference"], "candidate-specific prior distinction required")
        require(str(row["prior_task"]) in row["substantive_difference"], "prior-task-specific distinction required")

    pair_rows = payload.get("candidate_pairwise_matrix")
    require(isinstance(pair_rows, list) and len(pair_rows) == 276, "within-bank matrix must have 276 rows")
    assert isinstance(pair_rows, list)
    expected_pairs = {tuple(sorted(pair)) for pair in itertools.combinations(candidate_ids, 2)}
    actual_pairs = {tuple(sorted((row.get("left"), row.get("right")))) for row in pair_rows}
    require(actual_pairs == expected_pairs, "within-bank pair matrix is incomplete or duplicated")
    for row in pair_rows:
        nonplaceholder(row.get("shared_shell_or_surface"), f"pair {row.get('left')}/{row.get('right')} shared")
        difference = nonplaceholder(row.get("substantive_difference"), f"pair {row.get('left')}/{row.get('right')} difference")
        require(str(row["left"]) in difference and str(row["right"]) in difference, "pair-specific names required")
        lowered_difference = difference.lower()
        require(not any(token in lowered_difference for token in ("different tasks", "distinct behavior", "both candidates are different", "different things")), "generic pairwise prose is forbidden")
        nonplaceholder(row.get("left_only_counterexample"), f"pair {row.get('left')}/{row.get('right')} left counterexample")
        nonplaceholder(row.get("right_only_counterexample"), f"pair {row.get('left')}/{row.get('right')} right counterexample")
        left_pass = nonplaceholder(row.get("left_pass_right_fail"), f"pair {row.get('left')}/{row.get('right')} left-pass-right-fail")
        right_pass = nonplaceholder(row.get("right_pass_left_fail"), f"pair {row.get('left')}/{row.get('right')} right-pass-left-fail")
        require(str(row["left"]) in left_pass and str(row["right"]) in left_pass, "bilateral left discriminator must name both candidates")
        require(str(row["left"]) in right_pass and str(row["right"]) in right_pass, "bilateral right discriminator must name both candidates")

    high_overlap = [row for row in pair_rows if row.get("high_overlap_manual_discriminant") is not None]
    require(len(high_overlap) == 6, "exactly six frozen high-overlap pairs require manual discriminants")
    for row in high_overlap:
        nonplaceholder(row.get("high_overlap_manual_discriminant"), f"pair {row.get('left')}/{row.get('right')} manual discriminant")

    counts = payload.get("expected_counts")
    require(counts == {
        "families": 6,
        "candidates": 24,
        "candidates_per_family": 4,
        "checks_per_candidate": 5,
        "planned_mutants": 120,
        "all_prior_rows": 480,
        "pairwise_rows": 276,
    }, "expected_counts mismatch")
    require(check_count == 120 and mutant_count == 120, "functional check/mutant count mismatch")

    digest = hashlib.sha256(raw).hexdigest()
    require(markdown == independent_render(payload, digest), "rendering is not byte-identical to independent canonical rendering")
    require("Target-model calls: `0`" in markdown and "Efficacy cells: `0`" in markdown, "rendering omits zero-efficacy boundary")
    reject_outcome_tokens(raw.decode("utf-8"))
    reject_outcome_tokens(markdown)

    return {
        "ok": True,
        "ledger_sha256": digest,
        "families": 6,
        "candidates": 24,
        "checks": check_count,
        "planned_mutants": mutant_count,
        "all_prior_rows": len(prior_rows),
        "pairwise_rows": len(pair_rows),
        "target_model_calls": 0,
        "efficacy_cells": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(Path(manifest["json_file"]).name == manifest["json_file"], "unsafe JSON manifest path")
    require(Path(manifest["markdown_file"]).name == manifest["markdown_file"], "unsafe Markdown manifest path")
    raw = (OUT / manifest["json_file"]).read_bytes()
    payload = json.loads(raw)
    result = validate(payload, raw, (OUT / manifest["markdown_file"]).read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else "V5 pre-build ledger: GO (static)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
