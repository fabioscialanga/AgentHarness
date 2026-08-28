from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def create_app(store: Any) -> FastAPI:
    """Build the release-pointer API described in SPEC.md."""
    raise NotImplementedError("implement the public contract")
