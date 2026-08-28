from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "benchmarks/grading-env/mechanism-first-v5.2/references/transactional-release-pointer"
CHECKS = (
    "release_generation_cas",
    "release_artifact_approval",
    "release_publication_completeness",
    "release_failure_atomicity",
    "release_idempotent_replay",
)
PROBES = {name: 10 for name in CHECKS}
MUTANTS = list(CHECKS)
NEAR = "release_split_receipt_near_miss"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(ch: str) -> str:
    return "sha256:" + ch * 64


def command_fingerprint(channel_id: str, body: dict[str, Any]) -> str:
    value = {
        "artifact_digest": body["artifact_digest"],
        "channel_id": channel_id,
        "expected_generation": body["expected_generation"],
        "request_id": body["request_id"],
    }
    return hashlib.sha256(canonical(value)).hexdigest()


def load(root: Path):
    for name in list(sys.modules):
        if name == "release_pointer" or name.startswith("release_pointer."):
            del sys.modules[name]
    sys.path.insert(0, str(root))
    try:
        package = importlib.import_module("release_pointer")
        return package
    finally:
        sys.path.pop(0)


@dataclass
class Tx:
    number: int
    staged_channels: dict[str, Any] = field(default_factory=dict)
    staged_events: list[Any] = field(default_factory=list)
    staged_receipts: dict[str, Any] = field(default_factory=dict)
    active: bool = True


class EvaluatorStore:
    def __init__(self, package):
        self.Channel = package.Channel
        self.Event = package.PublicationEvent
        self.Receipt = package.Receipt
        self.StoreError = package.StoreError
        self.channels: dict[str, Any] = {}
        self.events: list[Any] = []
        self.receipts: dict[str, Any] = {}
        self.approved: set[str] = set()
        self.transactions: list[Tx] = []
        self.trace: list[tuple[Any, ...]] = []
        self.fail_on: str | None = None
        self.fail_used = False

    def _call(self, name: str, tx: Tx | None = None, *args: Any) -> None:
        self.trace.append((name, tx.number if tx else None, *args))
        if self.fail_on == name and not self.fail_used:
            self.fail_used = True
            raise self.StoreError(name)

    def _tx(self, tx: object) -> Tx:
        if type(tx) is not Tx or tx not in self.transactions or not tx.active:
            raise self.StoreError("invalid transaction")
        return tx

    def begin(self) -> object:
        self._call("begin")
        tx = Tx(len(self.transactions) + 1)
        self.transactions.append(tx)
        return tx

    def find_receipt(self, tx: object, request_id: str):
        current = self._tx(tx)
        self._call("find_receipt", current, request_id)
        return current.staged_receipts.get(request_id, self.receipts.get(request_id))

    def read_channel(self, tx: object, channel_id: str):
        current = self._tx(tx)
        self._call("read_channel", current, channel_id)
        return current.staged_channels.get(channel_id, self.channels.get(channel_id))

    def artifact_is_approved(self, tx: object, artifact_digest: str) -> bool:
        current = self._tx(tx)
        self._call("artifact_is_approved", current, artifact_digest)
        return artifact_digest in self.approved

    def stage_channel(self, tx: object, channel: Any) -> None:
        current = self._tx(tx)
        self._call("stage_channel", current, channel)
        current.staged_channels[channel.channel_id] = channel

    def stage_event(self, tx: object, event: Any) -> None:
        current = self._tx(tx)
        self._call("stage_event", current, event)
        current.staged_events.append(event)

    def stage_receipt(self, tx: object, receipt: Any) -> None:
        current = self._tx(tx)
        self._call("stage_receipt", current, receipt)
        current.staged_receipts[receipt.request_id] = receipt

    def list_events(self, tx: object, channel_id: str) -> list[Any]:
        current = self._tx(tx)
        self._call("list_events", current, channel_id)
        return [event for event in self.events + current.staged_events if event.channel_id == channel_id]

    def commit(self, tx: object) -> None:
        current = self._tx(tx)
        self._call("commit", current)
        self.channels.update(current.staged_channels)
        self.events.extend(current.staged_events)
        self.receipts.update(current.staged_receipts)
        current.active = False

    def rollback(self, tx: object) -> None:
        current = self._tx(tx)
        self._call("rollback", current)
        current.active = False

    def snapshot(self) -> tuple[Any, ...]:
        channels = tuple(sorted((key, value.artifact_digest, value.generation) for key, value in self.channels.items()))
        events = tuple(
            (event.request_id, event.channel_id, event.previous_digest, event.artifact_digest, event.generation)
            for event in self.events
        )
        receipts = tuple(
            sorted(
                (key, value.command_fingerprint, value.status_code, value.response_body)
                for key, value in self.receipts.items()
            )
        )
        return channels, events, receipts


