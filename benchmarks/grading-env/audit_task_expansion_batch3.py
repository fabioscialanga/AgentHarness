#!/usr/bin/env python3
"""Canonical, non-efficacy acceptance auditor for task-expansion batch 3."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks"
OUT = BENCH / "grading-env" / "task-expansion-batch3"
REPORT = OUT / "BATCH3_ACCEPTANCE_REPORT.json"
FREEZE_PATH = OUT / "BATCH3_PREBUILD_FREEZE.json"
SENSITIVITY_PATH = OUT / "MUTATION_SENSITIVITY.json"
PREBUILD_GENERATOR = BENCH / "grading-env" / "build_task_expansion_batch3_prebuild.py"
VISIBLE_GENERATOR = BENCH / "grading-env" / "build_task_expansion_batch3.py"
EXPECTED_FREEZE_SHA256 = "63f7404b1e62967e42c7f258ef3031b18a1699276e440bcd0bf30431c18b4713"
EXPECTED_PREBUILD_GENERATOR_SHA256 = "738108592c86892f7c0f6e8318fbe291e86773db2cf787078c1ed5e92800784d"
PACKAGES = {
    "signed-artifact-verifier": ("artifact_verifier", "verify.py"),
    "pii-redaction-pipeline": ("pii_redactor", "redact.py"),
    "lease-coordination-api": ("lease_api", "main.py"),
    "double-entry-ledger-api": ("ledger_api", "main.py"),
}
COMMON_FILES = {"SPEC.md", "CLAIMS_CONTRACT.template.json", "README.md", "pyproject.toml"}
PROCESS_CLAIMS = {"forbidden_paths", "tests_executed", "artifact_present"}
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", ".coverage", ".agentharness"}
FORBIDDEN_IDENTIFIER = re.compile(r"(?:^|[^a-z0-9])(hidden|check|mutant|probe|reference|evaluator|freeze)(?:[^a-z0-9]|$)", re.I)
PLACEHOLDER = re.compile(r"\b(?:todo|tbd|placeholder|generic (?:difference|comparison|text)|same as above|n/?a)\b", re.I)
ENVELOPE_KEYS = {
    "task_id", "critical_ok", "execution_status", "outcome_status", "classification_reason",
    "evaluation_instance_id", "lifecycle_started_at", "lifecycle_finished_at", "passed_checks",
    "failed_checks", "observations", "summary_path", "result_path",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gate(ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"ok": bool(ok), "detail": detail, **extra}


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    started = time.monotonic()
    try:
        done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": done.returncode == 0,
            "command": command,
            "cwd": str(cwd),
            "exit_code": done.returncode,
            "duration_seconds": round(time.monotonic() - started, 6),
            "stdout": done.stdout,
            "stderr": done.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False, "command": command, "cwd": str(cwd), "exit_code": None,
            "duration_seconds": round(time.monotonic() - started, 6),
            "stdout": exc.stdout or "", "stderr": f"timeout after {timeout}s: {exc.stderr or ''}",
        }


def expected_files(task: str) -> set[str]:
    package, module = PACKAGES[task]
    return COMMON_FILES | {f"{package}/__init__.py", f"{package}/{module}"}


def regular_files(root: Path) -> list[Path]:
    return sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix())


def meaningful_record(row: dict[str, Any], fields: tuple[str, ...]) -> bool:
    values = [row.get(field) for field in fields]
    return all(isinstance(value, str) and value.strip() and not PLACEHOLDER.search(value) for value in values)


def remove_caches() -> list[str]:
    removed: list[str] = []
    roots = [
        *(BENCH / task for task in PACKAGES), OUT / "references",
        BENCH / "grading-env", ROOT / "tests", ROOT / "src/agentharness",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_file() and path.suffix == ".pyc":
                removed.append(str(path.relative_to(ROOT))); path.unlink()
            elif path.is_dir() and (
                path.name in {"__pycache__", ".pytest_cache", "build", "dist"}
                or path.name.endswith(".egg-info")
            ):
                removed.append(str(path.relative_to(ROOT))); shutil.rmtree(path)
    return sorted(set(removed))


def static_audit(freeze: dict[str, Any], sensitivity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    checks: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    cleanup = remove_caches()
    freeze_sha = sha256(FREEZE_PATH)
    prebuild_sha = sha256(PREBUILD_GENERATOR)
    checks["freeze"] = {
        "normative_freeze_sha256": gate(freeze_sha == EXPECTED_FREEZE_SHA256, freeze_sha, expected=EXPECTED_FREEZE_SHA256),
        "prebuild_generator_sha256": gate(prebuild_sha == EXPECTED_PREBUILD_GENERATOR_SHA256, prebuild_sha, expected=EXPECTED_PREBUILD_GENERATOR_SHA256),
        "frozen_zero_efficacy": gate(freeze.get("efficacy_cells_collected") == 0, f"efficacy_cells_collected={freeze.get('efficacy_cells_collected')!r}"),
    }
    task_checks = {task: [row["id"] for row in freeze["tasks"][task]["checks"]] for task in PACKAGES}
    for task, ids in task_checks.items():
        root = BENCH / task
        paths = regular_files(root) if root.is_dir() else []
        names = {path.relative_to(root).as_posix() for path in paths}
        bad_nodes = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_symlink() or path.name in FORBIDDEN_PARTS or path.suffix == ".pyc") if root.exists() else []
        visible = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths)
        path_identifiers = "\n".join(sorted(names))
        identifier_hits = sorted(set(match.group(1).lower() for match in FORBIDDEN_IDENTIFIER.finditer(path_identifiers)))
        id_hits = sorted(check_id for check_id in ids if check_id in visible)
        claims_path = root / "CLAIMS_CONTRACT.template.json"
        claims = json.loads(claims_path.read_text(encoding="utf-8")) if claims_path.is_file() else {}
        claim_types = {row.get("type") for row in claims.get("claims", [])}
        expected = expected_files(task)
        checks[task] = {
            "exact_visible_allowlist": gate(names == expected, f"files={sorted(names)}", expected=sorted(expected)),
            "forbidden_identifiers_absent": gate(not identifier_hits and not id_hits, f"identifier_hits={identifier_hits}; check_id_hits={id_hits}"),
            "clean_visible_tree": gate(not bad_nodes, f"bad_nodes={bad_nodes}"),
            "process_claims_only": gate(bool(claim_types) and claim_types <= PROCESS_CLAIMS, f"claim_types={sorted(str(x) for x in claim_types)}"),
            "five_frozen_functional_checks": gate(len(ids) == 5 and len(set(ids)) == 5, f"check_ids={ids}"),
        }
    all_prior = freeze.get("all_prior_overlap_matrix", [])
    nearest = freeze.get("nearest_check_matrix", [])
    pairwise = freeze.get("new_task_pairwise_matrix", [])
    prior_keys = {(r.get("new_task"), r.get("prior_task")) for r in all_prior}
    nearest_keys = {(r.get("new_task"), r.get("new_check")) for r in nearest}
    pair_keys = {tuple(sorted((r.get("left", ""), r.get("right", "")))) for r in pairwise}
    expected_pairs = {tuple(sorted((left, right))) for index, left in enumerate(PACKAGES) for right in list(PACKAGES)[index + 1:]}
    expected_nearest = {(task, check_id) for task, ids in task_checks.items() for check_id in ids}
    checks["diversity"] = {
        "all_prior_64_complete": gate(len(all_prior) == 64 and len(prior_keys) == 64 and all(meaningful_record(r, ("shared_shell_or_surface", "substantive_difference", "non_implication")) for r in all_prior), f"records={len(all_prior)} unique={len(prior_keys)}"),
        "nearest_20_complete": gate(len(nearest) == 20 and nearest_keys == expected_nearest and all(meaningful_record(r, ("nearest_existing_task", "substantive_difference", "planned_probe", "planned_mutant")) for r in nearest), f"records={len(nearest)} unique={len(nearest_keys)}"),
        "pairwise_6_complete": gate(len(pairwise) == 6 and pair_keys == expected_pairs and all(meaningful_record(r, ("shared_shell", "substantive_difference")) for r in pairwise), f"records={len(pairwise)} unique={len(pair_keys)}"),
    }
    sensitivity_tasks = sensitivity.get("tasks", {})
    mutation_rows = 0
    mutation_ok = set(sensitivity_tasks) == set(PACKAGES)
    for task, ids in task_checks.items():
        rows = sensitivity_tasks.get(task, {})
        mutation_rows += len(rows)
        frozen_rows = {row["id"]: row for row in freeze["tasks"][task]["checks"]}
        mutation_ok = mutation_ok and set(rows) == set(ids)
        for check_id in ids:
            row = rows.get(check_id, {})
            frozen = frozen_rows[check_id]
            mutation_ok = mutation_ok and row.get("expected_failed_checks") == frozen.get("expected_mutant_failed_checks") == [check_id]
            mutation_ok = mutation_ok and row.get("expected_passed_checks") == frozen.get("expected_mutant_passed_checks") == [item for item in ids if item != check_id]
    checks["mutation_contract"] = {"exact_normative_20": gate(mutation_ok and mutation_rows == 20, f"mutants={mutation_rows}")}

    before = {p.relative_to(ROOT).as_posix(): sha256(p) for task in PACKAGES for p in regular_files(BENCH / task)}
    generator_run = run([sys.executable, str(VISIBLE_GENERATOR)], cwd=Path(tempfile.gettempdir()), timeout=120)
    after = {p.relative_to(ROOT).as_posix(): sha256(p) for task in PACKAGES for p in regular_files(BENCH / task)}
    checks["generator"] = {
        "uses_current_interpreter": gate(generator_run["command"][0] == sys.executable, repr(generator_run["command"])),
        "visible_byte_identity": gate(generator_run["ok"] and before == after, f"exit_code={generator_run['exit_code']}; changed={sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))}"),
    }
    remove_caches()
    artifact_bases = [
        *(BENCH / task for task in PACKAGES), VISIBLE_GENERATOR,
        ROOT / "src/agentharness/benchmark_hidden_evaluators.py",
        *(ROOT / f"src/agentharness/benchmark_hidden_evaluators_batch3{suffix}.py" for suffix in ("", "_signed", "_pii", "_lease", "_ledger")),
        Path(__file__).resolve(), ROOT / "tests/test_task_expansion_batch3.py", FREEZE_PATH, SENSITIVITY_PATH, OUT / "references",
    ]
    for base in artifact_bases:
        paths = [base] if base.is_file() else (regular_files(base) if base.is_dir() else [])
        for path in paths:
            if path.suffix != ".pyc" and not any(part in FORBIDDEN_PARTS for part in path.parts):
                hashes[path.relative_to(ROOT).as_posix()] = sha256(path)
    return checks, dict(sorted(hashes.items())), {"cleanup_removed": cleanup, "generator": generator_run}


def packaging_audit() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="batch3-packaging-") as tmp:
        temp = Path(tmp); wheels = temp / "wheelhouse"; wheels.mkdir()
        for task, (package, module) in PACKAGES.items():
            reference = OUT / "references" / task
            packaging_source = temp / f"source-{task}"
            shutil.copytree(reference, packaging_source)
            existing_wheels = set(wheels.glob("*.whl"))
            wheel = run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheels), str(packaging_source)], timeout=300)
            targets = sorted(set(wheels.glob("*.whl")) - existing_wheels)
            target = temp / f"install-{task}"
            install = run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(targets[-1])], timeout=300) if targets else {"ok": False, "command": [], "cwd": str(ROOT), "exit_code": None, "duration_seconds": 0.0, "stdout": "", "stderr": "wheel missing"}
            source = reference / package / module
            compiled = temp / f"{task}.pyc"
            started = time.monotonic()
            try:
                py_compile.compile(str(source), cfile=str(compiled), doraise=True)
                compile_row = gate(True, str(source.relative_to(ROOT)), duration_seconds=round(time.monotonic() - started, 6))
            except py_compile.PyCompileError as exc:
                compile_row = gate(False, str(exc), duration_seconds=round(time.monotonic() - started, 6))
            rows[task] = {"ok": bool(wheel["ok"] and install["ok"] and compile_row["ok"]), "wheel": wheel, "install": install, "py_compile": compile_row}
    return rows


@contextmanager
def mutant_environment(mutant: str, seed: str) -> Iterator[None]:
    old = {name: os.environ.get(name) for name in ("AGENTHARNESS_MUTANT", "PYTHONHASHSEED")}
    os.environ["AGENTHARNESS_MUTANT"] = mutant; os.environ["PYTHONHASHSEED"] = seed
    try:
        yield
    finally:
        for name, value in old.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value


def evaluate_copy(evaluate: Any, task: str, mutant: str = "", seed: str = "17") -> tuple[Any, float]:
    with tempfile.TemporaryDirectory(prefix=f"batch3-audit-{task}-") as tmp:
        workspace = Path(tmp) / task; shutil.copytree(OUT / "references" / task, workspace)
        package, module = PACKAGES[task]
        run_path = Path(tmp) / "run.json"
        run_path.write_text(json.dumps({
            "run_id": f"audit-{task}-{mutant or 'reference'}-{seed}", "workspace": str(workspace),
            "artifacts": {"changed_files": [f"{package}/{module}", "README.md", "pyproject.toml"], "commands": [{"cmd": "pytest -q", "exit_code": 0}], "outputs": [{"type": "file", "path": "README.md"}, {"type": "file", "path": "pyproject.toml"}]},
        }), encoding="utf-8")
        started = time.monotonic()
        with mutant_environment(mutant, seed): result = evaluate(run_path, task)
        return result, round(time.monotonic() - started, 6)


def dynamic_audit(freeze: dict[str, Any], sensitivity: dict[str, Any]) -> dict[str, Any]:
    source = str(ROOT / "src")
    if source not in sys.path: sys.path.insert(0, source)
    from agentharness.benchmark_hidden_evaluators import evaluate_benchmark_task
    tasks: dict[str, Any] = {}; mutation_rows: list[dict[str, Any]] = []; clean_rows: dict[str, Any] = {}
    total_started = time.monotonic()
    for task in PACKAGES:
        ids = [row["id"] for row in freeze["tasks"][task]["checks"]]
        result, duration = evaluate_copy(evaluate_benchmark_task, task)
        payload = result.to_dict()
        schema_ok = set(payload) == ENVELOPE_KEYS and isinstance(payload["observations"], list) and len(payload["observations"]) == 5
        exact = result.execution_status == "valid" and result.critical_ok and result.passed_checks == ids and result.failed_checks == [] and len(result.observations) == 5 and all(row.status == "pass" for row in result.observations)
        breakdown = [{"check_id": row.id, "status": row.status, "detail": row.detail} for row in result.observations]
        breakdown.append({"check_id": "evaluation_result_schema", "status": "pass" if schema_ok else "fail", "detail": f"keys={sorted(payload)}"})
        tasks[task] = {"ok": bool(exact and schema_ok), "duration_seconds": duration, "functional_passed": len(result.passed_checks), "functional_denominator": 5, "terminal_schema_passed": int(schema_ok), "total_passed": len(result.passed_checks) + int(schema_ok), "total_denominator": 6, "checks": breakdown}
        for mutant in ids:
            mutant_result, mutant_duration = evaluate_copy(evaluate_benchmark_task, task, mutant)
            normative = sensitivity["tasks"][task][mutant]
            ok = mutant_result.failed_checks == normative["expected_failed_checks"] and mutant_result.passed_checks == normative["expected_passed_checks"]
            mutation_rows.append({"task_id": task, "mutant": mutant, "ok": ok, "duration_seconds": mutant_duration, "expected_failed_checks": normative["expected_failed_checks"], "actual_failed_checks": mutant_result.failed_checks, "expected_passed_checks": normative["expected_passed_checks"], "actual_passed_checks": mutant_result.passed_checks})
        signatures = []
        copies = []
        for seed in ("13", "47", "89"):
            copy_result, copy_duration = evaluate_copy(evaluate_benchmark_task, task, seed=seed)
            signature = {"execution_status": copy_result.execution_status, "outcome_status": copy_result.outcome_status, "classification_reason": copy_result.classification_reason, "critical_ok": copy_result.critical_ok, "passed_checks": copy_result.passed_checks, "failed_checks": copy_result.failed_checks, "observations": [[row.id, row.status] for row in copy_result.observations]}
            signatures.append(signature); copies.append({"seed": seed, "duration_seconds": copy_duration, "signature": signature})
        clean_rows[task] = {"ok": signatures == [signatures[0]] * 3 and signatures[0]["passed_checks"] == ids, "independent_copies": 3, "copies": copies}
    dispatcher_ok = set(tasks) == set(PACKAGES) and all(row["functional_denominator"] == 5 for row in tasks.values())
    return {"ok": all(row["ok"] for row in tasks.values()) and len(mutation_rows) == 20 and all(row["ok"] for row in mutation_rows) and all(row["ok"] for row in clean_rows.values()) and dispatcher_ok, "command": [sys.executable, str(Path(__file__).resolve()), "--full"], "exit_code": 0 if dispatcher_ok else 1, "duration_seconds": round(time.monotonic() - total_started, 6), "dispatcher_recognition": gate(dispatcher_ok, f"recognized={sorted(tasks)}"), "reference_tasks": tasks, "mutations": {"ok": len(mutation_rows) == 20 and all(row["ok"] for row in mutation_rows), "passed": sum(row["ok"] for row in mutation_rows), "denominator": 20, "rows": mutation_rows}, "clean_room": clean_rows}


def legacy_audit(paths: list[str], evidence_path: str | None) -> dict[str, Any]:
    if evidence_path:
        path = Path(evidence_path).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8")); commands = payload["commands"]
            ok = bool(commands) and all(row.get("exit_code") == 0 for row in commands)
            return {"ok": ok, "source": "optional_evidence", "path": str(path), "commands": commands}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "source": "optional_evidence", "path": str(path), "commands": [], "error": str(exc)}
    selected = paths or ["tests/test_task_expansion_batch1.py", "tests/test_task_expansion_batch2.py"]
    env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "src")
    row = run([sys.executable, "-m", "pytest", "-q", *selected], env=env, timeout=1800)
    return {"ok": row["ok"], "source": "executed_configured_subset", "commands": [row]}


def all_static_ok(checks: dict[str, Any]) -> bool:
    return all(result["ok"] for group in checks.values() for result in group.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(); mode.add_argument("--quick", action="store_true"); mode.add_argument("--full", action="store_true")
    parser.add_argument("--legacy-test", action="append", default=[], help="pytest path for the full-mode legacy subset")
    parser.add_argument("--legacy-evidence", help="JSON containing a non-empty commands list with exit_code fields")
    args = parser.parse_args(argv)
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8")); sensitivity = json.loads(SENSITIVITY_PATH.read_text(encoding="utf-8"))
    static, hashes, operations = static_audit(freeze, sensitivity)
    quick = args.quick or not args.full
    packaging: dict[str, Any] = {"ok": False, "status": "not_run_in_quick_mode", "tasks": {}}
    dynamic = {"ok": False, "status": "not_run_in_quick_mode", "command": [sys.executable, str(Path(__file__).resolve()), "--full"], "exit_code": None, "duration_seconds": 0.0} if quick else dynamic_audit(freeze, sensitivity)
    legacy = {"ok": False, "status": "not_run_in_quick_mode", "commands": []} if quick else legacy_audit(args.legacy_test, args.legacy_evidence)
    if not quick:
        packaging_tasks = packaging_audit(); packaging = {"ok": all(row["ok"] for row in packaging_tasks.values()), "tasks": packaging_tasks}
    remove_caches()
    commit = run(["git", "rev-parse", "HEAD"], timeout=30)
    static_ok = all_static_ok(static)
    go = bool(not quick and static_ok and packaging["ok"] and dynamic["ok"] and legacy["ok"])
    payload = {
        "schema_version": 1,
        "report_kind": "batch3_non_efficacy_acceptance",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "quick" if quick else "full",
        "base_commit": commit["stdout"].strip() if commit["ok"] else None,
        "interpreter_fingerprint": {"executable": sys.executable, "version": sys.version, "implementation": platform.python_implementation(), "platform": platform.platform(), "cache_tag": sys.implementation.cache_tag},
        "efficacy_cells": 0,
        "campaign_boundary": "Task-pack acceptance only. No task-solving pilot, A/B cell, hidden efficacy score, contrast, confirmatory campaign, or efficacy claim is authorized or evaluated by this auditor.",
        "independent_review": {"evaluated": False, "claimed": False, "detail": "Independent review is outside this auditor and is not claimed by this report."},
        "static": {"ok": static_ok, "checks": static},
        "packaging": packaging,
        "dynamic": dynamic,
        "legacy_compatibility": legacy,
        "diversity_evidence": {"all_prior_overlap_matrix": freeze["all_prior_overlap_matrix"], "nearest_check_matrix": freeze["nearest_check_matrix"], "new_task_pairwise_matrix": freeze["new_task_pairwise_matrix"]},
        "operations": operations,
        "artifact_sha256": hashes,
        "go": go,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"go": go, "mode": payload["mode"], "static_ok": static_ok, "packaging_ok": packaging["ok"], "dynamic_ok": dynamic["ok"], "legacy_ok": legacy["ok"], "report": str(REPORT)}, indent=2, sort_keys=True))
    return 0 if (static_ok if quick else go) else 1


if __name__ == "__main__":
    raise SystemExit(main())
