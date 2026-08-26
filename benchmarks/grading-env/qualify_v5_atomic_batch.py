from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from materialize_v5_crypto_mutants import materialize_mutant

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(os.environ.get("V5_ATOMIC_BATCH_REFERENCE", ROOT / "benchmarks/grading-env/mechanism-first-v5/references/atomic-batch-state-machine")).resolve()
CHECKS = ("batch_all_or_none", "batch_duplicate_entity", "batch_error_index", "batch_idempotent_replay", "batch_response_order")
PROBE_COUNTS = {"batch_all_or_none": 6, "batch_duplicate_entity": 5, "batch_error_index": 19, "batch_idempotent_replay": 7, "batch_response_order": 5}
INITIAL = [("a","pending",1),("b","active",4),("c","suspended",7)]
PROBE_COUNTER = 0
DRIVER = r'''
import asyncio,json,os
from fastapi.testclient import TestClient
from batch_state_api.main import app
results=[]
with TestClient(app) as client:
 for action in json.loads(os.environ["BATCH_ACTIONS"]):
  if action["method"]=="POST":
   response=client.post("/batch-transition",json=action["body"]); results.append({"status":response.status_code,"body":response.content.decode("utf-8")})
  elif action["method"]=="RAW":
   response=client.post("/batch-transition",content=action["raw"],headers={"content-type":"application/json"}); results.append({"status":response.status_code,"body":response.content.decode("utf-8")})
  elif action["method"]=="FAIL_DELIVERY":
   raw=json.dumps(action["body"],sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
   async def exercise():
    sent=False
    async def receive():
     nonlocal sent
     if not sent: sent=True; return {"type":"http.request","body":raw,"more_body":False}
     return {"type":"http.disconnect"}
    async def send(message):
     if message["type"]=="http.response.body": raise RuntimeError("injected delivery failure")
    scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"POST","scheme":"http","path":"/batch-transition","raw_path":b"/batch-transition","query_string":b"","root_path":"","headers":[(b"content-type",b"application/json")],"client":("127.0.0.1",1),"server":("testserver",80),"state":{}}
    try: await app(scope,receive,send)
    except RuntimeError as exc: return str(exc)=="injected delivery failure"
    return False
   results.append({"delivery_failed":asyncio.run(exercise())})
  else:
   response=client.get("/entities/"+action["entity_id"]); results.append({"status":response.status_code,"body":response.content.decode("utf-8")})
print(json.dumps(results,sort_keys=True,separators=(",",":")))
'''
CONCURRENT_DRIVER = r'''
import json,os,time
from pathlib import Path
from fastapi.testclient import TestClient
from batch_state_api.main import app
barrier=Path(os.environ["BATCH_BARRIER"])
while not barrier.exists(): time.sleep(0.005)
with TestClient(app) as client:
 response=client.post("/batch-transition",json=json.loads(os.environ["BATCH_BODY"]))
print(json.dumps({"status":response.status_code,"body":response.content.decode("utf-8")},sort_keys=True,separators=(",",":")))
'''


