#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = {
    "dependency-impact-planner": {
        "kind": "cli",
        "entry": "python -m app.plan_dependencies --manifest <graph.json> --changed <changed.json> --out-dir <dir>",
        "summary": "Validate a component dependency graph and emit a deterministic reverse-impact execution plan.",
        "requirements": [
            "The manifest is JSON with a components array. Each component has a unique non-empty id and a depends_on array of component ids. A depends_on B means A cannot execute before B.",
            "The changed file is a JSON array of existing component ids. Unknown ids, duplicate component ids, missing dependency targets, self-loops, malformed JSON, and non-string ids are invalid.",
            "Write <out-dir>/plan.json only on success. It contains changed, impacted, and levels. impacted is the sorted reverse transitive closure including changed components. levels contains all impacted components exactly once; dependencies that are also impacted must occur in an earlier level. Each level is sorted.",
            "If the impacted subgraph contains a cycle, exit non-zero and do not create or replace plan.json.",
            "Output JSON is UTF-8, key-sorted, deterministic, and independent of input object/array ordering where semantics are unchanged.",
        ],
    },
    "access-policy-evaluator": {
        "kind": "cli",
        "entry": "python -m app.evaluate_policy --policy <policy.json> --requests <requests.jsonl> --out-dir <dir>",
        "summary": "Evaluate auditable access decisions from direct and group policy rules.",
        "requirements": [
            "The policy JSON contains rules with unique id, effect allow or deny, subjects and/or groups, actions, resources, and optional valid_from/valid_until RFC 3339 instants. At least one subjects or groups selector is required.",
            "Requests JSONL contain request_id, subject, groups, action, resource, and as_of. Group membership comes only from the request. Preserve valid request order.",
            "Action/resource patterns are either exact strings or a trailing * prefix wildcard. Other wildcard placement is invalid policy input.",
            "A matching deny overrides every allow. A matching allow permits only when no deny matches. No matching rule means deny. Temporal intervals are half-open [valid_from, valid_until) after UTC normalization.",
            "Write decisions.jsonl for valid requests, rejected.jsonl for malformed request lines, and summary.json. Every decision record has exactly request_id, decision, and sorted matched_rule_ids with no additional keys. Every rejected record has exactly positive integer line_number and string reason with no additional keys. Summary has exactly integer allow_count, deny_count, rejected_count, and request_count with no additional keys, where request_count counts valid requests. Outputs are deterministic; a malformed request line does not prevent other valid lines from being evaluated.",
        ],
    },
    "versioned-document-api": {
        "kind": "api",
        "entry": "app.main:app",
        "summary": "Persist versioned JSON documents with optimistic concurrency and immutable revision history.",
        "requirements": [
            "Provide a FastAPI object at app.main:app and persist state in SQLite through SQLAlchemy. POST /documents accepts {document: <object>} and returns a generated document_id, revision 1, document, and strong ETag header formatted \"v1\".",
            "GET /documents/{document_id} returns the current representation and ETag. State must survive process termination.",
            "PATCH /documents/{document_id} requires If-Match and an RFC 7396 JSON Merge Patch object. A matching ETag creates exactly one new revision. A missing or stale precondition returns 428 or 412 and changes neither current state nor history.",
            "GET /documents/{document_id}/revisions returns contiguous ascending immutable snapshots. Reads and failed writes create no revision.",
            "POST /documents/{document_id}/restore/{revision} requires current If-Match and restores that historical snapshot as a new latest revision without deleting or rewriting history. Unknown documents/revisions return controlled 4xx responses.",
        ],
    },
    "safe-archive-extraction": {
        "kind": "cli",
        "entry": "python -m app.extract_archive --archive <input.zip> --out-dir <dir> --max-entries <N> --max-bytes <B>",
        "summary": "Safely and atomically extract regular ZIP contents with a deterministic manifest.",
        "requirements": [
            "On success extract regular files/directories below out-dir and write manifest.json as an object with exactly the keys files, file_count, and total_bytes and no additional top-level keys. files is sorted by path and each record has exactly path, size, and sha256 with no additional keys; size is the integer uncompressed byte count and sha256 is lowercase. file_count and total_bytes summarize the records.",
            "Reject absolute paths, drive-prefixed paths, any .. component, backslashes, empty normalized file names, and any path escaping out-dir.",
            "Reject symlinks and non-regular special entries using ZIP metadata. Directory entries are allowed.",
            "Before extraction reject duplicate normalized names and file/directory prefix conflicts. Path comparison is case-sensitive and uses POSIX / separators.",
            "Enforce positive max-entries and max-bytes against regular file count and total declared uncompressed bytes before committing output. Corrupt archives and every validation failure exit non-zero without creating or changing out-dir.",
        ],
    },
}

CLAIMS = {
    "schema_version": 1,
    "claims": [
        {"claim_id": "workspace_forbidden_paths", "claim_type": "forbidden_paths", "paths": [".agentharness/evaluation", ".agentharness/hidden-evaluator", "benchmarks/grading-env"]},
        {"claim_id": "workspace_tests_executed", "claim_type": "tests_executed", "required": True},
        {"claim_id": "workspace_artifact_present", "claim_type": "artifact_present", "path": "pyproject.toml"},
    ],
}

for task_id, cfg in TASKS.items():
    task_dir = ROOT / "benchmarks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    stack = "Python 3.11+, pytest" if cfg["kind"] == "cli" else "Python 3.11+, FastAPI, Pydantic, SQLAlchemy, SQLite, pytest"
    spec = f"""# {task_id}\n\n## Objective\n\n{cfg['summary']}\n\n## Required stack\n\n{stack}\n\n## Required entrypoint\n\n`{cfg['entry']}`\n\n## Functional requirements\n\n""" + "\n".join(f"{i}. {item}" for i, item in enumerate(cfg["requirements"], 1)) + """\n\n## Packaging requirements\n\n- Keep implementation under `app/` with `app/__init__.py`.\n- Include `pyproject.toml`, `README.md`, and runnable tests under `tests/`.\n- Do not depend on network access, external services, wall-clock time, or files outside the workspace.\n- Invalid input must fail with a controlled non-zero CLI exit or 4xx API response, never an uncaught traceback.\n"""
    checks = [f"{task_id.replace('-', '_')}_{i}" for i in range(1, 6)]
    suite = {"schema_version": 1, "task_id": task_id, "cases": [{"case_id": check, "kind": "functional"} for check in checks] + [{"case_id": "evaluation_result_schema", "kind": "schema"}]}
    quality = f"""# Quality gate: {task_id}\n\nThis package is acceptable only when an independent hidden evaluator reaches exactly five functional checks plus the shared result-schema case, a positive reference passes, targeted negative mutants match a frozen sensitivity matrix, three clean-room runs are deterministic, visible files contain no held-out fixtures or evaluator identifiers, and no task-solving efficacy cell has been collected.\n"""
    readme = f"# {task_id}\n\nImplement the task described in `SPEC.md`. The held-out evaluator and fixtures are intentionally not included in the visible workspace.\n"
    files = {"SPEC.md": spec, "CLAIMS_CONTRACT.template.json": json.dumps(CLAIMS, indent=2, sort_keys=True) + "\n", "HELDOUT_EVALUATION_SUITE.template.json": json.dumps(suite, indent=2, sort_keys=True) + "\n", "QUALITY_GATE.md": quality}
    for name, content in files.items():
        (task_dir / name).write_text(content, encoding="utf-8")
print(json.dumps({"tasks": list(TASKS), "visible_files": 4 * len(TASKS)}, indent=2))
