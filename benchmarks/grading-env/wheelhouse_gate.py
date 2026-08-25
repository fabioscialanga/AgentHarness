#!/usr/bin/env python3
"""
wheelhouse_gate.py

Gate di completezza per il wheelhouse chiuso del benchmark AgentHarness.
Non si supera leggendo il manifest, si supera installando offline. Questo script
fa esattamente quello: crea venv usa e getta, installa con --no-index dal
wheelhouse, e prova i percorsi in-spec che possono rompersi per una wheel mancante.

Stdlib only, Python 3.11+. Non tocca nulla fuori da cartelle temporanee.
Niente rete: ogni install usa --no-index.

Uso minimo:
    python3 wheelhouse_gate.py \
        --wheelhouse ./wheelhouse \
        --constraints ./constraints-py312.txt \
        --manifest ./wheelhouse-manifest.json

Uso con soluzioni di riferimento e alternative (consigliato prima della campagna):
    python3 wheelhouse_gate.py \
        --wheelhouse ./wheelhouse \
        --constraints ./constraints-py312.txt \
        --manifest ./wheelhouse-manifest.json \
        --solution support-ticket-api=/path/to/reference/support-ticket \
        --solution support-ticket-emailstr=/path/to/alt/support-ticket-emailstr

Exit code 0 se tutti i controlli passano, 1 altrimenti. Pensato anche per la CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


PROBE_SCRIPT = textwrap.dedent(
    """
    import sys

    failures = []

    def check(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures.append(name + ": " + type(exc).__name__ + ": " + str(exc))

    def imp_fastapi():
        import fastapi  # noqa: F401

    def imp_httpx():
        import httpx  # noqa: F401

    def imp_uvicorn():
        import uvicorn  # noqa: F401

    def imp_starlette():
        import starlette  # noqa: F401

    def imp_sqlalchemy():
        import sqlalchemy  # noqa: F401

    def imp_anyio_sniffio():
        import anyio  # noqa: F401
        import sniffio  # noqa: F401

    def emailstr_model():
        from pydantic import BaseModel, EmailStr

        class M(BaseModel):
            email: EmailStr

        M(email="user@example.com")

    def emailstr_rejects_invalid():
        from pydantic import BaseModel, EmailStr, ValidationError

        class M(BaseModel):
            email: EmailStr

        try:
            M(email="not-an-email")
        except ValidationError:
            return
        raise AssertionError("EmailStr non ha rifiutato un indirizzo non valido")

    def testclient_boot():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/ping")
        assert resp.status_code == 200, resp.status_code

    check("import fastapi", imp_fastapi)
    check("import httpx", imp_httpx)
    check("import uvicorn", imp_uvicorn)
    check("import starlette", imp_starlette)
    check("import sqlalchemy", imp_sqlalchemy)
    check("import anyio + sniffio", imp_anyio_sniffio)
    check("pydantic EmailStr model (email-validator)", emailstr_model)
    check("EmailStr rifiuta invalido", emailstr_rejects_invalid)
    check("FastAPI TestClient (httpx)", testclient_boot)

    if failures:
        print("PROBE_FAIL")
        for f in failures:
            print(" - " + f)
        sys.exit(1)
    print("PROBE_OK")
    """
)


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.ok = True

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "passed": passed, "detail": detail})
        if not passed:
            self.ok = False

    def to_json(self) -> str:
        return json.dumps(
            {"verdict": "pass" if self.ok else "fail", "checks": self.checks},
            indent=2,
            ensure_ascii=True,
        )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def check_manifest_integrity(wheelhouse: Path, manifest_path: Path, result: Result) -> None:
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:  # noqa: BLE001
        result.add("manifest leggibile", False, f"{type(exc).__name__}: {exc}")
        return
    result.add("manifest leggibile", True)

    listed = {f["filename"]: f.get("sha256") for f in manifest.get("files", [])}
    actual = {p.name for p in wheelhouse.glob("*.whl")}

    missing_on_disk = sorted(set(listed) - actual)
    not_in_manifest = sorted(actual - set(listed))

    result.add(
        "tutte le wheel elencate sono presenti su disco",
        not missing_on_disk,
        "mancano: " + ", ".join(missing_on_disk) if missing_on_disk else "",
    )
    result.add(
        "nessuna wheel presente fuori dal manifest",
        not not_in_manifest,
        "fuori manifest: " + ", ".join(not_in_manifest) if not_in_manifest else "",
    )

    mismatched = []
    for name, declared in listed.items():
        p = wheelhouse / name
        if not p.is_file() or not declared:
            continue
        if sha256_of(p) != declared:
            mismatched.append(name)
    result.add(
        "hash delle wheel coerenti col manifest",
        not mismatched,
        "hash diversi: " + ", ".join(mismatched) if mismatched else "",
    )

    decl_c = manifest.get("constraints_sha256")
    cfile = manifest.get("constraints_file")
    if decl_c and cfile:
        cpath = manifest_path.parent / cfile
        if cpath.is_file():
            actual_constraints_hash = sha256_of(cpath)
            result.add(
                "hash del constraints coerente col manifest",
                actual_constraints_hash == decl_c,
                "" if actual_constraints_hash == decl_c else f"atteso {decl_c}",
            )


def make_venv(tmp: Path) -> Path:
    venv_dir = tmp / "venv"
    cp = run([sys.executable, "-m", "venv", str(venv_dir)])
    if cp.returncode != 0:
        raise RuntimeError("creazione venv fallita: " + cp.stderr)
    return venv_dir


def venv_python(venv_dir: Path) -> Path:
    cand = venv_dir / "bin" / "python"
    return cand if cand.exists() else venv_dir / "Scripts" / "python.exe"


def offline_install(
    py: Path, wheelhouse: Path, constraints: Path, requirements: list[str]
) -> subprocess.CompletedProcess[str]:
    cmd = [
        str(py),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "-c",
        str(constraints),
        *requirements,
    ]
    return run(cmd)


def gate_root_and_probes(
    wheelhouse: Path, constraints: Path, manifest_path: Path, result: Result
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:  # noqa: BLE001
        manifest = {}
    root_reqs = manifest.get(
        "root_requirements",
        ["fastapi", "httpx", "pydantic", "pytest", "pyyaml", "sqlalchemy"],
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            venv_dir = make_venv(tmp)
        except RuntimeError as exc:
            result.add("venv di probe creato", False, str(exc))
            return
        py = venv_python(venv_dir)

        cp = offline_install(py, wheelhouse, constraints, root_reqs)
        passed = cp.returncode == 0
        detail = "" if passed else (cp.stderr.strip().splitlines() or [""])[-1]
        result.add("install offline della radice (--no-index)", passed, detail)
        if not passed:
            return

        probe_file = tmp / "probe.py"
        probe_file.write_text(PROBE_SCRIPT)
        cp = run([str(py), str(probe_file)])
        passed = cp.returncode == 0 and "PROBE_OK" in cp.stdout
        detail = "" if passed else (cp.stdout + cp.stderr).strip()
        result.add("probe import in-spec (EmailStr, TestClient, sniffio)", passed, detail)


def gate_solution(
    name: str,
    solution_dir: Path,
    wheelhouse: Path,
    constraints: Path,
    grader_cmd: str | None,
    result: Result,
) -> None:
    if not solution_dir.exists():
        result.add(f"soluzione {name}: cartella esiste", False, str(solution_dir))
        return

    reqs: list[str]
    if (solution_dir / "pyproject.toml").is_file():
        reqs = [str(solution_dir)]
    elif (solution_dir / "requirements.txt").is_file():
        reqs = ["-r", str(solution_dir / "requirements.txt")]
    else:
        result.add(
            f"soluzione {name}: manifest trovata", False, "ne pyproject.toml ne requirements.txt"
        )
        return

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        solution_copy = tmp / "solution"
        shutil.copytree(
            solution_dir,
            solution_copy,
            ignore=shutil.ignore_patterns("build", "*.egg-info", "__pycache__", "*.pyc", ".pytest_cache"),
        )
        if (solution_copy / "pyproject.toml").is_file():
            reqs = [str(solution_copy)]
        else:
            reqs = ["-r", str(solution_copy / "requirements.txt")]
        try:
            venv_dir = make_venv(tmp)
        except RuntimeError as exc:
            result.add(f"soluzione {name}: venv creato", False, str(exc))
            return
        py = venv_python(venv_dir)

        cp = offline_install(py, wheelhouse, constraints, reqs)
        passed = cp.returncode == 0
        detail = "" if passed else (cp.stderr.strip().splitlines() or [""])[-1]
        result.add(f"soluzione {name}: install offline dalla propria manifest", passed, detail)
        if not passed or not grader_cmd:
            return

        cp = offline_install(py, wheelhouse, constraints, ["agentharness-verifier"])
        passed = cp.returncode == 0
        detail = "" if passed else (cp.stderr.strip().splitlines() or [""])[-1]
        result.add(f"soluzione {name}: install offline del grader", passed, detail)
        if not passed:
            return

        cmd = grader_cmd.format(python=str(py), solution=str(solution_copy))
        cp = run(shlex.split(cmd))
        passed = cp.returncode == 0
        detail = "" if passed else (cp.stdout + cp.stderr).strip()[-400:]
        result.add(f"soluzione {name}: grader esito di successo", passed, detail)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate di completezza del wheelhouse chiuso.")
    ap.add_argument("--wheelhouse", required=True, type=Path)
    ap.add_argument("--constraints", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument(
        "--solution",
        action="append",
        default=[],
        metavar="NOME=PATH",
        help="soluzione da installare offline, ripetibile",
    )
    ap.add_argument(
        "--grader-cmd",
        default=None,
        help="comando grader opzionale, con segnaposto {python} e {solution}; quando presente il gate installa anche agentharness-verifier offline nel venv della soluzione",
    )
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    for p in (args.wheelhouse, args.constraints, args.manifest):
        if not p.exists():
            print(f"ERRORE: percorso inesistente: {p}", file=sys.stderr)
            return 2

    result = Result()
    check_manifest_integrity(args.wheelhouse, args.manifest, result)
    gate_root_and_probes(args.wheelhouse, args.constraints, args.manifest, result)

    for entry in args.solution:
        if "=" not in entry:
            result.add(f"soluzione '{entry}': formato NOME=PATH", False, entry)
            continue
        name, _, path = entry.partition("=")
        gate_solution(
            name, Path(path), args.wheelhouse, args.constraints, args.grader_cmd, result
        )

    print("\n=== Gate wheelhouse: dettaglio ===")
    for c in result.checks:
        mark = "PASS" if c["passed"] else "FAIL"
        line = f"[{mark}] {c['check']}"
        if c["detail"]:
            line += f"\n        {c['detail']}"
        print(line)

    print("\n=== Verdetto ===")
    print("PASS, il wheelhouse copre i percorsi provati" if result.ok else "FAIL, wheelhouse incompleto o incoerente")

    if args.json_out:
        args.json_out.write_text(result.to_json())
        print(f"\nReport JSON scritto in {args.json_out}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
