from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .benchmark_hidden_evaluators import (
    HiddenEvaluationResult,
    _evaluation_dir,
    _finalize_hidden_evaluation,
    _interface_unreachable_result,
    _load_fastapi_app,
    _make_test_client,
    _working_directory,
)
from .benchmark_hidden_evaluators_batch1 import _json_payload, _recorder
from .benchmark_hidden_evaluators_batch2 import _finish_runtime

TASK_ID = "lease-coordination-api"
CHECKS = (
    "lease_acquire_fencing",
    "lease_concurrent_contention",
    "lease_renewal",
    "lease_release_reacquire",
    "lease_state_and_failure_atomicity",
)
FIELDS = {"resource", "owner", "fencing_token", "acquired_at", "expires_at", "status"}


def _expected(resource: str, owner: str, token: int, acquired: str, expires: str, status: str = "active") -> dict[str, Any]:
    return {
        "resource": resource,
        "owner": owner,
        "fencing_token": token,
        "acquired_at": acquired,
        "expires_at": expires,
        "status": status,
    }


def _response(response: Any) -> tuple[int, Any]:
    return response.status_code, _json_payload(response)


def _sqlite_state(db_path: Path) -> tuple[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...]:
    """Return every user table and row as a stable logical SQLite snapshot."""
    if not db_path.exists():
        return ()
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        snapshot = []
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({quoted})"))
            rows = []
            for row in connection.execute(f"SELECT * FROM {quoted}"):
                rows.append(tuple(value.hex() if isinstance(value, bytes) else repr(value) for value in row))
            snapshot.append((table, columns, tuple(sorted(rows))))
        return tuple(snapshot)


def _child_request(
    workspace: Path,
    db_path: Path,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any, str]:
    marker = "__AH_LEASE_RESPONSE__="
    script = r'''
import json, os
from pathlib import Path
from agentharness.benchmark_hidden_evaluators import _load_fastapi_app, _make_test_client
q = json.loads(os.environ["AH_LEASE_REQUEST"])
_, app = _load_fastapi_app(Path.cwd())
with _make_test_client(app) as client:
    response = client.request(q["method"], q["path"], json=q.get("body"))
try:
    payload = response.json()
except Exception:
    payload = response.text
print("__AH_LEASE_RESPONSE__=" + json.dumps({"status": response.status_code, "payload": payload}, sort_keys=True))
'''
    env = dict(os.environ)
    env["LEASE_DB_PATH"] = str(db_path)
    env["AGENTHARNESS_CROSS_PROCESS_CHILD"] = "1"
    env["AH_LEASE_REQUEST"] = json.dumps({"method": method, "path": path, "body": body}, sort_keys=True)
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=workspace, env=env,
        capture_output=True, text=True, check=False, timeout=60,
    )
    line = next((item for item in reversed(completed.stdout.splitlines()) if item.startswith(marker)), "")
    if completed.returncode != 0 or not line:
        diagnostic = completed.stderr.strip() or completed.stdout.strip() or f"child exit {completed.returncode}"
        return 599, None, diagnostic
    decoded = json.loads(line[len(marker):])
    return int(decoded["status"]), decoded.get("payload"), f"child_exit={completed.returncode}"


def _get_path(resource: str, as_of: str) -> str:
    return f"/leases/{quote(resource, safe='')}?as_of={quote(as_of, safe='')}"


def _durable_failure(
    client: Any,
    workspace: Path,
    db_path: Path,
    *,
    resource: str,
    as_of: str,
    method: str,
    suffix: str,
    body: dict[str, Any],
    expected_status: int,
) -> tuple[bool, str]:
    """Reject an operation and compare its complete public row before/after a restart."""
    before_response = client.get(_get_path(resource, as_of))
    before = _response(before_response)
    before_sqlite = _sqlite_state(db_path)
    failed_response = client.request(method, f"/leases/{quote(resource, safe='')}/{suffix}", json=body)
    failed = _response(failed_response)
    after_status, after_payload, child_detail = _child_request(
        workspace, db_path, "get", _get_path(resource, as_of)
    )
    after = (after_status, after_payload)
    after_sqlite = _sqlite_state(db_path)
    controlled = (
        failed[0] == expected_status
        and isinstance(failed[1], dict)
        and "detail" in failed[1]
        and "sqlite" not in json.dumps(failed[1]).lower()
        and "locked" not in json.dumps(failed[1]).lower()
    )
    ok = controlled and before == after and before_sqlite == after_sqlite and after_status != 599
    return ok, (
        f"op={failed}; public_state_equal={before == after}; "
        f"full_sqlite_state_equal={before_sqlite == after_sqlite}; {child_detail}"
    )


