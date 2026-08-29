from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"V5.2 qualification: NO-GO: {message}")


def main() -> int:
    pointer = load(HERE / "V5_2_QUALIFICATION_CURRENT.json")
    prebuild = HERE / pointer["prebuild_pointer_file"]
    ledger = HERE / pointer["ledger_file"]
    amendment = HERE / pointer["amendment_file"]
    require(digest(prebuild) == pointer["prebuild_pointer_sha256"], "prebuild pointer hash mismatch")
    require(digest(ledger) == pointer["ledger_sha256"], "ledger hash mismatch")
    require(digest(amendment) == pointer["amendment_sha256"], "amendment hash mismatch")
    task_review_pointer = pointer["task_reviews"]["transactional-release-pointer"]
    task_review_path = HERE / task_review_pointer["file"]
    require(digest(task_review_path) == task_review_pointer["sha256"], "task final review hash mismatch")
    task_review = load(task_review_path)
    require(task_review["decision"] == task_review_pointer["decision"] == "GO", "task final review not GO")
    require(task_review["reviewed_qualification_result_sha256"] == "b479bb3fefe0c688590c6a2dad54915bcb84173a0cc8805ecc38a36d881983a3", "task review targets another matrix")
    require(not any(task_review["findings"].values()), "task final review has findings")

    tier_review_pointer = pointer["task_reviews"]["two-tier-read-through-cache"]
    tier_review_path = HERE / tier_review_pointer["file"]
    require(digest(tier_review_path) == tier_review_pointer["sha256"], "tiered-cache final review hash mismatch")
    tier_review = load(tier_review_path)
    require(tier_review["decision"] == tier_review_pointer["decision"] == "GO", "tiered-cache final review not GO")
    tier_result_path = HERE / "qualification-results/two-tier-read-through-cache.json"
    require(digest(tier_result_path) == tier_review["reviewed_qualification_result_sha256"], "tiered-cache review/result mismatch")
    require(not any(tier_review["findings"].values()), "tiered-cache final review has findings")
    tier_result = load(tier_result_path)
    tier_rows = tier_result["matrix"]
    require(tier_result["ok"] is True and tier_result["total_scored_probes_per_implementation"] == 50, "tiered-cache matrix not qualified")
    require(len(tier_rows) == 7 and tier_rows[0]["failed"] == [], "tiered-cache reference or row count mismatch")
    require(all(row["failed"] == [row["implementation"]] for row in tier_rows[1:6]), "tiered-cache planned matrix not singleton")
    require(tier_rows[6]["implementation"] == "tier_l2_casefold_delete_near_miss", "tiered-cache near-miss identity mismatch")
    require(tier_rows[6]["failed"] == ["tier_two_level_invalidation"], "tiered-cache near miss not singleton invalidation")
    require(all(not row["common_failed"] for row in tier_rows), "tiered-cache common controls failed")

    amended = load(amendment)
    require(amended["status"] == "frozen_amendment", "amendment not frozen")
    require(amended["amends_ledger_sha256"] == pointer["ledger_sha256"], "amendment targets another ledger")
    draft = HERE / amended["source_draft_file"]
    review = HERE / amended["independent_review"]["file"]
    result = HERE / amended["executed_qualification"]["file"]
    require(digest(draft) == amended["source_draft_sha256"], "amendment draft hash mismatch")
    require(digest(review) == amended["independent_review"]["sha256"], "amendment review hash mismatch")
    require(digest(result) == amended["executed_qualification"]["sha256"], "qualification result hash mismatch")
    require(load(review)["decision"] == amended["independent_review"]["decision"] == "GO", "amendment review not GO")

    matrix = load(result)
    checks = matrix["checks"]
    rows = matrix["matrix"]
    require(matrix["ok"] is True, "executed matrix is not OK")
    require(matrix["task_id"] == "transactional-release-pointer", "result task mismatch")
    require(matrix["total_scored_probes_per_implementation"] == 50, "reference does not have 50 scored probes")
    require(matrix["target_model_calls"] == 0 and matrix["efficacy_cells"] is False, "efficacy activity in qualification")
    require(len(rows) == 7 and rows[0]["failed"] == [], "reference or row count mismatch")
    require(all(row["failed"] == [row["implementation"]] for row in rows[1:6]), "planned matrix is not singleton")
    require(rows[6]["implementation"] == "release_split_receipt_near_miss", "near-miss identity mismatch")
    require(rows[6]["failed"] == ["release_failure_atomicity"], "near miss is not singleton atomicity")
    require(all(not row["common_failed"] for row in rows), "common controls failed")
    require(set(checks) == set(matrix["probe_counts"]), "probe/check roster mismatch")
    require(all(matrix["probe_counts"][check] == 10 for check in checks), "check probe count mismatch")

    public = ROOT / "benchmarks/transactional-release-pointer"
    reference = HERE / "references/transactional-release-pointer"
    qualifier = ROOT / "benchmarks/grading-env/qualify_v5_2_release_pointer.py"
    materializer = ROOT / "benchmarks/grading-env/materialize_v5_crypto_mutants.py"
    for path in (
        public / "SPEC.md",
        public / "README.md",
        public / "pyproject.toml",
        public / "CLAIMS_CONTRACT.template.json",
        public / "release_pointer/__init__.py",
        public / "release_pointer/app.py",
        public / "release_pointer/interfaces.py",
        reference / "release_pointer/app.py",
        qualifier,
        materializer,
    ):
        require(path.is_file(), f"missing artifact {path.relative_to(ROOT)}")

    private_source = (reference / "release_pointer/app.py").read_text()
    require("AGENTHARNESS_MUTANT" not in private_source and "MUTANT =" not in private_source, "reference contains a runtime mutation selector")
    materializer_source = materializer.read_text()
    require('"transactional-release-pointer": Path("release_pointer/app.py")' in materializer_source, "materializer mapping missing")
    for mutation_id in (
        "release_generation_cas",
        "release_artifact_approval",
        "release_publication_completeness",
        "release_failure_atomicity",
        "release_idempotent_replay",
        "release_split_receipt_near_miss",
    ):
        require(
            f'("transactional-release-pointer", "{mutation_id}")' in materializer_source,
            f"direct source patch missing for {mutation_id}",
        )

    public_text = "\n".join(path.read_text(errors="replace") for path in public.rglob("*") if path.is_file())
    forbidden = [
        "AGENTHARNESS_MUTANT",
        "release_generation_cas",
        "release_artifact_approval",
        "release_publication_completeness",
        "release_failure_atomicity",
        "release_idempotent_replay",
        "release_split_receipt_near_miss",
        "mechanism-first-v5.2",
        "qualification-results",
    ]
    require(not [token for token in forbidden if token in public_text], "private qualification material leaked into public bundle")

    tier_public = ROOT / "benchmarks/two-tier-read-through-cache"
    tier_reference = HERE / "references/two-tier-read-through-cache"
    tier_qualifier = ROOT / "benchmarks/grading-env/qualify_v5_2_tiered_cache.py"
    for path in (
        tier_public / "SPEC.md",
        tier_public / "README.md",
        tier_public / "pyproject.toml",
        tier_public / "CLAIMS_CONTRACT.template.json",
        tier_public / "tiered_cache/__init__.py",
        tier_public / "tiered_cache/core.py",
        tier_public / "tiered_cache/interfaces.py",
        tier_reference / "tiered_cache/core.py",
        tier_qualifier,
    ):
        require(path.is_file(), f"missing artifact {path.relative_to(ROOT)}")
    tier_private_source = (tier_reference / "tiered_cache/core.py").read_text()
    require("AGENTHARNESS_MUTANT" not in tier_private_source and "MUTANT =" not in tier_private_source, "tiered-cache reference contains runtime selector")
    tier_mutations = (
        "tier_l1_short_circuit",
        "tier_l2_promotion",
        "tier_origin_fill",
        "tier_two_level_invalidation",
        "tier_failure_non_admission",
        "tier_l2_casefold_delete_near_miss",
    )
    for mutation_id in tier_mutations:
        require(
            f'("two-tier-read-through-cache", "{mutation_id}")' in materializer_source,
            f"direct source patch missing for {mutation_id}",
        )
    tier_public_text = "\n".join(path.read_text(errors="replace") for path in tier_public.rglob("*") if path.is_file())
    tier_forbidden = ["AGENTHARNESS_MUTANT", "mechanism-first-v5.2", "qualification-results", *tier_mutations]
    require(not [token for token in tier_forbidden if token in tier_public_text], "private tiered-cache qualification material leaked")

    receipt_review_pointer = pointer["task_reviews"]["portable-command-receipt-ledger"]
    receipt_review_path = HERE / receipt_review_pointer["file"]
    require(digest(receipt_review_path) == receipt_review_pointer["sha256"], "portable-receipt final review hash mismatch")
    receipt_review = load(receipt_review_path)
    require(receipt_review["decision"] == receipt_review_pointer["decision"] == "GO", "portable-receipt final review not GO")
    require(not receipt_review["findings"]["BLOCKER"] and not receipt_review["findings"]["HIGH"] and not receipt_review["findings"]["MEDIUM"], "portable-receipt final review has material findings")
    receipt_result_path = HERE / "qualification-results/portable-command-receipt-ledger.json"
    require(digest(receipt_result_path) == receipt_review["reviewed_qualification_result_sha256"], "portable-receipt review/result mismatch")
    receipt_result = load(receipt_result_path)
    receipt_rows = receipt_result["matrix"]
    require(receipt_result["ok"] is True and receipt_result["total_scored_probes_per_implementation"] == 50, "portable-receipt matrix not qualified")
    require(receipt_result["target_model_calls"] == 0 and receipt_result["efficacy_cells"] is False, "portable-receipt qualification used efficacy calls")
    require(len(receipt_rows) == 7 and receipt_rows[0]["failed"] == [], "portable-receipt reference or row count mismatch")
    require(all(row["failed"] == [row["implementation"]] for row in receipt_rows[1:6]), "portable-receipt planned matrix not singleton")
    require(receipt_rows[6]["implementation"] == "receipt_key_casefold_near_miss", "portable-receipt near-miss identity mismatch")
    require(receipt_rows[6]["failed"] == ["receipt_key_identity"], "portable-receipt near miss not singleton key identity")
    require(all(not row["common_failed"] for row in receipt_rows), "portable-receipt common controls failed")

    receipt_public = ROOT / "benchmarks/portable-command-receipt-ledger"
    receipt_reference = HERE / "references/portable-command-receipt-ledger"
    receipt_qualifier = ROOT / "benchmarks/grading-env/qualify_v5_2_portable_receipts.py"
    receipt_driver = ROOT / "benchmarks/grading-env/v5_2_receipt_process_driver.py"
    for path in (
        receipt_public / "SPEC.md",
        receipt_public / "README.md",
        receipt_public / "pyproject.toml",
        receipt_public / "CLAIMS_CONTRACT.template.json",
        receipt_public / "command_ledger/__init__.py",
        receipt_public / "command_ledger/app.py",
        receipt_reference / "command_ledger/app.py",
        receipt_qualifier,
        receipt_driver,
    ):
        require(path.is_file(), f"missing artifact {path.relative_to(ROOT)}")
    receipt_private_source = (receipt_reference / "command_ledger/app.py").read_text()
    require("AGENTHARNESS_MUTANT" not in receipt_private_source and "MUTANT =" not in receipt_private_source and "_MEMORY" not in receipt_private_source, "portable-receipt reference contains latent mutation state")
    receipt_mutations = (
        "receipt_key_identity",
        "receipt_tenant_identity",
        "receipt_command_identity",
        "receipt_revision_identity",
        "receipt_process_portability",
        "receipt_key_casefold_near_miss",
    )
    require('"portable-command-receipt-ledger": Path("command_ledger/app.py")' in materializer_source, "portable-receipt materializer mapping missing")
    require(all(mutation_id in materializer_source for mutation_id in receipt_mutations), "portable-receipt source patch roster incomplete")
    receipt_public_text = "\n".join(path.read_text(errors="replace") for path in receipt_public.rglob("*") if path.is_file())
    receipt_forbidden = ["AGENTHARNESS_MUTANT", "mechanism-first-v5.2", "qualification-results", *receipt_mutations]
    require(not [token for token in receipt_forbidden if token in receipt_public_text], "private portable-receipt qualification material leaked")

    require(pointer["status"] == "qualified_pre_efficacy", "qualification pointer not closed pre-efficacy")
    require(
        pointer["qualified_candidates"] == [
            "transactional-release-pointer",
            "two-tier-read-through-cache",
            "portable-command-receipt-ledger",
        ],
        "qualification roster mismatch",
    )
    require(pointer["pending_candidates"] == [], "pending roster is not empty")
    require(pointer["efficacy_cells_observed"] == pointer["efficacy_provider_calls"] == 0, "pointer claims efficacy activity")
    print("V5.2 tasks 10-12 qualification: GO (150 scored probes/reference + singleton matrices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
