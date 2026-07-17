from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")
ACTIONS = {"redact", "remove", "pseudonymize"}


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys: raise ValueError(f"invalid {label} fields")
    return value


def decode_selector(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.startswith("/"): raise ValueError("selector must be non-root pointer")
    result = []
    for raw in value[1:].split("/"):
        decoded = ""; i = 0
        while i < len(raw):
            if raw[i] == "~":
                if i + 1 >= len(raw) or raw[i + 1] not in "01": raise ValueError("invalid pointer escape")
                decoded += "~" if raw[i + 1] == "0" else "/"; i += 2
            else: decoded += raw[i]; i += 1
        result.append(decoded)
    return result


def encode_path(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(x.replace("~", "~0").replace("/", "~1") for x in parts)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def walk(value: Any, parts: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield parts + (key,), child
            yield from walk(child, parts + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            part = str(index)
            yield parts + (part,), child
            yield from walk(child, parts + (part,))


def match(pattern: list[str], path: tuple[str, ...]) -> bool:
    if len(pattern) != len(path): return False
    if MUTANT == "pii_selector_resolution" and "*" in pattern[:-1]: return False
    return all(expected == "*" or expected == actual for expected, actual in zip(pattern, path))


def parent_at(root: Any, path: tuple[str, ...]) -> tuple[Any, str]:
    parent = root
    for token in path[:-1]: parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    return parent, path[-1]


def transform(document: Any, rules_doc: Any, key_doc: Any) -> dict[str, Any]:
    rules_raw = exact(rules_doc, {"schema_version", "rules"}, "rules document")
    if rules_raw["schema_version"] != 1 or not isinstance(rules_raw["rules"], list): raise ValueError("invalid rules document")
    parsed = []; ids = set()
    for raw in rules_raw["rules"]:
        if not isinstance(raw, dict): raise ValueError("invalid rule")
        action = raw.get("action")
        required = {"id", "selector", "action", "replacement"} if action == "redact" else {"id", "selector", "action"}
        rule = exact(raw, required, "rule")
        if not isinstance(rule["id"], str) or not rule["id"] or rule["id"] in ids: raise ValueError("invalid or duplicate rule id")
        ids.add(rule["id"])
        if action not in ACTIONS: raise ValueError("invalid action")
        if action == "redact" and not isinstance(rule["replacement"], str): raise ValueError("replacement must be a string")
        pattern = decode_selector(rule["selector"])
        parsed.append((rule, pattern, sum(x != "*" for x in pattern)))
    key = exact(key_doc, {"secret_hex"}, "key")
    secret_hex = key["secret_hex"]
    if not isinstance(secret_hex, str) or not secret_hex or len(secret_hex) % 2:
        raise ValueError("invalid key")
    try: secret = bytes.fromhex(secret_hex)
    except ValueError as exc: raise ValueError("invalid key") from exc
    selected: dict[tuple[str, ...], dict[str, Any]] = {}
    original_values = dict(walk(document))
    for path in original_values:
        candidates = [(rule, specificity) for rule, pattern, specificity in parsed if match(pattern, path)]
        if not candidates: continue
        best = max(score for _, score in candidates)
        winners = [rule for rule, score in candidates if score == best]
        # IDs identify otherwise-identical rules; every public semantic field must
        # agree.  In particular, equal-specificity selectors are not interchangeable
        # merely because they happen to overlap at this path.
        semantics = {
            (r["selector"], r["action"], r.get("replacement")) for r in winners
        }
        if len(semantics) > 1 and MUTANT != "pii_rule_precedence": raise ValueError("conflicting equal-specificity rules")
        if MUTANT == "pii_rule_precedence":
            selected[path] = winners[0]
        else:
            selected[path] = sorted(winners, key=lambda r: r["id"])[0]
    output = copy.deepcopy(document)
    audit = []
    # Deepest paths first; descending array indexes prevent drift. Selecting an ancestor suppresses descendants.
    def order_key(path: tuple[str, ...]) -> tuple[Any, ...]:
        return (len(path),) + tuple((1, int(x)) if x.isdigit() else (0, x) for x in path)
    paths = sorted(selected, key=order_key, reverse=True)
    removed_ancestors: list[tuple[str, ...]] = []
    for path in paths:
        if any(path[:len(a)] == a for a in removed_ancestors): continue
        rule = selected[path]; parent, token = parent_at(output, path); current = parent[int(token)] if isinstance(parent, list) else parent[token]
        action = rule["action"]
        if action == "remove":
            if isinstance(parent, list): parent.pop(int(token))
            else: del parent[token]
            removed_ancestors.append(path)
        elif action == "redact":
            if isinstance(parent, list): parent[int(token)] = rule["replacement"]
            else: parent[token] = rule["replacement"]
        else:
            digest = hashlib.sha256(canonical(current)).hexdigest() if MUTANT == "pii_redaction_actions" else hmac.new(secret, canonical(current), hashlib.sha256).hexdigest()
            replacement = "hmac-sha256:" + digest
            if isinstance(parent, list): parent[int(token)] = replacement
            else: parent[token] = replacement
        audit.append({"path": encode_path(path), "rule_id": rule["id"], "selector": rule["selector"], "action": action})
    if MUTANT == "pii_structure_preservation" and selected:
        selected_top = {path[0] for path in selected}
        if isinstance(output, dict): output = {key: value for key, value in output.items() if key in selected_top}
    audit.sort(key=lambda x: (x["path"], x["rule_id"]))
    if MUTANT == "pii_atomic_audit" and audit: audit.pop()
    return {"redacted": output, "audit": audit}


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle: handle.write(canonical(value) + b"\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for flag in ("input", "rules", "key", "output-bundle"): parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.input.open(encoding="utf-8") as f: document = json.load(f)
        if not isinstance(document, (dict, list)): raise ValueError("input root must be object or array")
        with args.rules.open(encoding="utf-8") as f: rules = json.load(f)
        with args.key.open(encoding="utf-8") as f: key = json.load(f)
        atomic_write(args.output_bundle, transform(document, rules, key)); return 0
    except (OSError, ValueError, json.JSONDecodeError, KeyError, IndexError) as exc:
        print(f"redaction failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
