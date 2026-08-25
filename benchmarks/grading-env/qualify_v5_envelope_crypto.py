#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from materialize_v5_crypto_mutants import materialize_mutant

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(os.environ.get("V5_ENVELOPE_REFERENCE", ROOT / "benchmarks/grading-env/mechanism-first-v5/references/envelope-context-decryptor")).resolve()
CHECKS = (
    "envelope_context_binding",
    "envelope_key_version",
    "envelope_nonce_tag",
    "envelope_schema",
    "envelope_output_atomicity",
)
PROBE_COUNTS = {
    "envelope_context_binding": 5,
    "envelope_key_version": 7,
    "envelope_nonce_tag": 9,
    "envelope_schema": 14,
    "envelope_output_atomicity": 4,
}
KEY_V1 = bytes(range(0x00, 0x20))
KEY_V2 = bytes(range(0x20, 0x40))
NONCE = bytes(range(0xA0, 0xAC))
PLAINTEXT = b"\x00invoice payload\n\xff"
SENTINEL = b"DO-NOT-REPLACE\n"
PROBE_COUNTER = 0


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def context(extra: bool = False) -> dict[str, Any]:
    result = {"tenant": "tenant-a", "purpose": "invoice-export", "object_id": "invoice-0042"}
    if extra:
        result["debug"] = "forbidden"
    return result


def aad(ctx: dict[str, Any], key_id: str, *, omit_purpose: bool = False) -> bytes:
    result = {"tenant": ctx["tenant"], "purpose": ctx["purpose"], "object_id": ctx["object_id"], "schema_version": 1, "key_id": key_id}
    if omit_purpose:
        result.pop("purpose")
    return canonical(result)


def envelope(*, key: bytes = KEY_V2, key_id: str = "v2", ctx: dict[str, Any] | None = None, nonce: bytes = NONCE, omit_purpose: bool = False, truncate_tag: bool = False, corrupt_tag: bool = False) -> dict[str, Any]:
    clean_context = {key: value for key, value in (ctx or context()).items() if key in {"tenant", "purpose", "object_id"}}
    combined = AESGCM(key).encrypt(nonce, PLAINTEXT, aad(clean_context, key_id, omit_purpose=omit_purpose))
    ciphertext, tag = combined[:-16], combined[-16:]
    if truncate_tag:
        tag = tag[:12]
    if corrupt_tag:
        tag = bytes([tag[0] ^ 1]) + tag[1:]
    return {"schema_version": 1, "key_id": key_id, "nonce": nonce.hex(), "ciphertext": ciphertext.hex(), "tag": tag.hex()}


def keyring() -> dict[str, Any]:
    return {"schema_version": 1, "keys": [
        {"tenant": "tenant-a", "key_id": "v1", "status": "retired", "key_hex": KEY_V1.hex()},
        {"tenant": "tenant-a", "key_id": "v2", "status": "active", "key_hex": KEY_V2.hex()},
    ]}


def invoke(*, env_obj: dict[str, Any], ctx_obj: dict[str, Any], keyring_obj: dict[str, Any] | None = None, envelope_raw: bytes | None = None, context_raw: bytes | None = None, keyring_raw: bytes | None = None, mutant: str = "", expect_success: bool) -> bool:
    global PROBE_COUNTER
    PROBE_COUNTER += 1
    with tempfile.TemporaryDirectory(prefix="v5-envelope-probe-") as temporary:
        root = Path(temporary)
        envelope_path, context_path, keyring_path, output = root / "envelope.json", root / "context.json", root / "keyring.json", root / "plain.bin"
        envelope_path.write_bytes(envelope_raw if envelope_raw is not None else canonical(env_obj))
        context_path.write_bytes(context_raw if context_raw is not None else canonical(ctx_obj))
        keyring_path.write_bytes(keyring_raw if keyring_raw is not None else canonical(keyring_obj or keyring()))
        output.write_bytes(SENTINEL)
        implementation = REFERENCE
        if mutant:
            implementation = materialize_mutant(REFERENCE, "envelope-context-decryptor", mutant, root / "implementation")
        process_env = dict(os.environ)
        process_env["PYTHONPATH"] = str(implementation)
        process_env["PYTHONHASHSEED"] = "43"
        process_env.pop("AGENTHARNESS_MUTANT", None)
        done = subprocess.run(
            [sys.executable, "-m", "envelope_crypto.decrypt", "--envelope", str(envelope_path), "--context", str(context_path), "--keyring", str(keyring_path), "--output", str(output)],
            cwd=root, env=process_env, capture_output=True, text=True, timeout=20, check=False,
        )
        residue = [path for path in root.iterdir() if path.name.startswith(".plain.bin.")]
        if expect_success:
            return done.returncode == 0 and not done.stderr and output.read_bytes() == PLAINTEXT and not residue
        diagnostics = [line for line in done.stderr.splitlines() if line.strip()]
        base = done.returncode != 0 and len(diagnostics) == 1 and "Traceback" not in done.stderr and not residue
        return base and output.read_bytes() == SENTINEL


