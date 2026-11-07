"""CP3-B evidence tests using the existing explicit check and verify-run path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentharness.dep_evidence import (
    ApprovedDepControl, check_dep_workspace, local_environment_id, match_dep_evidence,
)
from agentharness.direct_check import check_workspace
from agentharness.cli import main as cli_main
from agentharness.risk_dep import detect_dependency_change


FROZEN = Path(__file__).resolve().parents[1] / "benchmarks" / "m3_dep" / "fixtures"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ApprovedDepControl]:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "user.name", "Synthetic")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    (repo / ".gitignore").write_text(".agentharness/\n.pytest_cache/\n__pycache__/\n", encoding="utf-8", newline="\n")
    (repo / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=1"]\n', encoding="utf-8", newline="\n")
    (repo / "tests").mkdir()
    (repo / "tests/test_dep.py").write_text("def test_dep():\n    assert True\n", encoding="utf-8", newline="\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    (repo / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=2"]\n', encoding="utf-8", newline="\n")
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    return repo, ApprovedDepControl(repo, local_environment_id())


def test_missing_evidence_is_uncovered(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    detected = detect_dependency_change(repo)
    assert match_dep_evidence(repo, detected, control).status == "uncovered"


def test_explicit_check_binds_and_covers(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    result = check_dep_workspace(repo, control, run_id="passing")
    assert result.check is not None and result.check.ok
    assert result.binding_path is not None and result.binding_path.is_file(), result.reason
    binding = json.loads(result.binding_path.read_text(encoding="utf-8"))
    assert binding["provenance"] == "local-capture"
    assert binding["state"]["state_id"] == detect_dependency_change(repo).state.state_id
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "covered", decision


def test_failed_check_is_failed(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    (repo / "tests/test_dep.py").write_text("def test_dep():\n    assert False\n", encoding="utf-8", newline="\n")
    result = check_dep_workspace(repo, control, run_id="failing")
    assert result.check is not None and not result.check.ok and result.binding_path is not None
    assert match_dep_evidence(repo, detect_dependency_change(repo), control).status == "failed"


def test_state_change_during_check_prevents_binding(project: tuple[Path, ApprovedDepControl],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    repo, control = project
    from agentharness import dep_evidence
    original = dep_evidence.check_workspace

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        path = repo / "pyproject.toml"
        path.write_text(path.read_text(encoding="utf-8").replace("a>=2", "a>=3"), encoding="utf-8", newline="\n")
        return result

    monkeypatch.setattr(dep_evidence, "check_workspace", changed)
    result = check_dep_workspace(repo, control, run_id="raced")
    assert result.check is not None and result.binding_path is None and result.reason == "state_changed"
    assert match_dep_evidence(repo, detect_dependency_change(repo), control).status != "covered"


def test_changed_state_invalidates_covered(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    assert check_dep_workspace(repo, control, run_id="old").binding_path is not None
    path = repo / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("a>=2", "a>=3"), encoding="utf-8", newline="\n")
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "state_changed"


def test_tampered_run_blocks_covered(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    assert check_dep_workspace(repo, control, run_id="good").binding_path is not None
    bad = check_dep_workspace(repo, control, run_id="tampered")
    assert bad.binding_path is not None
    bad.check.run_path.write_bytes(bad.check.run_path.read_bytes() + b"\n")
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "tampered"


def test_old_failure_does_not_override_current_success(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    (repo / "tests/test_dep.py").write_text("def test_dep():\n    assert False\n", encoding="utf-8", newline="\n")
    assert check_dep_workspace(repo, control, run_id="old-fail").binding_path is not None
    (repo / "tests/test_dep.py").write_text("def test_dep():\n    assert True\n", encoding="utf-8", newline="\n")
    path = repo / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("a>=2", "a>=3"), encoding="utf-8", newline="\n")
    assert check_dep_workspace(repo, control, run_id="new-pass").binding_path is not None
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "covered", decision


def test_expired_and_future_time(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    bound = check_dep_workspace(repo, control, run_id="timed")
    assert bound.binding_path is not None
    payload = json.loads(bound.binding_path.read_text(encoding="utf-8"))
    finished = datetime.fromisoformat(payload["reexecution_finished_at"].replace("Z", "+00:00"))
    detection = detect_dependency_change(repo)
    assert match_dep_evidence(repo, detection, control, now=finished + timedelta(hours=25)).reason == "expired"
    assert match_dep_evidence(repo, detection, control, now=finished - timedelta(minutes=6)).reason == "time"
    assert match_dep_evidence(repo, detection, control, now=finished - timedelta(minutes=2)).status == "covered"
    assert match_dep_evidence(repo, detection, control, now=finished + timedelta(hours=24)).status == "covered"


def test_unapproved_mapping_rejected(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, _ = project
    bad = ApprovedDepControl(repo, local_environment_id(), command="python -m pytest -q tests/test_other.py")
    with pytest.raises(ValueError):
        check_dep_workspace(repo, bad)


def test_cli_opt_in_writes_binding(project: tuple[Path, ApprovedDepControl], capsys: pytest.CaptureFixture[str]) -> None:
    repo, control = project
    code = cli_main(["check", "--workspace", str(repo), "--command", control.command,
                     "--approve-dep-control", "--run-id", "cli-bound", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True
    assert payload["m3_binding_path"] and Path(payload["m3_binding_path"]).is_file()
    assert match_dep_evidence(repo, detect_dependency_change(repo), control).status == "covered"


def test_cli_plain_check_keeps_m2_output(project: tuple[Path, ApprovedDepControl], capsys: pytest.CaptureFixture[str]) -> None:
    repo, control = project
    code = cli_main(["check", "--workspace", str(repo), "--command", control.command,
                     "--run-id", "plain", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True
    assert "m3_binding_path" not in payload
    assert not (repo / ".agentharness/runs/plain/m3-binding-v0.json").exists()


def test_unbound_green_report_is_unknown(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    assert check_workspace(repo, control.command, run_id="m2-only").ok
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "unverified"


def test_unrelated_check_is_uncovered(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    (repo / "tests/test_other.py").write_text("def test_other():\n    assert True\n", encoding="utf-8", newline="\n")
    assert check_workspace(repo, "python -m pytest -q tests/test_other.py", run_id="other").ok
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "uncovered" and decision.reason == "absent"


def test_tampered_output_is_unknown(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    bound = check_dep_workspace(repo, control, run_id="stdout-tampered")
    assert bound.binding_path is not None
    report = json.loads(bound.check.report_path.read_text(encoding="utf-8"))
    output = Path(report["results"][0]["audit"]["commands"][0]["reexecution"]["stdout_path"])
    output.write_bytes(output.read_bytes() + b"changed")
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "tampered"


def test_traversal_in_binding_is_not_read(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    bound = check_dep_workspace(repo, control, run_id="traversal")
    assert bound.binding_path is not None
    payload = json.loads(bound.binding_path.read_text(encoding="utf-8"))
    first = ".agentharness/runs/traversal/run.json"
    payload["artifact_sha256"][".agentharness/runs/traversal/../outside"] = payload["artifact_sha256"].pop(first)
    bound.binding_path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason in {"unsafe_path", "tampered"}


def test_large_artifact_is_unknown_budget(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    bound = check_dep_workspace(repo, control, run_id="large")
    assert bound.binding_path is not None
    bound.check.run_path.write_bytes(b" " * (1024 * 1024 + 1))
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "budget"


def test_timeout_is_unknown_not_failed(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    (repo / "tests/test_dep.py").write_text("import time\ndef test_dep():\n    time.sleep(3)\n", encoding="utf-8", newline="\n")
    bound = check_dep_workspace(repo, control, run_id="timeout", timeout_seconds=1)
    assert bound.binding_path is not None and not bound.check.ok
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "unverified"


def test_conflicting_valid_runs_are_unknown(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    external = repo.parent / "external-test-result.txt"
    source = f"from pathlib import Path\ndef test_dep():\n    assert Path({str(external)!r}).read_text().strip() == 'pass'\n"
    (repo / "tests/test_dep.py").write_text(source, encoding="utf-8", newline="\n")
    external.write_text("pass", encoding="utf-8")
    first = check_dep_workspace(repo, control, run_id="pass")
    assert first.binding_path is not None and first.check.ok
    external.write_text("fail", encoding="utf-8")
    second = check_dep_workspace(repo, control, run_id="fail")
    assert second.binding_path is not None and not second.check.ok
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "contradictory"


def test_run_directory_budget_fails_open(project: tuple[Path, ApprovedDepControl]) -> None:
    repo, control = project
    runs = repo / ".agentharness/runs"
    for number in range(129):
        (runs / f"empty-{number:03}").mkdir(parents=True)
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "budget"


def test_state_change_during_matching_is_unknown(project: tuple[Path, ApprovedDepControl],
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    repo, control = project
    assert check_dep_workspace(repo, control, run_id="current").binding_path is not None
    from agentharness import dep_evidence
    original = dep_evidence._candidate

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        path = repo / "pyproject.toml"
        path.write_text(path.read_text(encoding="utf-8").replace("a>=2", "a>=3"), encoding="utf-8", newline="\n")
        return result

    monkeypatch.setattr(dep_evidence, "_candidate", changed)
    decision = match_dep_evidence(repo, detect_dependency_change(repo), control)
    assert decision.status == "unknown" and decision.reason == "state_changed"


@pytest.mark.parametrize("number", (3, 25, 26, 27, 28, 29, 32, 33, 35, 37))
def test_frozen_oracle_artifacts_never_become_local_covered(number: int, tmp_path: Path) -> None:
    with zipfile.ZipFile(FROZEN / f"D{number:02}.zip") as archive:
        archive.extractall(tmp_path)
    repo = tmp_path / "repo"
    detection = detect_dependency_change(repo)
    assert detection.status == "risk"
    control = ApprovedDepControl(repo, "synthetic-python-pytest-v0")
    decision = match_dep_evidence(repo, detection, control)
    assert decision.status != "covered", (number, decision)
