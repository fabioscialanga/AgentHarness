from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MUTANT = os.getenv("AGENTHARNESS_MUTANT", "")


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--changed", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text())
        changed = json.loads(Path(args.changed).read_text())
        components = manifest["components"]
        if not isinstance(components, list) or not isinstance(changed, list) or not all(isinstance(x, str) for x in changed):
            raise ValueError("invalid input shape")
        ids = [item["id"] for item in components]
        if MUTANT != "dependency_graph_validation":
            if not all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] and isinstance(item.get("depends_on"), list) and all(isinstance(x, str) for x in item["depends_on"]) for item in components): raise ValueError("invalid component")
            if len(ids) != len(set(ids)): raise ValueError("duplicate id")
        graph = {item["id"]: list(item.get("depends_on", [])) for item in components}
        if MUTANT != "dependency_graph_validation":
            if any(dep not in graph or dep == node for node, deps in graph.items() for dep in deps): raise ValueError("invalid dependency")
            if any(x not in graph for x in changed): raise ValueError("unknown changed id")
        reverse = {node: [] for node in graph}
        for node, deps in graph.items():
            for dep in deps:
                if dep in reverse: reverse[dep].append(node)
        impacted = set(changed)
        queue = list(changed)
        while queue:
            current = queue.pop(0)
            for dependent in reverse.get(current, []):
                if dependent not in impacted:
                    impacted.add(dependent); queue.append(dependent)
        reported_impacted = set(changed) if MUTANT == "dependency_reverse_impact" else set(impacted)
        indegree = {node: sum(1 for dep in graph.get(node, []) if dep in impacted) for node in impacted}
        levels = []
        remaining = set(impacted)
        while remaining:
            level = [node for node in remaining if indegree[node] == 0]
            if not level:
                if MUTANT == "dependency_cycle_atomic":
                    level = list(remaining)
                else:
                    raise ValueError("cycle detected")
            level.sort()
            levels.append(level)
            for node in level:
                remaining.remove(node)
                for dependent in reverse.get(node, []):
                    if dependent in indegree: indegree[dependent] -= 1
        if MUTANT == "dependency_parallel_levels" and len(levels) > 1:
            levels = [sorted(impacted)]
        payload = {"changed": sorted(changed), "impacted": sorted(reported_impacted), "levels": levels}
        out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
        if MUTANT == "dependency_deterministic_output": payload["run_seed"] = os.getenv("PYTHONHASHSEED", "")
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        (out / "plan.json").write_text(text)
        return 0
    except Exception as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
