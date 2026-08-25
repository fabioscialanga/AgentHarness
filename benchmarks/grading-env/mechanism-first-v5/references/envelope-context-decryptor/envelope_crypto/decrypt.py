from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
LOWER_HEX_RE = re.compile(r"(?:[0-9a-f]{2})*\Z")
ENVELOPE_KEYS = {"schema_version", "key_id", "nonce", "ciphertext", "tag"}
CONTEXT_KEYS = {"tenant", "purpose", "object_id"}
KEYRING_KEYS = {"schema_version", "keys"}
KEY_KEYS = {"tenant", "key_id", "status", "key_hex"}


class Rejection(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    duplicate = False

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                duplicate = True
            result[key] = value
        return result

    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda item: (_ for _ in ()).throw(Rejection(f"non-finite {item}")))
    except (OSError, UnicodeError, json.JSONDecodeError, Rejection) as exc:
        raise Rejection("invalid JSON") from exc
    if duplicate or not isinstance(value, dict) or canonical(value) != raw:
        raise Rejection("invalid or non-canonical JSON object")
    return value


def exact(value: dict[str, Any], keys: set[str]) -> None:
    if set(value) != keys:
        raise Rejection("invalid schema")


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise Rejection("invalid ID")
    return value


def hex_bytes(value: Any, length: int | None = None) -> bytes:
    if not isinstance(value, str) or not LOWER_HEX_RE.fullmatch(value):
        raise Rejection("invalid hex")
    raw = bytes.fromhex(value)
    if length is not None and len(raw) != length:
        raise Rejection("invalid length")
    return raw


def parse_inputs(envelope_path: Path, context_path: Path, keyring_path: Path) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes, bytes, bytes]:
    envelope, context, keyring = load_json(envelope_path), load_json(context_path), load_json(keyring_path)
    exact(envelope, ENVELOPE_KEYS)
    mutant = os.environ.get("AGENTHARNESS_MUTANT", "")
    if mutant == "envelope_schema":
        context = {key: value for key, value in context.items() if key in CONTEXT_KEYS}
    exact(context, CONTEXT_KEYS)
    exact(keyring, KEYRING_KEYS)
    if type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1:
        raise Rejection("invalid envelope version")
    if type(keyring["schema_version"]) is not int or keyring["schema_version"] != 1 or not isinstance(keyring["keys"], list) or not keyring["keys"]:
        raise Rejection("invalid keyring")
    tenant, purpose, object_id = identifier(context["tenant"]), identifier(context["purpose"]), identifier(context["object_id"])
    key_id = identifier(envelope["key_id"])
    nonce = hex_bytes(envelope["nonce"], 12)
    ciphertext = hex_bytes(envelope["ciphertext"])
    tag = hex_bytes(envelope["tag"])
    allowed_tag_lengths = {12, 16} if mutant == "envelope_nonce_tag" else {16}
    if len(tag) not in allowed_tag_lengths:
        raise Rejection("invalid tag length")
    seen: set[tuple[str, str]] = set()
    active_counts: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    for row in keyring["keys"]:
        if not isinstance(row, dict):
            raise Rejection("invalid key")
        exact(row, KEY_KEYS)
        row_tenant, row_key_id = identifier(row["tenant"]), identifier(row["key_id"])
        identity = (row_tenant, row_key_id)
        if identity in seen:
            raise Rejection("duplicate key")
        seen.add(identity)
        if not isinstance(row["status"], str) or row["status"] not in {"active", "retired"}:
            raise Rejection("invalid key status")
        if row["status"] == "active":
            active_counts[row_tenant] = active_counts.get(row_tenant, 0) + 1
        records.append({**row, "key": hex_bytes(row["key_hex"], 32)})
    tenants = {row["tenant"] for row in records}
    if any(active_counts.get(tenant, 0) != 1 for tenant in tenants):
        raise Rejection("invalid active key count")
    if mutant == "envelope_key_version":
        selected = next((row for row in records if row["tenant"] == tenant and row["status"] == "active"), None)
    else:
        selected = next((row for row in records if row["tenant"] == tenant and row["key_id"] == key_id and row["status"] == "active"), None)
    if selected is None:
        raise Rejection("key unavailable")
    aad_object = {"tenant": tenant, "purpose": purpose, "object_id": object_id, "schema_version": 1, "key_id": key_id}
    return envelope, aad_object, selected["key"], nonce, ciphertext, tag


def decrypt(envelope_path: Path, context_path: Path, keyring_path: Path) -> bytes:
    envelope, aad_object, key, nonce, ciphertext, tag = parse_inputs(envelope_path, context_path, keyring_path)
    aad = canonical(aad_object)
    mutant = os.environ.get("AGENTHARNESS_MUTANT", "")
    try:
        if mutant == "envelope_nonce_tag" and len(tag) == 12:
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag, min_tag_length=12)).decryptor()
            decryptor.authenticate_additional_data(aad)
            return decryptor.update(ciphertext) + decryptor.finalize()
        return AESGCM(key).decrypt(nonce, ciphertext + tag, aad)
    except InvalidTag as exc:
        if mutant == "envelope_context_binding":
            legacy = dict(aad_object)
            legacy.pop("purpose")
            try:
                return AESGCM(key).decrypt(nonce, ciphertext + tag, canonical(legacy))
            except InvalidTag:
                pass
        raise Rejection("authentication failed") from exc


Replace = Callable[[str | bytes | os.PathLike[str] | os.PathLike[bytes], str | bytes | os.PathLike[str] | os.PathLike[bytes]], None]


def atomic_write(path: Path, data: bytes, *, replace: Replace = os.replace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.environ.get("AGENTHARNESS_MUTANT") == "envelope_output_atomicity":
            path.write_bytes(b"")
        replace(temporary, path)
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


def decrypt_to_file(
    envelope_path: Path,
    context_path: Path,
    keyring_path: Path,
    output_path: Path,
    *,
    replace: Replace = os.replace,
) -> None:
    plaintext = decrypt(Path(envelope_path), Path(context_path), Path(keyring_path))
    atomic_write(Path(output_path), plaintext, replace=replace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        decrypt_to_file(args.envelope, args.context, args.keyring, args.output)
        return 0
    except (Rejection, OSError, ValueError) as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
