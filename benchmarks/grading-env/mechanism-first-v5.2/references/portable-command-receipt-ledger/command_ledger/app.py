from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RECEIPT = re.compile(r"[\x21-\x7e]{1,128}")
MAX = 9223372036854775807


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _identity(tenant: str, command: str, revision: int, key: str) -> tuple[str, str, int, str]:
    return tenant, command, revision, key


def _valid_revision(value: str) -> int | None:
    if not value or not value.isascii() or not value.isdecimal() or (len(value) > 1 and value[0] == "0"):
        return None
    revision = int(value)
    return revision if 1 <= revision <= MAX else None


def _run(
    db_path: Path,
    execute_once: Callable[[str, str, int, str, dict[str, Any]], str],
    identity: tuple[str, str, int, str],
    callback_identity: tuple[str, str, int, str],
    payload: dict[str, Any],
) -> bytes:
    connection = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT response_body FROM receipts WHERE tenant=? AND command=? AND api_revision=? AND idempotency_key=?",
            identity,
        ).fetchone()
        if row is not None:
            body = bytes(row[0])
            connection.commit()
            return body
        receipt = execute_once(*callback_identity, payload)
        if not isinstance(receipt, str) or RECEIPT.fullmatch(receipt) is None:
            raise ValueError("invalid receipt")
        body = _json({"receipt": receipt})
        connection.execute(
            "INSERT INTO receipts(tenant,command,api_revision,idempotency_key,response_body) VALUES(?,?,?,?,?)",
            (*identity, body),
        )
        connection.commit()
        return body
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_app(db_path: str | Path, execute_once: Callable[[str, str, int, str, dict[str, Any]], str]) -> FastAPI:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS receipts("
            "tenant TEXT NOT NULL,command TEXT NOT NULL,api_revision INTEGER NOT NULL,"
            "idempotency_key TEXT NOT NULL,response_body BLOB NOT NULL,"
            "PRIMARY KEY(tenant,command,api_revision,idempotency_key))"
        )
        connection.commit()
    finally:
        connection.close()
    app = FastAPI()

    @app.post("/commands/{command}")
    async def command_endpoint(command: str, request: Request) -> Response:
        tenant = request.headers.get("x-tenant")
        revision_raw = request.headers.get("x-api-revision")
        key = request.headers.get("idempotency-key")
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"detail": "invalid_request"}, status_code=422)
        revision = _valid_revision(revision_raw) if isinstance(revision_raw, str) else None
        if (
            ID.fullmatch(command) is None
            or not isinstance(tenant, str)
            or ID.fullmatch(tenant) is None
            or not isinstance(key, str)
            or ID.fullmatch(key) is None
            or revision is None
            or not isinstance(payload, dict)
            or set(payload) != {"value"}
            or not isinstance(payload["value"], str)
            or ID.fullmatch(payload["value"]) is None
        ):
            return JSONResponse({"detail": "invalid_request"}, status_code=422)
        identity = _identity(tenant, command, revision, key)
        callback_identity = (tenant, command, revision, key)
        try:
            body = _run(path, execute_once, identity, callback_identity, payload)
        except Exception:
            return JSONResponse({"detail": "execution_failure"}, status_code=503)
        return Response(body, status_code=200, media_type="application/json")

    return app
