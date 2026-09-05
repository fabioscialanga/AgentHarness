# Security assessment bundle verification

AgentHarness can independently inspect the evidence bundle produced by AI Pentester Agent without launching the scanner, browser, network requests, or arbitrary subprocesses.

## Command

```bash
agentharness-security-bundle reports/<scan-id>
```

Equivalent module form:

```bash
python -m agentharness.security_bundle reports/<scan-id>
```

Machine-readable output:

```bash
agentharness-security-bundle reports/<scan-id> --json
```

Require an Ed25519 signature anchored to a separately supplied trusted public key:

```bash
agentharness-security-bundle \
  reports/<scan-id> \
  --public-key trusted-public.pem
```

`--public-key` implies that a matching signature is required. `--require-signature` can also reject unsigned bundles without supplying a trust key.

## What is verified

The verifier reads only local files and checks:

- presence and parseability of `manifest.json`, `report.json`, `report.html`, and `evidence.jsonl`;
- scan-id and target binding between manifest and report;
- SHA-256 digests for report artifacts;
- SHA-256 digest for the evidence file;
- contiguous evidence sequence and the complete `previous_hash` / `record_hash` chain;
- manifest record count and chain-head binding;
- unified assessment-budget accounting when present;
- Ed25519 signature validity when present;
- signer-key equality when an external trusted public key is supplied.

The implementation is independent from AI Pentester Agent. AgentHarness does not import its verifier or trust its exit code.

## Verdict semantics

| Verdict | Meaning |
| --- | --- |
| `supported` | Bundle integrity, budget accounting, and every requested trust check are supported. |
| `unsupported` | The bundle is structurally valid but contradicts a governed claim, for example a recorded budget overrun. |
| `inconclusive` | Integrity is coherent but an optional trust property was not established, for example an unsigned bundle when signer identity was not required. |
| `invalid` | The measurement artifact is missing, malformed, tampered, hash-chain invalid, or fails a required signature/trust check. |

A `supported` bundle does **not** mean that every security finding is a confirmed vulnerability. It means the assessment artifacts and the governance claims checked by this verifier survived independent verification.

## Trust boundary

AgentHarness deliberately does not add `python -m app.verify_evidence` to its generic command reexecution allowlist. Doing so would turn a security integration into an arbitrary-command exception.

Instead, `security_bundle.py` implements the file, hash-chain, budget, and signature checks directly. It performs no network access and launches no subprocess.

An unsigned bundle can still be internally tamper-evident, but it cannot establish who produced the manifest. A signature verified only against the public key embedded inside the same manifest proves cryptographic consistency, not external identity. Supplying a separately managed public key is what anchors signer trust.
