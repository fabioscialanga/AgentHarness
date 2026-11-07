"""Host payload normalization for the opt-in Stop-event prototype."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HostEvent:
    host: str
    kind: str
    repeated_stop: bool


def normalize_stop(host: str, payload: Any) -> HostEvent:
    if host not in {"claude", "codex"}:
        raise ValueError("host must be claude or codex")
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "Stop":
        raise ValueError("expected a Stop hook JSON object")
    repeated = payload.get("stop_hook_active", False)
    if type(repeated) is not bool:
        raise ValueError("stop_hook_active must be boolean")
    return HostEvent(host=host, kind="turn_finished", repeated_stop=repeated)
