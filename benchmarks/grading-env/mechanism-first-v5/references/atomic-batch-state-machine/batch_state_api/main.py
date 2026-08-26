from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LEGAL = {("pending", "active"), ("active", "suspended"), ("suspended", "active"), ("active", "closed"), ("suspended", "closed")}
MUTANT = os.environ.get("AGENTHARNESS_MUTANT", "")
DB_PATH = Path(os.environ.get("BATCH_STATE_DB", "batch-state.sqlite3")).resolve()
app = FastAPI()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


def response(value: Any, status: int = 200) -> Response:
    return Response(canonical(value), status_code=status, media_type="application/json")


def error(code: str, status: int, index: int | None = None, total: int = 0) -> Response:
    detail: dict[str, Any] = {"code": code}
    if index is not None:
        detail["index"] = total - 1 if MUTANT == "batch_error_index" else index
    return response({"detail": detail}, status)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def normalize(body: Any) -> tuple[str, list[dict[str, Any]]] | Response:
    if not isinstance(body, dict) or set(body) != {"command_id", "operations"}:
        return error("invalid_operation", 422, 0, 1)
    command_id = body["command_id"]
    operations = body["operations"]
    if not isinstance(command_id, str) or not ID.fullmatch(command_id) or not isinstance(operations, list) or not 1 <= len(operations) <= 32:
        return error("invalid_operation", 422, 0, max(1, len(operations) if isinstance(operations, list) else 1))
    ordered_raw = sorted(operations, key=lambda op: op.get("entity_id", "") if isinstance(op, dict) and isinstance(op.get("entity_id", ""), str) else "")
    for index, op in enumerate(ordered_raw):
        if not isinstance(op, dict) or set(op) != {"entity_id", "expected_version", "transition"}:
            return error("invalid_operation", 422, index, len(operations))
        if not isinstance(op["entity_id"], str) or not ID.fullmatch(op["entity_id"]):
            return error("invalid_operation", 422, index, len(operations))
        if type(op["expected_version"]) is not int or op["expected_version"] < 0:
            return error("invalid_operation", 422, index, len(operations))
        if not isinstance(op["transition"], str) or op["transition"] not in {"pending", "active", "suspended", "closed"}:
            return error("invalid_operation", 422, index, len(operations))
    return command_id, ordered_raw


def load_body(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)


def command_digest(command_id: str, ordered: list[dict[str, Any]], raw_operations: list[dict[str, Any]]) -> str:
    operations = raw_operations if MUTANT == "batch_idempotent_replay" else ordered
    material = {"command_id": command_id, "operations": operations}
    return hashlib.sha256(canonical(material)[:-1]).hexdigest()


def success_payload(command_id: str, rows: list[dict[str, Any]], request_order: list[str]) -> dict[str, Any]:
    if MUTANT == "batch_response_order":
        positions = {entity_id: index for index, entity_id in enumerate(request_order)}
        rows = sorted(rows, key=lambda row: positions[row["entity_id"]])
    else:
        rows = sorted(rows, key=lambda row: row["entity_id"])
    return {"command_id": command_id, "entities": rows}


def sequential_bug(command_id: str, ordered: list[dict[str, Any]], request_order: list[str], digest: str, duplicate_mode: bool) -> Response:
    committed: list[dict[str, Any]] = []
    for index, op in enumerate(ordered):
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state,version FROM entities WHERE entity_id=?", (op["entity_id"],)).fetchone()
            if row is None:
                conn.rollback(); return error("not_found", 404, index, len(ordered))
            if (row["state"], op["transition"]) not in LEGAL:
                conn.rollback(); return error("illegal_transition", 422, index, len(ordered))
            if row["version"] != op["expected_version"]:
                conn.rollback(); return error("stale_version", 409, index, len(ordered))
            new_version = row["version"] + 1
            conn.execute("UPDATE entities SET state=?,version=? WHERE entity_id=?", (op["transition"], new_version, op["entity_id"]))
            conn.commit()
            committed.append({"entity_id": op["entity_id"], "state": op["transition"], "version": new_version})
        finally:
            conn.close()
    payload = success_payload(command_id, committed, request_order)
    conn = connect()
    try:
        conn.execute("INSERT INTO commands(command_id,request_hash,response_json) VALUES(?,?,?)", (command_id, digest, canonical(payload).decode()))
        conn.commit()
    finally:
        conn.close()
    return response(payload)


