from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "benchmarks/grading-env/mechanism-first-v5.2/references/portable-command-receipt-ledger"
DRIVER = ROOT / "benchmarks/grading-env/v5_2_receipt_process_driver.py"
CHECKS = (
    "receipt_key_identity",
    "receipt_tenant_identity",
    "receipt_command_identity",
    "receipt_revision_identity",
    "receipt_process_portability",
)
PROBES = {check: 10 for check in CHECKS}
MUTANTS = list(CHECKS)
NEAR = "receipt_key_casefold_near_miss"


def load(root: Path):
    for name in list(sys.modules):
        if name == "command_ledger" or name.startswith("command_ledger."):
            del sys.modules[name]
    sys.path.insert(0, str(root))
    try:
        return importlib.import_module("command_ledger")
    finally:
        sys.path.pop(0)


def body(receipt: str) -> bytes:
    return json.dumps({"receipt": receipt}, sort_keys=True, separators=(",", ":")).encode()


def post(client: TestClient, identity: tuple[str, str, int, str], value: str):
    tenant, command, revision, key = identity
    return client.post(
        f"/commands/{command}",
        headers={"X-Tenant": tenant, "X-API-Revision": str(revision), "Idempotency-Key": key},
        json={"value": value},
    )


def pair(check: str, index: int) -> tuple[tuple[str, str, int, str], tuple[str, str, int, str]]:
    base = (f"Tenant{index}", f"Command{index}", 100 + index, f"Key{index}")
    if check == "receipt_key_identity":
        if index < 5:
            return (*base[:3], f"Key-{index}A"), (*base[:3], f"key-{index}a")
        return (*base[:3], f"Key-{index}A"), (*base[:3], f"Key-{index}B")
    if check == "receipt_tenant_identity":
        return (f"TenantA{index}", *base[1:]), (f"TenantB{index}", *base[1:])
    if check == "receipt_command_identity":
        return (base[0], f"CommandA{index}", *base[2:]), (base[0], f"CommandB{index}", *base[2:])
    if check == "receipt_revision_identity":
        return (base[0], base[1], 200 + index, base[3]), (base[0], base[1], 300 + index, base[3])
    raise AssertionError(check)


def identity_probe(implementation: Path, check: str, index: int) -> bool:
    try:
        package = load(implementation)
        calls: list[tuple[str, str, int, str, dict[str, Any]]] = []

        def execute_once(tenant: str, command: str, revision: int, key: str, payload: dict[str, Any]) -> str:
            calls.append((tenant, command, revision, key, payload))
            return f"Receipt-{index}-{len(calls)}-Qx7"

        first_identity, second_identity = pair(check, index)
        with tempfile.TemporaryDirectory(prefix="v52-receipt-id-") as raw:
            db = Path(raw) / "ledger.sqlite"
            with TestClient(package.create_app(db, execute_once)) as client:
                first = post(client, first_identity, f"ValueA{index}")
                replay = post(client, first_identity, f"ValueA{index}")
                second = post(client, second_identity, f"ValueB{index}")
            expected_calls = [
                (*first_identity, {"value": f"ValueA{index}"}),
                (*second_identity, {"value": f"ValueB{index}"}),
            ]
            return (
                [first.status_code, replay.status_code, second.status_code] == [200, 200, 200]
                and first.content == replay.content == body(f"Receipt-{index}-1-Qx7")
                and second.content == body(f"Receipt-{index}-2-Qx7")
                and calls == expected_calls
                and db.is_file()
            )
    except Exception:
        return False


def check_identity(implementation: Path, check: str) -> bool:
    return all(identity_probe(implementation, check, index) for index in range(10))


def run_driver(workspace: Path, db: Path, phase: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(DRIVER), "--workspace", str(workspace), "--db", str(db), "--phase", phase],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=True,
    )
    return json.loads(completed.stdout)


def portability_probe(implementation: Path, index: int) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix=f"v52-receipt-port-{index}-") as raw:
            root = Path(raw)
            p1root, p2root = root / "p1", root / "p2"
            p1root.mkdir()
            p2root.mkdir()
            p1db, p2db = p1root / "ledger.sqlite", p2root / "ledger.sqlite"
            p1 = run_driver(implementation, p1db, "p1")
            if not p1db.is_file():
                return False
            sidecars = [path.name for path in p1root.iterdir() if path.name != "ledger.sqlite"]
            if sidecars:
                return False
            shutil.copy2(p1db, p2db)
            p2 = run_driver(implementation, p2db, "p2")
            p1body = body("P1-receipt-1-X7q").hex()
            p2body = body("P2-receipt-1-X7q").hex()
            expected_p1_call = [["TenantP", "DeployP", 7, "KeyP", {"value": "ValueP"}]]
            expected_p2_call = [["TenantQ", "PromoteQ", 8, "KeyQ", {"value": "ValueQ"}]]
            if p1 != {
                "phase": "p1",
                "responses": [{"status": 200, "body_hex": p1body}, {"status": 200, "body_hex": p1body}],
                "calls": expected_p1_call,
            }:
                return False
            if p2 != {
                "phase": "p2",
                "responses": [{"status": 200, "body_hex": p1body}, {"status": 200, "body_hex": p2body}],
                "calls": expected_p2_call,
            }:
                return False
            connection = sqlite3.connect(p2db)
            try:
                rows = connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
            finally:
                connection.close()
            return rows == 2
    except Exception:
        return False


def check_portability(implementation: Path) -> bool:
    return all(portability_probe(implementation, index) for index in range(10))