def canon(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n"


def op(entity_id: str, expected: int, transition: str) -> dict[str,Any]:
    return {"entity_id":entity_id,"expected_version":expected,"transition":transition}


def batch(command: str, operations: list[dict[str,Any]]) -> dict[str,Any]:
    return {"command_id":command,"operations":operations}


def invoke(actions: list[dict[str,Any]], mutant: str="") -> dict[str,Any]:
    global PROBE_COUNTER
    PROBE_COUNTER += 1
    with tempfile.TemporaryDirectory(prefix="v5-atomic-batch-") as td:
        root=Path(td); database=root/"state.sqlite3"; implementation=REFERENCE
        conn=sqlite3.connect(database)
        conn.executescript("CREATE TABLE entities(entity_id TEXT PRIMARY KEY,state TEXT NOT NULL,version INTEGER NOT NULL);CREATE TABLE commands(command_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,response_json TEXT NOT NULL);")
        conn.executemany("INSERT INTO entities VALUES(?,?,?)",INITIAL); conn.commit(); conn.close()
        if mutant: implementation=materialize_mutant(REFERENCE,"atomic-batch-state-machine",mutant,root/"implementation")
        env=dict(os.environ); env["PYTHONPATH"]=str(implementation); env["BATCH_STATE_DB"]=str(database); env["BATCH_ACTIONS"]=json.dumps(actions,separators=(",",":")); env["PYTHONHASHSEED"]="53"; env["PYTHONWARNINGS"]="ignore"; env.pop("AGENTHARNESS_MUTANT",None)
        done=subprocess.run([sys.executable,"-c",DRIVER],cwd=root,env=env,capture_output=True,text=True,timeout=30,check=False)
        if done.returncode != 0 or done.stderr: return {"process_error":done.stderr or done.stdout}
        responses=json.loads(done.stdout)
        conn=sqlite3.connect(database)
        states=[list(row) for row in conn.execute("SELECT entity_id,state,version FROM entities ORDER BY entity_id")]
        commands=[list(row) for row in conn.execute("SELECT command_id,request_hash,response_json FROM commands ORDER BY command_id")]
        conn.close()
        return {"responses":responses,"states":states,"commands":commands}


def invoke_concurrent(bodies: list[dict[str,Any]], mutant: str="") -> dict[str,Any]:
    global PROBE_COUNTER
    PROBE_COUNTER += 1
    with tempfile.TemporaryDirectory(prefix="v5-atomic-concurrent-") as td:
        root=Path(td); database=root/"state.sqlite3"; barrier=root/"release"; implementation=REFERENCE
        conn=sqlite3.connect(database)
        conn.executescript("CREATE TABLE entities(entity_id TEXT PRIMARY KEY,state TEXT NOT NULL,version INTEGER NOT NULL);CREATE TABLE commands(command_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,response_json TEXT NOT NULL);")
        conn.executemany("INSERT INTO entities VALUES(?,?,?)",INITIAL); conn.commit(); conn.close()
        if mutant: implementation=materialize_mutant(REFERENCE,"atomic-batch-state-machine",mutant,root/"implementation")
        processes=[]
        for body in bodies:
            env=dict(os.environ); env["PYTHONPATH"]=str(implementation); env["BATCH_STATE_DB"]=str(database); env["BATCH_BODY"]=json.dumps(body,separators=(",",":")); env["BATCH_BARRIER"]=str(barrier); env["PYTHONHASHSEED"]="59"; env["PYTHONWARNINGS"]="ignore"; env.pop("AGENTHARNESS_MUTANT",None)
            processes.append(subprocess.Popen([sys.executable,"-c",CONCURRENT_DRIVER],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
        barrier.write_text("release",encoding="utf-8")
        responses=[]
        for process in processes:
            stdout,stderr=process.communicate(timeout=30)
            if process.returncode != 0 or stderr: return {"process_error":stderr or stdout}
            responses.append(json.loads(stdout))
        conn=sqlite3.connect(database)
        states=[list(row) for row in conn.execute("SELECT entity_id,state,version FROM entities ORDER BY entity_id")]
        commands=[list(row) for row in conn.execute("SELECT command_id,request_hash,response_json FROM commands ORDER BY command_id")]
        conn.close()
        return {"responses":responses,"states":states,"commands":commands}


def post(body: dict[str,Any]) -> dict[str,Any]: return {"method":"POST","body":body}
def raw(body: str) -> dict[str,Any]: return {"method":"RAW","raw":body}
def fail_delivery(body: dict[str,Any]) -> dict[str,Any]: return {"method":"FAIL_DELIVERY","body":body}

def error_response(code: str,status: int,index: int | None=None) -> dict[str,Any]:
    detail: dict[str, Any] = {"code":code}
    if index is not None: detail["index"]=index
    return {"status":status,"body":canon({"detail":detail})}


def success(command: str, rows: list[dict[str,Any]]) -> dict[str,Any]:
    return {"status":200,"body":canon({"command_id":command,"entities":sorted(rows,key=lambda row:row["entity_id"])})}


def unchanged(result: dict[str,Any]) -> bool: return result.get("states")==[list(row) for row in INITIAL] and result.get("commands")==[]

def rejected(result: dict[str,Any], code: str, status: int) -> bool:
    responses=result.get("responses",[])
    return len(responses)==1 and responses[0].get("status")==status and json.loads(responses[0].get("body","{}"))=={"detail":{"code":code,"index":json.loads(responses[0]["body"])["detail"].get("index")}} and unchanged(result)


def happy(mutant: str, reverse: bool=False, command: str="happy") -> bool:
    operations=[op("a",1,"active"),op("b",4,"suspended")]
    if reverse: operations.reverse()
    result=invoke([post(batch(command,operations))],mutant)
    expected=success(command,[{"entity_id":"a","state":"active","version":2},{"entity_id":"b","state":"suspended","version":5}])
    return result.get("responses")==[expected] and result.get("states")==[["a","active",2],["b","suspended",5],["c","suspended",7]] and len(result.get("commands",[]))==1


def check_all_or_none(mutant: str) -> bool:
    stale=invoke([post(batch("stale",[op("a",1,"active"),op("b",99,"suspended")]))],mutant)
    middle=invoke([post(batch("middle",[op("a",1,"active"),op("b",99,"suspended"),op("c",7,"active")]))],mutant)
    missing=invoke([post(batch("missing",[op("a",1,"active"),op("z",1,"active")]))],mutant)
    illegal=invoke([post(batch("illegal",[op("a",1,"active"),op("b",4,"pending")]))],mutant)
    competing=invoke_concurrent([batch("race-one",[op("a",1,"active"),op("b",4,"suspended")]),batch("race-two",[op("a",1,"active"),op("b",4,"suspended")])],mutant)
    competing_statuses=sorted(row["status"] for row in competing.get("responses",[]))
    competing_ok=len(competing_statuses)==2 and competing_statuses[0]==200 and competing_statuses[1] in {409,422} and competing.get("states")==[["a","active",2],["b","suspended",5],["c","suspended",7]] and len(competing.get("commands",[]))==1
    return all((happy(mutant),rejected(stale,"stale_version",409),rejected(middle,"stale_version",409),rejected(missing,"not_found",404),rejected(illegal,"illegal_transition",422),competing_ok))


def check_duplicate(mutant: str) -> bool:
    compatible=invoke([post(batch("dup-compatible",[op("a",1,"active"),op("a",2,"suspended")]))],mutant)
    conflict=invoke([post(batch("dup-conflict",[op("a",1,"active"),op("a",99,"suspended")]))],mutant)
    triple=invoke([post(batch("dup-triple",[op("a",1,"active"),op("a",2,"suspended"),op("a",3,"closed")]))],mutant)
    mixed=invoke([post(batch("dup-mixed",[op("a",1,"active"),op("b",4,"suspended"),op("a",2,"suspended")]))],mutant)
    return all((happy(mutant),rejected(compatible,"duplicate_entity",422),rejected(conflict,"duplicate_entity",422),rejected(triple,"duplicate_entity",422),rejected(mixed,"duplicate_entity",422)))


def check_error_index(mutant: str) -> bool:
    cases=[
      ([op("a",1,"suspended"),op("b",4,"suspended"),op("c",7,"active")],error_response("illegal_transition",422,0)),
      ([op("a",99,"active"),op("b",4,"suspended"),op("c",7,"active")],error_response("stale_version",409,0)),
      ([op("a",1,"active"),op("bb",1,"active"),op("c",7,"active")],error_response("not_found",404,1)),
      ([op("a",1,"active"),op("b",4,"suspended"),op("c",7,"pending")],error_response("illegal_transition",422,2)),
      ([op("a",1,"active"),op("b",4,"pending"),op("c",7,"active")],error_response("illegal_transition",422,1)),
      ([op("a",1,"active"),op("b",4,"suspended"),op("z",1,"active")],error_response("not_found",404,2)),
    ]
    answers=[happy(mutant)]
    for index,(operations,expected) in enumerate(cases):
        result=invoke([post(batch(f"index-{index}",operations))],mutant); answers.append(result.get("responses")==[expected] and unchanged(result))
    malformed: list[tuple[dict[str,Any],dict[str,Any]]] = [
      (raw("{"),error_response("invalid_operation",422,0)),
      (raw('{"command_id":"x","command_id":"y","operations":[{"entity_id":"a","expected_version":1,"transition":"active"}]}'),error_response("invalid_operation",422,0)),
      (post({"command_id":"bad-extra","operations":[op("a",1,"active")],"extra":1}),error_response("invalid_operation",422,0)),
      (raw("[]"),error_response("invalid_operation",422,0)),
      (post(batch("empty",[])),error_response("invalid_operation",422,0)),
      (post(batch("oversized",[op(f"x{i:02d}",1,"active") for i in range(33)])),error_response("invalid_operation",422,0)),
      (post(batch("op-extra",[{**op("a",1,"active"),"extra":1},op("z",1,"active")])),error_response("invalid_operation",422,0)),
      (post(batch("bool-version",[op("z",1,"active"),op("a",True,"active")])),error_response("invalid_operation",422,0)),
      (post(batch("negative-version",[op("a",1,"active"),op("b",-1,"suspended")])),error_response("invalid_operation",422,1)),
      (post(batch("bad-transition",[op("a",1,"active"),op("c",7,"unknown")])),error_response("invalid_operation",422,1)),
      (post(batch("bad-id",[op("z",1,"active"),op("",1,"active")])),error_response("invalid_operation",422,0)),
      (post(batch("missing-id",[op("z",1,"active"),{"expected_version":1,"transition":"active"}])),error_response("invalid_operation",422,0)),
    ]
    for action,expected in malformed:
        result=invoke([action],mutant); answers.append(result.get("responses")==[expected] and unchanged(result))
    return all(answers)


def check_idempotency(mutant: str) -> bool:
    first=batch("replay",[op("b",4,"suspended"),op("a",1,"active")]); reordered=batch("replay",[op("a",1,"active"),op("b",4,"suspended")])
    replay=invoke([post(first),post(reordered)],mutant)
    exact=invoke([post(first),post(first)],mutant)
    conflict=invoke([post(first),post(batch("replay",[op("a",1,"active")]))],mutant)
    other=invoke([post(first),post(batch("other",[op("c",7,"active")]))],mutant)
    concurrent=invoke_concurrent([first,reordered],mutant)
    delivery_body=batch("delivery",[op("a",1,"active"),op("b",4,"suspended")])
    delivery=invoke([fail_delivery(delivery_body),post(delivery_body)],mutant)
    replay_equal=len(replay.get("responses",[]))==2 and replay["responses"][0]==replay["responses"][1]
    exact_equal=len(exact.get("responses",[]))==2 and exact["responses"][0]==exact["responses"][1]
    conflict_ok=len(conflict.get("responses",[]))==2 and conflict["responses"][0]["status"]==200 and conflict["responses"][1]==error_response("command_conflict",409)
    concurrent_ok=len(concurrent.get("responses",[]))==2 and concurrent["responses"][0]==concurrent["responses"][1] and concurrent["responses"][0]["status"]==200 and concurrent.get("states")==[["a","active",2],["b","suspended",5],["c","suspended",7]] and len(concurrent.get("commands",[]))==1
    delivery_expected=success("delivery",[{"entity_id":"a","state":"active","version":2},{"entity_id":"b","state":"suspended","version":5}])
    delivery_ok=delivery.get("responses")==[{"delivery_failed":True},delivery_expected] and delivery.get("states")==[["a","active",2],["b","suspended",5],["c","suspended",7]] and len(delivery.get("commands",[]))==1
    return all((happy(mutant),replay_equal and len(replay.get("commands",[]))==1,exact_equal and len(exact.get("commands",[]))==1,conflict_ok and conflict.get("states")==[["a","active",2],["b","suspended",5],["c","suspended",7]] and len(conflict.get("commands",[]))==1,other.get("responses",[None,None])[1]==success("other",[{"entity_id":"c","state":"active","version":8}]) and len(other.get("commands",[]))==2,concurrent_ok,delivery_ok))


def check_response_order(mutant: str) -> bool:
    permutations=[
      [op("c",7,"active"),op("a",1,"active"),op("b",4,"suspended")],
      [op("b",4,"suspended"),op("c",7,"active"),op("a",1,"active")],
      [op("a",1,"active"),op("c",7,"active"),op("b",4,"suspended")],
      [op("b",4,"suspended"),op("a",1,"active")],
    ]
    answers=[happy(mutant)]
    for index,operations in enumerate(permutations):
        command=f"order-{index}"; result=invoke([post(batch(command,operations))],mutant)
        rows=[{"entity_id":item["entity_id"],"state":item["transition"],"version":{"a":2,"b":5,"c":8}[item["entity_id"]]} for item in operations]
        answers.append(result.get("responses")==[success(command,rows)])
    return all(answers)

FUNCTIONS={"batch_all_or_none":check_all_or_none,"batch_duplicate_entity":check_duplicate,"batch_error_index":check_error_index,"batch_idempotent_replay":check_idempotency,"batch_response_order":check_response_order}


def evaluate(mutant: str="") -> dict[str,Any]:
    global PROBE_COUNTER
    checks={}; executed={}
    for name in CHECKS:
        PROBE_COUNTER=0; functional=FUNCTIONS[name](mutant); executed[name]=PROBE_COUNTER; checks[name]=functional and PROBE_COUNTER==PROBE_COUNTS[name]
    return {"implementation":mutant or "reference","passed":[n for n,v in checks.items() if v],"failed":[n for n,v in checks.items() if not v],"checks":checks,"executed_probes":executed}


def main(argv: list[str] | None=None) -> int:
    global REFERENCE
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args(argv)
    if args.workspace: REFERENCE=args.workspace.resolve(); rows=[evaluate()]; ok=rows[0]["failed"]==[]
    else:
        rows=[evaluate()]+[evaluate(name) for name in CHECKS]; expected={"reference":[]}|{name:[name] for name in CHECKS}; ok=all(row["failed"]==expected[row["implementation"]] for row in rows)
    print(json.dumps({"ok":ok,"task_id":"atomic-batch-state-machine","matrix":rows,"probe_counts":PROBE_COUNTS,"total_probes_per_implementation":sum(PROBE_COUNTS.values()),"reference_runs":1,"mutant_runs":0 if args.workspace else 5,"target_model_calls":0,"efficacy_cells":0},indent=2,sort_keys=True)); return 0 if ok else 1

if __name__=="__main__": raise SystemExit(main())
