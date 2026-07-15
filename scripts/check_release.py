#!/usr/bin/env python3
"""Validate that a release tag matches package metadata and the changelog."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

TAG_PATTERN = re.compile(r"^v(?P<version>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")


def validate_release(tag: str, pyproject_path: Path, changelog_path: Path) -> list[str]:
    errors: list[str] = []
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        return [f"tag must use stable semantic-version form vMAJOR.MINOR.PATCH, got: {tag!r}"]

    tag_version = tag[1:]
    with pyproject_path.open("rb") as stream:
        project = tomllib.load(stream)["project"]
    package_version = str(project["version"])
    if package_version != tag_version:
        errors.append(
            f"tag version {tag_version!r} does not match pyproject version {package_version!r}"
        )

    changelog = changelog_path.read_text(encoding="utf-8")
    release_heading = re.compile(
        rf"^## {re.escape(tag_version)} - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE
    )
    if release_heading.search(changelog) is None:
        errors.append(
            f"CHANGELOG.md must contain a dated '## {tag_version} - YYYY-MM-DD' heading"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Release tag, for example v0.1.0")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    args = parser.parse_args(argv)

    try:
        errors = validate_release(args.tag, args.pyproject, args.changelog)
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"release validation failed: {error}", file=sys.stderr)
        return 1

    print(f"release validation passed for {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
