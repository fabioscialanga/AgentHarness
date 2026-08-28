from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V5 = HERE.parent / "mechanism-first-v5"
V51 = HERE.parent / "mechanism-first-v5.1"
DRAFT = HERE / "V5_2_REPLACEMENT_DRAFT.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"V5.2 draft: NO-GO: {message}")


def main() -> int:
    draft = json.loads(DRAFT.read_text())
    require(draft["status"] == "draft_pre_admission", "draft must not claim frozen status")

    v5_pointer_path = V5 / "V5_PREBUILD_CURRENT.json"
    v5_pointer = json.loads(v5_pointer_path.read_text())
    v5_ledger = V5 / v5_pointer["json_file"]
    require(
        digest(v5_ledger) == draft["inherits"]["v5_ledger_sha256"] == v5_pointer["json_sha256"],
        "inherited V5 ledger hash mismatch",
    )

    v51_pointer = json.loads((V51 / "V5_1_PREBUILD_CURRENT.json").read_text())
    v51_ledger = V51 / v51_pointer["json_file"]
    require(
        digest(v51_ledger) == draft["inherits"]["v5_1_ledger_sha256"] == v51_pointer["json_sha256"],
        "inherited V5.1 ledger hash mismatch",
    )

    candidates = draft["candidates"]
    require(len(candidates) == 3, "exactly three replacements required")
    require(
        [item["family_id"] for item in candidates]
        == ["transactional-transitions", "cache-idempotency", "cache-idempotency"],
        "replacement family slots mismatch",
    )
    candidate_ids = [item["candidate_id"] for item in candidates]
    require(len(set(candidate_ids)) == 3, "duplicate candidate IDs")

    all_check_ids: list[str] = []
    for candidate in candidates:
        checks = candidate["checks"]
        require(len(checks) == 5, f"{candidate['candidate_id']} must have exactly five checks")
        check_ids = [item["check_id"] for item in checks]
        require(len(set(check_ids)) == 5, f"{candidate['candidate_id']} has duplicate checks")
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
            require(candidate[field].strip(), f"{candidate['candidate_id']} lacks {field}")
        all_check_ids.extend(check_ids)

    require(len(set(all_check_ids)) == 15, "check IDs are not globally unique")
    requirements = draft["admission_requirements"]
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

    print("V5.2 replacement draft: GO (static structure; semantic admission still required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
