from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V5 = HERE.parent / "mechanism-first-v5"
V51 = HERE.parent / "mechanism-first-v5.1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"V5.2 pre-build: NO-GO: {message}")


def validate_candidate(candidate: dict, review: dict) -> None:
    candidate_id = candidate["candidate_id"]
    checks = candidate["checks"]
    check_ids = [item["check_id"] for item in checks]
    require(len(checks) == 5, f"{candidate_id} must have exactly five checks")
    require(len(set(check_ids)) == 5, f"{candidate_id} has duplicate checks")
    for check in checks:
        require(check["counterexample"].strip(), f"{check['check_id']} lacks counterexample")
        require(check["mutant"].startswith("Unconditionally"), f"{check['check_id']} mutant is not unconditional")
    for field in (
        "public_interface",
        "normative_profile",
        "near_miss",
        "qualification_controls",
        "anti_overlap",
        "anti_duplication",
    ):
        require(candidate[field].strip(), f"{candidate_id} lacks {field}")

    require(review["candidate_id"] == candidate_id, f"review candidate mismatch for {candidate_id}")
    require(review["decision"] == "GO", f"review is not GO for {candidate_id}")
    require(review["check_order"] == check_ids, f"review check order mismatch for {candidate_id}")
    rows = review["rows"]
    require(rows["reference"] == ["PASS"] * 5, f"reference row mismatch for {candidate_id}")
    planned = [row for name, row in rows.items() if name.startswith("mutant_")]
    near = [row for name, row in rows.items() if name.startswith("near_miss_")]
    require(len(planned) == 5, f"planned mutant row count mismatch for {candidate_id}")
    require(len(near) == 1, f"near-miss row count mismatch for {candidate_id}")
    expected_singletons = {
        tuple("FAIL" if index == target else "PASS" for index in range(5))
        for target in range(5)
    }
    require({tuple(row) for row in planned} == expected_singletons, f"singleton matrix mismatch for {candidate_id}")
    require(near[0].count("FAIL") == 1 and near[0].count("PASS") == 4, f"near miss is not singleton for {candidate_id}")


def main() -> int:
    pointer_path = HERE / "V5_2_PREBUILD_CURRENT.json"
    pointer = load(pointer_path)
    require(pointer["status"] == "frozen_prebuild", "pointer is not frozen")

    ledger_path = HERE / pointer["json_file"]
    draft_path = HERE / pointer["source_draft_file"]
    review_path = HERE / pointer["admission_review_file"]
    rejection_path = HERE / pointer["pre_admission_rejections_file"]
    require(digest(ledger_path) == pointer["json_sha256"], "ledger hash mismatch")
    require(ledger_path.name == f"V5_2_REPLACEMENT_LEDGER.{pointer['json_sha256']}.json", "ledger filename/hash mismatch")
    require(digest(draft_path) == pointer["source_draft_sha256"], "source draft hash mismatch")
    require(digest(review_path) == pointer["admission_review_sha256"], "admission review hash mismatch")
    require(digest(rejection_path) == pointer["pre_admission_rejections_sha256"], "rejection history hash mismatch")

    v5_pointer_path = V5 / "V5_PREBUILD_CURRENT.json"
    v5_pointer = load(v5_pointer_path)
    v5_ledger_path = V5 / v5_pointer["json_file"]
    require(digest(v5_pointer_path) == pointer["inherits_v5_pointer_sha256"], "V5 pointer hash mismatch")
    require(digest(v5_ledger_path) == pointer["inherits_v5_ledger_sha256"] == v5_pointer["json_sha256"], "V5 ledger hash mismatch")

    v51_pointer_path = V51 / "V5_1_PREBUILD_CURRENT.json"
    v51_pointer = load(v51_pointer_path)
    v51_ledger_path = V51 / v51_pointer["json_file"]
    require(digest(v51_pointer_path) == pointer["inherits_v5_1_pointer_sha256"], "V5.1 pointer hash mismatch")
    require(digest(v51_ledger_path) == pointer["inherits_v5_1_ledger_sha256"] == v51_pointer["json_sha256"], "V5.1 ledger hash mismatch")

    ledger = load(ledger_path)
    review = load(review_path)
    rejections = load(rejection_path)
    require(ledger["status"] == "frozen_prebuild", "ledger is not frozen")
    require(ledger["source_draft_sha256"] == pointer["source_draft_sha256"], "ledger draft binding mismatch")
    require(ledger["admission_review"]["decision"] == "GO", "ledger review is not GO")
    require(ledger["admission_review"]["sha256"] == pointer["admission_review_sha256"], "ledger review binding mismatch")
    require(ledger["pre_admission_rejections"]["sha256"] == pointer["pre_admission_rejections_sha256"], "ledger rejection binding mismatch")
    require(review["decision"] == "GO", "review artifact is not GO")
    require(review["reviewed_draft_sha256"] == pointer["source_draft_sha256"], "review targets another draft")
    require(review["efficacy_cells_observed"] == review["efficacy_provider_calls"] == 0, "review occurred after efficacy activity")
    require(rejections["efficacy_cells_observed"] == rejections["efficacy_provider_calls"] == 0, "rejections occurred after efficacy activity")

    candidates = ledger["candidates"]
    require(len(candidates) == 3, "exactly three replacements required")
    require(
        [item["family_id"] for item in candidates]
        == ["transactional-transitions", "cache-idempotency", "cache-idempotency"],
        "replacement family slots mismatch",
    )
    candidate_ids = [item["candidate_id"] for item in candidates]
    require(candidate_ids == pointer["replacement_candidate_ids"], "pointer candidate roster mismatch")
    require(len(set(candidate_ids)) == 3, "duplicate candidate IDs")
    reviews = review["candidate_verdicts"]
    require([item["candidate_id"] for item in reviews] == candidate_ids, "review roster/order mismatch")
    for candidate, candidate_review in zip(candidates, reviews, strict=True):
        validate_candidate(candidate, candidate_review)

    all_check_ids = [check["check_id"] for candidate in candidates for check in candidate["checks"]]
    require(len(set(all_check_ids)) == 15, "check IDs are not globally unique")
    requirements = ledger["admission_requirements"]
    require(requirements["exact_checks_per_candidate"] == 5, "check-count rule changed")
    for field in (
        "singleton_matrix",
        "independent_public_near_miss",
        "source_level_mutants_only",
        "fresh_state_per_check",
        "public_bundle_leak_free",
        "all_prior_overlap_evidence_required",
    ):
        require(requirements[field] is True, f"admission requirement {field} disabled")

    require(pointer["efficacy_cells_observed"] == pointer["efficacy_provider_calls"] == 0, "pointer claims efficacy activity")
    print("V5.2 replacement ledger: GO (hash-bound + reviewed singleton matrices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
