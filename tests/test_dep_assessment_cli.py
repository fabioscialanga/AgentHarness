"""The DEP consultation reads existing evidence but never runs a check."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentharness.cli import main as cli_main
from agentharness.dep_evidence import ApprovedDepControl, check_dep_workspace, local_environment_id


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "Synthetic"),
                 ("config", "user.email", "synthetic@example.invalid"),
                 ("config", "core.autocrlf", "false")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / ".gitignore").write_text(".agentharness/\n.pytest_cache/\n__pycache__/\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=1"]\n', encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/test_dep.py").write_text("def test_dep():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True, capture_output=True)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    return root


def _risk(root: Path) -> None:
    (root / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=2"]\n', encoding="utf-8")


def _bind(root: Path, run_id: str) -> Path:
    result = check_dep_workspace(root, ApprovedDepControl(root, local_environment_id()), run_id=run_id)
    assert result.binding_path is not None, result.reason
    return result.binding_path


def test_no_control_never_claims_covered(project: Path, capsys: pytest.CaptureFixture[str],
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from agentharness import dep_assessment
    _risk(project)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("matcher called without selected approved control")

    monkeypatch.setattr(dep_assessment, "match_dep_evidence", forbidden)
    assert cli_main(["dep-assess", "--project", str(project), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "m3.dep-assess.v0"
    assert result["detection"]["status"] == "risk"
    assert result["evidence"]["status"] == "unknown"
    assert result["evidence"]["reason"] == "control_not_selected"
    assert not (project / ".agentharness/runs").exists()


def test_selected_fixed_mapping_without_evidence_is_uncovered(project: Path,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    _risk(project)
    assert cli_main(["dep-assess", "--project", str(project), "--control", "DEP-PEP621-PYTEST-V0", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["detection"]["status"] == "risk"
    assert result["evidence"]["status"] == "uncovered"
    assert result["evidence"]["reason"] == "absent"
    assert result["evidence"]["control_mapping_id"] == "DEP-PEP621-PYTEST-V0"
    assert not (project / ".agentharness/runs").exists()


def test_consultation_makes_no_reexecution_or_network_call(project: Path, capsys: pytest.CaptureFixture[str],
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    from agentharness import reexecution
    _risk(project)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("unexpected execution or network call")

    monkeypatch.setattr(reexecution, "reexecute_command", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert cli_main(["dep-assess", "--project", str(project), "--control", "DEP-PEP621-PYTEST-V0", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evidence"]["status"] == "uncovered"


def test_unapproved_mapping_cannot_cover(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _risk(project)
    assert cli_main(["dep-assess", "--project", str(project), "--control", "DEP-OTHER", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evidence"]["status"] == "unknown"
    assert result["evidence"]["reason"] == "control_mapping_unapproved"


def test_no_change_and_abstain_skip_evidence(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=1.0"]\n', encoding="utf-8")
    assert cli_main(["dep-assess", "--project", str(project), "--json"]) == 0
    no_change = json.loads(capsys.readouterr().out)
    assert no_change["detection"]["status"] == "no_change" and no_change["evidence"] is None
    (project / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=1"]\n', encoding="utf-8")
    assert cli_main(["dep-assess", "--project", str(project), "--json"]) == 0
    abstain = json.loads(capsys.readouterr().out)
    assert abstain["detection"]["status"] == "abstain" and abstain["evidence"] is None


def test_selected_local_binding_is_covered_read_only(project: Path, capsys: pytest.CaptureFixture[str],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from agentharness import dep_evidence
    _risk(project)
    binding = _bind(project, "approved")
    before = {p.relative_to(project).as_posix(): p.read_bytes() for p in (project / ".agentharness/runs").rglob("*") if p.is_file()}

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("check executed by dep-assess")

    monkeypatch.setattr(dep_evidence, "check_workspace", forbidden)
    assert cli_main(["dep-assess", "--project", str(project), "--control-run", "approved", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["detection"]["status"] == "risk"
    assert result["evidence"]["status"] == "covered"
    assert result["evidence"]["control_binding"] == ".agentharness/runs/approved/m3-binding-v0.json"
    assert result["evidence"]["artifact_refs"] == [".agentharness/runs/approved/"]
    after = {p.relative_to(project).as_posix(): p.read_bytes() for p in (project / ".agentharness/runs").rglob("*") if p.is_file()}
    assert before == after and binding.is_file()
    assert cli_main(["dep-assess", "--project", str(project), "--control-run", "approved"]) == 0
    text = capsys.readouterr().out
    assert "DEP detection: risk" in text and "DEP evidence: covered" in text
    assert "dependency safety is not established" in text


def test_unapproved_or_malformed_binding_is_unknown(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _risk(project)
    binding = _bind(project, "candidate")
    payload = json.loads(binding.read_text(encoding="utf-8"))
    payload["provenance"] = "benchmark-oracle"
    binding.write_text(json.dumps(payload), encoding="utf-8")
    assert cli_main(["dep-assess", "--project", str(project), "--control-run", "candidate", "--json"]) == 0
    oracle = json.loads(capsys.readouterr().out)
    assert oracle["evidence"]["status"] == "unknown" and oracle["evidence"]["reason"] == "control_binding_unapproved"
    binding.write_text("{malformed", encoding="utf-8")
    assert cli_main(["dep-assess", "--project", str(project), "--control-run", "candidate", "--json"]) == 0
    malformed = json.loads(capsys.readouterr().out)
    assert malformed["evidence"]["status"] == "unknown"
    assert malformed["evidence"]["reason"].startswith("control_binding_")
    binding.write_bytes(b"x" * (1024 * 1024 + 1))
    assert cli_main(["dep-assess", "--project", str(project), "--control-run", "candidate", "--json"]) == 0
    oversized = json.loads(capsys.readouterr().out)
    assert oversized["evidence"]["status"] == "unknown"
    assert oversized["evidence"]["reason"] == "control_binding_budget"


def test_failed_and_tampered_evidence_are_distinct(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _risk(project)
    test_file = project / "tests/test_dep.py"
    test_file.write_text("def test_dep():\n    assert False\n", encoding="utf-8")
    _bind(project, "failed")
    assert cli_main(["dep-assess", "--project", str(project), "--control", "DEP-PEP621-PYTEST-V0", "--json"]) == 0
    failed = json.loads(capsys.readouterr().out)
    assert failed["evidence"]["status"] == "failed"
    assert failed["evidence"]["artifact_refs"] == [".agentharness/runs/failed/"]

    report = json.loads((project / ".agentharness/runs/failed/verify-report.json").read_text(encoding="utf-8"))
    execution = report["results"][0]["audit"]["commands"][0]["reexecution"]
    stdout = Path(execution["stdout_path"])
    stdout.write_bytes(stdout.read_bytes() + b"tampered\n")
    assert cli_main(["dep-assess", "--project", str(project), "--control", "DEP-PEP621-PYTEST-V0", "--json"]) == 0
    tampered = json.loads(capsys.readouterr().out)
    assert tampered["evidence"]["status"] == "unknown"
    assert tampered["evidence"]["reason"] == "tampered"


def test_invalid_control_run_is_unknown(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _risk(project)
    assert cli_main(["dep-assess", "--project", str(project), "--control-run", "../other", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evidence"]["status"] == "unknown" and result["evidence"]["reason"] == "control_run_invalid"


def test_subprocess_cli_end_to_end(project: Path) -> None:
    _risk(project)
    _bind(project, "e2e")
    runs = project / ".agentharness/runs"
    before = sorted(p.relative_to(runs).as_posix() for p in runs.rglob("*"))
    completed = subprocess.run([sys.executable, "-m", "agentharness", "dep-assess", "--project", str(project),
                                "--control-run", "e2e", "--json"], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["detection"]["status"] == "risk" and result["evidence"]["status"] == "covered"
    assert sorted(p.relative_to(runs).as_posix() for p in runs.rglob("*")) == before