def _independent_race(workspace: Path, db_path: Path, root: Path) -> tuple[list[tuple[int, Any, str]], str]:
    marker = "__AH_RACE__="
    script = r'''
import json, os, time
from pathlib import Path
from agentharness.benchmark_hidden_evaluators import _load_fastapi_app, _make_test_client
ready, gate = Path(os.environ["AH_READY"]), Path(os.environ["AH_GATE"])
_, app = _load_fastapi_app(Path.cwd())
with _make_test_client(app) as client:
    ready.write_text("ready")
    deadline = time.monotonic() + 30
    while not gate.exists():
        if time.monotonic() >= deadline: raise TimeoutError("race gate")
        time.sleep(.002)
    response = client.post("/leases/process-race/acquire", json={
        "owner": os.environ["AH_OWNER"], "duration_seconds": 10,
        "now": "2040-02-01T00:00:00Z"
    })
try: payload = response.json()
except Exception: payload = response.text
print("__AH_RACE__=" + json.dumps({"status": response.status_code, "payload": payload}, sort_keys=True))
'''
    gate = root / "race.go"
    processes: list[subprocess.Popen[str]] = []
    for index, owner in enumerate(("race-a", "race-b")):
        env = dict(os.environ)
        env.update({
            "LEASE_DB_PATH": str(db_path),
            "AGENTHARNESS_CROSS_PROCESS_CHILD": "1",
            "AH_OWNER": owner,
            "AH_READY": str(root / f"ready-{index}"),
            "AH_GATE": str(gate),
        })
        processes.append(subprocess.Popen(
            [sys.executable, "-c", script], cwd=workspace, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ))
    deadline = time.monotonic() + 45
    while not all((root / f"ready-{index}").exists() for index in range(2)):
        if time.monotonic() >= deadline:
            for process in processes: process.kill()
            raise TimeoutError("independent contenders did not become ready")
        if any(process.poll() is not None for process in processes):
            break
        time.sleep(.005)
    gate.touch()
    outcomes: list[tuple[int, Any, str]] = []
    diagnostics: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=60)
        line = next((item for item in reversed(stdout.splitlines()) if item.startswith(marker)), "")
        diagnostic = stderr.strip() or f"exit={process.returncode}"
        diagnostics.append(diagnostic)
        if process.returncode != 0 or not line:
            outcomes.append((599, None, diagnostic))
        else:
            value = json.loads(line[len(marker):])
            outcomes.append((int(value["status"]), value.get("payload"), diagnostic))
    return outcomes, "; ".join(diagnostics)


