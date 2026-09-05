import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentharness.security_bundle import verify_security_bundle


GENESIS_HASH = "0" * 64


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _record(sequence, previous_hash, *, kind="network", action="GET", outcome="200"):
    payload = {
        "schema_version": 1,
        "sequence": sequence,
        "kind": kind,
        "action": action,
        "subject": "https://example.test/",
        "outcome": outcome,
        "details": {"content_type": "text/html"},
        "previous_hash": previous_hash,
    }
    payload["record_hash"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def _write_bundle(tmp_path, *, used=3, maximum=5):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    first = _record(1, GENESIS_HASH, kind="governance", action="scope-check", outcome="allowed")
    second = _record(2, first["record_hash"])
    records = [first, second]
    evidence_bytes = (
        "\n".join(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in records)
        + "\n"
    ).encode("utf-8")
    (bundle / "evidence.jsonl").write_bytes(evidence_bytes)

    report = {
        "scan_id": "proof123",
        "target": "https://example.test",
        "status": "completed",
        "metadata": {
            "assessment_budget": {
                "maximum": maximum,
                "used": used,
                "remaining": max(0, maximum - used),
                "by_phase": {"assessment": used},
            },
            "evidence": {
                "record_count": len(records),
                "chain_head": second["record_hash"],
            },
        },
    }
    report_bytes = (json.dumps(report, indent=2) + "\n").encode("utf-8")
    html_bytes = b"<html><body>report</body></html>"
    (bundle / "report.json").write_bytes(report_bytes)
    (bundle / "report.html").write_bytes(html_bytes)

    manifest = {
        "schema_version": 1,
        "scan_id": "proof123",
        "target": "https://example.test",
        "status": "completed",
        "evidence": {
            "file": "evidence.jsonl",
            "record_count": len(records),
            "chain_head": second["record_hash"],
            "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        },
        "artifacts": {
            "report.json": {"sha256": hashlib.sha256(report_bytes).hexdigest()},
            "report.html": {"sha256": hashlib.sha256(html_bytes).hexdigest()},
        },
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def _sign_bundle(bundle, tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_path = tmp_path / "trusted-public.pem"
    public_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical = _canonical({key: value for key, value in manifest.items() if key != "signature"})
    raw_public = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    manifest["signature"] = {
        "algorithm": "ed25519",
        "key_id": "test-key",
        "public_key_fingerprint_sha256": hashlib.sha256(raw_public).hexdigest(),
        "public_key_raw_base64": base64.b64encode(raw_public).decode("ascii"),
        "signature_base64": base64.b64encode(private_key.sign(canonical)).decode("ascii"),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return public_path


def test_unsigned_valid_bundle_is_inconclusive_without_identity_anchor(tmp_path):
    bundle = _write_bundle(tmp_path)

    result = verify_security_bundle(bundle)

    assert result.status == "inconclusive"
    assert any(
        item["name"] == "manifest-signature" and item["status"] == "inconclusive"
        for item in result.checks
    )


def test_signed_bundle_is_supported_with_trusted_public_key(tmp_path):
    bundle = _write_bundle(tmp_path)
    public_path = _sign_bundle(bundle, tmp_path)

    result = verify_security_bundle(bundle, trusted_public_key=public_path)

    assert result.status == "supported"
    assert result.ok is True
    assert result.signature["trusted"] is True


def test_tampered_evidence_is_invalid(tmp_path):
    bundle = _write_bundle(tmp_path)
    evidence = bundle / "evidence.jsonl"
    evidence.write_text(evidence.read_text(encoding="utf-8").replace('"outcome":"200"', '"outcome":"500"'), encoding="utf-8")

    result = verify_security_bundle(bundle)

    assert result.status == "invalid"
    assert any("sha256 mismatch" in error or "record_hash mismatch" in error for error in result.errors)


def test_budget_overrun_is_unsupported_when_bundle_integrity_is_coherent(tmp_path):
    bundle = _write_bundle(tmp_path, used=6, maximum=5)

    result = verify_security_bundle(bundle)

    assert result.status == "unsupported"
    assert any(
        item["name"] == "assessment-budget" and item["status"] == "unsupported"
        for item in result.checks
    )


def test_require_signature_rejects_unsigned_bundle(tmp_path):
    bundle = _write_bundle(tmp_path)

    result = verify_security_bundle(bundle, require_signature=True)

    assert result.status == "invalid"
    assert any("required manifest signature" in error for error in result.errors)
