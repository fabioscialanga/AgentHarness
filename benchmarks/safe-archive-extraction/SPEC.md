# safe-archive-extraction

## Objective

Safely and atomically extract regular ZIP contents with a deterministic manifest.

## Required stack

Python 3.11+, pytest

## Required entrypoint

`python -m app.extract_archive --archive <input.zip> --out-dir <dir> --max-entries <N> --max-bytes <B>`

## Functional requirements

1. On success extract regular files/directories below out-dir and write manifest.json as an object with exactly the keys files, file_count, and total_bytes and no additional top-level keys. files is sorted by path and each record has exactly path, size, and sha256 with no additional keys; size is the integer uncompressed byte count and sha256 is lowercase. file_count and total_bytes summarize the records.
2. Reject absolute paths, drive-prefixed paths, any .. component, backslashes, empty normalized file names, and any path escaping out-dir.
3. Reject symlinks and non-regular special entries using ZIP metadata. Directory entries are allowed.
4. Before extraction reject duplicate normalized names and file/directory prefix conflicts. Path comparison is case-sensitive and uses POSIX / separators.
5. Enforce positive max-entries and max-bytes against regular file count and total declared uncompressed bytes before committing output. Corrupt archives and every validation failure exit non-zero without creating or changing out-dir.

## Packaging requirements

- Keep implementation under `app/` with `app/__init__.py`.
- Include `pyproject.toml`, `README.md`, and runnable tests under `tests/`.
- Do not depend on network access, external services, wall-clock time, or files outside the workspace.
- Invalid input must fail with a controlled non-zero CLI exit or 4xx API response, never an uncaught traceback.
