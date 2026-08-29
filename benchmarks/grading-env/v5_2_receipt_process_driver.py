from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def load(workspace: Path):
    sys.path.insert(0, str(workspace))
    try:
        return importlib.import_module("command_ledger")
    finally:
        sys.path.pop(0)


def post(client: TestClient, tenant: str, command: str, revision: int, key: str, value: str):
    return client.post(
        f"/commands/{command}",
        headers={"X-Tenant": tenant, "X-API-Revision": str(revision), "Idempotency-Key": key},
        json={"value": value},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--phase", choices=("p1", "p2"), required=True)
    args = parser.parse_args()
    package = load(args.workspace.resolve())
    calls: list[list[object]] = []

    def execute_once(tenant: str, command: str, revision: int, key: str, payload: dict[str, object]) -> str:
        calls.append([tenant, command, revision, key, payload])
        return f"{args.phase.upper()}-receipt-{len(calls)}-X7q"

    with TestClient(package.create_app(args.db.resolve(), execute_once)) as client:
        if args.phase == "p1":
            first = post(client, "TenantP", "DeployP", 7, "KeyP", "ValueP")
            replay = post(client, "TenantP", "DeployP", 7, "KeyP", "ValueP")
            rows = [first, replay]
        else:
            replay = post(client, "TenantP", "DeployP", 7, "KeyP", "ValueP")
            positive = post(client, "TenantQ", "PromoteQ", 8, "KeyQ", "ValueQ")
            rows = [replay, positive]
    print(
        json.dumps(
            {
                "phase": args.phase,
                "responses": [{"status": row.status_code, "body_hex": row.content.hex()} for row in rows],
                "calls": calls,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
