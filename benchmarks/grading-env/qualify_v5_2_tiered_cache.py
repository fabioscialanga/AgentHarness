from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "benchmarks/grading-env/mechanism-first-v5.2/references/two-tier-read-through-cache"
CHECKS = (
    "tier_l1_short_circuit",
    "tier_l2_promotion",
    "tier_origin_fill",
    "tier_two_level_invalidation",
    "tier_failure_non_admission",
)
PROBES = {check: 10 for check in CHECKS}
MUTANTS = list(CHECKS)
NEAR = "tier_l2_casefold_delete_near_miss"
SENTINEL = b"__origin_error__"


def load(root: Path):
    for name in list(sys.modules):
        if name == "tiered_cache" or name.startswith("tiered_cache."):
            del sys.modules[name]
    sys.path.insert(0, str(root))
    try:
        return importlib.import_module("tiered_cache")
    finally:
        sys.path.pop(0)


class Tier:
    def __init__(self, name: str, trace: list[tuple[Any, ...]]):
        self.name = name
        self.trace = trace
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        self.trace.append((f"{self.name}.get", key))
        return self.data.get(key)

    def put(self, key: str, value: bytes) -> None:
        self.trace.append((f"{self.name}.put", key, value))
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.trace.append((f"{self.name}.delete", key))
        self.data.pop(key, None)


class Origin:
    def __init__(self, trace: list[tuple[Any, ...]], origin_error):
        self.trace = trace
        self.origin_error = origin_error
        self.actions: list[Any] = []

    def load(self, key: str) -> bytes:
        self.trace.append(("origin.load", key))
        if not self.actions:
            raise AssertionError("unexpected origin call")
        action = self.actions.pop(0)
        if isinstance(action, self.origin_error):
            raise action
        return action


class Scenario:
    def __init__(self, implementation: Path):
        self.package = load(implementation)
        self.trace: list[tuple[Any, ...]] = []
        self.l1 = Tier("l1", self.trace)
        self.l2 = Tier("l2", self.trace)
        self.origin = Origin(self.trace, self.package.OriginError)
        self.cache = self.package.TieredCache(self.l1, self.l2, self.origin)


def probe(implementation: Path, function) -> bool:
    try:
        return bool(function(Scenario(implementation)))
    except Exception:
        return False


def token(index: int, label: int) -> bytes:
    value = bytes((index + label + offset) % 251 + 1 for offset in range(17))
    if value == SENTINEL:
        raise AssertionError("reserved sentinel collision")
    return value


