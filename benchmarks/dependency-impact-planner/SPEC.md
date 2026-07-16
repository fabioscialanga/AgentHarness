# dependency-impact-planner

## Objective

Validate a component dependency graph and emit a deterministic reverse-impact execution plan.

## Required stack

Python 3.11+, pytest

## Required entrypoint

`python -m app.plan_dependencies --manifest <graph.json> --changed <changed.json> --out-dir <dir>`

## Functional requirements

1. The manifest is JSON with a components array. Each component has a unique non-empty id and a depends_on array of component ids. A depends_on B means A cannot execute before B.
2. The changed file is a JSON array of existing component ids. Unknown ids, duplicate component ids, missing dependency targets, self-loops, malformed JSON, and non-string ids are invalid.
3. Write <out-dir>/plan.json only on success. It contains changed, impacted, and levels. impacted is the sorted reverse transitive closure including changed components. levels contains all impacted components exactly once; dependencies that are also impacted must occur in an earlier level. Each level is sorted.
4. If the impacted subgraph contains a cycle, exit non-zero and do not create or replace plan.json.
5. Output JSON is UTF-8, key-sorted, deterministic, and independent of input object/array ordering where semantics are unchanged.

## Packaging requirements

- Keep implementation under `app/` with `app/__init__.py`.
- Include `pyproject.toml`, `README.md`, and runnable tests under `tests/`.
- Do not depend on network access, external services, wall-clock time, or files outside the workspace.
- Invalid input must fail with a controlled non-zero CLI exit or 4xx API response, never an uncaught traceback.
