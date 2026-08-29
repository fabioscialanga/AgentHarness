from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI


def create_app(
    db_path: str | Path,
    execute_once: Callable[[str, str, int, str, dict[str, Any]], str],
) -> FastAPI:
    """Build the portable command receipt API described in SPEC.md."""
    raise NotImplementedError("implement the public contract")
