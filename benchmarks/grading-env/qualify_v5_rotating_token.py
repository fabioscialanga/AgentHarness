#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from materialize_v5_crypto_mutants import materialize_mutant

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(os.environ.get("V5_ROTATING_TOKEN_REFERENCE", ROOT / "benchmarks/grading-env/mechanism-first-v5/references/rotating-key-token-verifier")).resolve()
CHECKS = (
    "token_rotation_window",
    "token_issuer_audience",
    "token_algorithm_pin",
    "token_time_claims",
    "token_canonical_encoding",
)
PROBE_COUNTS = {
    "token_rotation_window": 8,
    "token_issuer_audience": 6,
    "token_algorithm_pin": 3,
    "token_time_claims": 9,
    "token_canonical_encoding": 8,
}
SENTINEL = b"pre-existing report: preserve exactly\n\x00"
OLD_SECRET = bytes.fromhex("11" * 32)
NEW_SECRET = bytes.fromhex("22" * 32)
PROBE_COUNTER = 0


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def stamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def token(*, kid: str = "old-key", secret: bytes = OLD_SECRET, algorithm: str = "HS256", payload: dict[str, Any] | None = None, payload_raw: bytes | None = None, header_raw: bytes | None = None) -> str:
    header_raw = header_raw if header_raw is not None else canonical({"alg": algorithm, "kid": kid})
    if payload_raw is None:
        payload_raw = canonical(payload or base_payload())
    header_segment, payload_segment = b64(header_raw), b64(payload_raw)
    digest = hashlib.sha256 if algorithm == "HS256" else hashlib.sha512
    signature = hmac.new(secret, f"{header_segment}.{payload_segment}".encode("ascii"), digest).digest()
    return f"{header_segment}.{payload_segment}.{b64(signature)}"


def base_payload() -> dict[str, Any]:
    return {
        "aud": ["service.read", "service.write"],
        "exp": stamp("2041-01-01T00:00:00Z"),
        "iat": stamp("2030-01-01T00:00:00Z"),
        "iss": "issuer.example",
        "jti": "token-001",
        "nbf": stamp("2030-01-01T00:00:00Z"),
        "sub": "subject-001",
    }


def keyring() -> dict[str, Any]:
    return {
        "keys": [
            {"active_from": "2030-01-01T00:00:00Z", "alg": "HS256", "kid": "old-key", "retire_at": "2035-01-01T00:00:00Z", "secret_hex": OLD_SECRET.hex()},
            {"active_from": "2034-01-01T00:00:00Z", "alg": "HS256", "kid": "new-key", "retire_at": "2040-01-01T00:00:00Z", "secret_hex": NEW_SECRET.hex()},
        ],
        "schema_version": 1,
    }


