from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def match(pattern: str, value: str) -> bool:
    if "*" not in pattern: return pattern == value
    if not pattern.endswith("*") or pattern.count("*") != 1: raise ValueError("invalid wildcard")
    if MUTANT == "policy_wildcard_matching": return pattern == value
    return value.startswith(pattern[:-1])


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--policy",required=True); parser.add_argument("--requests",required=True); parser.add_argument("--out-dir",required=True); args=parser.parse_args()
    try:
        policy=json.loads(Path(args.policy).read_text()); rules=policy["rules"]
        ids=[r["id"] for r in rules]
        if len(ids)!=len(set(ids)): raise ValueError("duplicate rule")
        for r in rules:
            if r.get("effect") not in {"allow","deny"} or not (r.get("subjects") or r.get("groups")): raise ValueError("invalid rule")
            if not isinstance(r.get("actions"),list) or not r["actions"] or not all(isinstance(p,str) for p in r["actions"]): raise ValueError("invalid actions")
            if not isinstance(r.get("resources"),list) or not r["resources"] or not all(isinstance(p,str) for p in r["resources"]): raise ValueError("invalid resources")
            for p in [*r.get("actions",[]),*r.get("resources",[])]:
                if "*" in p and (not p.endswith("*") or p.count("*")!=1): raise ValueError("invalid wildcard")
            start=parse_time(r["valid_from"]) if r.get("valid_from") else None
            end=parse_time(r["valid_until"]) if r.get("valid_until") else None
            if start is not None and end is not None and start>=end: raise ValueError("invalid interval")
        decisions=[]; rejected=[]
        for line_no,line in enumerate(Path(args.requests).read_text().splitlines(),1):
            try:
                req=json.loads(line)
                for key in ["request_id","subject","groups","action","resource","as_of"]:
                    if key not in req: raise ValueError(f"missing {key}")
                as_of=parse_time(req["as_of"]); matched=[]
                for rule in rules:
                    direct=req["subject"] in rule.get("subjects",[])
                    group=bool(set(req["groups"]) & set(rule.get("groups",[])))
                    if MUTANT == "policy_subject_group_composition": direct=False
                    if not (direct or group): continue
                    if not any(match(p,req["action"]) for p in rule.get("actions",[])): continue
                    if not any(match(p,req["resource"]) for p in rule.get("resources",[])): continue
                    start=parse_time(rule["valid_from"]) if rule.get("valid_from") else None
                    end=parse_time(rule["valid_until"]) if rule.get("valid_until") else None
                    temporal=(start is None or as_of>=start) and (end is None or as_of<end)
                    if MUTANT == "policy_temporal_validity": temporal=(start is None or as_of>=start)
                    if temporal: matched.append(rule)
                effects={r["effect"] for r in matched}
                if MUTANT == "policy_deny_default_precedence": decision="allow" if "allow" in effects else "deny"
                else: decision="deny" if "deny" in effects else ("allow" if "allow" in effects else "deny")
                decisions.append({"request_id":req["request_id"],"decision":decision,"matched_rule_ids":sorted(r["id"] for r in matched)})
            except Exception as exc:
                rejected.append({"line_number":line_no,"reason":"invalid_request"})
        if MUTANT == "policy_rejections_determinism": rejected.append({"line_number":999,"reason":os.getenv("PYTHONHASHSEED","")})
        out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
        (out/"decisions.jsonl").write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in decisions))
        (out/"rejected.jsonl").write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rejected))
        summary={"allow_count":sum(x["decision"]=="allow" for x in decisions),"deny_count":sum(x["decision"]=="deny" for x in decisions),"rejected_count":len(rejected),"request_count":len(decisions)}
        (out/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
        return 0
    except Exception as exc:
        print(str(exc),file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
