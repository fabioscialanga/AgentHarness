"""Conservative preflight and benchmark bridge checks; no host integration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentharness import risk_dep
from scripts.m3_cp3d_prepare import _preflight_no_risk, _repo, evaluate
from scripts.m3_cp3d_oracle_bridge import main as oracle_bridge


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    return tmp_path


def test_preflight_clean_equivalent_and_risky(root: Path) -> None:
    clean, _ = _repo(root, "clean", None)
    equivalent, _ = _repo(root, "equivalent", '[project]\nname="sample"\ndependencies=["my-pkg>=1.0"]\n')
    risky, _ = _repo(root, "risky", '[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n')
    assert _preflight_no_risk(clean)
    assert _preflight_no_risk(equivalent)
    assert not _preflight_no_risk(risky)


def test_preflight_unknown_syntax_falls_through(root: Path) -> None:
    repo, _ = _repo(root, "unknown", '[project]\nname="sample"\ndependencies=["My_Pkg @ https://example.invalid/x"]\n')
    assert not _preflight_no_risk(repo)


def test_assume_unchanged_cannot_hide_dep_change(root: Path) -> None:
    repo, _ = _repo(root, "assume", None)
    subprocess.run(["git", "-C", str(repo), "update-index", "--assume-unchanged", "pyproject.toml"],
                   check=True, capture_output=True)
    (repo / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n',
                                         encoding="utf-8")
    assert not _preflight_no_risk(repo)


def test_preflight_race_falls_through(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = _repo(root, "raced", None)
    original = risk_dep._git
    calls = 0

    def changed(path: Path, *args: str, **kwargs: object) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            (repo / "pyproject.toml").write_text('[project]\nname="sample"\ndependencies=["My_Pkg>=2"]\n', encoding="utf-8")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(risk_dep, "_git", changed)
    assert not _preflight_no_risk(repo)


def test_preflight_symlink_falls_through(root: Path) -> None:
    repo, _ = _repo(root, "linked", None)
    target = root / "target.toml"
    target.write_bytes((repo / "pyproject.toml").read_bytes())
    (repo / "pyproject.toml").unlink()
    try:
        (repo / "pyproject.toml").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert not _preflight_no_risk(repo)


def test_disabled_path_does_not_call_git(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, control = _repo(root, "disabled", None)

    def forbidden(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("Git called when disabled")

    monkeypatch.setattr(risk_dep, "_git", forbidden)
    assert evaluate(repo, control, enabled=False) == "disabled"


def test_no_risk_does_not_hash_interpreter(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import m3_cp3d_prepare
    repo, _ = _repo(root, "no-env", None)

    def forbidden() -> None:
        raise AssertionError("interpreter fingerprint requested without risk")

    monkeypatch.setattr(m3_cp3d_prepare.dep_evidence, "local_environment_id", forbidden)
    assert evaluate(repo, enabled=True) == "no_dep_risk"
    assert evaluate(repo, enabled=False) == "disabled"


def test_no_risk_skips_matcher(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import m3_cp3d_prepare
    repo, control = _repo(root, "skip", '[project]\nname="sample"\ndependencies=["my-pkg>=1.0"]\n')

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("matcher called for equivalent change")

    monkeypatch.setattr(m3_cp3d_prepare.dep_evidence, "match_dep_evidence", forbidden)
    assert evaluate(repo, control, enabled=True) == "no_dep_risk"


def test_oracle_bridge_never_promotes_covered() -> None:
    result = oracle_bridge()
    assert result["integrity_validated"] is True
    assert result["fixtures"] == 37
    assert result["production_covered_from_oracle"] == 0
    assert all(row["production_decision"] != "covered" for row in result["rows"])
