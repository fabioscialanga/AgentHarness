from __future__ import annotations

import argparse
import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


GENESIS_HASH = "0" * 64
EVIDENCE_SCHEMA_VERSION = 1
SIGNATURE_ALGORITHM = "ed25519"


@dataclass
class SecurityBundleVerification:
    bundle_dir: Path
    status: str
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scan_id: str = ""
    target: str = ""
    signature: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "supported"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "bundle_dir": str(self.bundle_dir),
            "scan_id": self.scan_id,
            "target": self.target,
            "checks": self.checks,
            "errors": self.errors,
            "signature": self.signature,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    return _canonical_json_bytes(unsigned)


def _record_hash(record: dict[str, Any]) -> str:
    payload = {
        "schema_version": int(record.get("schema_version")),
        "sequence": int(record.get("sequence")),
        "kind": str(record.get("kind")),
        "action": str(record.get("action")),
        "subject": str(record.get("subject")),
        "outcome": str(record.get("outcome")),
        "details": record.get("details", {}),
        "previous_hash": str(record.get("previous_hash", "")),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"evidence.jsonl line {line_number} must contain a JSON object")
        records.append(value)
    return records


def _verify_chain(records: list[dict[str, Any]]) -> tuple[bool, str, list[str]]:
    previous_hash = GENESIS_HASH
    errors: list[str] = []
    for expected_sequence, record in enumerate(records, start=1):
        try:
            schema_version = int(record.get("schema_version"))
            sequence = int(record.get("sequence"))
            details = record.get("details", {})
            previous = str(record.get("previous_hash", ""))
            stored_hash = str(record.get("record_hash", ""))
            if not isinstance(details, dict):
                errors.append(f"record {expected_sequence}: details must be an object")
                continue
            if schema_version != EVIDENCE_SCHEMA_VERSION:
                errors.append(
                    f"record {expected_sequence}: unsupported schema_version={schema_version}"
                )
            if sequence != expected_sequence:
                errors.append(f"record {expected_sequence}: non-contiguous sequence={sequence}")
            if previous != previous_hash:
                errors.append(f"record {expected_sequence}: previous_hash mismatch")
            calculated = _record_hash(record)
            if stored_hash != calculated:
                errors.append(f"record {expected_sequence}: record_hash mismatch")
            previous_hash = stored_hash
        except (TypeError, ValueError) as exc:
            errors.append(f"record {expected_sequence}: malformed fields ({exc})")
    return not errors, previous_hash if records else GENESIS_HASH, errors


