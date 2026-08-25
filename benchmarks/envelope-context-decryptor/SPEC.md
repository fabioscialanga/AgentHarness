# Envelope context decryptor

## Objective

Implement authenticated decryption for an AES-256-GCM envelope whose tenant and business context are cryptographically bound.

## Public interface

Run:

`python -m envelope_crypto.decrypt --envelope ENVELOPE --context CONTEXT --keyring KEYRING --output PLAINTEXT`

The module must also export:

`decrypt_to_file(envelope_path, context_path, keyring_path, output_path, *, replace=os.replace)`

The keyword-only adapter is called as `replace(staging_path, output_path)` only after complete validation and authentication. If it raises before committing the replacement, preserve the prior output and remove staging residue. An adapter that has already committed is a post-commit delivery failure and is not rolled back.

ENVELOPE is UTF-8 JSON with exactly `schema_version`, `key_id`, `nonce`, `ciphertext`, and `tag`. Version 1 means AES-256-GCM. Nonce is exactly 12 bytes lowercase hex, tag exactly 16 bytes lowercase hex, and ciphertext lowercase even-length hex.

CONTEXT has exactly `tenant`, `purpose`, and `object_id`. KEYRING has exactly `schema_version:1` and a non-empty `keys` list. Each key has exactly `tenant`, `key_id`, `status`, and `key_hex`; status is `active` or `retired`, key material is exactly 32 bytes lowercase hex, `(tenant,key_id)` is unique, and each tenant has exactly one active key. IDs follow ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`.

Select the exact `(tenant,key_id)` record and require it to be active. Canonical AAD is compact sorted UTF-8 JSON containing exactly `tenant`, `purpose`, `object_id`, envelope `schema_version`, and envelope `key_id`.

All JSON must itself use canonical compact sorted UTF-8 encoding and rejects duplicate keys, unknown/missing fields, invalid UTF-8 and non-finite values. Validate and authenticate completely before atomically replacing PLAINTEXT. On controlled rejection return non-zero, emit one diagnostic line, preserve an existing output byte-for-byte, and remove staging files.

## Quality

Use Python 3.12 and `cryptography`, include tests and run instructions, use no network, randomness, implicit clock, or files outside the workspace.
