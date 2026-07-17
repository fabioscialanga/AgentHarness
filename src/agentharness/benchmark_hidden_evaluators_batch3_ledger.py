from __future__ import annotations

import json
import os
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

TASK_ID = "double-entry-ledger-api"
CHECKS = (
    "ledger_account_identity",
    "ledger_balanced_posting",
    "ledger_idempotency_conflict",
    "ledger_balances_and_journal",
    "ledger_compensating_reversal",
)
ACCOUNT_FIELDS = {"id", "currency"}
ENTRY_FIELDS = {"account_id", "direction", "amount"}
TX_FIELDS = {"id", "idempotency_key", "currency", "entries", "reverses"}
BALANCE_FIELDS = {"account_id", "currency", "balance"}
JOURNAL_FIELDS = {"account_id", "entries"}
RECORD_FIELDS = {"transaction_id", "sequence", "account_id", "direction", "amount"}


def _response(response: Any) -> tuple[int, Any]:
    return response.status_code, _json_payload(response)


def _controlled(response: Any, status: int) -> bool:
    payload = _json_payload(response)
    raw = json.dumps(payload, default=str).lower()
    return response.status_code == status and isinstance(payload, dict) and "detail" in payload and "sqlite" not in raw and "locked" not in raw and "traceback" not in raw


def _tx_schema(value: Any, *, key: str | None = None, reverses: str | None | object = ...) -> bool:
    if not isinstance(value, dict) or set(value) != TX_FIELDS:
        return False
    if not isinstance(value.get("id"), str) or not value["id"] or not isinstance(value.get("idempotency_key"), str):
        return False
    if key is not None and value["idempotency_key"] != key:
        return False
    if not isinstance(value.get("currency"), str) or not isinstance(value.get("entries"), list):
        return False
    if reverses is not ... and value.get("reverses") != reverses:
        return False
    return all(
        isinstance(entry, dict) and set(entry) == ENTRY_FIELDS
        and isinstance(entry["account_id"], str)
        and entry["direction"] in {"debit", "credit"}
        and isinstance(entry["amount"], str)
        for entry in value["entries"]
    )


def _snapshot(client: Any, accounts: list[str], transactions: list[str]) -> dict[str, Any]:
    """Complete public state for all accounts and transactions involved in an operation."""
    result: dict[str, Any] = {}
    for account in sorted(set(accounts)):
        encoded = quote(account, safe="")
        for suffix in ("", "/balance", "/journal"):
            path = f"/accounts/{encoded}{suffix}"
            result[path] = _response(client.get(path))
    for transaction in sorted(set(t for t in transactions if t)):
        path = f"/transactions/{quote(transaction, safe='')}"
        result[path] = _response(client.get(path))
    return result


