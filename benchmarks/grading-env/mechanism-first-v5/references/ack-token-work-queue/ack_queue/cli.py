from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
TOKEN = re.compile(r"[0-9a-f]{64}")
MUTANT = os.environ.get("AGENTHARNESS_MUTANT", "")


class Reject(Exception):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def envelope(result: Any) -> bytes:
    return canonical({"result": result, "status": "ok"})


def load(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Reject("duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(Reject(f"invalid JSON constant {value}")))
    except Reject:
        raise
    except Exception as exc:
        raise Reject("invalid request JSON") from exc


def exact(body: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) != keys:
        raise Reject("invalid request shape")
    return body


def valid_id(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Reject("invalid identifier")
    return value


def integer(value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > 9223372036854775807:
        raise Reject("invalid integer")
    return value


def job(row: sqlite3.Row, now: int | None = None) -> dict[str, Any]:
    state, worker, token, expires = row["state"], row["worker"], row["token"], row["expires_at"]
    expired = state == "claimed" and now is not None and (now > expires if MUTANT == "ack_visibility_timeout" else now >= expires)
    if expired:
        state, worker, token, expires = "available", None, None, None
    return {"attempts": row["attempts"], "expires_at": expires, "job_id": row["job_id"], "payload": json.loads(row["payload_json"]), "state": state, "token": token, "worker": worker}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def schema(conn: sqlite3.Connection) -> None:
    conn.executescript("CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,state TEXT NOT NULL,worker TEXT,token TEXT,expires_at INTEGER,attempts INTEGER NOT NULL);CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,envelope BLOB NOT NULL);")


def digest(command: str, body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical({"command": command, "request": body})).hexdigest()


def replay_or_begin(conn: sqlite3.Connection, command: str, body: dict[str, Any]) -> tuple[str, bytes | None]:
    request_id = valid_id(body.get("request_id"))
    request_hash = digest(command, body)
    conn.execute("BEGIN IMMEDIATE")
    old = conn.execute("SELECT request_hash,envelope FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if old is not None:
        if old["request_hash"] != request_hash:
            raise Reject("request_id conflict")
        return request_hash, bytes(old["envelope"])
    return request_hash, None


def store(conn: sqlite3.Connection, request_id: str, request_hash: str, data: bytes) -> bytes:
    conn.execute("INSERT INTO requests VALUES(?,?,?)", (request_id, request_hash, data))
    conn.commit()
    return data


def mutate(command: str, body: dict[str, Any], db: Path) -> bytes:
    if not db.is_file():
        raise Reject("queue is not initialized")
    conn = connect(db)
    try:
        near_miss_precheck = None
        if MUTANT == "ack_stale_toctou" and command in {"ack", "nack"}:
            candidate = exact(body, {"request_id", "worker", "job_id", "token", "now"})
            pre = conn.execute("SELECT state,worker,token,expires_at FROM jobs WHERE job_id=?", (candidate["job_id"],)).fetchone()
            near_miss_precheck = pre is not None and pre["state"] == "claimed" and pre["worker"] == candidate["worker"] and pre["token"] == candidate["token"]
        request_hash, replay = replay_or_begin(conn, command, body)
        if replay is not None:
            conn.rollback()
            return replay
        request_id = body["request_id"]
        if command == "enqueue":
            exact(body, {"request_id", "job_id", "payload_object"})
            job_id = valid_id(body["job_id"])
            if not isinstance(body["payload_object"], dict):
                raise Reject("payload_object must be object")
            if conn.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone():
                raise Reject("job conflict")
            payload_json = canonical(body["payload_object"]).decode().rstrip("\n")
            conn.execute("INSERT INTO jobs VALUES(?,?,\"available\",NULL,NULL,NULL,0)", (job_id, payload_json))
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return store(conn, request_id, request_hash, envelope(job(row)))
        if command == "claim":
            exact(body, {"request_id", "worker", "now", "lease_seconds"})
            worker, now, lease = valid_id(body["worker"]), integer(body["now"]), integer(body["lease_seconds"], positive=True)
            if now > 9223372036854775807 - lease:
                raise Reject("lease expiry overflow")
            comparison = ">" if MUTANT == "ack_visibility_timeout" else ">="
            row = conn.execute(f"SELECT * FROM jobs WHERE state='available' OR (state='claimed' AND ? {comparison} expires_at) ORDER BY job_id LIMIT 1", (now,)).fetchone()
            if row is None:
                claimed = conn.execute("SELECT * FROM jobs WHERE state='claimed' ORDER BY job_id LIMIT 1").fetchone()
                if MUTANT == "ack_single_claim" and claimed is not None:
                    fake = dict(job(claimed)); fake["worker"] = worker; fake["token"] = secrets.token_hex(32); fake["expires_at"] = now + lease
                    data = envelope(fake)
                    return store(conn, request_id, request_hash, data)
                if MUTANT == "ack_attempt_accounting" and claimed is not None:
                    conn.execute("UPDATE jobs SET attempts=attempts+1 WHERE job_id=?", (claimed["job_id"],))
                return store(conn, request_id, request_hash, envelope(None))
            token = secrets.token_hex(32)
            conn.execute("UPDATE jobs SET state='claimed',worker=?,token=?,expires_at=?,attempts=attempts+1 WHERE job_id=?", (worker, token, now + lease, row["job_id"]))
            current = conn.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
            return store(conn, request_id, request_hash, envelope(job(current)))
        if command in {"ack", "nack"}:
            exact(body, {"request_id", "worker", "job_id", "token", "now"})
            worker, job_id = valid_id(body["worker"]), valid_id(body["job_id"])
            token, now = body["token"], integer(body["now"])
            if not isinstance(token, str) or not TOKEN.fullmatch(token):
                raise Reject("invalid token")
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            token_ok = row is not None and (row["token"] == token or MUTANT == "ack_stale_worker_rejected" or (MUTANT == "ack_stale_toctou" and near_miss_precheck))
            worker_ok = row is not None and (row["worker"] == worker or (MUTANT == "ack_stale_toctou" and near_miss_precheck))
            if row is None or row["state"] != "claimed" or not worker_ok or not token_ok or now >= row["expires_at"]:
                raise Reject("ownership mismatch")
            if command == "ack":
                conn.execute("UPDATE jobs SET state='completed',worker=NULL,token=NULL,expires_at=NULL WHERE job_id=?", (job_id,))
            else:
                payload = "{}" if MUTANT == "ack_nack_requeues" else row["payload_json"]
                conn.execute("UPDATE jobs SET state='available',worker=NULL,token=NULL,expires_at=NULL,payload_json=? WHERE job_id=?", (payload, job_id))
            current = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return store(conn, request_id, request_hash, envelope(job(current)))
        raise Reject("unknown mutation")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read(command: str, body: dict[str, Any], db: Path) -> bytes:
    if not db.is_file():
        raise Reject("queue is not initialized")
    conn = connect(db)
    try:
        if command == "get":
            exact(body, {"job_id", "now"}); job_id, now = valid_id(body["job_id"]), integer(body["now"])
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None: raise Reject("job not found")
            return envelope(job(row, now))
        exact(body, {"request_id"}); request_id = valid_id(body["request_id"])
        row = conn.execute("SELECT envelope FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None: raise Reject("request not found")
        return bytes(row["envelope"])
    finally:
        conn.close()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ack-result-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "enqueue", "claim", "ack", "nack", "get", "result"))
    parser.add_argument("--db", required=True, type=Path); parser.add_argument("--request", required=True, type=Path); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        body = load(args.request)
        if args.command == "init":
            exact(body, set()); conn = connect(args.db); schema(conn); conn.commit(); conn.close(); data = envelope({"initialized": True})
        elif args.command in {"enqueue", "claim", "ack", "nack"}:
            data = mutate(args.command, body, args.db)
        else:
            data = read(args.command, body, args.db)
        write_atomic(args.output, data)
        return 0
    except Exception as exc:
        print(f"ack_queue: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