@app.post("/batch-transition")
async def batch_transition(request: Request) -> Response:
    try:
        body = load_body(await request.body())
    except Exception:
        return error("invalid_operation", 422, 0, 1)
    parsed = normalize(body)
    if isinstance(parsed, Response):
        return parsed
    command_id, ordered = parsed
    raw_operations = body["operations"]
    request_order = [op["entity_id"] for op in raw_operations]
    digest = command_digest(command_id, ordered, raw_operations)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT request_hash,response_json FROM commands WHERE command_id=?", (command_id,)).fetchone()
        if existing is not None:
            if existing["request_hash"] != digest:
                return error("command_conflict", 409)
            return Response(existing["response_json"].encode(), status_code=200, media_type="application/json")
        seen: set[str] = set()
        has_duplicate = False
        for index, op in enumerate(ordered):
            if op["entity_id"] in seen:
                has_duplicate = True
                if MUTANT != "batch_duplicate_entity":
                    return error("duplicate_entity", 422, index, len(ordered))
            seen.add(op["entity_id"])
        if MUTANT == "batch_all_or_none":
            for index, op in enumerate(ordered):
                row = conn.execute("SELECT state,version FROM entities WHERE entity_id=?", (op["entity_id"],)).fetchone()
                if row is None:
                    return error("not_found", 404, index, len(ordered))
                if (row["state"], op["transition"]) not in LEGAL:
                    return error("illegal_transition", 422, index, len(ordered))
            conn.close()
            return sequential_bug(command_id, ordered, request_order, digest, False)
        if MUTANT == "batch_duplicate_entity" and has_duplicate:
            conn.close()
            return sequential_bug(command_id, ordered, request_order, digest, True)
        snapshot: dict[str, sqlite3.Row] = {}
        for index, op in enumerate(ordered):
            row = conn.execute("SELECT state,version FROM entities WHERE entity_id=?", (op["entity_id"],)).fetchone()
            if row is None:
                conn.rollback(); return error("not_found", 404, index, len(ordered))
            snapshot[op["entity_id"]] = row
            if (row["state"], op["transition"]) not in LEGAL:
                conn.rollback(); return error("illegal_transition", 422, index, len(ordered))
        for index, op in enumerate(ordered):
            if snapshot[op["entity_id"]]["version"] != op["expected_version"]:
                conn.rollback(); return error("stale_version", 409, index, len(ordered))
        committed=[]
        for op in ordered:
            new_version=snapshot[op["entity_id"]]["version"]+1
            conn.execute("UPDATE entities SET state=?,version=? WHERE entity_id=?",(op["transition"],new_version,op["entity_id"]))
            committed.append({"entity_id":op["entity_id"],"state":op["transition"],"version":new_version})
        payload=success_payload(command_id,committed,request_order)
        conn.execute("INSERT INTO commands(command_id,request_hash,response_json) VALUES(?,?,?)",(command_id,digest,canonical(payload).decode()))
        conn.commit()
        return response(payload)
    except sqlite3.Error:
        try: conn.rollback()
        except sqlite3.Error: pass
        return error("transaction_error",500)
    finally:
        try: conn.close()
        except sqlite3.Error: pass


@app.get("/entities/{entity_id}")
def get_entity(entity_id: str) -> Response:
    conn=connect()
    try: row=conn.execute("SELECT entity_id,state,version FROM entities WHERE entity_id=?",(entity_id,)).fetchone()
    finally: conn.close()
    if row is None: return error("not_found",404)
    return response({"entity_id":row["entity_id"],"state":row["state"],"version":row["version"]})
