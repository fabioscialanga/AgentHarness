"""Explicit, read-only DEP consultation for the CLI; no host integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dep_evidence import (MAPPING_ID, ApprovedDepControl, approved_dep_control_from_run,
                           local_environment_id, match_dep_evidence)
from .risk_dep import detect_dependency_change


SCHEMA_VERSION = "m3.dep-assess.v0"


def assess_dep(project: str | Path, *, control_mapping: str | None = None,
               control_run: str | None = None) -> dict[str, Any]:
    """Detect DEP risk, then assess only a selected approved local control."""
    input_path = Path(project)
    root = input_path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project_invalid")
    if control_mapping is not None and control_run is not None:
        raise ValueError("control_selection_ambiguous")
    detected = detect_dependency_change(input_path)
    candidate = detected.candidate
    state = detected.state
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": str(root),
        "detection": {
            "status": detected.status,
            "reason": detected.reason,
            "rule_id": candidate.rule_id if candidate else None,
            "description": candidate.description if candidate else None,
            "scope": list(candidate.scope) if candidate else [],
            "state_id": state.state_id if state else None,
        },
        "evidence": None,
    }
    if detected.status != "risk":
        return payload

    if control_run is None and control_mapping is None:
        payload["evidence"] = {"status": "unknown", "reason": "control_not_selected",
                               "control_mapping_id": None, "control_run": None, "control_binding": None,
                               "run_ids": [], "artifact_refs": []}
        return payload
    try:
        if control_run is not None:
            control = approved_dep_control_from_run(root, control_run)
        elif control_mapping == MAPPING_ID:
            environment_id = local_environment_id()
            if environment_id is None:
                raise ValueError("environment_unverified")
            control = ApprovedDepControl(root, environment_id)
        else:
            raise ValueError("control_mapping_unapproved")
    except (ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "control_unreadable"
        payload["evidence"] = {"status": "unknown", "reason": reason,
                               "control_mapping_id": control_mapping, "control_run": control_run,
                               "control_binding": None,
                               "run_ids": [], "artifact_refs": []}
        return payload
    decision = match_dep_evidence(root, detected, control)
    payload["evidence"] = {
        "status": decision.status,
        "reason": decision.reason,
        "control_mapping_id": control.mapping_id,
        "control_run": control_run,
        "control_binding": f".agentharness/runs/{control_run}/m3-binding-v0.json" if control_run else None,
        "run_ids": list(decision.run_ids),
        "artifact_refs": [f".agentharness/runs/{run_id}/" for run_id in decision.run_ids],
    }
    return payload
