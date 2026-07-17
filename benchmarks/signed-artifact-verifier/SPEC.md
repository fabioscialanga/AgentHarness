# signed-artifact-verifier

## Objective

Offline trust verification combining canonical signed manifests, key validity, exact inventory, and byte integrity.

## Required stack

Python 3.12, pytest

## Public interface and behavior

- python -m artifact_verifier.verify --manifest MANIFEST --keyring KEYRING --artifact-root ROOT --as-of RFC3339 --output REPORT
- controlled nonzero exit, diagnostic on stderr, and byte-identical preservation of a pre-existing report
- all regular files recursively below artifact-root must appear exactly once; output must be outside artifact-root
- exact object: schema_version=1, keys; each exact key object is key_id,secret_hex,valid_from,valid_until; key IDs are unique and secret_hex encodes 16..64 bytes
- exact object: schema_version=1, key_id, valid_from, valid_until, files, signature; IDs match [A-Za-z0-9][A-Za-z0-9._-]{0,63}; signature and sha256 are 64 lowercase hex; size is integer 0..9223372036854775807; files are exact path,size,sha256 objects
- POSIX relative regular-file paths only; reject absolute, empty, dot, dot-dot, backslash, duplicate-normalized, symlink, device, FIFO, and socket entries; directories are not inventory records
- manifest without signature, UTF-8 JSON with sorted object keys, compact separators, ensure_ascii=false; HMAC-SHA256 lowercase hex
- exact object: ok=true,key_id,manifest_sha256,file_count,total_bytes,files; files sorted by path with path,size,sha256
- each valid_from must precede valid_until; valid_from <= as_of < valid_until for both selected key and manifest; Z or explicit offset required and compared as instants

## Packaging and quality requirements

- The workspace root is the runnable project.
- Keep the importable implementation in the package named by the public entrypoint.
- Declare runtime and test dependencies in pyproject.toml.
- Include automated tests and exact run instructions.
- Do not use network services, implicit wall-clock time, or files outside the workspace.
- Invalid input must produce a controlled CLI failure or HTTP 4xx response, not an uncaught traceback.