class Scenario:
    def __init__(self, implementation: Path):
        package = load(implementation)
        self.package = package
        self.store = EvaluatorStore(package)
        self.store.channels["stable"] = package.Channel("stable", digest("a"), 7)
        self.store.approved.add(digest("b"))
        self.app = package.create_app(self.store)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def close(self) -> None:
        self.client.close()

    def body(self, request_id: str, expected: int = 7, artifact: str | None = None) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "expected_generation": expected,
            "artifact_digest": artifact or digest("b"),
        }

    def post(self, body: dict[str, Any], channel: str = "stable"):
        return self.client.post(f"/v1/channels/{channel}/publish", json=body)


def probe(implementation: Path, function) -> bool:
    scenario = Scenario(implementation)
    try:
        return bool(function(scenario))
    except Exception:
        return False
    finally:
        scenario.close()


def no_writes(store: EvaluatorStore) -> bool:
    return not any(row[0].startswith("stage_") or row[0] == "commit" for row in store.trace)


def check_generation(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        generation = index + 3
        s.store.channels["stable"] = s.package.Channel("stable", digest("a"), generation)
        expected = generation - 1 if index % 2 == 0 else generation + 1
        before = s.store.snapshot()
        response = s.post(s.body(f"generation-{index}", expected))
        names = [row[0] for row in s.store.trace]
        return (
            response.status_code == 409
            and response.json() == {"detail": "generation_conflict"}
            and s.store.snapshot() == before
            and names == ["begin", "find_receipt", "read_channel", "rollback"]
            and no_writes(s.store)
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def check_approval(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        artifact = digest("c" if index % 2 == 0 else "d")
        before = s.store.snapshot()
        response = s.post(s.body(f"approval-{index}", artifact=artifact))
        names = [row[0] for row in s.store.trace]
        return (
            response.status_code == 422
            and response.json() == {"detail": "artifact_not_approved"}
            and s.store.snapshot() == before
            and names == ["begin", "find_receipt", "read_channel", "artifact_is_approved", "rollback"]
            and no_writes(s.store)
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def expected_body(request_id: str, channel: str = "stable", previous: str | None = None, artifact: str | None = None, generation: int = 8) -> bytes:
    return canonical(
        {
            "artifact_digest": artifact or digest("b"),
            "channel_id": channel,
            "generation": generation,
            "previous_digest": previous or digest("a"),
            "request_id": request_id,
        }
    )


def check_completeness(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        request_id = f"complete-{index}"
        response = s.post(s.body(request_id))
        body = expected_body(request_id)
        names = [row[0] for row in s.store.trace]
        state_ok = s.store.snapshot() == (
            (("stable", digest("b"), 8),),
            ((request_id, "stable", digest("a"), digest("b"), 8),),
            ((request_id, command_fingerprint("stable", s.body(request_id)), 200, body),),
        )
        views_ok = (
            s.client.get("/v1/channels/stable").json()
            == {"artifact_digest": digest("b"), "channel_id": "stable", "generation": 8}
            and s.client.get("/v1/publication-events", params={"channel_id": "stable"}).json()
            == [{"artifact_digest": digest("b"), "channel_id": "stable", "generation": 8, "previous_digest": digest("a"), "request_id": request_id}]
            and s.client.get(f"/v1/publication-receipts/{request_id}").content == body
        )
        return (
            response.status_code == 200
            and response.content == body
            and state_ok
            and names == ["begin", "find_receipt", "read_channel", "artifact_is_approved", "stage_channel", "stage_event", "stage_receipt", "commit"]
            and views_ok
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def seed_prior(s: Scenario, index: int) -> None:
    request_id = f"prior-{index}"
    body = s.body(request_id)
    response = expected_body(request_id)
    s.store.events.append(s.package.PublicationEvent(request_id, "stable", digest("0"), digest("a"), 7))
    s.store.receipts[request_id] = s.package.Receipt(request_id, command_fingerprint("stable", body), 200, response)


def check_atomicity(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        seed_prior(s, index)
        before = s.store.snapshot()
        s.store.fail_on = "stage_receipt" if index < 5 else "commit"
        response = s.post(s.body(f"atomic-{index}"))
        names = [row[0] for row in s.store.trace]
        return (
            response.status_code == 503
            and response.json() == {"detail": "storage_failure"}
            and s.store.fail_used
            and s.store.fail_on in names
            and "rollback" in names
            and s.store.snapshot() == before
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


def check_replay(implementation: Path) -> bool:
    def run(s: Scenario, index: int) -> bool:
        request_id = f"replay-{index}"
        original = s.body(request_id)
        body = expected_body(request_id)
        s.store.channels["stable"] = s.package.Channel("stable", digest("b"), 8)
        s.store.events.append(s.package.PublicationEvent(request_id, "stable", digest("a"), digest("b"), 8))
        s.store.receipts[request_id] = s.package.Receipt(request_id, command_fingerprint("stable", original), 200, body)
        before = s.store.snapshot()
        exact = s.post(original)
        conflict_body = dict(original)
        conflict_body["artifact_digest"] = digest("c")
        conflict = s.post(conflict_body)
        names = [row[0] for row in s.store.trace]
        return (
            exact.status_code == 200
            and exact.content == body
            and conflict.status_code == 409
            and conflict.json() == {"detail": "request_id_conflict"}
            and s.store.snapshot() == before
            and not any(name.startswith("stage_") or name == "commit" for name in names)
            and names.count("read_channel") == 0
            and names.count("artifact_is_approved") == 0
        )
    return all(probe(implementation, lambda s, i=i: run(s, i)) for i in range(10))


FUNCTIONS = {
    "release_generation_cas": check_generation,
    "release_artifact_approval": check_approval,
    "release_publication_completeness": check_completeness,
    "release_failure_atomicity": check_atomicity,
    "release_idempotent_replay": check_replay,
}


def common_controls(implementation: Path) -> tuple[dict[str, bool], dict[str, int]]:
    invalid_cases: list[Any] = [
        None,
        [],
        "text",
        {},
        {"request_id": "r", "expected_generation": 7},
        {"request_id": "r", "expected_generation": True, "artifact_digest": digest("b")},
        {"request_id": "", "expected_generation": 7, "artifact_digest": digest("b")},
        {"request_id": "r", "expected_generation": -1, "artifact_digest": digest("b")},
        {"request_id": "r", "expected_generation": 7, "artifact_digest": "SHA256:" + "b" * 64},
        {"request_id": "r", "expected_generation": 7, "artifact_digest": digest("b"), "extra": 1},
    ]

    def invalid(s: Scenario, body: Any) -> bool:
        response = s.client.post("/v1/channels/stable/publish", json=body)
        return response.status_code == 422 and response.json() == {"detail": "invalid_request"} and s.store.trace == []

    validation = all(probe(implementation, lambda s, b=body: invalid(s, b)) for body in invalid_cases)

    def malformed(s: Scenario) -> bool:
        response = s.client.post("/v1/channels/stable/publish", content=b"{", headers={"content-type": "application/json"})
        return response.status_code == 422 and response.json() == {"detail": "invalid_request"} and s.store.trace == []

    validation = validation and probe(implementation, malformed)
    return {"release_strict_validation": validation}, {"release_strict_validation": len(invalid_cases) + 1}


def materialize(mutant: str, temporary: Path) -> Path:
    sys.path.insert(0, str(ROOT / "benchmarks/grading-env"))
    try:
        from materialize_v5_crypto_mutants import materialize_mutant
        return materialize_mutant(REFERENCE, "transactional-release-pointer", mutant, temporary / mutant)
    finally:
        sys.path.pop(0)


def evaluate(implementation: Path, name: str) -> dict[str, Any]:
    common, common_probes = common_controls(implementation)
    checks = {check: FUNCTIONS[check](implementation) for check in CHECKS}
    return {
        "implementation": name,
        "checks": checks,
        "failed": [check for check in CHECKS if not checks[check]],
        "passed": [check for check in CHECKS if checks[check]],
        "common_controls": common,
        "common_failed": [check for check, passed in common.items() if not passed],
        "common_probe_counts": common_probes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    matrix: list[dict[str, Any]] = []
    if args.workspace:
        matrix.append(evaluate(args.workspace.resolve(), "candidate"))
    else:
        with tempfile.TemporaryDirectory(prefix="v52-release-") as raw:
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
            and matrix[6]["failed"] == ["release_failure_atomicity"]
            and not matrix[6]["common_failed"]
        )
    print(
        json.dumps(
            {
                "task_id": "transactional-release-pointer",
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
