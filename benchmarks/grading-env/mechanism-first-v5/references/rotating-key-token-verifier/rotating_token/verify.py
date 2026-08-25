from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
B64_RE = re.compile(r"[A-Za-z0-9_-]+\Z")
HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
RFC3339_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z")
TOKEN_KEYS = {"aud", "exp", "iat", "iss", "jti", "nbf", "sub"}
HEADER_KEYS = {"alg", "kid"}
KEY_KEYS = {"kid", "alg", "secret_hex", "active_from", "retire_at"}


class Rejection(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def strict_json(raw: bytes, *, token_part: bool = False) -> dict[str, Any]:
    duplicate = False

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                duplicate = True
            out[key] = value
        return out

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(Rejection(f"non-finite {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, Rejection) as exc:
        raise Rejection("invalid JSON") from exc
    allow_duplicate = token_part and os.environ.get("AGENTHARNESS_MUTANT") == "token_canonical_encoding"
    if duplicate and not allow_duplicate:
        raise Rejection("duplicate JSON key")
    if not isinstance(value, dict):
        raise Rejection("JSON object required")
    if not allow_duplicate and canonical(value) != raw:
        raise Rejection("non-canonical JSON")
    return value


def parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not RFC3339_RE.fullmatch(value) or ":60" in value:
        raise Rejection("invalid RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Rejection("invalid RFC3339") from exc
    if parsed.utcoffset() is None:
        raise Rejection("timezone required")
    return parsed


def decode_segment(segment: str) -> bytes:
    if not segment or not B64_RE.fullmatch(segment) or "=" in segment:
        raise Rejection("invalid base64url")
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * ((-len(segment)) % 4))
    except Exception as exc:
        raise Rejection("invalid base64url") from exc
    if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != segment:
        raise Rejection("non-canonical base64url")
    return raw


def exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise Rejection("invalid schema")


def validate_id(value: Any) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise Rejection("invalid ID")
    return value


def load_keyring(path: Path) -> list[dict[str, Any]]:
    try:
        root = strict_json(path.read_bytes())
    except OSError as exc:
        raise Rejection("keyring unavailable") from exc
    exact_keys(root, {"schema_version", "keys"})
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise Rejection("invalid keyring version")
    if not isinstance(root["keys"], list) or not root["keys"]:
        raise Rejection("invalid keyring")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in root["keys"]:
        if not isinstance(row, dict):
            raise Rejection("invalid key")
        exact_keys(row, KEY_KEYS)
        kid = validate_id(row["kid"])
        if kid in seen:
            raise Rejection("duplicate key")
        seen.add(kid)
        if row["alg"] != "HS256" or not isinstance(row["alg"], str):
            raise Rejection("invalid algorithm")
        if not isinstance(row["secret_hex"], str) or not HEX64_RE.fullmatch(row["secret_hex"]):
            raise Rejection("invalid secret")
        start, end = parse_time(row["active_from"]), parse_time(row["retire_at"])
        if not start < end:
            raise Rejection("invalid key window")
        rows.append({**row, "start": start, "end": end})
    return rows


def verify_token(*, token: str, keyring_path: Path, issuer: str, audience: str, as_of: str) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        raise Rejection("invalid token")
    header_segment, payload_segment, signature_segment = token.split(".")
    header = strict_json(decode_segment(header_segment), token_part=True)
    payload = strict_json(decode_segment(payload_segment), token_part=True)
    exact_keys(header, HEADER_KEYS)
    exact_keys(payload, TOKEN_KEYS)
    kid = validate_id(header["kid"])
    validate_id(payload["sub"])
    validate_id(payload["jti"])
    if not isinstance(payload["iss"], str) or not payload["iss"]:
        raise Rejection("invalid issuer")
    audiences = payload["aud"]
    if not isinstance(audiences, list) or not audiences or any(not isinstance(item, str) or not item for item in audiences) or len(set(audiences)) != len(audiences):
        raise Rejection("invalid audience")
    for name in ("iat", "nbf", "exp"):
        if type(payload[name]) is not int or not 0 <= payload[name] <= 2**63 - 1:
            raise Rejection("invalid time claim")
    if payload["nbf"] >= payload["exp"]:
        raise Rejection("invalid time interval")
    selected = next((row for row in load_keyring(keyring_path) if row["kid"] == kid), None)
    if selected is None:
        raise Rejection("unknown key")
    mutant = os.environ.get("AGENTHARNESS_MUTANT", "")
    algorithm = header.get("alg")
    if mutant == "token_algorithm_pin":
        if algorithm not in {"HS256", "HS512"}:
            raise Rejection("invalid algorithm")
        digest = hashlib.sha256 if algorithm == "HS256" else hashlib.sha512
    else:
        if algorithm != "HS256" or selected["alg"] != "HS256":
            raise Rejection("invalid algorithm")
        digest = hashlib.sha256
    signature = decode_segment(signature_segment)
    expected = hmac.new(bytes.fromhex(selected["secret_hex"]), f"{header_segment}.{payload_segment}".encode("ascii"), digest).digest()
    if not hmac.compare_digest(signature, expected):
        raise Rejection("invalid signature")
    now = parse_time(as_of)
    if now < selected["start"]:
        raise Rejection("key inactive")
    if mutant != "token_rotation_window" and now >= selected["end"]:
        raise Rejection("key retired")
    timestamp = int(now.timestamp())
    if timestamp < payload["nbf"]:
        raise Rejection("token not active")
    if (timestamp > payload["exp"] if mutant == "token_time_claims" else timestamp >= payload["exp"]):
        raise Rejection("token expired")
    if payload["iss"] != issuer:
        raise Rejection("issuer mismatch")
    if mutant != "token_issuer_audience" and audience not in audiences:
        raise Rejection("audience mismatch")
    return {
        "alg": algorithm,
        "aud": audiences,
        "exp": payload["exp"],
        "iat": payload["iat"],
        "iss": payload["iss"],
        "jti": payload["jti"],
        "kid": kid,
        "nbf": payload["nbf"],
        "ok": True,
        "sub": payload["sub"],
    }


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        report = verify_token(token=args.token, keyring_path=args.keyring, issuer=args.issuer, audience=args.audience, as_of=args.as_of)
        atomic_write(args.output, canonical(report) + b"\n")
        return 0
    except (Rejection, OSError, ValueError) as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