def invoke_replace_failure(mutant: str, *, existing_output: bool = True, commit_then_raise: bool = False) -> bool:
    global PROBE_COUNTER
    PROBE_COUNTER += 1
    with tempfile.TemporaryDirectory(prefix="v5-envelope-commit-probe-") as temporary:
        root = Path(temporary)
        envelope_path, context_path, keyring_path, output = root / "envelope.json", root / "context.json", root / "keyring.json", root / "plain.bin"
        ctx = context()
        envelope_path.write_bytes(canonical(envelope(ctx=ctx)))
        context_path.write_bytes(canonical(ctx))
        keyring_path.write_bytes(canonical(keyring()))
        if existing_output:
            output.write_bytes(SENTINEL)
        implementation = REFERENCE
        if mutant:
            implementation = materialize_mutant(REFERENCE, "envelope-context-decryptor", mutant, root / "implementation")
        process_env = dict(os.environ)
        process_env["PYTHONPATH"] = str(implementation)
        process_env.pop("AGENTHARNESS_MUTANT", None)
        adapter_body = "    import os\n    os.replace(source, destination)\n    raise OSError('injected postcommit delivery failure')\n" if commit_then_raise else "    raise OSError('injected precommit failure')\n"
        program = (
            "from pathlib import Path\n"
            "from envelope_crypto.decrypt import decrypt_to_file\n"
            "def injected_replace(source, destination):\n" + adapter_body +
            f"try:\n    decrypt_to_file(Path({str(envelope_path)!r}), Path({str(context_path)!r}), Path({str(keyring_path)!r}), Path({str(output)!r}), replace=injected_replace)\n"
            "except OSError:\n    raise SystemExit(7)\n"
            "raise SystemExit(0)\n"
        )
        done = subprocess.run([sys.executable, "-c", program], cwd=root, env=process_env, capture_output=True, text=True, timeout=20, check=False)
        residue = [path for path in root.iterdir() if path.name.startswith(".plain.bin.")]
        if done.returncode != 7 or done.stdout or done.stderr or residue:
            return False
        if commit_then_raise:
            return output.read_bytes() == PLAINTEXT
        return output.read_bytes() == SENTINEL if existing_output else not output.exists()


def happy(mutant: str) -> bool:
    ctx = context()
    return invoke(env_obj=envelope(ctx=ctx), ctx_obj=ctx, mutant=mutant, expect_success=True)


def check_context(mutant: str) -> bool:
    ctx = context()
    legacy = envelope(ctx=ctx, omit_purpose=True)
    base = envelope(ctx=ctx)
    swapped_tenant = {**ctx, "tenant": "tenant-b"}
    swapped_purpose = {**ctx, "purpose": "refund-export"}
    swapped_object = {**ctx, "object_id": "invoice-0043"}
    return all((
        happy(mutant),
        invoke(env_obj=legacy, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=swapped_tenant, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=swapped_purpose, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=swapped_object, mutant=mutant, expect_success=False),
    ))


def check_key_version(mutant: str) -> bool:
    ctx = context()
    wrong_version = envelope(key=KEY_V2, key_id="v1", ctx=ctx)
    retired = envelope(key=KEY_V1, key_id="v1", ctx=ctx)
    unknown = envelope(key=KEY_V2, key_id="v3", ctx=ctx)
    tenant_b = {"tenant": "tenant-b", "purpose": ctx["purpose"], "object_id": ctx["object_id"]}
    cross_ring = keyring()
    cross_ring["keys"].append({"tenant": "tenant-b", "key_id": "v1", "status": "active", "key_hex": KEY_V1.hex()})
    cross_tenant = envelope(key=KEY_V1, key_id="v2", ctx=tenant_b)
    zero_active = keyring(); zero_active["keys"][1]["status"] = "retired"
    two_active = keyring(); two_active["keys"][0]["status"] = "active"
    return all((
        happy(mutant),
        invoke(env_obj=wrong_version, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=retired, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=unknown, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=cross_tenant, ctx_obj=tenant_b, keyring_obj=cross_ring, mutant=mutant, expect_success=False),
        invoke(env_obj=envelope(ctx=ctx), ctx_obj=ctx, keyring_obj=zero_active, mutant=mutant, expect_success=False),
        invoke(env_obj=envelope(ctx=ctx), ctx_obj=ctx, keyring_obj=two_active, mutant=mutant, expect_success=False),
    ))


