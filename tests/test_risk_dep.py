"""M3 CP3-A detection tests. The frozen fixtures are never rewritten."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from agentharness.risk_dep import detect_dependency_change, normalize_requirement


FIXTURES = Path(__file__).resolve().parents[1] / "benchmarks" / "m3_dep" / "fixtures"
EXPECTED = {"S": "risk", "N": "no_change", "A": "abstain"}


@pytest.mark.parametrize("number", range(1, 38))
def test_frozen_dep_detection(number: int, tmp_path: Path) -> None:
    archive_path = FIXTURES / f"D{number:02}.zip"
    with zipfile.ZipFile(archive_path) as archive:
        assert all(name.startswith("repo/") and ".." not in Path(name).parts for name in archive.namelist())
        archive.extractall(tmp_path)
    repo = tmp_path / "repo"
    scenario = json.loads((repo / "scenario.json").read_text(encoding="utf-8"))
    if scenario["state_kind"] == "committed":
        result = detect_dependency_change(repo, base_commit=scenario["base_commit"], target_commit=scenario["target_commit"])
    else:
        result = detect_dependency_change(repo)
    assert result.status == EXPECTED[scenario["risk_label"]], (number, result)
    if result.status == "risk":
        assert result.candidate is not None
        assert result.candidate.rule_id == "DEP-PEP621-V0"
        assert result.candidate.scope == ("pyproject.toml",)
        assert result.state is not None and len(result.state.state_id) == 64
    else:
        assert result.candidate is None
    if number == 12:
        assert result.reason == "explicit_range_required"


@pytest.mark.parametrize("left,right", [
    ("My_Pkg==1.0", "my-pkg==1.0.0"),
    ("requests[PDF,cli]>=2,<3", "requests[cli,pdf]<3.0,>=2.0"),
    ("requests>=1,<2,>=1", "requests<2,>=1"),
])
def test_supported_equivalences(left: str, right: str) -> None:
    assert normalize_requirement(left) == normalize_requirement(right)


@pytest.mark.parametrize("item", [
    "requests; python_version >= '3.11'", "requests @ https://example.invalid/a.whl",
    "requests~=2.3", "requests==1.0rc1", "requests==1!2", "requests==1.*",
    "requests===2", "requests[bad extra]>=2",
])
def test_unsupported_syntax_abstains(item: str) -> None:
    with pytest.raises(ValueError):
        normalize_requirement(item)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["a>=1"]\n', encoding="utf-8")
    _git(repo, "add", "pyproject.toml")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def test_state_identity_is_stable_and_changes_with_staging(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = repo / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("a>=1", "a>=2"), encoding="utf-8")
    first = detect_dependency_change(repo)
    second = detect_dependency_change(repo)
    assert first.status == second.status == "risk"
    assert first.state == second.state
    _git(repo, "add", "pyproject.toml")
    staged = detect_dependency_change(repo)
    assert staged.status == "risk"
    assert staged.state.state_id != first.state.state_id
    path.write_text(path.read_text(encoding="utf-8").replace("a>=2", "a>=3"), encoding="utf-8")
    unstaged = detect_dependency_change(repo)
    assert unstaged.state.state_id not in {first.state.state_id, staged.state.state_id}


def test_other_tracked_change_is_no_dep_change_but_changes_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    other = repo / "tests.txt"
    other.write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "tests.txt")
    _git(repo, "commit", "-qm", "add test input")
    other.write_text("updated\n", encoding="utf-8")
    first = detect_dependency_change(repo)
    assert first.status == "no_change"
    other.write_text("updated again\n", encoding="utf-8")
    second = detect_dependency_change(repo)
    assert second.status == "no_change"
    assert first.state.state_id != second.state.state_id


def test_untracked_pyproject_is_risk(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "rm", "-q", "pyproject.toml")
    _git(repo, "commit", "-qm", "remove pyproject")
    (repo / "pyproject.toml").write_text('[project]\ndependencies=["b>=1"]\n', encoding="utf-8")
    result = detect_dependency_change(repo)
    assert result.status == "risk"


def test_empty_optional_group_addition_is_detected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = repo / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8") + "\n[project.optional-dependencies]\ndev=[]\n", encoding="utf-8")
    assert detect_dependency_change(repo).status == "risk"


def test_oversized_pyproject_abstains(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_bytes(b" " * (1024 * 1024 + 1))
    result = detect_dependency_change(repo)
    assert result.status == "abstain" and result.reason == "file_budget"


def test_symlink_pyproject_abstains_where_supported(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = tmp_path / "outside.toml"
    target.write_text('[project]\ndependencies=["x>=1"]\n', encoding="utf-8")
    (repo / "pyproject.toml").unlink()
    try:
        (repo / "pyproject.toml").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = detect_dependency_change(repo)
    assert result.status == "abstain" and result.reason == "symlink"


def test_git_error_abstains(tmp_path: Path) -> None:
    result = detect_dependency_change(tmp_path)
    assert result.status == "abstain" and result.reason == "git_invalid"


def test_git_timeout_abstains(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    original = subprocess.Popen
    def slow(_args: object, **kwargs: object):
        return original([sys.executable, "-c", "import time; time.sleep(2)"], **kwargs)
    monkeypatch.setattr("agentharness.risk_dep.subprocess.Popen", slow)
    monkeypatch.setattr("agentharness.risk_dep.GIT_TIMEOUT_SECONDS", 0.03)
    result = detect_dependency_change(repo)
    assert result.status == "abstain" and result.reason == "git_timeout"


def test_git_output_is_stopped_at_byte_limit(tmp_path: Path) -> None:
    from agentharness import risk_dep
    repo = _repo(tmp_path)
    with pytest.raises(risk_dep._Abstain) as error:
        risk_dep._git(repo, "show", "HEAD:pyproject.toml", max_bytes=4)
    assert error.value.reason == "git_output_budget"


def test_combined_rev_parse_preserves_state_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agentharness import risk_dep
    repo = _repo(tmp_path)
    path = repo / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("a>=1", "a>=2"), encoding="utf-8")
    original = risk_dep._git
    combined = detect_dependency_change(repo)

    def separate(root: Path, *args: str, **kwargs: object) -> bytes:
        if args == ("rev-parse", "--show-toplevel", "HEAD"):
            return original(root, "rev-parse", "--show-toplevel") + original(root, "rev-parse", "HEAD")
        return original(root, *args, **kwargs)

    monkeypatch.setattr(risk_dep, "_git", separate)
    legacy_output = detect_dependency_change(repo)
    assert combined.status == legacy_output.status
    assert combined.state == legacy_output.state
