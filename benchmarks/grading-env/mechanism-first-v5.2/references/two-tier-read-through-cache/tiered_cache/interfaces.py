from __future__ import annotations

from typing import Protocol


class OriginError(Exception):
    """Controlled origin failure; it must not be cached."""


class TierStore(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, value: bytes) -> None: ...
    def delete(self, key: str) -> None: ...


class Origin(Protocol):
    def load(self, key: str) -> bytes: ...
