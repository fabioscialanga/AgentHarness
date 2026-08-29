from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"V5 pre-efficacy suite: NO-GO: {message}")


def main() -> int:
    pointer = load(HERE / "V5_PRE_EFFICACY_CURRENT.json")
    require(pointer["status"] == "GO_pre_efficacy", "pointer status is not GO")
    require(pointer["qualification_only"] is True, "pointer is not qualification-only")
    require(pointer["target_model_calls"] == pointer["efficacy_cells_observed"] == 0, "pointer claims target activity")

    for inherited in pointer["inherited_freezes"]:
        path = (HERE / inherited["file"]).resolve()
        require(path.is_file() and digest(path) == inherited["sha256"], f"inherited freeze mismatch: {inherited['file']}")

    runner_path = (HERE / pointer["runner_file"]).resolve()
    report_path = HERE / pointer["report_file"]
    require(digest(runner_path) == pointer["runner_sha256"], "runner hash mismatch")
    require(digest(report_path) == pointer["report_sha256"], "report hash mismatch")
    review_pointer = pointer["independent_final_review"]
    review_path = HERE / review_pointer["file"]
    require(digest(review_path) == review_pointer["sha256"], "independent review hash mismatch")
    review = load(review_path)
    require(review["decision"] == review_pointer["decision"] == "GO", "independent review is not GO")
    require(not any(review["findings"].values()), "independent review has findings")
    require(review["reviewed_report_sha256"] == pointer["report_sha256"], "independent review targets another report")
    require(review["target_model_calls"] == review["efficacy_cells_observed"] == 0, "independent review records target activity")

    spec = importlib.util.spec_from_file_location("v5_pre_efficacy_runner", runner_path)
    if spec is None or spec.loader is None:
        raise SystemExit("V5 pre-efficacy suite: NO-GO: cannot load runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = load(report_path)
    tasks = report["tasks"]
    require(report["status"] == "GO" and report["qualification_only"] is True, "report is not qualification GO")
    require(report["target_model_calls"] == report["efficacy_cells_observed"] == 0, "report records efficacy activity")
    require(report["task_count"] == pointer["task_count"] == len(tasks) == len(module.ROSTER) == 12, "task count mismatch")
    require(report["task_ids"] == [task["task_id"] for task in tasks], "task roster mismatch")
    require(len(set(report["task_ids"])) == 12, "duplicate task ID")
    require(
        report["total_declared_probes_per_reference_pass"] == pointer["total_declared_probes_per_reference_pass"] == 548,
        "probe total mismatch",
    )

    for qualifier_name, task in zip(module.ROSTER, tasks, strict=True):
        qualifier_path = ROOT / task["qualifier"]
        require(qualifier_path.name == qualifier_name, f"qualifier order mismatch for {task['task_id']}")
        require(digest(qualifier_path) == task["qualifier_sha256"], f"qualifier hash mismatch for {task['task_id']}")
        result_path = ROOT / task["result_file"]
        require(digest(result_path) == task["result_sha256"], f"raw result hash mismatch for {task['task_id']}")
        payload = load(result_path)
        normalized = module.validate_payload(payload, qualifier_name)
        require(normalized["task_id"] == task["task_id"], f"result task mismatch for {task['task_id']}")
        require(normalized["probe_total_per_implementation"] == task["probe_total_per_implementation"], f"probe mismatch for {task['task_id']}")
        require(normalized["variant_failures"] == task["variant_failures"], f"matrix mismatch for {task['task_id']}")
        tree_sha, file_count = module.public_tree(task["task_id"])
        require(tree_sha == task["public_bundle_tree_sha256"], f"public tree mismatch for {task['task_id']}")
        require(file_count == task["public_bundle_files"], f"public file count mismatch for {task['task_id']}")

    print("V5 pre-efficacy suite: GO (12/12 tasks, 548 declared probes/reference pass, zero target calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