def _reject_unchanged(
    client: Any,
    *,
    accounts: list[str],
    transactions: list[str],
    method: str,
    path: str,
    status: int,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> tuple[bool, str]:
    before = _snapshot(client, accounts, transactions)
    kwargs: dict[str, Any] = {}
    if body is not None:
        kwargs["json"] = body
    if headers is not None:
        kwargs["headers"] = headers
    response = client.request(method, path, **kwargs)
    after = _snapshot(client, accounts, transactions)
    ok = _controlled(response, status) and before == after
    return ok, f"{method} {path}={_response(response)}; full_state_equal={before == after}"


def _child_batch(workspace: Path, db_path: Path, requests: list[dict[str, Any]]) -> tuple[list[tuple[int, Any]], str]:
    marker = "__AH_LEDGER_BATCH__="
    script = r'''
import json, os
from pathlib import Path
from agentharness.benchmark_hidden_evaluators import _load_fastapi_app, _make_test_client
requests = json.loads(os.environ["AH_LEDGER_REQUESTS"])
_, app = _load_fastapi_app(Path.cwd())
out = []
with _make_test_client(app) as client:
    for request in requests:
        kwargs = {}
        if request.get("body") is not None: kwargs["json"] = request["body"]
        if request.get("headers") is not None: kwargs["headers"] = request["headers"]
        response = client.request(request["method"], request["path"], **kwargs)
        try: payload = response.json()
        except Exception: payload = response.text
        out.append([response.status_code, payload])
print("__AH_LEDGER_BATCH__=" + json.dumps(out, sort_keys=True))
'''
    env = dict(os.environ)
    env.update({
        "LEDGER_DB_PATH": str(db_path),
        "AGENTHARNESS_CROSS_PROCESS_CHILD": "1",
        "AH_LEDGER_REQUESTS": json.dumps(requests, sort_keys=True),
    })
    done = subprocess.run(
        [sys.executable, "-c", script], cwd=workspace, env=env,
        capture_output=True, text=True, check=False, timeout=90,
    )
    line = next((line for line in reversed(done.stdout.splitlines()) if line.startswith(marker)), "")
    if done.returncode != 0 or not line:
        return [(599, None)], done.stderr.strip() or done.stdout.strip() or f"exit={done.returncode}"
    values = json.loads(line[len(marker):])
    return [(int(item[0]), item[1]) for item in values], f"child_exit={done.returncode}"


def _race(
    workspace: Path,
    db_path: Path,
    root: Path,
    *,
    name: str,
    path: str,
    bodies: list[dict[str, Any]],
    keys: list[str],
) -> tuple[list[tuple[int, Any]], str]:
    marker = "__AH_LEDGER_RACE__="
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
        if time.monotonic() >= deadline: raise TimeoutError("ledger race gate")
        time.sleep(.002)
    response = client.post(os.environ["AH_PATH"], json=json.loads(os.environ["AH_BODY"]), headers={"Idempotency-Key": os.environ["AH_KEY"]})
try: payload = response.json()
except Exception: payload = response.text
print("__AH_LEDGER_RACE__=" + json.dumps([response.status_code, payload], sort_keys=True))
'''
    gate = root / f"{name}.go"
    processes: list[subprocess.Popen[str]] = []
    for index, (body, key) in enumerate(zip(bodies, keys, strict=True)):
        env = dict(os.environ)
        env.update({
            "LEDGER_DB_PATH": str(db_path), "AGENTHARNESS_CROSS_PROCESS_CHILD": "1",
            "AH_READY": str(root / f"{name}.ready.{index}"), "AH_GATE": str(gate),
            "AH_PATH": path, "AH_BODY": json.dumps(body, sort_keys=True), "AH_KEY": key,
        })
        processes.append(subprocess.Popen(
            [sys.executable, "-c", script], cwd=workspace, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ))
    deadline = time.monotonic() + 60
    while not all((root / f"{name}.ready.{i}").exists() for i in range(len(processes))):
        if time.monotonic() > deadline or any(p.poll() is not None for p in processes):
            break
        time.sleep(.005)
    gate.touch()
    outcomes: list[tuple[int, Any]] = []
    diagnostics: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=90)
        line = next((line for line in reversed(stdout.splitlines()) if line.startswith(marker)), "")
        diagnostics.append(stderr.strip() or f"exit={process.returncode}")
        if process.returncode != 0 or not line:
            outcomes.append((599, None))
        else:
            value = json.loads(line[len(marker):])
            outcomes.append((int(value[0]), value[1]))
    return outcomes, "; ".join(diagnostics)


def _create(client: Any, account: str, currency: str = "USD") -> bool:
    response = client.post("/accounts", json={"id": account, "currency": currency})
    return _response(response) == (201, {"id": account, "currency": currency})


def evaluate_ledger(workspace: Path) -> HiddenEvaluationResult:
    observations, passed, failed, record = _recorder()
    evaluation_dir = _evaluation_dir(workspace, TASK_ID)
    with tempfile.TemporaryDirectory(prefix="ah-ledger-complete-") as temporary:
        root = Path(temporary)
        db_path = root / "ledger.sqlite3"
        old_db = os.environ.get("LEDGER_DB_PATH")
        os.environ["LEDGER_DB_PATH"] = str(db_path)
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
                # Accounts: exact schema, strict identity/currency, immutability, and durability.
                account_ok = True
                account_details: list[str] = []
                for account, currency in (("acct.Main-1", "USD"), ("acct.EUR", "EUR")):
                    response = client.post("/accounts", json={"id": account, "currency": currency})
                    account_ok &= _response(response) == (201, {"id": account, "currency": currency}) and set((_json_payload(response) or {})) == ACCOUNT_FIELDS
                durable, child_detail = _child_batch(workspace, db_path, [
                    {"method": "GET", "path": "/accounts/acct.Main-1"},
                    {"method": "GET", "path": "/accounts/acct.Main-1/balance"},
                    {"method": "GET", "path": "/accounts/acct.Main-1/journal"},
                ])
                account_ok &= durable == [
                    (200, {"id": "acct.Main-1", "currency": "USD"}),
                    (200, {"account_id": "acct.Main-1", "currency": "USD", "balance": "0.00"}),
                    (200, {"account_id": "acct.Main-1", "entries": []}),
                ]
                account_details.append(f"restart={durable}; {child_detail}")
                invalid_accounts = [
                    ({"id": "acct.Main-1", "currency": "EUR"}, 409),
                    ({"id": "", "currency": "USD"}, 422),
                    ({"id": " bad", "currency": "USD"}, 422),
                    ({"id": "a" * 65, "currency": "USD"}, 422),
                    ({"id": "é", "currency": "USD"}, 422),
                    ({"id": "new", "currency": "usd"}, 422),
                    ({"id": "new", "currency": "us"}, 422),
                    ({"id": "new", "currency": "US"}, 422),
                    ({"id": "new", "currency": "USDX"}, 422),
                    ({"id": "new", "currency": "U1D"}, 422),
                    ({"id": "new"}, 422),
                    ({"id": "new", "currency": "USD", "extra": 1}, 422),
                    ({"id": 7, "currency": "USD"}, 422),
                ]
                for body, status in invalid_accounts:
                    ok, detail = _reject_unchanged(
                        client, accounts=["acct.Main-1", "acct.EUR", "new"], transactions=[],
                        method="POST", path="/accounts", body=body, status=status,
                    )
                    account_ok &= ok; account_details.append(detail)
                for method in ("PUT", "PATCH", "DELETE"):
                    body = {"id": "acct.Main-1", "currency": "EUR"} if method != "DELETE" else None
                    ok, detail = _reject_unchanged(
                        client, accounts=["acct.Main-1"], transactions=[], method=method,
                        path="/accounts/acct.Main-1", body=body, status=405,
                    )
                    account_ok &= ok; account_details.append(detail)
                account_ok &= client.get("/accounts/does-not-exist").status_code == 404
                record(CHECKS[0], account_ok, " | ".join(account_details))

                # Balanced posting and complete grammar validation use isolated accounts.
                balanced_ok = all(_create(client, name, currency) for name, currency in (
                    ("bal.A", "USD"), ("bal.B", "USD"), ("bal.C", "USD"),
                    ("bal.EUR", "EUR"), ("bal.largeA", "USD"), ("bal.largeB", "USD"),
                ))
                balanced_details: list[str] = []
                valid_body = {"entries": [
                    {"account_id": "bal.C", "direction": "credit", "amount": "1.5"},
                    {"account_id": "bal.A", "direction": "debit", "amount": "2"},
                    {"account_id": "bal.B", "direction": "credit", "amount": "0.50"},
                ]}
                valid = client.post("/transactions", json=valid_body, headers={"Idempotency-Key": "bal-valid"})
                expected_entries = [
                    {"account_id": "bal.A", "direction": "debit", "amount": "2.00"},
                    {"account_id": "bal.B", "direction": "credit", "amount": "0.50"},
                    {"account_id": "bal.C", "direction": "credit", "amount": "1.50"},
                ]
                valid_payload = _json_payload(valid)
                balanced_ok &= valid.status_code == 201 and _tx_schema(valid_payload, key="bal-valid", reverses=None) and valid_payload.get("entries") == expected_entries
                balanced_details.append(f"valid={_response(valid)}")
                invalid_postings: list[tuple[dict[str, Any], str]] = [
                    ({"entries": [{"account_id":"bal.A","direction":"debit","amount":"2.00"},{"account_id":"bal.B","direction":"credit","amount":"1.99"}]}, "bal-unbalanced"),
                    ({"entries": [{"account_id":"bal.A","direction":"debit","amount":"1"},{"account_id":"bal.EUR","direction":"credit","amount":"1"}]}, "bal-mixed"),
                    ({"entries": [{"account_id":"bal.A","direction":"debit","amount":"1"},{"account_id":"bal.unknown","direction":"credit","amount":"1"}]}, "bal-unknown"),
                    ({"entries": [{"account_id":"bal.A","direction":"debit","amount":"1"}]}, "bal-short"),
                ]
                bad_amounts: list[Any] = ["0", "0.0", "00.10", "01", "+1", "-1", "1.", ".1", "1.000", "1e2", "1,00", "NaN", "Infinity", 1, None]
                for index, value in enumerate(bad_amounts):
                    invalid_postings.append(({"entries": [
                        {"account_id":"bal.A","direction":"debit","amount":value},
                        {"account_id":"bal.B","direction":"credit","amount":"1"},
                    ]}, f"bal-amount-{index}"))
                invalid_postings.extend([
                    ({"entries":[{"account_id":"bal.A","direction":"charge","amount":"1"},{"account_id":"bal.B","direction":"credit","amount":"1"}]}, "bal-direction"),
                    ({"entries":[{"account_id":"bad id","direction":"debit","amount":"1"},{"account_id":"bal.B","direction":"credit","amount":"1"}]}, "bal-account-id"),
                    ({"entries":[{"account_id":"bal.A","direction":"debit","amount":"1","extra":1},{"account_id":"bal.B","direction":"credit","amount":"1"}]}, "bal-extra-entry"),
                    ({"entries":[], "extra":1}, "bal-extra-body"),
                ])
                known_tx = [valid_payload.get("id", "")] if isinstance(valid_payload, dict) else []
                for body, key in invalid_postings:
                    involved = [str(entry["account_id"]) for entry in body.get("entries", []) if isinstance(entry, dict) and entry.get("account_id") in {"bal.A","bal.B","bal.C","bal.EUR"}]
                    ok, detail = _reject_unchanged(
                        client, accounts=involved or ["bal.A", "bal.B"], transactions=known_tx,
                        method="POST", path="/transactions", body=body,
                        headers={"Idempotency-Key": key}, status=422,
                    )
                    balanced_ok &= ok; balanced_details.append(detail)
                missing_key_ok, detail = _reject_unchanged(
                    client, accounts=["bal.A","bal.B"], transactions=known_tx,
                    method="POST", path="/transactions", body={"entries":[
                        {"account_id":"bal.A","direction":"debit","amount":"1"},
                        {"account_id":"bal.B","direction":"credit","amount":"1"}]}, status=422,
                )
                balanced_ok &= missing_key_ok; balanced_details.append(detail)
                huge = "9" * 80
                huge_post = client.post("/transactions", headers={"Idempotency-Key":"bal-huge"}, json={"entries":[
                    {"account_id":"bal.largeA","direction":"debit","amount":huge},
                    {"account_id":"bal.largeB","direction":"credit","amount":huge + ".00"},
                ]})
                huge_payload = _json_payload(huge_post)
                huge_debit = _response(client.get("/accounts/bal.largeA/balance"))
                huge_credit = _response(client.get("/accounts/bal.largeB/balance"))
                balanced_ok &= (
                    huge_post.status_code == 201
                    and _tx_schema(huge_payload, key="bal-huge", reverses=None)
                    and all(e["amount"] == huge + ".00" for e in huge_payload.get("entries", []))
                    and huge_debit == (200, {"account_id":"bal.largeA","currency":"USD","balance":"-" + huge + ".00"})
                    and huge_credit == (200, {"account_id":"bal.largeB","currency":"USD","balance":huge + ".00"})
                )
                balanced_details.append(f"huge_status={huge_post.status_code}; huge_schema={_tx_schema(huge_payload, key='bal-huge', reverses=None)}; huge_balances={(huge_debit,huge_credit)}")
                record(CHECKS[1], balanced_ok, " | ".join(balanced_details))

                # Canonical idempotency survives restart and simultaneous independent imports.
                idem_ok = all(_create(client, name) for name in ("idem.A", "idem.B", "idem.C", "race.A", "race.B"))
                idem_details: list[str] = []
                body = {"entries":[
                    {"account_id":"idem.C","direction":"credit","amount":"3.00"},
                    {"account_id":"idem.A","direction":"debit","amount":"5"},
                    {"account_id":"idem.B","direction":"credit","amount":"2.0"},
                ]}
                first = client.post("/transactions", headers={"Idempotency-Key":"idem-key"}, json=body)
                first_payload = _json_payload(first)
                replay_body = {"entries":[
                    {"account_id":"idem.B","direction":"credit","amount":"2.00"},
                    {"account_id":"idem.C","direction":"credit","amount":"3"},
                    {"account_id":"idem.A","direction":"debit","amount":"5.0"},
                ]}
                replay_results, restart_detail = _child_batch(workspace, db_path, [{
                    "method":"POST", "path":"/transactions", "body":replay_body,
                    "headers":{"Idempotency-Key":"idem-key"},
                }])
                idem_ok &= first.status_code == 201 and _tx_schema(first_payload, key="idem-key", reverses=None) and replay_results == [(200, first_payload)]
                idem_details.append(f"first={_response(first)}; restart_replay={replay_results}; {restart_detail}")
                txid = first_payload.get("id", "") if isinstance(first_payload, dict) else ""
                ok, detail = _reject_unchanged(
                    client, accounts=["idem.A","idem.B","idem.C"], transactions=[txid],
                    method="POST", path="/transactions", headers={"Idempotency-Key":"idem-key"},
                    body={"entries":[{"account_id":"idem.A","direction":"debit","amount":"6"},{"account_id":"idem.B","direction":"credit","amount":"6"}]}, status=409,
                )
                idem_ok &= ok; idem_details.append(detail)
                race_body = {"entries":[{"account_id":"race.A","direction":"debit","amount":"7"},{"account_id":"race.B","direction":"credit","amount":"7.00"}]}
                outcomes, race_detail = _race(
                    workspace, db_path, root, name="posting", path="/transactions",
                    bodies=[race_body, {"entries":list(reversed(race_body["entries"]))}],
                    keys=["race-duplicate", "race-duplicate"],
                )
                ids = {payload.get("id") for status, payload in outcomes if status in {200,201} and isinstance(payload, dict)}
                race_journal = _json_payload(client.get("/accounts/race.A/journal"))
                raw = json.dumps(outcomes, default=str).lower()
                idem_ok &= sorted(status for status, _ in outcomes) == [200,201] and len(ids) == 1 and all(_tx_schema(payload, key="race-duplicate", reverses=None) for _, payload in outcomes) and isinstance(race_journal, dict) and len(race_journal.get("entries", [])) == 1 and "sqlite" not in raw and "locked" not in raw
                durable_race, durable_detail = _child_batch(workspace, db_path, [
                    {"method":"GET", "path":f"/transactions/{next(iter(ids), '')}"},
                    {"method":"GET", "path":"/accounts/race.A/journal"},
                ])
                idem_ok &= len(ids) == 1 and durable_race[0][0] == 200 and durable_race[0][1].get("id") in ids and durable_race[1] == (200, race_journal)
                idem_details.append(f"race={outcomes}; journal={race_journal}; durable={durable_race}; {race_detail}; {durable_detail}")
                record(CHECKS[2], idem_ok, " | ".join(idem_details))

                # Exact transaction/balance/journal schemas, filtering and ordering.
                journal_ok = all(_create(client, name) for name in ("journal.A","journal.B","journal.C"))
                journal_details: list[str] = []
                posts = [
                    ("journal-one", [
                        {"account_id":"journal.B","direction":"credit","amount":"1"},
                        {"account_id":"journal.A","direction":"debit","amount":"3"},
                        {"account_id":"journal.A","direction":"credit","amount":"2.00"},
                    ]),
                    ("journal-two", [
                        {"account_id":"journal.C","direction":"debit","amount":"4.25"},
                        {"account_id":"journal.A","direction":"credit","amount":"4.2"},
                        {"account_id":"journal.B","direction":"credit","amount":"0.05"},
                    ]),
                ]
                tx_payloads: list[dict[str, Any]] = []
                for key, entries in posts:
                    response = client.post("/transactions", headers={"Idempotency-Key":key}, json={"entries":entries})
                    payload = _json_payload(response)
                    journal_ok &= response.status_code == 201 and _tx_schema(payload, key=key, reverses=None)
                    if isinstance(payload, dict): tx_payloads.append(payload)
                expected_first = [
                    {"account_id":"journal.A","direction":"credit","amount":"2.00"},
                    {"account_id":"journal.A","direction":"debit","amount":"3.00"},
                    {"account_id":"journal.B","direction":"credit","amount":"1.00"},
                ]
                expected_second = [
                    {"account_id":"journal.A","direction":"credit","amount":"4.20"},
                    {"account_id":"journal.B","direction":"credit","amount":"0.05"},
                    {"account_id":"journal.C","direction":"debit","amount":"4.25"},
                ]
                journal_ok &= len(tx_payloads) == 2 and tx_payloads[0].get("entries") == expected_first and tx_payloads[1].get("entries") == expected_second
                balance_a = _response(client.get("/accounts/journal.A/balance"))
                journal_a = _response(client.get("/accounts/journal.A/journal"))
                journal_b = _response(client.get("/accounts/journal.B/journal"))
                entries_a = journal_a[1].get("entries", []) if isinstance(journal_a[1], dict) else []
                expected_a = []
                if len(tx_payloads) == 2:
                    expected_a = [
                        {"transaction_id":tx_payloads[0]["id"],"sequence":entries_a[0].get("sequence") if entries_a else None,"account_id":"journal.A","direction":"credit","amount":"2.00"},
                        {"transaction_id":tx_payloads[0]["id"],"sequence":entries_a[0].get("sequence") if entries_a else None,"account_id":"journal.A","direction":"debit","amount":"3.00"},
                        {"transaction_id":tx_payloads[1]["id"],"sequence":entries_a[2].get("sequence") if len(entries_a)>2 else None,"account_id":"journal.A","direction":"credit","amount":"4.20"},
                    ]
                journal_ok &= balance_a == (200, {"account_id":"journal.A","currency":"USD","balance":"3.20"}) and set(balance_a[1]) == BALANCE_FIELDS
                journal_ok &= journal_a[0] == 200 and set(journal_a[1]) == JOURNAL_FIELDS and entries_a == expected_a and all(set(item) == RECORD_FIELDS and isinstance(item["sequence"], int) for item in entries_a)
                journal_ok &= journal_b[0] == 200 and all(item.get("account_id") == "journal.B" for item in journal_b[1].get("entries", [])) and [item.get("transaction_id") for item in journal_b[1].get("entries", [])] == [p["id"] for p in tx_payloads]
                requests = [{"method":"GET", "path":f"/transactions/{p['id']}"} for p in tx_payloads] + [
                    {"method":"GET","path":"/accounts/journal.A/balance"},
                    {"method":"GET","path":"/accounts/journal.A/journal"},
                ]
                restarted, detail = _child_batch(workspace, db_path, requests)
                journal_ok &= restarted == [(200,p) for p in tx_payloads] + [balance_a, journal_a]
                journal_ok &= client.get("/transactions/not-a-real-transaction").status_code == 404 and client.get("/accounts/not-real/balance").status_code == 404 and client.get("/accounts/not-real/journal").status_code == 404
                journal_details.append(f"transactions={tx_payloads}; balance={balance_a}; journal_a={journal_a}; journal_b={journal_b}; restart_equal={restarted == [(200,p) for p in tx_payloads] + [balance_a,journal_a]}; {detail}")
                record(CHECKS[3], journal_ok, " | ".join(journal_details))

                # Two independently imported contenders race to append one reversal.
                reversal_ok = all(_create(client, name) for name in ("reverse.A","reverse.B"))
                reversal_details: list[str] = []
                original_response = client.post("/transactions", headers={"Idempotency-Key":"reverse-original"}, json={"entries":[
                    {"account_id":"reverse.A","direction":"debit","amount":"8.75"},
                    {"account_id":"reverse.B","direction":"credit","amount":"8.75"},
                ]})
                original = _json_payload(original_response)
                original_id = original.get("id", "") if isinstance(original, dict) else ""
                original_snapshot = _response(client.get(f"/transactions/{original_id}"))
                outcomes, race_detail = _race(
                    workspace, db_path, root, name="reversal",
                    path=f"/transactions/{original_id}/reverse",
                    bodies=[{}, {}], keys=["reverse-race-a", "reverse-race-b"],
                )
                winners = [(status,payload) for status,payload in outcomes if status == 201]
                losers = [(status,payload) for status,payload in outcomes if status == 409]
                raw = json.dumps(outcomes, default=str).lower()
                winner = winners[0][1] if len(winners) == 1 else {}
                expected_swapped = [
                    {"account_id":"reverse.A","direction":"credit","amount":"8.75"},
                    {"account_id":"reverse.B","direction":"debit","amount":"8.75"},
                ]
                reversal_ok &= original_response.status_code == 201 and _tx_schema(original, key="reverse-original", reverses=None)
                reversal_ok &= len(winners) == 1 and len(losers) == 1 and _tx_schema(winner, reverses=original_id) and winner.get("entries") == expected_swapped and isinstance(losers[0][1], dict) and "detail" in losers[0][1] and "sqlite" not in raw and "locked" not in raw
                winner_key = winner.get("idempotency_key", "") if isinstance(winner, dict) else ""
                replay_results, replay_detail = _child_batch(workspace, db_path, [{
                    "method":"POST", "path":f"/transactions/{original_id}/reverse", "body":{},
                    "headers":{"Idempotency-Key":winner_key},
                }])
                reversal_ok &= replay_results == [(200, winner)]
                current_original = _response(client.get(f"/transactions/{original_id}"))
                balance_ra = _response(client.get("/accounts/reverse.A/balance"))
                balance_rb = _response(client.get("/accounts/reverse.B/balance"))
                journal_ra = _response(client.get("/accounts/reverse.A/journal"))
                journal_rb = _response(client.get("/accounts/reverse.B/journal"))
                reversal_ok &= current_original == original_snapshot and balance_ra == (200,{"account_id":"reverse.A","currency":"USD","balance":"0.00"}) and balance_rb == (200,{"account_id":"reverse.B","currency":"USD","balance":"0.00"})
                for journal, account in ((journal_ra,"reverse.A"),(journal_rb,"reverse.B")):
                    values = journal[1].get("entries", []) if isinstance(journal[1], dict) else []
                    reversal_ok &= journal[0] == 200 and len(values) == 2 and [v.get("transaction_id") for v in values] == [original_id,winner.get("id")] and all(v.get("account_id") == account and set(v) == RECORD_FIELDS for v in values)
                losing_key = "reverse-race-b" if winner_key == "reverse-race-a" else "reverse-race-a"
                ok, detail = _reject_unchanged(
                    client, accounts=["reverse.A","reverse.B"], transactions=[original_id,winner.get("id","")],
                    method="POST", path=f"/transactions/{original_id}/reverse", body={},
                    headers={"Idempotency-Key":losing_key}, status=409,
                )
                reversal_ok &= ok; reversal_details.append(detail)
                unknown_before = _snapshot(client,["reverse.A","reverse.B"],[original_id,winner.get("id","")])
                unknown = client.post("/transactions/unknown-transaction/reverse", json={}, headers={"Idempotency-Key":"reverse-unknown"})
                unknown_after = _snapshot(client,["reverse.A","reverse.B"],[original_id,winner.get("id","")])
                reversal_ok &= _controlled(unknown,404) and unknown_before == unknown_after
                reversal_details.append(f"race={outcomes}; replay={replay_results}; original_immutable={current_original == original_snapshot}; balances={(balance_ra,balance_rb)}; journals={(journal_ra,journal_rb)}; unknown={_response(unknown)},atomic={unknown_before == unknown_after}; {race_detail}; {replay_detail}")
                record(CHECKS[4], reversal_ok, " | ".join(reversal_details))
        except Exception as exc:
            return _finish_runtime(TASK_ID, workspace, CHECKS, observations, passed, failed, record, exc)
        finally:
            if old_db is None:
                os.environ.pop("LEDGER_DB_PATH", None)
            else:
                os.environ["LEDGER_DB_PATH"] = old_db
    return _finalize_hidden_evaluation(
        task_id=TASK_ID, evaluation_dir=evaluation_dir,
        passed_checks=passed, failed_checks=failed, observations=observations,
    )
