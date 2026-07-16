# versioned-document-api

## Objective

Persist versioned JSON documents with optimistic concurrency and immutable revision history.

## Required stack

Python 3.11+, FastAPI, Pydantic, SQLAlchemy, SQLite, pytest

## Required entrypoint

`app.main:app`

## Functional requirements

1. Provide a FastAPI object at app.main:app and persist state in SQLite through SQLAlchemy. POST /documents accepts {document: <object>} and returns a generated document_id, revision 1, document, and strong ETag header formatted "v1".
2. GET /documents/{document_id} returns the current representation and ETag. State must survive process termination.
3. PATCH /documents/{document_id} requires If-Match and an RFC 7396 JSON Merge Patch object. A matching ETag creates exactly one new revision. A missing or stale precondition returns 428 or 412 and changes neither current state nor history.
4. GET /documents/{document_id}/revisions returns contiguous ascending immutable snapshots. Reads and failed writes create no revision.
5. POST /documents/{document_id}/restore/{revision} requires current If-Match and restores that historical snapshot as a new latest revision without deleting or rewriting history. Unknown documents/revisions return controlled 4xx responses.

## Packaging requirements

- Keep implementation under `app/` with `app/__init__.py`.
- Include `pyproject.toml`, `README.md`, and runnable tests under `tests/`.
- Do not depend on network access, external services, wall-clock time, or files outside the workspace.
- Invalid input must fail with a controlled non-zero CLI exit or 4xx API response, never an uncaught traceback.
