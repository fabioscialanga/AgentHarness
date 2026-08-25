"""Implement the command described in SPEC.md."""

import os
from pathlib import Path
from typing import Callable


def decrypt_to_file(
    envelope_path: Path,
    context_path: Path,
    keyring_path: Path,
    output_path: Path,
    *,
    replace: Callable[[str | bytes | os.PathLike[str] | os.PathLike[bytes], str | bytes | os.PathLike[str] | os.PathLike[bytes]], None] = os.replace,
) -> None:
    raise NotImplementedError("See SPEC.md")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("See SPEC.md")


if __name__ == "__main__":
    raise SystemExit(main())