def check_l1(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        key = f"Doc-{index}"
        first, second, third = token(index, 1), token(index, 31), token(index, 61)
        s.l1.data[key] = first
        s.l2.data[key] = second
        s.origin.actions = [third]
        result = s.cache.get(key)
        return result is first and s.trace == [("l1.get", key)] and s.l2.data[key] is second and s.origin.actions == [third]
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def check_l2(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        key = f"Layer-{index}"
        second, third = token(index, 21), token(index, 71)
        s.l2.data[key] = second
        s.origin.actions = [third]
        result = s.cache.get(key)
        return (
            result is second
            and s.l1.data.get(key) is second
            and s.l2.data[key] is second
            and s.origin.actions == [third]
            and s.trace == [("l1.get", key), ("l2.get", key), ("l1.put", key, second)]
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def check_origin(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        key = f"Origin-{index}"
        loaded = token(index, 41)
        s.origin.actions = [loaded]
        result = s.cache.get(key)
        return (
            result is loaded
            and s.l1.data.get(key) is loaded
            and s.l2.data.get(key) is loaded
            and s.trace
            == [
                ("l1.get", key),
                ("l2.get", key),
                ("origin.load", key),
                ("l2.put", key, loaded),
                ("l1.put", key, loaded),
            ]
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def check_invalidation(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        key = f"Doc-{index}" if index < 5 else f"doc-{index}"
        stale1, stale2, fresh = token(index, 3), token(index, 33), token(index, 93)
        s.l1.data[key] = stale1
        s.l2.data[key] = stale2
        s.origin.actions = [fresh]
        result = s.cache.invalidate(key)
        loaded = s.cache.get(key)
        return (
            result is None
            and loaded is fresh
            and s.trace[:5]
            == [
                ("l1.delete", key),
                ("l2.delete", key),
                ("l1.get", key),
                ("l2.get", key),
                ("origin.load", key),
            ]
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def check_failure(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        key = f"Failure-{index}"
        failure = s.package.OriginError(f"failure-{index}")
        fresh = token(index, 111)
        s.origin.actions = [failure, fresh]
        try:
            s.cache.get(key)
            return False
        except s.package.OriginError as caught:
            if caught is not failure:
                return False
        first_trace = list(s.trace)
        if any(row[0].endswith(".put") for row in first_trace) or s.l1.data or s.l2.data:
            return False
        result = s.cache.get(key)
        return (
            result is fresh
            and s.origin.actions == []
            and sum(row == ("origin.load", key) for row in s.trace) == 2
            and first_trace == [("l1.get", key), ("l2.get", key), ("origin.load", key)]
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


FUNCTIONS = {
    "tier_l1_short_circuit": check_l1,
    "tier_l2_promotion": check_l2,
    "tier_origin_fill": check_origin,
    "tier_two_level_invalidation": check_invalidation,
    "tier_failure_non_admission": check_failure,
}


def common_controls(implementation: Path) -> tuple[dict[str, bool], dict[str, int]]:
    invalid_keys: list[Any] = [None, True, 1, "", "bad/key", " x", "x " , "x" * 65]

    def invalid(s: Scenario, value: Any, operation: str) -> bool:
        try:
            getattr(s.cache, operation)(value)
            return False
        except ValueError:
            return s.trace == []
        except Exception:
            return False

    key_guard = all(
        probe(implementation, lambda s, v=value, op=operation: invalid(s, v, op))
        for value in invalid_keys
        for operation in ("get", "invalidate")
    )

    def invalid_origin(s: Scenario, value: Any) -> bool:
        s.origin.actions = [value]
        try:
            s.cache.get("Valid-Key")
            return False
        except ValueError:
            return not any(row[0].endswith(".put") for row in s.trace)
        except Exception:
            return False

    origin_guard = all(probe(implementation, lambda s, v=value: invalid_origin(s, v)) for value in (None, b"", "bytes", 1, True))

    def valid_boundaries(s: Scenario, key: str) -> bool:
        value = token(len(key), 17)
        s.origin.actions = [value]
        return s.cache.get(key) is value

    boundaries = all(probe(implementation, lambda s, k=key: valid_boundaries(s, k)) for key in ("A", "z" * 64, "Case.Key-1"))
    return (
        {
            "tier_invalid_key_guard": key_guard,
            "tier_invalid_origin_guard": origin_guard,
            "tier_key_boundaries": boundaries,
        },
        {
            "tier_invalid_key_guard": len(invalid_keys) * 2,
            "tier_invalid_origin_guard": 5,
            "tier_key_boundaries": 3,
        },
    )


def materialize(mutant: str, temporary: Path) -> Path:
    sys.path.insert(0, str(ROOT / "benchmarks/grading-env"))
    try:
        from materialize_v5_crypto_mutants import materialize_mutant
        return materialize_mutant(REFERENCE, "two-tier-read-through-cache", mutant, temporary / mutant)
    finally:
        sys.path.pop(0)


def evaluate(implementation: Path, name: str) -> dict[str, Any]:
    common, counts = common_controls(implementation)
    checks = {check: FUNCTIONS[check](implementation) for check in CHECKS}
    return {
        "implementation": name,
        "checks": checks,
        "failed": [check for check in CHECKS if not checks[check]],
        "passed": [check for check in CHECKS if checks[check]],
        "common_controls": common,
        "common_failed": [check for check, passed in common.items() if not passed],
        "common_probe_counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    matrix: list[dict[str, Any]] = []
    if args.workspace:
        matrix.append(evaluate(args.workspace.resolve(), "candidate"))
    else:
        with tempfile.TemporaryDirectory(prefix="v52-tiered-") as raw:
            temporary = Path(raw)
            matrix.append(evaluate(REFERENCE, "reference"))
            for mutant in MUTANTS + [NEAR]:
                matrix.append(evaluate(materialize(mutant, temporary), mutant))
    if args.workspace:
        ok = not matrix[0]["failed"] and not matrix[0]["common_failed"]
    else:
        ok = (
            not matrix[0]["failed"]
            and not matrix[0]["common_failed"]
            and all(row["failed"] == [row["implementation"]] and not row["common_failed"] for row in matrix[1:6])
            and matrix[6]["failed"] == ["tier_two_level_invalidation"]
            and not matrix[6]["common_failed"]
        )
    print(
        json.dumps(
            {
                "task_id": "two-tier-read-through-cache",
                "ok": ok,
                "checks": list(CHECKS),
                "probe_counts": PROBES,
                "total_scored_probes_per_implementation": 50,
                "matrix": matrix,
                "target_model_calls": 0,
                "efficacy_cells": False,
            },
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
