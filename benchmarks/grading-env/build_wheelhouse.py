from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_ROOT = Path(__file__).resolve().parent
ALLOWLIST_PATH = ENV_ROOT / "allowed-top-level.in"
CONSTRAINTS_PATH = ENV_ROOT / f"constraints-py{sys.version_info.major}{sys.version_info.minor}.txt"
WHEELHOUSE_DIR = ENV_ROOT / "wheelhouse"
MANIFEST_PATH = ENV_ROOT / "wheelhouse-manifest.json"


def canonical_dependency_name(spec: str) -> str:
    candidate = spec.strip()
    for separator in ("[", ";", "<", ">", "=", "!", "~", " "):
        candidate = candidate.split(separator, 1)[0]
    return candidate.replace("_", "-").lower()


def parse_seed_specs(path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().lower()
            sections.setdefault(current_section, [])
            continue
        if current_section is None:
            raise RuntimeError(f"allowlist entry outside section: {line}")
        sections[current_section].append(line)
    return sections


def repo_project_version() -> str:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload.get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("project version missing from pyproject.toml")
    return version.strip()


def repo_project_dependencies() -> list[str]:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload.get("project", {})
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise RuntimeError("project dependencies in pyproject.toml must be a list")
    return [str(item) for item in dependencies]


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def pip_freeze(tmp_venv_python: Path) -> list[str]:
    output = run([str(tmp_venv_python), "-m", "pip", "freeze"]).stdout
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return sorted(set(lines), key=str.lower)


def wheel_manifest(path: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for wheel_path in sorted(path.glob("*")):
        if not wheel_path.is_file():
            continue
        digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        entries.append(
            {
                "filename": wheel_path.name,
                "sha256": digest,
                "size_bytes": wheel_path.stat().st_size,
            }
        )
    return entries


def unique_specs_by_name(specs: list[str]) -> list[str]:
    chosen: dict[str, str] = {}
    for spec in specs:
        chosen[canonical_dependency_name(spec)] = spec
    return sorted(chosen.values(), key=str.lower)


def main() -> int:
    seed_specs = parse_seed_specs(ALLOWLIST_PATH)
    top_level_solution = sorted(seed_specs.get("api-solution", []) + seed_specs.get("cli-solution", []), key=str.lower)
    grader_packages = sorted(
        [spec for spec in seed_specs.get("grader", []) if canonical_dependency_name(spec) != "agentharness"],
        key=str.lower,
    )
    top_level_specs = unique_specs_by_name(repo_project_dependencies() + top_level_solution + grader_packages + ["wheel"])

    agentharness_version = repo_project_version()
    pinned_root_requirements = sorted(set(top_level_specs) | {f"agentharness=={agentharness_version}"}, key=str.lower)

    WHEELHOUSE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_root = Path(tmp_dir)
        venv_dir = temp_root / "resolver-venv"
        run([sys.executable, "-m", "venv", str(venv_dir)])
        python_bin = venv_dir / "bin" / "python"
        run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        run([str(python_bin), "-m", "pip", "install", *top_level_specs])

        frozen = pip_freeze(python_bin)
        agentharness_pin = f"agentharness=={agentharness_version}"
        constraints_lines = sorted(set(frozen + [agentharness_pin]), key=str.lower)
        CONSTRAINTS_PATH.write_text("\n".join(constraints_lines) + "\n", encoding="utf-8")

        shutil.rmtree(WHEELHOUSE_DIR)
        WHEELHOUSE_DIR.mkdir(parents=True, exist_ok=True)

        third_party_constraints = temp_root / "third-party-constraints.txt"
        third_party_constraints.write_text(
            "\n".join(line for line in constraints_lines if not line.lower().startswith("agentharness==")) + "\n",
            encoding="utf-8",
        )
        run([str(python_bin), "-m", "pip", "download", "-d", str(WHEELHOUSE_DIR), "-r", str(third_party_constraints)])
        run([str(python_bin), "-m", "pip", "wheel", "--no-deps", "-w", str(WHEELHOUSE_DIR), str(REPO_ROOT)])

    manifest_payload = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "agentharness_version": agentharness_version,
        "allowed_top_level": {
            key: sorted({canonical_dependency_name(spec) for spec in value})
            for key, value in sorted(seed_specs.items())
        },
        "seed_specs": {
            key: sorted(value, key=str.lower)
            for key, value in sorted(seed_specs.items())
        },
        "constraints_file": CONSTRAINTS_PATH.name,
        "constraints_sha256": hashlib.sha256(CONSTRAINTS_PATH.read_bytes()).hexdigest(),
        "files": wheel_manifest(WHEELHOUSE_DIR),
        "root_requirements": pinned_root_requirements,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"constraints": str(CONSTRAINTS_PATH), "wheelhouse": str(WHEELHOUSE_DIR), "manifest": str(MANIFEST_PATH)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
