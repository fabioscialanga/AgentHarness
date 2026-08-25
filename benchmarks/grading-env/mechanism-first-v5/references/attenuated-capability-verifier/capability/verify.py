from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPABILITY_BASE = {"actions", "depth", "expires_at", "id", "issuer", "max_depth", "not_before", "resource_prefix", "subject", "tenant"}
REQUEST_KEYS = {"action", "path", "subject", "tenant"}
TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
HEX64 = re.compile(r"[0-9a-f]{64}")


class Rejection(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def load_object(path: Path) -> dict[str, Any]:
    duplicate = False
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        out: dict[str, Any] = {}
        for key, value in rows:
            if key in out:
                duplicate = True
            out[key] = value
        return out
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda item: (_ for _ in ()).throw(Rejection(f"non-finite {item}")))
    except Rejection:
        raise
    except Exception as exc:
        raise Rejection("invalid JSON") from exc
    if duplicate or not isinstance(value, dict) or canonical(value) != raw:
        raise Rejection("invalid or non-canonical JSON object")
    return value


def parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        raise Rejection("invalid RFC3339 UTC time")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise Rejection("invalid RFC3339 UTC time") from exc
    return parsed


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise Rejection(f"invalid {name}")
    return value


def canonical_path(value: Any, *, prefix: bool) -> str:
    path = require_text(value, "path")
    if not path.startswith("/") or "?" in path or "#" in path:
        raise Rejection("invalid path")
    if path != "/":
        parts = path.split("/")[1:]
        if prefix:
            if parts[-1] != "":
                raise Rejection("prefix must end with slash")
            parts = parts[:-1]
        elif parts[-1] == "":
            raise Rejection("request path must not end with slash")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise Rejection("invalid path segments")
    return path


def contains_path(prefix: str, path: str) -> bool:
    return prefix == "/" or path == prefix[:-1] or path.startswith(prefix)


def parse_capability(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Rejection("invalid capability")
    expected = CAPABILITY_BASE if index == 0 else CAPABILITY_BASE | {"parent_digest"}
    if set(value) != expected:
        raise Rejection("invalid capability schema")
    for name in ("id", "issuer", "subject", "tenant"):
        require_text(value[name], name)
    canonical_path(value["resource_prefix"], prefix=True)
    actions = value["actions"]
    if not isinstance(actions, list) or not actions or any(not isinstance(item, str) or not item for item in actions) or actions != sorted(set(actions)):
        raise Rejection("invalid actions")
    if type(value["depth"]) is not int or type(value["max_depth"]) is not int or value["depth"] < 0 or value["max_depth"] < 0:
        raise Rejection("invalid depth")
    if parse_time(value["not_before"]) >= parse_time(value["expires_at"]):
        raise Rejection("invalid interval")
    if index and (not isinstance(value["parent_digest"], str) or not HEX64.fullmatch(value["parent_digest"])):
        raise Rejection("invalid parent digest")
    return value


def parse_inputs(chain_path: Path, request_path: Path, keyring_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, bytes]]:
    chain = load_object(chain_path)
    request = load_object(request_path)
    keyring = load_object(keyring_path)
    if set(chain) != {"links", "schema_version"} or chain["schema_version"] != 1 or not isinstance(chain["links"], list) or not chain["links"]:
        raise Rejection("invalid chain schema")
    if set(request) != REQUEST_KEYS:
        raise Rejection("invalid request schema")
    for name in ("action", "subject", "tenant"):
        require_text(request[name], name)
    canonical_path(request["path"], prefix=False)
    if set(keyring) != {"keys", "schema_version"} or keyring["schema_version"] != 1 or not isinstance(keyring["keys"], list):
        raise Rejection("invalid keyring schema")
    keys: dict[str, bytes] = {}
    for row in keyring["keys"]:
        if not isinstance(row, dict) or set(row) != {"delegator", "secret_hex"}:
            raise Rejection("invalid key row")
        delegator = require_text(row["delegator"], "delegator")
        secret_hex = row["secret_hex"]
        if delegator in keys or not isinstance(secret_hex, str) or not HEX64.fullmatch(secret_hex):
            raise Rejection("invalid key row")
        keys[delegator] = bytes.fromhex(secret_hex)
    links: list[dict[str, Any]] = []
    for index, link in enumerate(chain["links"]):
        if not isinstance(link, dict) or set(link) != {"capability", "signature_hex"} or not isinstance(link["signature_hex"], str) or not HEX64.fullmatch(link["signature_hex"]):
            raise Rejection("invalid link")
        links.append({"capability": parse_capability(link["capability"], index), "signature_hex": link["signature_hex"]})
    return links, request, keys


