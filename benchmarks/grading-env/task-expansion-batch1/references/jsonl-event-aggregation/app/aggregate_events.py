from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    source = Path(args.input)
    if not source.is_file():
        print("input file not found", file=sys.stderr)
        return 2
    groups: dict[tuple[str, str], dict] = {}
    rejected: list[dict] = []
    acquired: set[str] = set()
    accepted = 0
    duplicates = 0
    total = 0
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        event_id = None
        if not raw.strip():
            rejected.append({"line_number": line_number, "event_id": None, "reason": "blank_line"})
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            rejected.append({"line_number": line_number, "event_id": None, "reason": "malformed_json"})
            continue
        if not isinstance(value, dict):
            rejected.append({"line_number": line_number, "event_id": None, "reason": "not_object"})
            continue
        event_id = value.get("event_id") if isinstance(value.get("event_id"), str) else None
        required = ["event_id", "actor_id", "event_type", "occurred_at", "value"]
        if any(key not in value for key in required):
            rejected.append({"line_number": line_number, "event_id": event_id, "reason": "missing_field"})
            continue
        try:
            if not all(isinstance(value[key], str) and value[key] for key in ["event_id", "actor_id", "event_type"]):
                raise ValueError
            if isinstance(value["value"], bool) or not isinstance(value["value"], int) or value["value"] < 0:
                raise ValueError
            occurred = parse_timestamp(value["occurred_at"])
        except (ValueError, TypeError):
            if MUTANT == "jsonl_invalid_and_duplicate_handling" and event_id:
                acquired.add(event_id)
            rejected.append({"line_number": line_number, "event_id": event_id, "reason": "invalid_field"})
            continue
        valid_event_id = str(value["event_id"])
        if valid_event_id in acquired:
            duplicates += 1
            if MUTANT != "jsonl_invalid_and_duplicate_handling":
                rejected.append({"line_number": line_number, "event_id": valid_event_id, "reason": "duplicate_event_id"})
                continue
        acquired.add(valid_event_id)
        date_key = occurred.date().isoformat() if MUTANT != "jsonl_utc_date_normalization" else value["occurred_at"][:10]
        key = (date_key, value["event_type"])
        group = groups.setdefault(key, {"date": date_key, "event_type": value["event_type"], "event_count": 0, "unique_actor_count": 0, "value_total": 0, "_actors": set()})
        group["event_count"] += 1
        group["_actors"].add(value["actor_id"])
        group["unique_actor_count"] = len(group["_actors"])
        if MUTANT != "jsonl_grouped_counts":
            group["value_total"] += value["value"]
        accepted += 1
        total += value["value"]
    output_groups = []
    for key in sorted(groups):
        item = dict(groups[key])
        item.pop("_actors")
        output_groups.append(item)
    summary = {"accepted_count": accepted, "rejected_count": len(rejected), "duplicate_count": duplicates, "group_count": len(output_groups), "value_total": total}
    if MUTANT == "jsonl_summary_consistency":
        summary["accepted_count"] += 1
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    aggregate_payload = {"groups": output_groups, "summary": summary}
    if MUTANT == "jsonl_deterministic_outputs":
        aggregate_payload["run_seed"] = os.getenv("PYTHONHASHSEED", "")
    aggregates_text = json.dumps(aggregate_payload, indent=2, sort_keys=True) + "\n"
    rejected_text = "".join(json.dumps(item, sort_keys=True) + "\n" for item in rejected)
    (out / "aggregates.json").write_text(aggregates_text, encoding="utf-8")
    (out / "rejected.jsonl").write_text(rejected_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
