"""Read-only benchmark bridge: oracle labels never become production evidence."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from agentharness.dep_evidence import ApprovedDepControl, local_environment_id, match_dep_evidence
from agentharness.risk_dep import detect_dependency_change


ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "m3_dep"


def main() -> dict:
    sys.path.insert(0, str(ROOT))
    from validate_dataset import main as validate_dataset

    with contextlib.redirect_stdout(io.StringIO()):
        validate_dataset()  # Manifest, ZIPs, schema and inventory are checked first.
    ledger = json.loads((ROOT / "ledger.json").read_text(encoding="utf-8"))
    rows = []
    expected = {"S": "risk", "N": "no_change", "A": "abstain"}
    with tempfile.TemporaryDirectory(prefix="m3-oracle-bridge-") as temporary:
        for scenario in ledger["scenarios"]:
            with zipfile.ZipFile(ROOT / "fixtures" / f"{scenario['id']}.zip") as archive:
                archive.extractall(Path(temporary) / scenario["id"])
            repo = Path(temporary) / scenario["id"] / "repo"
            kwargs = ({"base_commit": scenario["base_commit"], "target_commit": scenario["target_commit"]}
                      if scenario["state_kind"] == "committed" else {})
            detected = detect_dependency_change(repo, **kwargs)
            if detected.status != expected[scenario["risk_label"]]:
                raise RuntimeError(f"risk label mismatch: {scenario['id']}")
            production = "not_applicable"
            if detected.status == "risk" and scenario["state_kind"] == "working-tree":
                control = ApprovedDepControl(repo, local_environment_id())
                production = match_dep_evidence(repo, detected, control,
                                                now=datetime.fromisoformat(scenario["evaluation_clock_at"])
                                                if scenario.get("evaluation_clock_at") else None).status
                if production == "covered":
                    raise RuntimeError(f"oracle promoted to covered: {scenario['id']}")
            rows.append({"fixture": scenario["id"], "risk_label": scenario["risk_label"],
                         "detected": detected.status, "oracle_evidence_label": scenario["evidence_label"],
                         "oracle_runs": len(scenario["evidence_inventory"]),
                         "production_decision": production})
    return {"schema_version": "m3.cp3d-oracle-bridge.v0", "integrity_validated": True,
            "production_covered_from_oracle": 0, "fixtures": len(rows), "rows": rows}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