def _public_raw(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _load_trusted_public_key(path: Path) -> Ed25519PublicKey:
    value = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(value, Ed25519PublicKey):
        raise TypeError("Trusted public key must be Ed25519")
    return value


def _verify_signature(
    manifest: dict[str, Any],
    *,
    trusted_public_key: Path | None,
) -> dict[str, Any]:
    signature = manifest.get("signature")
    if not isinstance(signature, dict):
        return {
            "present": False,
            "valid": False,
            "trusted": False,
            "key_id": "",
            "fingerprint": "",
            "error": "manifest is unsigned",
        }
    try:
        if signature.get("algorithm") != SIGNATURE_ALGORITHM:
            raise ValueError("unsupported signature algorithm")
        raw_public = base64.b64decode(
            str(signature.get("public_key_raw_base64", "")), validate=True
        )
        raw_signature = base64.b64decode(
            str(signature.get("signature_base64", "")), validate=True
        )
        public_key = Ed25519PublicKey.from_public_bytes(raw_public)
        fingerprint = hashlib.sha256(raw_public).hexdigest()
        if fingerprint != str(signature.get("public_key_fingerprint_sha256", "")):
            raise ValueError("public-key fingerprint mismatch")
        public_key.verify(raw_signature, _canonical_manifest_bytes(manifest))

        trusted = False
        if trusted_public_key is not None:
            trusted_key = _load_trusted_public_key(trusted_public_key)
            if _public_raw(trusted_key) != raw_public:
                raise ValueError("signature key does not match trusted public key")
            trusted_key.verify(raw_signature, _canonical_manifest_bytes(manifest))
            trusted = True
        return {
            "present": True,
            "valid": True,
            "trusted": trusted,
            "key_id": str(signature.get("key_id", "")),
            "fingerprint": fingerprint,
            "error": "",
        }
    except (ValueError, TypeError, OSError, InvalidSignature) as exc:
        return {
            "present": True,
            "valid": False,
            "trusted": False,
            "key_id": str(signature.get("key_id", "")),
            "fingerprint": str(signature.get("public_key_fingerprint_sha256", "")),
            "error": str(exc) or type(exc).__name__,
        }


def verify_security_bundle(
    bundle_dir: str | Path,
    *,
    trusted_public_key: str | Path | None = None,
    require_signature: bool = False,
) -> SecurityBundleVerification:
    root = Path(bundle_dir).resolve()
    trusted_path = Path(trusted_public_key).resolve() if trusted_public_key else None
    checks: list[dict[str, Any]] = []
    invalid_errors: list[str] = []
    unsupported: list[str] = []
    inconclusive: list[str] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})
        if status == "invalid":
            invalid_errors.append(detail)
        elif status == "unsupported":
            unsupported.append(detail)
        elif status == "inconclusive":
            inconclusive.append(detail)

    required = {
        "manifest.json": root / "manifest.json",
        "report.json": root / "report.json",
        "report.html": root / "report.html",
        "evidence.jsonl": root / "evidence.jsonl",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        return SecurityBundleVerification(
            bundle_dir=root,
            status="invalid",
            reason="Required security-assessment artifacts are missing.",
            checks=[
                {
                    "name": "required-artifacts",
                    "status": "invalid",
                    "detail": "missing: " + ", ".join(missing),
                }
            ],
            errors=["missing: " + ", ".join(missing)],
        )

    try:
        manifest = _load_json_object(required["manifest.json"])
        report = _load_json_object(required["report.json"])
        records = _load_jsonl(required["evidence.jsonl"])
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return SecurityBundleVerification(
            bundle_dir=root,
            status="invalid",
            reason="Security-assessment artifacts could not be parsed.",
            checks=[{"name": "parse", "status": "invalid", "detail": str(exc)}],
            errors=[str(exc)],
        )

    scan_id = str(manifest.get("scan_id", ""))
    target = str(manifest.get("target", ""))
    if manifest.get("schema_version") != 1:
        check("manifest-schema", "invalid", "manifest schema_version is unsupported")
    else:
        check("manifest-schema", "supported", "manifest schema_version=1")

    if not records:
        check("evidence-present", "invalid", "evidence.jsonl contains no records")
    else:
        check("evidence-present", "supported", f"records={len(records)}")

    if str(report.get("scan_id", "")) != scan_id or str(report.get("target", "")) != target:
        check("report-binding", "invalid", "report scan_id/target do not match manifest")
    else:
        check("report-binding", "supported", f"scan_id={scan_id}; target={target}")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        check("artifact-digests", "invalid", "manifest artifacts section is missing")
    else:
        digest_errors: list[str] = []
        for name in ("report.json", "report.html"):
            spec = artifacts.get(name)
            expected = spec.get("sha256") if isinstance(spec, dict) else None
            actual = _sha256_file(required[name])
            if not isinstance(expected, str) or actual != expected:
                digest_errors.append(f"{name} sha256 mismatch")
        check(
            "artifact-digests",
            "invalid" if digest_errors else "supported",
            "; ".join(digest_errors) if digest_errors else "report artifact digests match manifest",
        )

    evidence_spec = manifest.get("evidence")
    if not isinstance(evidence_spec, dict):
        check("evidence-digest", "invalid", "manifest evidence section is missing")
        evidence_spec = {}
    else:
        actual_evidence_sha = _sha256_file(required["evidence.jsonl"])
        if evidence_spec.get("sha256") != actual_evidence_sha:
            check("evidence-digest", "invalid", "evidence.jsonl sha256 mismatch")
        else:
            check("evidence-digest", "supported", "evidence.jsonl digest matches manifest")

    chain_valid, chain_head, chain_errors = _verify_chain(records)
    check(
        "evidence-chain",
        "supported" if chain_valid else "invalid",
        f"chain_head={chain_head}" if chain_valid else "; ".join(chain_errors[:5]),
    )
    if int(evidence_spec.get("record_count", -1) or 0) != len(records):
        check("evidence-count", "invalid", "manifest record_count does not match evidence.jsonl")
    else:
        check("evidence-count", "supported", f"record_count={len(records)}")
    if str(evidence_spec.get("chain_head", "")) != chain_head:
        check("chain-head-binding", "invalid", "manifest chain_head does not match evidence chain")
    else:
        check("chain-head-binding", "supported", "manifest chain_head matches evidence chain")

    metadata = report.get("metadata")
    budget = metadata.get("assessment_budget") if isinstance(metadata, dict) else None
    if not isinstance(budget, dict):
        check("assessment-budget", "inconclusive", "report has no unified assessment_budget summary")
    else:
        try:
            maximum = int(budget.get("maximum", 0) or 0)
            used = int(budget.get("used", 0) or 0)
            remaining = int(budget.get("remaining", 0) or 0)
            by_phase = budget.get("by_phase", {})
            phase_total = (
                sum(int(value) for value in by_phase.values())
                if isinstance(by_phase, dict)
                else -1
            )
            if maximum < 1 or used < 0 or used > maximum:
                check(
                    "assessment-budget",
                    "unsupported",
                    f"budget violated: used={used}; maximum={maximum}",
                )
            elif remaining != maximum - used or phase_total != used:
                check(
                    "assessment-budget",
                    "unsupported",
                    "budget accounting is internally inconsistent",
                )
            else:
                check(
                    "assessment-budget",
                    "supported",
                    f"used={used}; maximum={maximum}; remaining={remaining}",
                )
        except (TypeError, ValueError) as exc:
            check("assessment-budget", "invalid", f"budget summary malformed: {exc}")

    signature = _verify_signature(manifest, trusted_public_key=trusted_path)
    if signature.get("present"):
        if not signature.get("valid"):
            check("manifest-signature", "invalid", f"signature invalid: {signature.get('error', '')}")
        elif trusted_path is not None and not signature.get("trusted"):
            check("manifest-signature", "invalid", "signature does not match trusted public key")
        elif signature.get("trusted"):
            check("manifest-signature", "supported", "Ed25519 signature matches trusted public key")
        else:
            check(
                "manifest-signature",
                "inconclusive",
                "signature is cryptographically valid but no external trust key was supplied",
            )
    elif require_signature or trusted_path is not None:
        check("manifest-signature", "invalid", "required manifest signature is missing")
    else:
        check("manifest-signature", "inconclusive", "manifest is unsigned; identity trust not evaluated")

    if invalid_errors:
        status = "invalid"
        reason = "The bundle cannot be accepted as a valid measurement artifact."
    elif unsupported:
        status = "unsupported"
        reason = "The bundle is structurally valid but contradicts a governed assessment claim."
    elif inconclusive:
        status = "inconclusive"
        reason = "Bundle integrity is coherent, but one or more optional trust claims were not established."
    else:
        status = "supported"
        reason = "Bundle integrity, budget accounting and requested trust checks are supported."

    return SecurityBundleVerification(
        bundle_dir=root,
        status=status,
        reason=reason,
        checks=checks,
        errors=[*invalid_errors, *unsupported, *inconclusive],
        scan_id=scan_id,
        target=target,
        signature=signature,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agentharness.security_bundle",
        description="Independently verify an AI Pentester Agent evidence bundle without network access.",
    )
    parser.add_argument("bundle_dir", type=Path, help="Directory containing manifest.json and evidence artifacts")
    parser.add_argument("--public-key", type=Path, help="Optional trusted Ed25519 public key PEM")
    parser.add_argument("--require-signature", action="store_true", help="Reject unsigned bundles")
    parser.add_argument("--json", action="store_true", help="Print structured JSON")
    args = parser.parse_args(argv)

    result = verify_security_bundle(
        args.bundle_dir,
        trusted_public_key=args.public_key,
        require_signature=args.require_signature or bool(args.public_key),
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"[{result.status.upper()}] security bundle")
        print(result.reason)
        if result.scan_id:
            print(f"Scan: {result.scan_id}")
        if result.target:
            print(f"Target: {result.target}")
        for item in result.checks:
            print(f"- {item['name']}: {item['status']} — {item['detail']}")

    if result.status == "supported":
        return 0
    if result.status == "invalid":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
