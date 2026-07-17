from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
ID_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
HEX = set("0123456789abcdef")
RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


def fail(message: str) -> None:
    raise ValueError(message)


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"invalid {label} fields")
    return value


def valid_id(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or not value[0].isalnum() or any(c not in ID_CHARS for c in value):
        fail("invalid key id")
    return value


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or RFC3339.fullmatch(value) is None:
        fail("invalid RFC3339 timestamp with explicit offset")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None:
        fail("timestamp requires an explicit offset")
    return parsed


def safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail("invalid path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ("", ".", "..") for part in p.parts) or str(p) != value:
        fail("unsafe or non-normalized path")
    return value


def lower_hex(value: Any, length: int | None = None) -> str:
    if not isinstance(value, str) or (length is not None and len(value) != length) or any(c not in HEX for c in value):
        fail("invalid lowercase hex")
    return value


def load(path: Path) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail("duplicate JSON object key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> Any:
        fail(f"invalid JSON constant: {value}")

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify(manifest_path: Path, keyring_path: Path, root: Path, as_of_text: str, output: Path) -> dict[str, Any]:
    manifest = exact(load(manifest_path), {"schema_version", "key_id", "valid_from", "valid_until", "files", "signature"}, "manifest")
    if manifest["schema_version"] != 1 or isinstance(manifest["schema_version"], bool): fail("invalid schema version")
    key_id = valid_id(manifest["key_id"])
    signature = lower_hex(manifest["signature"], 64)
    mf_from, mf_until, as_of = timestamp(manifest["valid_from"]), timestamp(manifest["valid_until"]), timestamp(as_of_text)
    if mf_from >= mf_until or not mf_from <= as_of < mf_until: fail("manifest outside trust window")
    if not isinstance(manifest["files"], list): fail("files must be an array")
    declared: dict[str, dict[str, Any]] = {}
    for raw in manifest["files"]:
        item = exact(raw, {"path", "size", "sha256"}, "file")
        path = safe_path(item["path"])
        if path in declared: fail("duplicate path")
        if isinstance(item["size"], bool) or not isinstance(item["size"], int) or not 0 <= item["size"] <= 9223372036854775807: fail("invalid size")
        lower_hex(item["sha256"], 64)
        declared[path] = item
    ring = exact(load(keyring_path), {"schema_version", "keys"}, "keyring")
    if ring["schema_version"] != 1 or isinstance(ring["schema_version"], bool) or not isinstance(ring["keys"], list): fail("invalid keyring")
    keys: dict[str, tuple[bytes, datetime, datetime]] = {}
    for raw in ring["keys"]:
        key = exact(raw, {"key_id", "secret_hex", "valid_from", "valid_until"}, "key")
        kid = valid_id(key["key_id"])
        if kid in keys: fail("duplicate key id")
        secret_hex = lower_hex(key["secret_hex"])
        if len(secret_hex) % 2 or not 32 <= len(secret_hex) <= 128: fail("invalid secret")
        start, end = timestamp(key["valid_from"]), timestamp(key["valid_until"])
        if start >= end: fail("invalid key interval")
        keys[kid] = (bytes.fromhex(secret_hex), start, end)
    if key_id not in keys: fail("unknown key")
    secret, key_from, key_until = keys[key_id]
    if as_of < key_from or (as_of >= key_until and MUTANT != "signed_manifest_trust_window"): fail("key outside trust window")
    payload = dict(manifest); payload.pop("signature")
    expected = hmac.new(secret, canonical(payload), hashlib.sha256).hexdigest()
    if MUTANT != "signed_manifest_authenticity" and not hmac.compare_digest(expected, signature): fail("invalid signature")
    if not root.is_dir(): fail("artifact root is not a directory")
    try:
        output.resolve().relative_to(root.resolve())
    except ValueError:
        pass
    else:
        fail("output must be outside artifact root")
    observed: dict[str, Path] = {}
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        mode = candidate.lstat().st_mode
        if stat.S_ISDIR(mode): continue
        if not stat.S_ISREG(mode): fail("non-regular artifact")
        safe_path(relative)
        observed[relative] = candidate
    if set(declared) - set(observed): fail("missing file")
    if MUTANT != "signed_manifest_inventory" and set(observed) - set(declared): fail("unexpected file")
    records = []
    for path in sorted(declared):
        candidate, item = observed[path], declared[path]
        data = candidate.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != item["size"]: fail("size mismatch")
        if MUTANT != "signed_manifest_content_integrity" and digest != item["sha256"]: fail("digest mismatch")
        records.append({"path": path, "size": len(data), "sha256": digest})
    return {"ok": True, "key_id": key_id, "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "file_count": len(records), "total_bytes": sum(x["size"] for x in records), "files": records}


def atomic_write(output: Path, result: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(result) + b"\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, output)
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True); parser.add_argument("--as-of", required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if MUTANT == "signed_manifest_atomic_report": args.output.write_text('{"ok":true}\n', encoding="utf-8")
        result = verify(args.manifest, args.keyring, args.artifact_root, args.as_of, args.output)
        atomic_write(args.output, result)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
