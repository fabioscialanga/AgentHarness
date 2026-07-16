# access-policy-evaluator

## Objective

Evaluate auditable access decisions from direct and group policy rules.

## Required stack

Python 3.11+, pytest

## Required entrypoint

`python -m app.evaluate_policy --policy <policy.json> --requests <requests.jsonl> --out-dir <dir>`

## Functional requirements

1. The policy JSON contains rules with unique id, effect allow or deny, subjects and/or groups, actions, resources, and optional valid_from/valid_until RFC 3339 instants. At least one subjects or groups selector is required.
2. Requests JSONL contain request_id, subject, groups, action, resource, and as_of. Group membership comes only from the request. Preserve valid request order.
3. Action/resource patterns are either exact strings or a trailing * prefix wildcard. Other wildcard placement is invalid policy input.
4. A matching deny overrides every allow. A matching allow permits only when no deny matches. No matching rule means deny. Temporal intervals are half-open [valid_from, valid_until) after UTC normalization.
5. Write decisions.jsonl for valid requests, rejected.jsonl for malformed request lines, and summary.json. Every decision record has exactly request_id, decision, and sorted matched_rule_ids with no additional keys. Every rejected record has exactly positive integer line_number and string reason with no additional keys. Summary has exactly integer allow_count, deny_count, rejected_count, and request_count with no additional keys, where request_count counts valid requests. Outputs are deterministic; a malformed request line does not prevent other valid lines from being evaluated.

## Packaging requirements

- Keep implementation under `app/` with `app/__init__.py`.
- Include `pyproject.toml`, `README.md`, and runnable tests under `tests/`.
- Do not depend on network access, external services, wall-clock time, or files outside the workspace.
- Invalid input must fail with a controlled non-zero CLI exit or 4xx API response, never an uncaught traceback.