def verify(chain_path: Path, request_path: Path, keyring_path: Path, as_of_text: str) -> dict[str, Any]:
    links, request, keys = parse_inputs(chain_path, request_path, keyring_path)
    as_of = parse_time(as_of_text)
    mutant = os.environ.get("AGENTHARNESS_MUTANT", "")
    ids: set[str] = set()
    ancestor_limits: list[int] = []
    for index, link in enumerate(links):
        cap = link["capability"]
        if cap["id"] in ids:
            raise Rejection("duplicate capability id")
        ids.add(cap["id"])
        signer = cap["issuer"] if index == 0 else links[index - 1]["capability"]["subject"]
        if cap["issuer"] != signer or signer not in keys:
            raise Rejection("unauthorized signer")
        if not (mutant == "capability_chain_signatures" and index < len(links) - 1):
            expected = hmac.new(keys[signer], canonical(cap), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, link["signature_hex"]):
                raise Rejection("invalid signature")
        if mutant != "capability_time_intersection" or index == len(links) - 1:
            if not (parse_time(cap["not_before"]) <= as_of < parse_time(cap["expires_at"])):
                raise Rejection("outside capability interval")
        if index == 0:
            if cap["depth"] != 0 or cap.get("parent_digest") is not None or cap["depth"] > cap["max_depth"]:
                raise Rejection("invalid root depth")
        else:
            parent = links[index - 1]["capability"]
            if cap["parent_digest"] != hashlib.sha256(canonical(parent)).hexdigest():
                raise Rejection("invalid parent digest")
            if mutant != "capability_depth" and cap["depth"] != parent["depth"] + 1:
                raise Rejection("invalid depth increment")
            if cap["tenant"] != parent["tenant"] or not set(cap["actions"]).issubset(parent["actions"]):
                raise Rejection("capability broadens authority")
            if mutant != "capability_attenuation" and not contains_path(parent["resource_prefix"], cap["resource_prefix"][:-1] if cap["resource_prefix"] != "/" else "/"):
                raise Rejection("capability broadens path")
            if mutant != "capability_time_intersection" and (parse_time(cap["not_before"]) < parse_time(parent["not_before"]) or parse_time(cap["expires_at"]) > parse_time(parent["expires_at"])):
                raise Rejection("capability broadens time")
            if mutant != "capability_depth" and cap["max_depth"] > parent["max_depth"]:
                raise Rejection("capability broadens depth")
        ancestor_limits.append(cap["max_depth"])
        if mutant != "capability_depth" and any(cap["depth"] > limit for limit in ancestor_limits):
            raise Rejection("delegation depth exceeded")
    leaf = links[-1]["capability"]
    if request["tenant"] != leaf["tenant"] or request["subject"] != leaf["subject"] or request["action"] not in leaf["actions"]:
        raise Rejection("request not authorized")
    path_ok = leaf["resource_prefix"].rstrip("/") in request["path"] if mutant == "capability_request_match" else contains_path(leaf["resource_prefix"], request["path"])
    if not path_ok:
        raise Rejection("request path not authorized")
    return {"action": request["action"], "allowed": True, "as_of": as_of_text, "capability_id": leaf["id"], "path": request["path"], "subject": request["subject"], "tenant": request["tenant"]}


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chain", type=Path, required=True); parser.add_argument("--request", type=Path, required=True); parser.add_argument("--keyring", type=Path, required=True); parser.add_argument("--as-of", required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = verify(args.chain, args.request, args.keyring, args.as_of)
        atomic_write(args.output, canonical(report))
    except (Rejection, OSError) as exc:
        print(f"rejected: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
