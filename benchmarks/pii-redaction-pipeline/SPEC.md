# pii-redaction-pipeline

## Objective

Recursive structure-preserving privacy transformation with selector semantics, keyed pseudonymization, and field-level audit.

## Required stack

Python 3.12, pytest

## Public interface and behavior

- redact replaces any selected JSON value with the rule replacement string; remove deletes the selected object member or array element with array removals applied by descending original index; pseudonymize replaces any selected value with hmac-sha256:HEX over canonical compact sorted-key UTF-8 JSON
- exact object redacted,audit; audit records are exact path,rule_id,selector,action objects sorted by canonical path then rule_id
- python -m pii_redactor.redact --input INPUT --rules RULES --key KEY --output-bundle BUNDLE
- controlled nonzero exit and byte-identical preservation of a pre-existing single bundle; staging is same-filesystem and removed after failure
- one UTF-8 JSON object or array root
- exact object secret_hex with a non-empty even-length hexadecimal HMAC key
- exact object schema_version=1,rules; each unique rule is id,selector,action and replacement only for redact
- non-root RFC6901-style pointer beginning slash; segments use ~0 and ~1 escapes; a whole segment * matches one object key or one existing array index
- unmatched selectors are valid no-ops; exact segments outrank wildcard segments; equal-specificity rules selecting one path must be identical or the rules document is invalid

## Packaging and quality requirements

- The workspace root is the runnable project.
- Keep the importable implementation in the package named by the public entrypoint.
- Declare runtime and test dependencies in pyproject.toml.
- Include automated tests and exact run instructions.
- Do not use network services, implicit wall-clock time, or files outside the workspace.
- Invalid input must produce a controlled CLI failure or HTTP 4xx response, not an uncaught traceback.
