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
    require(pointer["qualified_candidates"] == ["transactional-release-pointer"], "qualification roster mismatch")
    require(pointer["efficacy_cells_observed"] == pointer["efficacy_provider_calls"] == 0, "pointer claims efficacy activity")
    print("V5.2 task 10 qualification: GO (50/50 + singleton matrix + amended near miss)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
