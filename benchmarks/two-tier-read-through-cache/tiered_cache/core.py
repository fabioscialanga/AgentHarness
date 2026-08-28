from __future__ import annotations

from typing import Any


class TieredCache:
    def __init__(self, l1: Any, l2: Any, origin: Any):
        raise NotImplementedError("implement the public contract")

    def get(self, key: str) -> bytes:
        raise NotImplementedError("implement the public contract")

    def invalidate(self, key: str) -> None:
        raise NotImplementedError("implement the public contract")
