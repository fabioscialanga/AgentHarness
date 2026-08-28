from __future__ import annotations

import re
from typing import Any

from .interfaces import OriginError

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _key(value: Any) -> str:
    if not isinstance(value, str) or KEY.fullmatch(value) is None:
        raise ValueError("invalid key")
    return value


def _value(value: Any) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, bytes) or not value:
        raise ValueError("invalid tier value")
    return value


class TieredCache:
    def __init__(self, l1: Any, l2: Any, origin: Any):
        self._l1 = l1
        self._l2 = l2
        self._origin = origin

    def get(self, key: str) -> bytes:
        key = _key(key)
        first = _value(self._l1.get(key))
        if first is not None:
            return first
        second = _value(self._l2.get(key))
        if second is not None:
            self._l1.put(key, second)
            return second
        loaded = self._origin.load(key)
        if not isinstance(loaded, bytes) or not loaded:
            raise ValueError("invalid origin value")
        self._l2.put(key, loaded)
        self._l1.put(key, loaded)
        return loaded

    def invalidate(self, key: str) -> None:
        key = _key(key)
        self._l1.delete(key)
        self._l2.delete(key)
