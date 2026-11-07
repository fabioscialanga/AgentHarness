"""Read-only integrity validation for the frozen M3 DEP dataset (not a matcher)."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    ledger = json.loads((ROOT / "ledger.json").read_text(encoding="utf-8"))
    scenarios = ledger["scenarios"]
    assert len(scenarios) == 37
    assert [x["id"] for x in scenarios] == [f"D{n:02}" for n in range(1, 38)]
    manifest = (ROOT / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    assert len(manifest) == 42  # attributes, generator, validator, schema, ledger, 37 ZIPs
    for line in manifest:
        expected, relative = line.split("  ", 1)
        assert digest((ROOT / relative).read_bytes()) == expected, relative
    stats: dict[str, int] = {}
    for scenario in scenarios:
        ident = scenario["id"]
        path = ROOT / "fixtures" / f"{ident}.zip"
        assert digest(path.read_bytes()) == scenario["fixture_sha256"]
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            names = archive.namelist()
            assert "repo/.git/HEAD" in names
            assert "repo/scenario.diff" in names
            assert "repo/scenario.json" in names
            assert "repo/pyproject.toml" in names
            assert digest(archive.read("repo/scenario.diff")) == scenario["diff_sha256"]
            embedded = json.loads(archive.read("repo/scenario.json"))
            for key in ("id", "risk_label", "evidence_label", "base_commit", "target_commit", "diff_sha256"):
                assert embedded[key] == scenario[key], (ident, key)
            for evidence in scenario["evidence_inventory"]:
                run = evidence["run_id"]
                for relative, expected in evidence["artifact_sha256"].items():
                    assert digest(archive.read("repo/" + relative)) == expected, (ident, relative)
                if evidence["binding_present"]:
                    binding = json.loads(archive.read(f"repo/.agentharness/runs/{run}/m3-binding-v0.json"))
                    assert binding["schema_version"] == "m3.binding.v0"
                    assert binding["provenance"] == "benchmark-oracle"
                    assert binding["run_id"] == run
                    if ident == "D28":
                        assert binding["state"]["diff_sha256"] != scenario["diff_sha256"]
                    else:
                        assert binding["state"]["diff_sha256"] == scenario["diff_sha256"]
            def result(run: str) -> tuple[dict, dict]:
                report = json.loads(archive.read(f"repo/.agentharness/runs/{run}/verify-report.json"))
                execution = report["results"][0]["audit"]["commands"][0]["reexecution"]
                return report, execution

            if ident in {"D25", "D32"}:
                run = "D25-current" if ident == "D25" else "D32-tampered"
                report, _ = result(run)
                assert digest(archive.read(f"repo/.agentharness/runs/{run}/run.json")) != report["run_sha256"]
            if ident == "D26":
                _, execution = result("D26-current")
                suffix = Path(execution["stdout_path"]).name
                matches = [x for x in names if x.endswith("/" + suffix)]
                assert len(matches) == 1
                assert digest(archive.read(matches[0])) != execution["stdout_sha256"]
            if ident in {"D27", "D35", "D37"}:
                _, execution = result(f"{ident}-current")
                clock = datetime.fromisoformat(scenario["evaluation_clock_at"])
                finished = datetime.fromisoformat(execution["finished_at"].replace("Z", "+00:00"))
                age = (clock - finished).total_seconds()
                if ident == "D27":
                    assert age > 24 * 3600
                elif ident == "D35":
                    assert age < -5 * 60
                else:
                    assert -5 * 60 <= age < 0
            if ident == "D29":
                pass_report, pass_execution = result("D29-pass")
                fail_report, fail_execution = result("D29-fail")
                assert pass_report["ok"] and pass_execution["exit_code"] == 0
                assert not fail_report["ok"] and fail_execution["exit_code"] != 0
            if ident == "D33":
                report, execution = result("D33-current")
                assert not report["ok"] and execution["timed_out"] and execution["exit_code"] is None
            # Filename and content check for credentials, env files and personal paths.
            for name in names:
                assert not re.search(r"(^|/)(\.env|id_rsa|credentials)(/|$)", name, re.I), (ident, name)
                if name.endswith((".json", ".toml", ".py", ".diff", ".txt", ".stdout", ".stderr")):
                    data = archive.read(name)
                    assert b"C:\\Users\\" not in data and b"/home/" not in data, (ident, name)
        key = scenario["risk_label"] + "/" + scenario["evidence_label"]
        stats[key] = stats.get(key, 0) + 1
    print("VALID: 37 fixture; manifest, ZIP CRC, diff, artifact hash, label e path sensibili coerenti")
    print("Label:", ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    for ident in ("D02", "D04", "D19", "D29", "D31", "D33", "D36", "D37"):
        row = next(x for x in scenarios if x["id"] == ident)
        print(ident, [(r["run_id"], r["report_ok"], r["claim_status"], r["exit_code"], r["timed_out"])
                      for r in row["evidence_inventory"]])


if __name__ == "__main__":
    main()
