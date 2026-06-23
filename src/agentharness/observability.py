from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class EventLogger:
    trace_id: str
    output_path: Path
    run_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        output_path: str | Path,
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> "EventLogger":
        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(trace_id=trace_id or uuid4().hex, output_path=path, run_id=run_id)

    def emit(self, event_type: str, **payload: Any) -> None:
        record = {
            "ts": utc_now_iso(),
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "event_type": event_type,
            "payload": payload,
        }
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def default_trace_path(workspace: str | Path, trace_kind: str, trace_id: str | None = None) -> Path:
    resolved_workspace = Path(workspace).resolve()
    final_trace_id = trace_id or uuid4().hex
    return resolved_workspace / ".agentharness" / "traces" / trace_kind / f"{final_trace_id}.jsonl"