def evaluate_lease(workspace: Path) -> HiddenEvaluationResult:
    observations, passed, failed, record = _recorder()
    evaluation_dir = _evaluation_dir(workspace, TASK_ID)

    with tempfile.TemporaryDirectory(prefix="ah-lease-complete-") as temporary:
        root = Path(temporary)
        db_path = root / "leases.sqlite3"
        old_db = os.environ.get("LEASE_DB_PATH")
        os.environ["LEASE_DB_PATH"] = str(db_path)
        try:
            try:
                _, app = _load_fastapi_app(workspace)
            except Exception as exc:
                return _interface_unreachable_result(
                    task_id=TASK_ID, evaluation_dir=evaluation_dir,
                    passed_checks=passed, failed_checks=failed, observations=observations,
                    check_ids=CHECKS, detail=f"app discovery failed: {exc}",
                    reason="interface_unreachable:app_load_failed",
                )

            with _working_directory(workspace), _make_test_client(app) as client:
                # Acquire, exact wire representation, expiry/release takeover, and a
                # post-restart fourth generation prove that the counter is durable.
                acquire_ok = True
                acquire_detail: list[str] = []
                first = client.post("/leases/generations/acquire", json={
                    "owner": "owner-a", "duration_seconds": 10,
                    "now": "2040-01-01T01:00:00+01:00",
                })
                exact_first = _expected(
                    "generations", "owner-a", 1,
                    "2040-01-01T00:00:00Z", "2040-01-01T00:00:10Z",
                )
                acquire_ok &= _response(first) == (201, exact_first) and set((_json_payload(first) or {})) == FIELDS
                acquire_detail.append(f"first={_response(first)}")
                conflict_ok, detail = _durable_failure(
                    client, workspace, db_path, resource="generations",
                    as_of="2040-01-01T00:00:01Z", method="post", suffix="acquire",
                    body={"owner":"blocked","duration_seconds":5,"now":"2040-01-01T00:00:02Z"},
                    expected_status=409,
                )
                acquire_ok &= conflict_ok; acquire_detail.append(detail)
                second = client.post("/leases/generations/acquire", json={
                    "owner":"owner-b", "duration_seconds":10, "now":"2040-01-01T00:00:10Z"
                })
                acquire_ok &= _response(second) == (201, _expected(
                    "generations", "owner-b", 2, "2040-01-01T00:00:10Z", "2040-01-01T00:00:20Z"
                ))
                released = client.post("/leases/generations/release", json={
                    "owner":"owner-b", "fencing_token":2, "now":"2040-01-01T00:00:11Z"
                })
                third = client.post("/leases/generations/acquire", json={
                    "owner":"owner-c", "duration_seconds":10, "now":"2040-01-01T00:00:12Z"
                })
                acquire_ok &= released.status_code == 200 and _response(third) == (201, _expected(
                    "generations", "owner-c", 3, "2040-01-01T00:00:12Z", "2040-01-01T00:00:22Z"
                ))
                fourth_status, fourth_payload, fourth_detail = _child_request(
                    workspace, db_path, "post", "/leases/generations/acquire",
                    {"owner":"owner-d","duration_seconds":10,"now":"2040-01-01T00:00:22Z"},
                )
                expected_fourth = _expected(
                    "generations", "owner-d", 4, "2040-01-01T00:00:22Z", "2040-01-01T00:00:32Z"
                )
                acquire_ok &= (fourth_status, fourth_payload) == (201, expected_fourth)
                acquire_detail.append(f"second={_response(second)}; third={_response(third)}; fourth={(fourth_status,fourth_payload)}; {fourth_detail}")
                record(CHECKS[0], acquire_ok, " | ".join(acquire_detail))

                # Both contenders import the candidate independently and wait at a
                # filesystem gate, avoiding in-process/thread-only concurrency.
                outcomes, race_detail = _independent_race(workspace, db_path, root)
                statuses = sorted(item[0] for item in outcomes)
                winners = [item for item in outcomes if item[0] == 201]
                losers = [item for item in outcomes if item[0] == 409]
                winner_payload = winners[0][1] if len(winners) == 1 else None
                durable_status, durable_payload, durable_detail = _child_request(
                    workspace, db_path, "get", _get_path("process-race", "2040-02-01T00:00:01Z")
                )
                takeover_status, takeover_payload, takeover_detail = _child_request(
                    workspace, db_path, "post", "/leases/process-race/acquire",
                    {"owner":"race-next","duration_seconds":10,"now":"2040-02-01T00:00:10Z"},
                )
                raw_errors = " ".join(json.dumps(item, default=str) for item in outcomes).lower()
                race_ok = (
                    statuses == [201, 409]
                    and len(losers) == 1 and isinstance(losers[0][1], dict) and "detail" in losers[0][1]
                    and isinstance(winner_payload, dict) and set(winner_payload) == FIELDS
                    and winner_payload.get("fencing_token") == 1
                    and winner_payload.get("owner") in {"race-a", "race-b"}
                    and (durable_status, durable_payload) == (200, winner_payload)
                    and (takeover_status, takeover_payload) == (201, _expected(
                        "process-race", "race-next", 2,
                        "2040-02-01T00:00:10Z", "2040-02-01T00:00:20Z",
                    ))
                    and "sqlite" not in raw_errors and "locked" not in raw_errors
                )
                record(CHECKS[1], race_ok, f"outcomes={outcomes}; durable={(durable_status,durable_payload)}; takeover={(takeover_status,takeover_payload)}; {race_detail}; {durable_detail}; {takeover_detail}")

                # Renewal guards and time rules each use an undisturbed resource;
                # every rejection is compared with a fresh-process public GET.
                renew_ok = True
                renew_details: list[str] = []
                renew_specs = [
                    ("renew-wrong", {"owner":"other","fencing_token":1,"duration_seconds":20,"now":"2040-03-01T00:00:02Z"}, 412),
                    ("renew-stale", {"owner":"holder","fencing_token":99,"duration_seconds":20,"now":"2040-03-01T00:00:02Z"}, 412),
                    ("renew-short", {"owner":"holder","fencing_token":1,"duration_seconds":5,"now":"2040-03-01T00:00:02Z"}, 409),
                    ("renew-back", {"owner":"holder","fencing_token":1,"duration_seconds":20,"now":"2040-02-28T23:59:59Z"}, 409),
                ]
                for resource, body, expected_status in renew_specs:
                    created = client.post(f"/leases/{resource}/acquire", json={
                        "owner":"holder","duration_seconds":10,"now":"2040-03-01T00:00:00Z"
                    })
                    renew_ok &= created.status_code == 201
                    ok, detail = _durable_failure(
                        client, workspace, db_path, resource=resource,
                        as_of="2040-03-01T00:00:01Z", method="post", suffix="renew",
                        body=body, expected_status=expected_status,
                    )
                    renew_ok &= ok; renew_details.append(detail)
                expired_resource = "renew-expired"
                client.post(f"/leases/{expired_resource}/acquire", json={
                    "owner":"holder","duration_seconds":10,"now":"2040-03-01T00:00:00Z"
                })
                ok, detail = _durable_failure(
                    client, workspace, db_path, resource=expired_resource,
                    as_of="2040-03-01T00:00:10Z", method="post", suffix="renew",
                    body={"owner":"holder","fencing_token":1,"duration_seconds":20,"now":"2040-03-01T00:00:10Z"},
                    expected_status=409,
                )
                renew_ok &= ok; renew_details.append(detail)
                good_created = client.post("/leases/renew-good/acquire", json={
                    "owner":"holder","duration_seconds":10,"now":"2040-03-01T01:00:00+01:00"
                })
                good = client.post("/leases/renew-good/renew", json={
                    "owner":"holder","fencing_token":1,"duration_seconds":20,"now":"2040-03-01T00:00:03Z"
                })
                exact_good = _expected("renew-good", "holder", 1, "2040-03-01T00:00:00Z", "2040-03-01T00:00:23Z")
                renew_ok &= good_created.status_code == 201 and _response(good) == (200, exact_good) and set((_json_payload(good) or {})) == FIELDS
                ok, detail = _durable_failure(
                    client, workspace, db_path, resource="renew-good",
                    as_of="2040-03-01T00:00:04Z", method="post", suffix="renew",
                    body={"owner":"holder","fencing_token":1,"duration_seconds":30,"now":"2040-03-01T00:00:02Z"},
                    expected_status=409,
                )
                renew_ok &= ok; renew_details.extend([f"good={_response(good)}", detail])
                record(CHECKS[2], renew_ok, " | ".join(renew_details))

                # Release/reacquire protects the new holder from every stale or
                # unauthorized capability. Released response semantics are tested
                # in the state check so that each named reference mutant is local.
                release_ok = True
                release_details: list[str] = []
                client.post("/leases/release-cycle/acquire", json={"owner":"same","duration_seconds":20,"now":"2040-04-01T00:00:00Z"})
                release_one = client.post("/leases/release-cycle/release", json={"owner":"same","fencing_token":1,"now":"2040-04-01T00:00:01Z"})
                reacquired = client.post("/leases/release-cycle/acquire", json={"owner":"same","duration_seconds":20,"now":"2040-04-01T00:00:02Z"})
                release_ok &= release_one.status_code == 200 and _response(reacquired) == (201, _expected(
                    "release-cycle", "same", 2, "2040-04-01T00:00:02Z", "2040-04-01T00:00:22Z"
                ))
                for suffix, body, status in [
                    ("release", {"owner":"same","fencing_token":1,"now":"2040-04-01T00:00:03Z"}, 412),
                    ("renew", {"owner":"same","fencing_token":1,"duration_seconds":30,"now":"2040-04-01T00:00:03Z"}, 412),
                    ("release", {"owner":"intruder","fencing_token":2,"now":"2040-04-01T00:00:03Z"}, 412),
                ]:
                    ok, detail = _durable_failure(
                        client, workspace, db_path, resource="release-cycle",
                        as_of="2040-04-01T00:00:04Z", method="post", suffix=suffix,
                        body=body, expected_status=status,
                    )
                    release_ok &= ok; release_details.append(detail)
                client.post("/leases/double-release/acquire", json={"owner":"holder","duration_seconds":20,"now":"2040-04-02T00:00:00Z"})
                client.post("/leases/double-release/release", json={"owner":"holder","fencing_token":1,"now":"2040-04-02T00:00:01Z"})
                ok, detail = _durable_failure(
                    client, workspace, db_path, resource="double-release",
                    as_of="2040-04-02T00:00:02Z", method="post", suffix="release",
                    body={"owner":"holder","fencing_token":1,"now":"2040-04-02T00:00:02Z"}, expected_status=409,
                )
                release_ok &= ok; release_details.append(detail)
                client.post("/leases/release-expired/acquire", json={"owner":"holder","duration_seconds":1,"now":"2040-04-03T00:00:00Z"})
                ok, detail = _durable_failure(
                    client, workspace, db_path, resource="release-expired",
                    as_of="2040-04-03T00:00:01Z", method="post", suffix="release",
                    body={"owner":"holder","fencing_token":1,"now":"2040-04-03T00:00:01Z"}, expected_status=409,
                )
                release_ok &= ok; release_details.append(detail)
                record(CHECKS[3], release_ok, f"release={release_one.status_code}; reacquire={_response(reacquired)} | " + " | ".join(release_details))

                # Exact active/expired/released boundaries plus exhaustive request
                # validation and exact error classes. Validation failures are also
                # durable before/after snapshots, including cross-process reads.
                state_ok = True
                state_details: list[str] = []
                state_create = client.post("/leases/state/acquire", json={
                    "owner":"state-owner","duration_seconds":10,"now":"2040-05-01T00:00:00Z"
                })
                active = _response(client.get(_get_path("state", "2040-05-01T00:00:09.999999Z")))
                expired = _response(client.get(_get_path("state", "2040-05-01T00:00:10Z")))
                released_response = client.post("/leases/state/release", json={
                    "owner":"state-owner","fencing_token":1,"now":"2040-05-01T00:00:05Z"
                })
                before_release = _response(client.get(_get_path("state", "2040-05-01T00:00:04.999999Z")))
                at_release = _response(client.get(_get_path("state", "2040-05-01T00:00:05Z")))
                base = _expected("state", "state-owner", 1, "2040-05-01T00:00:00Z", "2040-05-01T00:00:10Z")
                state_ok &= (
                    _response(state_create) == (201, base)
                    and active == (200, base)
                    and expired == (200, {**base, "status":"expired"})
                    and before_release == (200, base)
                    and _response(released_response) == (200, {**base, "status":"released"})
                    and at_release == (200, {**base, "status":"released"})
                )
                state_details.append(f"active={active}; expired={expired}; release={_response(released_response)}; historical={before_release}; boundary={at_release}")

                # Current generation makes an earlier as_of invalid.
                client.post("/leases/predate/acquire", json={"owner":"a","duration_seconds":1,"now":"2040-05-02T00:00:00Z"})
                client.post("/leases/predate/acquire", json={"owner":"b","duration_seconds":10,"now":"2040-05-02T00:00:01Z"})
                predate = _response(client.get(_get_path("predate", "2040-05-02T00:00:00.999999Z")))
                unknown = _response(client.get(_get_path("never-acquired", "2040-05-01T00:00:00Z")))
                absent_renew = _response(client.post("/leases/absent/renew", json={"owner":"a","fencing_token":1,"duration_seconds":1,"now":"2040-05-01T00:00:00Z"}))
                absent_release = _response(client.post("/leases/absent/release", json={"owner":"a","fencing_token":1,"now":"2040-05-01T00:00:00Z"}))
                state_ok &= predate[0] == 409 and unknown[0] == 404 and absent_renew[0] == 404 and absent_release[0] == 404

                # One stable active row is the canary for all malformed requests.
                client.post("/leases/validation/acquire", json={"owner":"valid","duration_seconds":100,"now":"2040-06-01T00:00:00Z"})
                invalid_cases: list[tuple[str, str, dict[str, Any], int]] = [
                    ("post", "acquire", {"owner":"x","duration_seconds":0,"now":"2040-06-01T00:00:01Z"}, 422),
                    ("post", "acquire", {"owner":"x","duration_seconds":86401,"now":"2040-06-01T00:00:01Z"}, 422),
                    ("post", "acquire", {"owner":"x","duration_seconds":1.5,"now":"2040-06-01T00:00:01Z"}, 422),
                    ("post", "acquire", {"owner":"x","duration_seconds":"1","now":"2040-06-01T00:00:01Z"}, 422),
                    ("post", "acquire", {"owner":"bad owner","duration_seconds":1,"now":"2040-06-01T00:00:01Z"}, 422),
                    ("post", "acquire", {"owner":"x","duration_seconds":1,"now":"not-a-time"}, 422),
                    ("post", "acquire", {"owner":"x","duration_seconds":1,"now":"2040-06-01T00:00:01"}, 422),
                    ("post", "acquire", {"owner":"x","duration_seconds":1,"now":"2040-06-01T00:00:01Z","extra":1}, 422),
                    ("post", "renew", {"owner":"valid","fencing_token":1,"duration_seconds":20,"now":"2040-06-01T00:00:01Z","extra":1}, 422),
                    ("post", "release", {"owner":"valid","fencing_token":1,"now":"2040-06-01T00:00:01Z","extra":1}, 422),
                ]
                for method, suffix, body, status in invalid_cases:
                    ok, detail = _durable_failure(
                        client, workspace, db_path, resource="validation",
                        as_of="2040-06-01T00:00:02Z", method=method, suffix=suffix,
                        body=body, expected_status=status,
                    )
                    state_ok &= ok; state_details.append(detail)
                bad_resource = client.post("/leases/%20/acquire", json={"owner":"x","duration_seconds":1,"now":"2040-06-01T00:00:01Z"})
                bad_query_time = client.get("/leases/validation?as_of=2040-06-01T00%3A00%3A02")
                malformed_query_time = client.get("/leases/validation?as_of=bogus")
                offset_get = _response(client.get(_get_path("validation", "2040-06-01T01:00:02+01:00")))
                backward = _response(client.post("/leases/validation/release", json={"owner":"valid","fencing_token":1,"now":"2039-01-01T00:00:00Z"}))
                state_ok &= (
                    bad_resource.status_code == 422
                    and bad_query_time.status_code == 422
                    and malformed_query_time.status_code == 422
                    and offset_get == (200, _expected("validation", "valid", 1, "2040-06-01T00:00:00Z", "2040-06-01T00:01:40Z"))
                    and backward[0] == 409
                )
                state_details.append(f"predate={predate}; unknown={unknown}; absent={(absent_renew,absent_release)}; bad_resource={bad_resource.status_code}; query_times={(bad_query_time.status_code,malformed_query_time.status_code)}; offset={offset_get}; backward={backward}")
                record(CHECKS[4], state_ok, " | ".join(state_details))

        except Exception as exc:
            return _finish_runtime(TASK_ID, workspace, CHECKS, observations, passed, failed, record, exc)
        finally:
            if old_db is None:
                os.environ.pop("LEASE_DB_PATH", None)
            else:
                os.environ["LEASE_DB_PATH"] = old_db

    return _finalize_hidden_evaluation(
        task_id=TASK_ID, evaluation_dir=evaluation_dir,
        passed_checks=passed, failed_checks=failed, observations=observations,
    )