def check_nonce_tag(mutant: str) -> bool:
    ctx = context()
    truncated = envelope(ctx=ctx, truncate_tag=True)
    short_nonce = envelope(ctx=ctx, nonce=NONCE[:-1])
    long_nonce = envelope(ctx=ctx, nonce=NONCE + b"\xac")
    extended_tag = envelope(ctx=ctx); extended_tag["tag"] += "00"
    altered_tag = envelope(ctx=ctx, corrupt_tag=True)
    altered_nonce = envelope(ctx=ctx); altered_nonce["nonce"] = (bytes([NONCE[0] ^ 1]) + NONCE[1:]).hex()
    odd_ciphertext = envelope(ctx=ctx); odd_ciphertext["ciphertext"] = odd_ciphertext["ciphertext"][:-1]
    upper_ciphertext = envelope(ctx=ctx); upper_ciphertext["ciphertext"] = upper_ciphertext["ciphertext"].upper()
    return all((
        happy(mutant),
        invoke(env_obj=truncated, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=short_nonce, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=long_nonce, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=extended_tag, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=altered_tag, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=altered_nonce, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=odd_ciphertext, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=upper_ciphertext, ctx_obj=ctx, mutant=mutant, expect_success=False),
    ))


def check_schema(mutant: str) -> bool:
    ctx = context(extra=True)
    valid_for_core = envelope(ctx=ctx)
    clean = context(); base = envelope(ctx=clean)
    missing_context = {"tenant": clean["tenant"], "purpose": clean["purpose"]}
    extra_envelope = {**base, "debug": True}
    missing_envelope = dict(base); missing_envelope.pop("tag")
    bad_version = {**base, "schema_version": 2}
    bool_version = {**base, "schema_version": True}
    noncanonical_context = json.dumps(clean, sort_keys=True).encode("utf-8")
    noncanonical_envelope = json.dumps(base, sort_keys=True).encode("utf-8")
    noncanonical_keyring = json.dumps(keyring(), sort_keys=True).encode("utf-8")
    duplicate_context = b'{"object_id":"invoice-0042","purpose":"invoice-export","tenant":"shadow","tenant":"tenant-a"}'
    invalid_utf8 = b"\xff"
    duplicate_keyring = b'{"keys":[],"keys":[],"schema_version":1}'
    malformed_status = keyring(); malformed_status["keys"][0]["status"] = []
    return all((
        happy(mutant),
        invoke(env_obj=valid_for_core, ctx_obj=ctx, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=missing_context, mutant=mutant, expect_success=False),
        invoke(env_obj=extra_envelope, ctx_obj=clean, mutant=mutant, expect_success=False),
        invoke(env_obj=missing_envelope, ctx_obj=clean, mutant=mutant, expect_success=False),
        invoke(env_obj=bad_version, ctx_obj=clean, mutant=mutant, expect_success=False),
        invoke(env_obj=bool_version, ctx_obj=clean, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, context_raw=noncanonical_context, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, envelope_raw=noncanonical_envelope, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, keyring_raw=noncanonical_keyring, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, context_raw=duplicate_context, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, envelope_raw=invalid_utf8, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, keyring_raw=duplicate_keyring, mutant=mutant, expect_success=False),
        invoke(env_obj=base, ctx_obj=clean, keyring_obj=malformed_status, mutant=mutant, expect_success=False),
    ))


def check_atomicity(mutant: str) -> bool:
    return all((
        happy(mutant),
        invoke_replace_failure(mutant, existing_output=True),
        invoke_replace_failure(mutant, existing_output=False),
        invoke_replace_failure(mutant, existing_output=True, commit_then_raise=True),
    ))


FUNCTIONS = {
    "envelope_context_binding": check_context,
    "envelope_key_version": check_key_version,
    "envelope_nonce_tag": check_nonce_tag,
    "envelope_schema": check_schema,
    "envelope_output_atomicity": check_atomicity,
}


def evaluate(mutant: str = "") -> dict[str, Any]:
    global PROBE_COUNTER
    checks: dict[str, bool] = {}
    executed: dict[str, int] = {}
    for name in CHECKS:
        PROBE_COUNTER = 0
        functional = FUNCTIONS[name](mutant)
        executed[name] = PROBE_COUNTER
        checks[name] = functional and PROBE_COUNTER == PROBE_COUNTS[name]
    return {"implementation": mutant or "reference", "passed": [name for name, ok in checks.items() if ok], "failed": [name for name, ok in checks.items() if not ok], "checks": checks, "executed_probes": executed}


def main(argv: list[str] | None = None) -> int:
    global REFERENCE
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, help="candidate workspace containing envelope_crypto/decrypt.py")
    args = parser.parse_args(argv)
    if args.workspace:
        REFERENCE = args.workspace.resolve()
        rows = [evaluate("")]
        ok = rows[0]["failed"] == []
    else:
        rows = [evaluate("")] + [evaluate(name) for name in CHECKS]
        expected = {"reference": []} | {name: [name] for name in CHECKS}
        ok = all(row["failed"] == expected[row["implementation"]] for row in rows)
    print(json.dumps({"ok": ok, "task_id": "envelope-context-decryptor", "matrix": rows, "probe_counts": PROBE_COUNTS, "total_probes_per_implementation": sum(PROBE_COUNTS.values()), "reference_runs": 1, "mutant_runs": 0 if args.workspace else 5, "target_model_calls": 0, "efficacy_cells": 0}, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
