"""Create the frozen, synthetic M3 DEP benchmark. Never called by an AgentHarness hook.

This is dataset preparation, not a detector or evidence matcher. It deliberately
invokes the existing check command only for the scenarios that require an artifact.
Run it explicitly in an isolated development environment with pytest installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentharness.direct_check import check_workspace


HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
COMMAND = "python -m pytest -q tests/test_dep.py"
OTHER_COMMAND = "python -m pytest -q tests/test_other.py"
BASE_DEP = '  "requests>=2,<3",\n  "urllib3>=1,<3",'
BASE = f'''[project]
name = "fixture-project"
version = "0.1.0"
description = "Synthetic DEP fixture"
dependencies = [
{BASE_DEP}
]

[project.optional-dependencies]
dev = ["pytest>=8,<9"]
'''
PASS_TEST = "def test_dependency_smoke():\n    assert True\n"
FAIL_TEST = "def test_dependency_smoke():\n    assert False, 'synthetic failure'\n"
SLEEP_TEST = "import time\ndef test_dependency_smoke():\n    time.sleep(3)\n"
OTHER_TEST = "def test_unrelated():\n    assert True\n"
LABELS = {
    1: ("S", "U"), 2: ("S", "C"), 3: ("S", "?"), 4: ("S", "F"),
    5: ("N", "—"), 6: ("N", "—"), 7: ("S", "U"), 8: ("S", "?"),
    9: ("A", "?"), 10: ("S", "U"), 11: ("S", "C"), 12: ("A", "?"),
    13: ("N", "—"), 14: ("N", "—"), 15: ("N", "—"), 16: ("N", "—"),
    17: ("N", "—"), 18: ("S", "U"), 19: ("S", "C"), 20: ("A", "?"),
    21: ("A", "?"), 22: ("A", "?"), 23: ("A", "?"), 24: ("A", "?"),
    25: ("S", "?"), 26: ("S", "?"), 27: ("S", "?"), 28: ("S", "?"),
    29: ("S", "?"), 30: ("S", "U"), 31: ("S", "C"), 32: ("S", "?"),
    33: ("S", "?"), 34: ("A", "?"), 35: ("S", "?"), 36: ("S", "F"),
    37: ("S", "C"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return sha(path.read_bytes())


def run(*args: str, cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, encoding="utf-8")
    return proc.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run("git", *args, cwd=repo)


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def repo_init(repo: Path, number: int) -> str:
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture Builder")
    git(repo, "config", "user.email", "fixture@example.invalid")
    write(repo / ".gitignore", ".agentharness/\n.pytest_cache/\n__pycache__/\nscenario.diff\nscenario.json\n")
    write(repo / "tests/test_dep.py", PASS_TEST)
    write(repo / "tests/test_other.py", OTHER_TEST)
    if number != 10:
        write(repo / "pyproject.toml", BASE)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Synthetic baseline")
    return git(repo, "rev-parse", "HEAD")


def altered(number: int) -> str:
    if number == 5:
        return BASE.replace(BASE_DEP, '  "urllib3>=1,<3",\n  "requests>=2,<3",')
    if number == 6:
        return BASE.replace("dependencies = [", "# dependency list\ndependencies = [  # formatting only")
    if number == 7:
        return BASE.replace('dev = ["pytest>=8,<9"]', 'dev = ["pytest>=8,<9", "ruff>=0.7"]')
    if number in {8, 19}:
        return BASE.replace('dev = ["pytest>=8,<9"]', 'dev = ["pytest>=8,<10"]')
    if number == 9:
        return BASE.replace('"requests>=2,<3",', '"requests>=2,<3", broken-token')
    if number == 10:
        return BASE
    if number == 13:
        return BASE.replace('"requests>=2,<3"', '"ReQuEsTs>=2,<3"')
    if number == 14:
        return BASE.replace('"requests>=2,<3"', '"requests[PDF,cli]>=2,<3"')
    if number == 15:
        return BASE.replace('"requests>=2,<3"', '"requests<3,>=2"')
    if number == 16:
        return BASE.replace('"requests>=2,<3"', '"requests>=2.0,<3.0"')
    if number == 17:
        return BASE.replace("Synthetic DEP fixture", "Edited description")
    if number == 18:
        return BASE.replace('  "urllib3>=1,<3",\n', "")
    if number == 20:
        return BASE.replace('"requests>=2,<3"', '"requests>=2,<3; python_version >= \'3.11\'"')
    if number == 21:
        return BASE.replace('"requests>=2,<3"', '"requests @ https://example.invalid/requests.whl"')
    if number == 22:
        return BASE.replace('"requests>=2,<3"', '"requests~=2.31"')
    if number == 23:
        return BASE + 'dynamic = ["dependencies"]\n'
    if number == 24:
        return BASE.replace('  "urllib3>=1,<3",', '  "requests<2",\n  "urllib3>=1,<3",')
    if number == 34:
        return BASE.replace('"requests>=2,<3"', '"requests>=1!2.0rc1,<3"')
    return BASE.replace('"requests>=2,<3"', '"requests>=2.32,<3"')


def report_for(result) -> dict:
    return json.loads(result.report_path.read_text(encoding="utf-8"))


def check(repo: Path, name: str, command: str = COMMAND, timeout: int = 15):
    return check_workspace(repo, command, run_id=name, timeout_seconds=timeout)


def artifact_files(repo: Path) -> list[Path]:
    return sorted(p for p in (repo / ".agentharness").rglob("*") if p.is_file())


def snapshot_digest(repo: Path, run_id: str) -> str:
    snap = repo / ".agentharness/runs" / run_id / "workspace"
    entries = [f"{p.relative_to(snap).as_posix()}\0{digest(p)}" for p in sorted(snap.rglob("*")) if p.is_file()]
    return sha("\n".join(entries).encode())


def binding(repo: Path, scenario: dict, result, *, state_digest: str, clock: datetime) -> None:
    # Offline benchmark oracle. Production M3 must capture these fields itself.
    report = report_for(result)
    reexecution = report.get("results", [{}])[0].get("audit", {}).get("commands", [{}])[0].get("reexecution", {})
    files = {}
    for path in artifact_files(repo):
        if path.name == "m3-binding-v0.json":
            continue
        files[path.relative_to(repo).as_posix()] = digest(path)
    payload = {
        "schema_version": "m3.binding.v0", "provenance": "benchmark-oracle",
        "risk_id": "dep-pep621-dependency-change", "rule_id": "DEP-PEP621-V0",
        "run_id": result.run_id,
        "state": {"base_commit": scenario["base_commit"], "target_commit": scenario["target_commit"],
                  "diff_sha256": state_digest, "state_id": sha((scenario["target_commit"] + state_digest).encode()),
                  "kind": scenario["state_kind"]},
        "scope": {"risk_paths": ["pyproject.toml"], "evidence_paths": ["pyproject.toml", "tests/test_dep.py"]},
        "check": {"mapping_id": "DEP-PEP621-PYTEST-V0", "command": result.command,
                  "cwd": ".", "environment_id": "synthetic-python-pytest-v0"},
        "snapshot_sha256": snapshot_digest(repo, result.run_id),
        "artifact_sha256": files,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "evaluated_at": clock.isoformat(),
        "reexecution_finished_at": reexecution.get("finished_at"),
    }
    write(result.artifact_dir / "m3-binding-v0.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")


def diff_bytes(repo: Path, base: str, target: str, kind: str) -> bytes:
    if kind == "committed":
        return subprocess.check_output(["git", "diff", "--binary", base, target], cwd=repo)
    patch = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=repo)
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    for name in sorted(untracked):
        data = (repo / name).read_bytes()
        patch += b"\nUNTRACKED\0" + name.encode() + b"\0" + len(data).to_bytes(8, "big") + data
    return patch


def make_one(root: Path, number: int) -> dict:
    ident = f"D{number:02d}"
    repo = root / ident
    base_commit = repo_init(repo, number)
    old = None
    if number in {3, 31}:
        if number == 31:
            write(repo / "tests/test_dep.py", FAIL_TEST)
        old = check(repo, ident + "-old")
    write(repo / "pyproject.toml", altered(number))
    if number == 14:
        # The baseline contains the same extras in opposite order.
        git(repo, "show", "HEAD:pyproject.toml")
        base_text = BASE.replace('"requests>=2,<3"', '"requests[cli,pdf]>=2,<3"')
        write(repo / "pyproject.toml", base_text)
        git(repo, "add", "pyproject.toml")
        git(repo, "commit", "-qm", "Extras baseline")
        base_commit = git(repo, "rev-parse", "HEAD")
        write(repo / "pyproject.toml", altered(number))
    if number == 16:
        baseline = BASE.replace('"requests>=2,<3"', '"requests==1.0"')
        write(repo / "pyproject.toml", baseline)
        git(repo, "add", "pyproject.toml")
        git(repo, "commit", "-qm", "Exact version baseline")
        base_commit = git(repo, "rev-parse", "HEAD")
        write(repo / "pyproject.toml", baseline.replace("==1.0", "==1.0.0"))
    if number == 23:
        write(repo / "pyproject.toml", BASE.replace("[project.optional-dependencies]", 'dynamic = ["dependencies"]\n\n[project.optional-dependencies]'))
    if number in {4, 36}:
        write(repo / "tests/test_dep.py", FAIL_TEST)
    if number == 31:
        write(repo / "tests/test_dep.py", PASS_TEST)
    if number == 33:
        write(repo / "tests/test_dep.py", SLEEP_TEST)
    if number in {11, 12}:
        git(repo, "add", "pyproject.toml")
        git(repo, "commit", "-qm", "Dependency change")
    target_commit = git(repo, "rev-parse", "HEAD")
    kind = "committed" if number in {11, 12} else "working-tree"
    patch = diff_bytes(repo, base_commit, target_commit, kind)
    patch_path = repo / "scenario.diff"
    patch_path.write_bytes(patch)
    state_digest = sha(patch)
    binding_digest = state_digest
    scenario = {
        "id": ident, "risk_label": LABELS[number][0], "evidence_label": LABELS[number][1],
        "base_commit": None if number == 12 else base_commit, "target_commit": target_commit,
        "state_kind": kind, "diff_sha256": state_digest,
        "approved_mapping_id": "DEP-PEP621-PYTEST-V0",
        "notes": [],
    }
    current = None
    if number == 29:
        control = Path(tempfile.gettempdir()) / "agentharness-m3-d29-control.txt"
        write(repo / "tests/test_dep.py", "from pathlib import Path\nimport tempfile\ndef test_dependency_smoke():\n    assert (Path(tempfile.gettempdir()) / 'agentharness-m3-d29-control.txt').read_text().strip() == 'pass'\n")
        control.write_text("pass", encoding="utf-8")
        patch = diff_bytes(repo, base_commit, target_commit, kind)
        patch_path.write_bytes(patch)
        state_digest = sha(patch)
        binding_digest = state_digest
        scenario["diff_sha256"] = state_digest
    if number in {2, 4, 8, 11, 19, 25, 26, 27, 28, 30, 31, 32, 33, 35, 36, 37}:
        command = OTHER_COMMAND if number in {8, 30} else COMMAND
        current = check(repo, ident + "-current", command, 1 if number == 33 else 15)
    if number in {25, 32}:
        bad = current if number == 25 else check(repo, ident + "-tampered")
        bad.run_path.write_text(bad.run_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        scenario["notes"].append("run.json mutated after verify-run")
    if number == 26:
        report = report_for(current)
        items = report.get("results", [{}])[0].get("audit", {}).get("commands", [{}])[0].get("reexecution", {})
        for key in ("stdout_path", "stdout_file"):
            if isinstance(items.get(key), str):
                candidate = Path(items[key])
                if candidate.is_file():
                    candidate.write_bytes(candidate.read_bytes() + b"\nTAMPERED\n")
                    break
        else:
            scenario["notes"].append("stdout path unavailable; digest field deliberately mutated")
            text = current.report_path.read_text(encoding="utf-8")
            current.report_path.write_text(text.replace("sha256", "sha25X", 1), encoding="utf-8")
    if number == 28:
        binding_digest = state_digest
        write(repo / "tests/test_other.py", OTHER_TEST + "\n# changed after check\n")
        patch = diff_bytes(repo, base_commit, target_commit, kind)
        patch_path.write_bytes(patch)
        state_digest = sha(patch)
        scenario["diff_sha256"] = state_digest
        scenario["notes"].append("working tree changed after execution; binding is intentionally prechange")
    if number == 29:
        # Same repo state and command, but an external input changes. The omitted
        # input is a deliberate environment-binding limit, documented in the ledger.
        first = check(repo, ident + "-pass")
        control.write_text("fail", encoding="utf-8")
        second = check(repo, ident + "-fail")
        control.unlink()
        scenario["notes"].append("opposite outcomes via omitted external environment input; neither run may be promoted to covered")
        current = first
    if number == 36:
        check(repo, ident + "-other-pass", OTHER_COMMAND)
    clock = datetime.now(timezone.utc)
    if current:
        report = report_for(current)
        finished = report.get("results", [{}])[0].get("audit", {}).get("commands", [{}])[0].get("reexecution", {}).get("finished_at")
        try:
            finish_time = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            finish_time = clock
        if number == 27:
            clock = finish_time + timedelta(hours=25)
            report["evaluated_at"] = clock.isoformat()
            write(current.report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
        elif number == 35:
            clock = finish_time - timedelta(minutes=6)
        elif number == 37:
            clock = finish_time - timedelta(minutes=2)
        scenario["evaluation_clock_at"] = clock.isoformat()
        if number not in {8, 30}:
            binding(repo, scenario, current, state_digest=binding_digest, clock=clock)
    if number == 3 and old:
        scenario["notes"].append("artifact pre-dates dependency diff")
    write(repo / "scenario.json", json.dumps(scenario, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return scenario


def archive(repo: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(repo.rglob("*")):
            if not path.is_file() or any(part in {"__pycache__", ".pytest_cache"} for part in path.relative_to(repo).parts):
                continue
            zf.write(path, "repo/" + path.relative_to(repo).as_posix())


def evidence_inventory(repo: Path) -> list[dict]:
    inventory = []
    runs = repo / ".agentharness" / "runs"
    if not runs.exists():
        return inventory
    for path in sorted(runs.iterdir()):
        report_path = path / "verify-report.json"
        if not report_path.is_file():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        result = report.get("results", [{}])[0]
        execution = result.get("audit", {}).get("commands", [{}])[0].get("reexecution", {})
        inventory.append({
            "run_id": path.name, "command": execution.get("command"),
            "report_ok": report.get("ok"), "claim_status": result.get("status"),
            "truth_source": result.get("truth_source"), "exit_code": execution.get("exit_code"),
            "timed_out": execution.get("timed_out"), "finished_at": execution.get("finished_at"),
            "binding_present": (path / "m3-binding-v0.json").is_file(),
            "artifact_sha256": {
                p.relative_to(repo).as_posix(): digest(p)
                for p in sorted(path.rglob("*")) if p.is_file() and "workspace" not in p.relative_to(path).parts
            },
        })
    return inventory


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--manifest-only":
        freeze_manifest()
        return
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    if any(FIXTURES.iterdir()):
        raise SystemExit("fixtures directory is not empty; frozen data must not be overwritten")
    ledger = []
    with tempfile.TemporaryDirectory(prefix=".build-", dir=HERE) as temp:
        root = Path(temp)
        for number in range(1, 38):
            scenario = make_one(root, number)
            scenario["evidence_inventory"] = evidence_inventory(root / scenario["id"])
            zip_path = FIXTURES / (scenario["id"] + ".zip")
            archive(root / scenario["id"], zip_path)
            scenario["fixture_sha256"] = digest(zip_path)
            ledger.append(scenario)
            print(scenario["id"], scenario["risk_label"], scenario["evidence_label"], flush=True)
    write(HERE / "ledger.json", json.dumps({"schema_version": "m3.dep-ledger.v0", "scenarios": ledger}, indent=2,
                                            ensure_ascii=False, sort_keys=True) + "\n")
    freeze_manifest()


def freeze_manifest() -> None:
    manifest_paths = [HERE / ".gitattributes", HERE / "ledger.json", HERE / "m3-binding-v0.schema.json", HERE / "build_fixtures.py",
                      HERE / "validate_dataset.py", *sorted(FIXTURES.glob("*.zip"))]
    write(HERE / "MANIFEST.sha256", "".join(f"{digest(p)}  {p.relative_to(HERE).as_posix()}\n" for p in manifest_paths))


if __name__ == "__main__":
    main()