def common_controls(implementation: Path) -> tuple[dict[str, bool], dict[str, int]]:
    def invalid_requests() -> bool:
        try:
            package = load(implementation)
            calls: list[Any] = []
            with tempfile.TemporaryDirectory(prefix="v52-receipt-invalid-") as raw:
                db = Path(raw) / "ledger.sqlite"
                with TestClient(package.create_app(db, lambda *args: calls.append(args) or "Never")) as client:
                    responses = [
                        client.post("/commands/Bad$Path", headers={"X-Tenant": "T", "X-API-Revision": "1", "Idempotency-Key": "K"}, json={"value": "V"}),
                        client.post("/commands/C", headers={"X-API-Revision": "1", "Idempotency-Key": "K"}, json={"value": "V"}),
                        client.post("/commands/C", headers={"X-Tenant": "T", "X-API-Revision": "01", "Idempotency-Key": "K"}, json={"value": "V"}),
                        client.post("/commands/C", headers={"X-Tenant": "T", "X-API-Revision": "1", "Idempotency-Key": "bad/key"}, json={"value": "V"}),
                        client.post("/commands/C", headers={"X-Tenant": "T", "X-API-Revision": "1", "Idempotency-Key": "K"}, json={"other": "V"}),
                    ]
                connection = sqlite3.connect(db)
                try:
                    rows = connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
                finally:
                    connection.close()
                return all(response.status_code == 422 for response in responses) and calls == [] and rows == 0
        except Exception:
            return False

    def failure_nonadmission() -> bool:
        try:
            package = load(implementation)
            attempts = 0

            def callback(*args):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("controlled")
                return "Recovered-Q7"

            with tempfile.TemporaryDirectory(prefix="v52-receipt-failure-") as raw:
                db = Path(raw) / "ledger.sqlite"
                with TestClient(package.create_app(db, callback)) as client:
                    identity = ("Tenant", "Command", 9, "Key")
                    first = post(client, identity, "Value")
                    second = post(client, identity, "Value")
                return first.status_code == 503 and second.status_code == 200 and second.content == body("Recovered-Q7") and attempts == 2
        except Exception:
            return False

    def boundaries() -> bool:
        try:
            package = load(implementation)
            calls = 0

            def callback(*args):
                nonlocal calls
                calls += 1
                return "R"

            with tempfile.TemporaryDirectory(prefix="v52-receipt-bound-") as raw:
                with TestClient(package.create_app(Path(raw) / "ledger.sqlite", callback)) as client:
                    first = post(client, ("A", "Z" * 64, 1, "K"), "V")
                    second = post(client, ("T" * 64, "C", 9223372036854775807, "I" * 64), "X" * 64)
                return first.status_code == second.status_code == 200 and calls == 2
        except Exception:
            return False

    controls = {
        "receipt_invalid_request_guard": invalid_requests(),
        "receipt_failure_nonadmission": failure_nonadmission(),
        "receipt_boundaries": boundaries(),
    }
    return controls, {"receipt_invalid_request_guard": 5, "receipt_failure_nonadmission": 2, "receipt_boundaries": 2}


def materialize(mutant: str, temporary: Path) -> Path:
    sys.path.insert(0, str(ROOT / "benchmarks/grading-env"))
    try:
        from materialize_v5_crypto_mutants import materialize_mutant
        return materialize_mutant(REFERENCE, "portable-command-receipt-ledger", mutant, temporary / mutant)
    finally:
        sys.path.pop(0)


def evaluate(implementation: Path, name: str) -> dict[str, Any]:
    common, counts = common_controls(implementation)
    checks = {
        "receipt_key_identity": check_identity(implementation, "receipt_key_identity"),
        "receipt_tenant_identity": check_identity(implementation, "receipt_tenant_identity"),
        "receipt_command_identity": check_identity(implementation, "receipt_command_identity"),
        "receipt_revision_identity": check_identity(implementation, "receipt_revision_identity"),
        "receipt_process_portability": check_portability(implementation),
    }
    return {
        "implementation": name,
        "checks": checks,
        "failed": [check for check in CHECKS if not checks[check]],
        "passed": [check for check in CHECKS if checks[check]],
        "common_controls": common,
        "common_failed": [check for check, passed in common.items() if not passed],
        "common_probe_counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    matrix: list[dict[str, Any]] = []
    if args.workspace:
        matrix.append(evaluate(args.workspace.resolve(), "candidate"))
    else:
        with tempfile.TemporaryDirectory(prefix="v52-receipt-") as raw:
            temporary = Path(raw)
            matrix.append(evaluate(REFERENCE, "reference"))
            for mutant in MUTANTS + [NEAR]:
                matrix.append(evaluate(materialize(mutant, temporary), mutant))
    if args.workspace:
        ok = not matrix[0]["failed"] and not matrix[0]["common_failed"]
    else:
        ok = (
            not matrix[0]["failed"]
            and not matrix[0]["common_failed"]
            and all(row["failed"] == [row["implementation"]] and not row["common_failed"] for row in matrix[1:6])
            and matrix[6]["failed"] == ["receipt_key_identity"]
            and not matrix[6]["common_failed"]
        )
    print(
        json.dumps(
            {
                "task_id": "portable-command-receipt-ledger",
                "ok": ok,
                "checks": list(CHECKS),
                "probe_counts": PROBES,
                "total_scored_probes_per_implementation": 50,
                "matrix": matrix,
                "target_model_calls": 0,
                "efficacy_cells": False,
            },
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
