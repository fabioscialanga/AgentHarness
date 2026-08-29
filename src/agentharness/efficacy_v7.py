from __future__ import annotations

"""Provider-free V7 protocol delta layered on the qualified V6 primitives."""

from pathlib import Path
from typing import Mapping, Sequence

from . import efficacy_v6 as v6

PILOT_ID = "mechanism-first-controlled-repair-v7"
CALIBRATION_TASKS = (
    "streaming-csv-quoted-records",
    "length-prefixed-frame-parser",
    "atomic-batch-state-machine",
)
EVALUATION_TASKS = v6.EVALUATION_TASKS
CONDITIONS = v6.CONDITIONS
CONDITION_ORDERS = v6.CONDITION_ORDERS
TASK_DEFECTS = v6.TASK_DEFECTS
TASK_CHECKS = v6.TASK_CHECKS
REFERENCE_RELATIVE = v6.REFERENCE_RELATIVE
OPAQUE_FINDING_IDS = v6.OPAQUE_FINDING_IDS
FINDING_CONTENT = v6.FINDING_CONTENT
FORBIDDEN_AGENT_TOKENS = v6.FORBIDDEN_AGENT_TOKENS

# V7 changes the diagnosis budget and calibration roster, not the already
# qualified source-native materialization, finding, cloning, or quota logic.
canonical_hash = v6.canonical_hash
tree_manifest = v6.tree_manifest
tree_fingerprint = v6.tree_fingerprint
leakage_scan = v6.leakage_scan
materialize_clean_reference = v6.materialize_clean_reference
materialize_controlled_start = v6.materialize_controlled_start
clone_pair = v6.clone_pair
opaque_review_feedback = v6.opaque_review_feedback
validate_opaque_feedback = v6.validate_opaque_feedback
evaluate_review = v6.evaluate_review
conservative_usage_percent = v6.conservative_usage_percent
quota_admission = v6.quota_admission


def evaluate_heldout(workspace: Path, task_id: str, *, repo_root: Path | None = None):
    result = dict(v6.evaluate_heldout(workspace, task_id, repo_root=repo_root))
    # V6 already records the source evaluator's schema as 5. Preserve that
    # provenance while identifying the enclosing campaign cell as V7.
    result["schema_version"] = 7
    return result


def calibration_admission(rows: Sequence[Mapping[str, object]]) -> str:
    if len(rows) != 3 or {str(row.get("task_id")) for row in rows} != set(CALIBRATION_TASKS):
        return "INVALID"
    validity = ("invocation_valid", "heldout_valid", "target_evaluated", "guards_evaluated", "guards_passed")
    if any(
        row.get("condition") != "A-baseline"
        or any(row.get(key) is not True for key in validity)
        or type(row.get("target_passed")) is not bool
        for row in rows
    ):
        return "INVALID"
    recovered = sum(row.get("target_passed") is True for row in rows)
    return "ADMIT" if recovered <= 1 else "CEILING"


def validate_marker_accounting(markers: Sequence[Mapping[str, object]], *, evaluation_admitted: bool) -> None:
    expected = {
        (f"v7-cal-{index:03d}:A-baseline:repair-1", task, "A-baseline")
        for index, task in enumerate(CALIBRATION_TASKS, 1)
    }
    if evaluation_admitted:
        expected |= {
            (f"v7-eval-{index:03d}:{condition}:repair-1", task, condition)
            for index, task in enumerate(EVALUATION_TASKS, 1)
            for condition in CONDITIONS
        }
    observed: set[tuple[str, str, str]] = set()
    for marker in markers:
        key = (str(marker.get("invocation_id")), str(marker.get("task_id")), str(marker.get("condition")))
        if marker.get("phase") != "repair" or marker.get("initial_provider_call") is not False or key in observed:
            raise ValueError("provider_marker_invalid")
        observed.add(key)
    if observed != expected or len(markers) != len(expected):
        raise ValueError("provider_marker_roster_mismatch")


def finalize_results(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    result = dict(v6.finalize_results(rows))
    result["schema_version"] = 7
    return result
