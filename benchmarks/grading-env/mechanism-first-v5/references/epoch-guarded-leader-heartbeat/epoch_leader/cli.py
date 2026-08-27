from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RFC3339 = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})")
MUTANT = os.environ.get("AGENTHARNESS_MUTANT", "")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_INT = 9223372036854775807


class Reject(Exception):
    pass


class StrictParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Reject("invalid arguments")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def envelope(value: Any) -> bytes:
    return canonical({"result": value, "status": "ok"})


def load(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Reject("duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(Reject("invalid JSON constant")))
    except Reject:
        raise
    except Exception as exc:
        raise Reject("invalid request JSON") from exc


def exact(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise Reject("invalid request shape")
    return value


def identifier(value: Any) -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise Reject("invalid identifier")
    return value


def integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise Reject("invalid integer")
    return value


def instant(value: Any) -> int:
    if not isinstance(value, str) or RFC3339.fullmatch(value) is None:
        raise Reject("invalid RFC3339 instant")
    if re.search(r":60(?:[.,]|Z|[+-])", value):
        raise Reject("leap second")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise Reject("invalid RFC3339 instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Reject("naive instant")
    delta = parsed.astimezone(UTC) - EPOCH
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    if not -62135596800000000 <= micros <= 253402300799999999:
        raise Reject("instant out of range")
    return micros


def render(micros: int) -> str:
    try:
        value = EPOCH + timedelta(microseconds=micros)
    except OverflowError as exc:
        raise Reject("instant overflow") from exc
    base = f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    fraction = f"{value.microsecond:06d}".rstrip("0")
    return base + (f".{fraction}" if fraction else "") + "Z"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS campaign(singleton INTEGER PRIMARY KEY CHECK(singleton=1),campaign_id TEXT NOT NULL,ttl_seconds INTEGER NOT NULL,current_leader TEXT,current_epoch INTEGER NOT NULL,expires_at_us INTEGER,next_sequence INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS publications(sequence INTEGER PRIMARY KEY,leader_id TEXT NOT NULL,epoch INTEGER NOT NULL,payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,envelope BLOB NOT NULL)")


def initialized(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ready = tables == {"campaign", "publications", "requests"} and conn.execute("SELECT COUNT(*) FROM campaign WHERE singleton=1").fetchone()[0] == 1
        conn.close()
        return ready
    except sqlite3.Error:
        return False


def digest(command: str, body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical({"command": command, "request": body})).hexdigest()


def result_leader(row: sqlite3.Row) -> dict[str, Any]:
    return {"campaign_id": row["campaign_id"], "epoch": row["current_epoch"], "expires_at": render(row["expires_at_us"]), "leader_id": row["current_leader"]}


def replay_or_begin(conn: sqlite3.Connection, command: str, body: dict[str, Any]) -> tuple[str, bytes | None]:
    request_id = identifier(body.get("request_id"))
    request_hash = digest(command, body)
    old = conn.execute("SELECT request_hash,envelope FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if old is None:
        return request_hash, None
    if old["request_hash"] != request_hash:
        raise Reject("request_id conflict")
    return request_hash, bytes(old["envelope"])


def commit_result(conn: sqlite3.Connection, request_id: str, request_hash: str, data: bytes) -> bytes:
    conn.execute("INSERT INTO requests VALUES(?,?,?)", (request_id, request_hash, data))
    conn.commit()
    return data


def mutate(command: str, body: dict[str, Any], db: Path) -> bytes:
    if command == "acquire":
        exact(body, {"request_id", "campaign_id", "ttl_seconds", "leader_id", "now"})
        campaign_id = identifier(body["campaign_id"]); leader_id = identifier(body["leader_id"])
        ttl = integer(body["ttl_seconds"], 1, 86400); now = instant(body["now"])
        if now > 253402300799999999 - ttl * 1_000_000:
            raise Reject("expiry overflow")
    else:
        if not initialized(db):
            raise Reject("campaign not initialized")
        required = {"request_id", "leader_id", "epoch", "now"} | ({"payload_object"} if command == "publish" else set())
        exact(body, required)
        leader_id = identifier(body["leader_id"]); epoch = integer(body["epoch"], 1, MAX_INT); now = instant(body["now"])
        if command == "publish" and not isinstance(body["payload_object"], dict):
            raise Reject("payload must be object")
    was_initialized = initialized(db)
    conn = connect(db)
    if command == "acquire" and not was_initialized:
        conn.execute("PRAGMA journal_mode=WAL")
    optimistic_acquire = False
    if command == "acquire" and MUTANT == "leader_one_winner":
        observed = conn.execute("SELECT expires_at_us FROM campaign WHERE singleton=1").fetchone() if was_initialized else None
        optimistic_acquire = observed is None or now >= observed["expires_at_us"]
        if optimistic_acquire:
            time.sleep(0.15)
    outside_sequence: int | None = None
    if command == "publish" and MUTANT == "leader_publication_order":
        existing = conn.execute("SELECT next_sequence FROM campaign WHERE singleton=1").fetchone()
        outside_sequence = existing[0] if existing else 1
        time.sleep(0.15)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if command == "acquire":
            schema(conn)
        request_hash, replay = replay_or_begin(conn, command, body)
        if replay is not None:
            conn.rollback()
            return replay
        request_id = body["request_id"]
        row = conn.execute("SELECT * FROM campaign WHERE singleton=1").fetchone()
        if command == "acquire":
            if row is None:
                conn.execute("INSERT INTO campaign VALUES(1,?,?,?,?,?,1)", (campaign_id, ttl, leader_id, 1, now + ttl * 1_000_000))
            else:
                if row["campaign_id"] != campaign_id or row["ttl_seconds"] != ttl:
                    raise Reject("campaign mismatch")
                active = now <= row["expires_at_us"] if MUTANT == "leader_expiry_boundary" else now < row["expires_at_us"]
                if active:
                    if MUTANT == "leader_one_winner" and optimistic_acquire:
                        fake = {"campaign_id": campaign_id, "epoch": row["current_epoch"], "expires_at": render(now + ttl * 1_000_000), "leader_id": leader_id}
                        return commit_result(conn, request_id, request_hash, envelope(fake))
                    raise Reject("leader active")
                next_epoch = 7 if MUTANT == "leader_epoch_monotonic" else row["current_epoch"] + 1
                if next_epoch > MAX_INT:
                    raise Reject("epoch overflow")
                conn.execute("UPDATE campaign SET current_leader=?,current_epoch=?,expires_at_us=? WHERE singleton=1", (leader_id, next_epoch, now + ttl * 1_000_000))
            current = conn.execute("SELECT * FROM campaign WHERE singleton=1").fetchone()
            return commit_result(conn, request_id, request_hash, envelope(result_leader(current)))
        assert row is not None
        epoch_bypass = MUTANT == "leader_stale_epoch_publish" or (MUTANT == "leader_epoch_heartbeat_near_miss" and command == "publish")
        if row["current_leader"] != leader_id or (row["current_epoch"] != epoch and not epoch_bypass) or now >= row["expires_at_us"]:
            raise Reject("stale leader generation")
        if command == "heartbeat":
            expiry = now + row["ttl_seconds"] * 1_000_000
            if expiry > 253402300799999999:
                raise Reject("expiry overflow")
            conn.execute("UPDATE campaign SET expires_at_us=? WHERE singleton=1", (expiry,))
            current = conn.execute("SELECT * FROM campaign WHERE singleton=1").fetchone()
            return commit_result(conn, request_id, request_hash, envelope(result_leader(current)))
        payload_text = canonical(body["payload_object"]).decode().rstrip("\n")
        payload_hash = hashlib.sha256(payload_text.encode()).hexdigest()
        sequence = outside_sequence if outside_sequence is not None else row["next_sequence"]
        conn.execute("INSERT INTO publications VALUES(?,?,?,?,?)", (sequence, leader_id, epoch, payload_hash, payload_text))
        conn.execute("UPDATE campaign SET next_sequence=? WHERE singleton=1", (sequence + 1,))
        data = envelope({"epoch": epoch, "leader_id": leader_id, "payload_sha256": payload_hash, "sequence": sequence})
        return commit_result(conn, request_id, request_hash, data)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def status(body: dict[str, Any], db: Path) -> bytes:
    exact(body, {"now"}); now = instant(body["now"])
    if not db.is_file():
        raise Reject("campaign not initialized")
    conn = connect(db)
    try:
        row = conn.execute("SELECT * FROM campaign WHERE singleton=1").fetchone()
        if row is None:
            raise Reject("campaign not initialized")
        leader = {"active": now < row["expires_at_us"], "epoch": row["current_epoch"], "expires_at": render(row["expires_at_us"]), "leader_id": row["current_leader"]}
        publications = []
        for item in conn.execute("SELECT * FROM publications ORDER BY sequence"):
            publications.append({"epoch": item["epoch"], "leader_id": item["leader_id"], "payload": json.loads(item["payload_json"]), "payload_sha256": item["payload_sha256"], "sequence": item["sequence"]})
        return envelope({"campaign_id": row["campaign_id"], "leader": leader, "publications": publications, "ttl_seconds": row["ttl_seconds"]})
    finally:
        conn.close()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".leader-result-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = StrictParser(add_help=False)
    parser.add_argument("command", choices=("acquire", "heartbeat", "publish", "status"))
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        body = load(args.request)
        data = status(body, args.db) if args.command == "status" else mutate(args.command, body, args.db)
        write_atomic(args.output, data)
        return 0
    except Exception as exc:
        sys.stderr.write(f"epoch_leader: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