def invoke(*, compact: str, as_of: str, issuer: str = "issuer.example", audience: str = "service.read", mutant: str = "", expect_success: bool) -> bool:
    global PROBE_COUNTER
    PROBE_COUNTER += 1
    with tempfile.TemporaryDirectory(prefix="v5-token-probe-") as temporary:
        root = Path(temporary)
        keyring_path, output = root / "keyring.json", root / "report.json"
        keyring_path.write_bytes(canonical(keyring()))
        output.write_bytes(SENTINEL)
        implementation = REFERENCE
        if mutant:
            implementation = materialize_mutant(REFERENCE, "rotating-key-token-verifier", mutant, root / "implementation")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(implementation)
        env["PYTHONHASHSEED"] = "43"
        env.pop("AGENTHARNESS_MUTANT", None)
        done = subprocess.run(
            [sys.executable, "-m", "rotating_token.verify", "--token", compact, "--keyring", str(keyring_path), "--issuer", issuer, "--audience", audience, "--as-of", as_of, "--output", str(output)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        residue = [path for path in root.iterdir() if path.name.startswith(".report.json.")]
        if expect_success:
            if done.returncode != 0 or done.stderr or residue:
                if os.environ.get("V5_DEBUG"):
                    print({"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr, "files": sorted(path.name for path in root.iterdir())}, file=sys.stderr)
                return False
            try:
                report = json.loads(output.read_text(encoding="utf-8"))
                header_segment, payload_segment, _signature = compact.split(".")
                header = json.loads(base64.urlsafe_b64decode(header_segment + "=" * ((-len(header_segment)) % 4)))
                payload = json.loads(base64.urlsafe_b64decode(payload_segment + "=" * ((-len(payload_segment)) % 4)))
                expected = {
                    "alg": header["alg"], "aud": payload["aud"], "exp": payload["exp"],
                    "iat": payload["iat"], "iss": payload["iss"], "jti": payload["jti"],
                    "kid": header["kid"], "nbf": payload["nbf"], "ok": True, "sub": payload["sub"],
                }
            except Exception:
                return False
            return report == expected and output.read_bytes() == canonical(expected) + b"\n"
        diagnostics = [line for line in done.stderr.splitlines() if line.strip()]
        return done.returncode != 0 and len(diagnostics) == 1 and "Traceback" not in done.stderr and output.read_bytes() == SENTINEL and not residue


def check_rotation(mutant: str) -> bool:
    cases = (
        invoke(compact=token(), as_of="2029-12-31T23:59:59Z", mutant=mutant, expect_success=False),
        invoke(compact=token(), as_of="2030-01-01T00:00:00Z", mutant=mutant, expect_success=True),
        invoke(compact=token(kid="new-key", secret=NEW_SECRET), as_of="2033-12-31T23:59:59Z", mutant=mutant, expect_success=False),
        invoke(compact=token(kid="new-key", secret=NEW_SECRET), as_of="2034-01-01T00:00:00Z", mutant=mutant, expect_success=True),
        invoke(compact=token(), as_of="2034-12-31T23:59:59Z", mutant=mutant, expect_success=True),
        invoke(compact=token(), as_of="2035-01-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(kid="new-key", secret=NEW_SECRET), as_of="2039-12-31T23:59:59Z", mutant=mutant, expect_success=True),
        invoke(compact=token(kid="new-key", secret=NEW_SECRET), as_of="2040-01-01T00:00:00Z", mutant=mutant, expect_success=False),
    )
    return all(cases)


def check_issuer_audience(mutant: str) -> bool:
    reordered = base_payload()
    reordered["aud"] = ["service.write", "service.read"]
    wrong_issuer = base_payload()
    wrong_issuer["iss"] = "issuer.other"
    cases = (
        invoke(compact=token(), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=True),
        invoke(compact=token(payload=reordered), as_of="2034-06-01T00:00:00Z", audience="service.read", mutant=mutant, expect_success=True),
        invoke(compact=token(payload=wrong_issuer), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(), as_of="2034-06-01T00:00:00Z", issuer="Issuer.example", mutant=mutant, expect_success=False),
        invoke(compact=token(), as_of="2034-06-01T00:00:00Z", audience="service.delete", mutant=mutant, expect_success=False),
        invoke(compact=token(), as_of="2034-06-01T00:00:00Z", audience="Service.read", mutant=mutant, expect_success=False),
    )
    return all(cases)


def check_algorithm(mutant: str) -> bool:
    return all((
        invoke(compact=token(), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=True),
        invoke(compact=token(algorithm="HS512"), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(algorithm="none"), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
    ))


def check_time(mutant: str) -> bool:
    exp_boundary = base_payload(); exp_boundary["exp"] = stamp("2034-06-01T00:00:00Z")
    nbf_boundary = base_payload(); nbf_boundary["nbf"] = stamp("2034-06-01T00:00:00Z")
    malformed_bool = base_payload(); malformed_bool["iat"] = True
    malformed_negative = base_payload(); malformed_negative["nbf"] = -1
    malformed_string = base_payload(); malformed_string["exp"] = "2035"
    inverted = base_payload(); inverted["nbf"] = inverted["exp"]
    return all((
        invoke(compact=token(payload=exp_boundary), as_of="2034-05-31T23:59:59Z", mutant=mutant, expect_success=True),
        invoke(compact=token(payload=exp_boundary), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload=nbf_boundary), as_of="2034-05-31T23:59:59Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload=nbf_boundary), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=True),
        invoke(compact=token(payload=malformed_bool), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload=malformed_negative), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload=malformed_string), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload=inverted), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(), as_of="2034-06-01T00:00:00", mutant=mutant, expect_success=False),
    ))


def check_canonical(mutant: str) -> bool:
    payload = base_payload()
    prefix = canonical({key: payload[key] for key in sorted(payload) if key != "sub"})[:-1]
    duplicate_raw = prefix + b',"sub":"shadow","sub":"subject-001"}'
    duplicate_header = b'{"alg":"HS256","alg":"HS256","kid":"old-key"}'
    noncanonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    compact = token()
    header_segment, payload_segment, signature_segment = compact.split(".")
    padded_header = f"{header_segment}=.{payload_segment}.{signature_segment}"
    padded_payload = f"{header_segment}.{payload_segment}=.{signature_segment}"
    padded_signature = f"{header_segment}.{payload_segment}.{signature_segment}="
    return all((
        invoke(compact=compact, as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=True),
        invoke(compact=token(payload_raw=duplicate_raw), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(header_raw=duplicate_header), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload_raw=noncanonical), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=token(payload_raw=b"\xff"), as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=padded_header, as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=padded_payload, as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
        invoke(compact=padded_signature, as_of="2034-06-01T00:00:00Z", mutant=mutant, expect_success=False),
    ))


FUNCTIONS = {
    "token_rotation_window": check_rotation,
    "token_issuer_audience": check_issuer_audience,
    "token_algorithm_pin": check_algorithm,
    "token_time_claims": check_time,
    "token_canonical_encoding": check_canonical,
}


def evaluate(mutant: str = "") -> dict[str, Any]:
    global PROBE_COUNTER
    results: dict[str, bool] = {}
    executed: dict[str, int] = {}
    for check in CHECKS:
        PROBE_COUNTER = 0
        functional = FUNCTIONS[check](mutant)
        executed[check] = PROBE_COUNTER
        results[check] = functional and PROBE_COUNTER == PROBE_COUNTS[check]
    return {"implementation": mutant or "reference", "passed": [name for name, ok in results.items() if ok], "failed": [name for name, ok in results.items() if not ok], "checks": results, "executed_probes": executed}


def main(argv: list[str] | None = None) -> int:
    global REFERENCE
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, help="candidate workspace containing rotating_token/verify.py")
    args = parser.parse_args(argv)
    if args.workspace:
        REFERENCE = args.workspace.resolve()
        rows = [evaluate("")]
        ok = rows[0]["failed"] == []
    else:
        rows = [evaluate("")] + [evaluate(check) for check in CHECKS]
        expected = {"reference": []} | {check: [check] for check in CHECKS}
        ok = all(row["failed"] == expected[row["implementation"]] for row in rows)
    payload = {"ok": ok, "task_id": "rotating-key-token-verifier", "matrix": rows, "probe_counts": PROBE_COUNTS, "total_probes_per_implementation": sum(PROBE_COUNTS.values()), "reference_runs": 1, "mutant_runs": 0 if args.workspace else len(CHECKS), "target_model_calls": 0, "efficacy_cells": 0}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
