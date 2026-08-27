from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from materialize_v5_crypto_mutants import materialize_mutant

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=Path(os.environ.get("V5_ACK_QUEUE_REFERENCE",ROOT/"benchmarks/grading-env/mechanism-first-v5/references/ack-token-work-queue")).resolve()
CHECKS=("ack_stale_worker_rejected","ack_single_claim","ack_visibility_timeout","ack_nack_requeues","ack_attempt_accounting")
PROBE_COUNTS={name:6 for name in CHECKS}
PROBE_COUNTS["ack_stale_worker_rejected"]=24
PROBE_COUNTS["ack_nack_requeues"]=7
TOKEN=re.compile(r"[0-9a-f]{64}")
PROBE_COUNTER=0
WAIT_DRIVER=r'''
import os,sys,time
from pathlib import Path
barrier=Path(os.environ["ACK_BARRIER"])
Path(os.environ["ACK_READY"]).write_text("ready")
while not barrier.exists(): time.sleep(0.005)
os.execv(sys.executable,[sys.executable,"-m","ack_queue.cli",*sys.argv[1:]])
'''


def canon(value: Any) -> bytes: return (json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()
def env(result: Any) -> bytes: return canon({"result":result,"status":"ok"})


class Scenario:
    def __init__(self,mutant: str=""):
        self.temp=tempfile.TemporaryDirectory(prefix="v5-ack-"); self.root=Path(self.temp.name); self.db=self.root/"queue.sqlite3"; self.impl=REFERENCE
        if mutant: self.impl=materialize_mutant(REFERENCE,"ack-token-work-queue",mutant,self.root/"implementation")
        result=self.call("init",{},True)
        if result.get("data")!=env({"initialized":True}): raise RuntimeError(result)
    def close(self): self.temp.cleanup()
    def _paths(self,name: str,body: Any):
        request=self.root/f"{name}.request.json"; output=self.root/f"{name}.output.json"; request.write_bytes(canon(body)); return request,output
    def call(self,command: str,body: Any,success: bool,tag: str="call",output_mode: str="absent") -> dict[str,Any]:
        request,output=self._paths(f"{tag}-{os.urandom(3).hex()}",body); sentinel=b"preserve-me\n"
        if output_mode=="existing": output.write_bytes(sentinel)
        if output_mode=="delivery_fail": output.mkdir()
        run=subprocess.run([sys.executable,"-m","ack_queue.cli",command,"--db",str(self.db),"--request",str(request),"--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl),"PYTHONHASHSEED":"61"},capture_output=True,timeout=30)
        if success:
            ok=run.returncode==0 and run.stdout==b"" and run.stderr==b"" and output.is_file()
            return {"ok":ok,"data":output.read_bytes() if output.is_file() else b"","returncode":run.returncode,"stderr":run.stderr}
        if output_mode=="delivery_fail": preserved=output.is_dir()
        else: preserved=output.read_bytes()==sentinel if output_mode=="existing" else not output.exists()
        return {"ok":run.returncode!=0 and run.stdout==b"" and run.stderr.count(b"\n")==1 and b"Traceback" not in run.stderr and preserved,"returncode":run.returncode,"stderr":run.stderr}
    def reject_both(self,command: str,body: Any) -> bool:
        before=self.snapshot(); a=self.call(command,body,False,output_mode="existing"); middle=self.snapshot(); b=self.call(command,body,False,output_mode="absent"); return a["ok"] and b["ok"] and before==middle==self.snapshot()
    def reject_raw_both(self,command: str,text: str) -> bool:
        before=self.snapshot(); sentinel=b"preserve-me\n"
        answers=[]
        for mode in ("existing","absent"):
            request=self.root/f"raw-{os.urandom(3).hex()}.json"; output=self.root/f"raw-{os.urandom(3).hex()}.out"; request.write_text(text,encoding="utf-8")
            if mode=="existing": output.write_bytes(sentinel)
            run=subprocess.run([sys.executable,"-m","ack_queue.cli",command,"--db",str(self.db),"--request",str(request),"--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
            preserved=output.read_bytes()==sentinel if mode=="existing" else not output.exists()
            answers.append(run.returncode!=0 and not run.stdout and run.stderr.count(b"\n")==1 and b"Traceback" not in run.stderr and preserved and self.snapshot()==before)
        return all(answers)
    def snapshot(self):
        conn=sqlite3.connect(self.db); jobs=conn.execute("SELECT job_id,payload_json,state,worker,token,expires_at,attempts FROM jobs ORDER BY job_id").fetchall(); requests=conn.execute("SELECT request_id,request_hash,envelope FROM requests ORDER BY request_id").fetchall(); conn.close(); return jobs,requests
    def concurrent_claims(self,requests: list[dict[str,Any]]) -> list[dict[str,Any]]:
        barrier=self.root/f"barrier-{os.urandom(3).hex()}"; processes=[]; outputs=[]
        ready_paths=[]
        for index,body in enumerate(requests):
            request=self.root/f"concurrent-{index}-{os.urandom(3).hex()}.json"; output=self.root/f"concurrent-{index}-{os.urandom(3).hex()}.out"; request.write_bytes(canon(body)); outputs.append(output)
            ready=self.root/f"ready-{index}-{os.urandom(3).hex()}"; ready_paths.append(ready)
            environment={**os.environ,"PYTHONPATH":str(self.impl),"ACK_BARRIER":str(barrier),"ACK_READY":str(ready),"PYTHONHASHSEED":"67"}
            args=[sys.executable,"-c",WAIT_DRIVER,"claim","--db",str(self.db),"--request",str(request),"--output",str(output)]
            processes.append(subprocess.Popen(args,cwd=self.root,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        deadline=time.monotonic()+10
        while not all(path.exists() for path in ready_paths):
            if time.monotonic()>deadline: raise RuntimeError("claim processes did not become ready")
            time.sleep(0.005)
        barrier.write_text("go")
        rows=[]
        for process,output in zip(processes,outputs):
            stdout,stderr=process.communicate(timeout=30); rows.append({"ok":process.returncode==0 and not stdout and not stderr,"data":output.read_bytes() if output.exists() else b""})
        return rows
    def race_stale_ack_against_generation_change(self, old_token: str) -> bool:
        request=self.root/f"race-ack-{os.urandom(3).hex()}.json"; output=self.root/f"race-ack-{os.urandom(3).hex()}.out"
        request.write_bytes(canon({"request_id":"race-old","worker":"w","job_id":"job","token":old_token,"now":6}))
        lock=sqlite3.connect(self.db,timeout=20); lock.execute("BEGIN IMMEDIATE")
        process=subprocess.Popen([sys.executable,"-m","ack_queue.cli","ack","--db",str(self.db),"--request",str(request),"--output",str(output)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl),"PYTHONHASHSEED":"71"},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        time.sleep(0.2)
        replacement="e"*64
        lock.execute("UPDATE jobs SET state='claimed',worker='w',token=?,expires_at=16,attempts=attempts+1 WHERE job_id='job'",(replacement,)); lock.commit(); lock.close()
        stdout,stderr=process.communicate(timeout=30)
        row=self.snapshot()[0][0]
        return process.returncode!=0 and not stdout and stderr.count(b"\n")==1 and not output.exists() and row[2]=="claimed" and row[4]==replacement


def job_from(data: bytes) -> Any:
    parsed=json.loads(data)
    if data!=canon(parsed) or not isinstance(parsed,dict) or set(parsed)!={"result","status"} or parsed["status"]!="ok": raise AssertionError("noncanonical envelope")
    result=parsed["result"]
    if result is None: return None
    keys={"job_id","payload","state","worker","token","expires_at","attempts"}
    if not isinstance(result,dict) or set(result)!=keys or result["state"] not in {"available","claimed","completed"} or type(result["attempts"]) is not int or result["attempts"]<0 or not isinstance(result["payload"],dict): raise AssertionError("invalid job envelope")
    if result["state"]=="claimed":
        if not isinstance(result["worker"],str) or not isinstance(result["token"],str) or not TOKEN.fullmatch(result["token"]) or type(result["expires_at"]) is not int: raise AssertionError("invalid claimed ownership")
    elif any(result[key] is not None for key in ("worker","token","expires_at")): raise AssertionError("nonclaimed ownership fields")
    return result
def enqueue(s: Scenario,request_id="enqueue",job_id="job",payload=None): return s.call("enqueue",{"request_id":request_id,"job_id":job_id,"payload_object":payload if payload is not None else {"value":1}},True)
def claim(s: Scenario,request_id: str,worker: str,now: int,lease=10): return s.call("claim",{"request_id":request_id,"worker":worker,"now":now,"lease_seconds":lease},True)


def probe(function):
    global PROBE_COUNTER; PROBE_COUNTER+=1
    s=function();
    try: return s[0]
    finally: s[1].close()


def uninitialized_probe(mutant: str, command: str, body: dict[str,Any]) -> bool:
    global PROBE_COUNTER; PROBE_COUNTER+=1
    with tempfile.TemporaryDirectory(prefix="v5-ack-uninitialized-") as td:
        root=Path(td); implementation=REFERENCE; db=root/"absent.sqlite3"; request=root/"request.json"; output=root/"output.json"; request.write_bytes(canon(body))
        if mutant: implementation=materialize_mutant(REFERENCE,"ack-token-work-queue",mutant,root/"implementation")
        run=subprocess.run([sys.executable,"-m","ack_queue.cli",command,"--db",str(db),"--request",str(request),"--output",str(output)],cwd=root,env={**os.environ,"PYTHONPATH":str(implementation)},capture_output=True,timeout=30)
        return run.returncode!=0 and not run.stdout and run.stderr.count(b"\n")==1 and not db.exists() and not output.exists()


def check_stale(mutant: str) -> bool:
    answers=[]
    def p1():
        s=Scenario(mutant); enqueue(s); c=job_from(claim(s,"c1","worker",0)["data"]); a=s.call("ack",{"request_id":"a1","worker":"worker","job_id":"job","token":c["token"],"now":1},True); return job_from(a["data"])["state"]=="completed",s
    answers.append(probe(p1))
    def stale(same_worker=True,nack=False):
        s=Scenario(mutant); enqueue(s); old=job_from(claim(s,"c1","worker",0,5)["data"]); new=job_from(claim(s,"c2","worker" if same_worker else "other",6,10)["data"]); command="nack" if nack else "ack"; body={"request_id":"old","worker":"worker","job_id":"job","token":old["token"],"now":7}; ok=s.reject_both(command,body); current=job_from(s.call("get",{"job_id":"job","now":7},True)["data"]); fresh=s.call("ack",{"request_id":"fresh","worker":new["worker"],"job_id":"job","token":new["token"],"now":8},True); return ok and current["token"]==new["token"] and job_from(fresh["data"])["state"]=="completed",s
    answers.extend([probe(lambda:stale(True,False)),probe(lambda:stale(False,False)),probe(lambda:stale(True,True))])
    def malformed():
        s=Scenario(mutant); enqueue(s); claim(s,"c1","worker",0); ok=s.reject_both("ack",{"request_id":"bad","worker":"worker","job_id":"job","token":"0"*63,"now":1}); return ok,s
    answers.append(probe(malformed))
    def replay():
        s=Scenario(mutant); enqueue(s); c=job_from(claim(s,"c1","worker",0)["data"]); body={"request_id":"a1","worker":"worker","job_id":"job","token":c["token"],"now":1}; first=s.call("ack",body,True); second=s.call("ack",body,True); stored=s.call("result",{"request_id":"a1"},True); return first["data"]==second["data"]==stored["data"],s
    answers.append(probe(replay))
    def toctou():
        s=Scenario(mutant); enqueue(s); old=job_from(claim(s,"c-race","w",0,5)["data"]); return s.race_stale_ack_against_generation_change(old["token"]),s
    answers.append(probe(toctou))
    def raw_malformed():
        s=Scenario(mutant); return s.reject_raw_both("enqueue","{"),s
    def raw_nan():
        s=Scenario(mutant); return s.reject_raw_both("enqueue",'{"request_id":"nan","job_id":"x","payload_object":{"x":NaN}}'),s
    def raw_duplicate():
        s=Scenario(mutant); return s.reject_raw_both("enqueue",'{"request_id":"one","request_id":"two","job_id":"x","payload_object":{}}'),s
    def duplicate_job():
        s=Scenario(mutant); enqueue(s,"e1","x"); return s.reject_both("enqueue",{"request_id":"e2","job_id":"x","payload_object":{}}),s
    def changed_replay():
        s=Scenario(mutant); enqueue(s,"same","x",{"v":1}); return s.reject_both("enqueue",{"request_id":"same","job_id":"x","payload_object":{"v":2}}),s
    def cross_command():
        s=Scenario(mutant); enqueue(s,"shared","x"); return s.reject_both("claim",{"request_id":"shared","worker":"w","now":0,"lease_seconds":1}),s
    def bool_now():
        s=Scenario(mutant); return s.reject_both("claim",{"request_id":"bool","worker":"w","now":True,"lease_seconds":1}),s
    def overflow():
        s=Scenario(mutant); return s.reject_both("claim",{"request_id":"overflow","worker":"w","now":9223372036854775807,"lease_seconds":1}),s
    def expiry_ack():
        s=Scenario(mutant); enqueue(s); current=job_from(claim(s,"c-exp","w",0,5)["data"]); return s.reject_both("ack",{"request_id":"a-exp","worker":"w","job_id":"job","token":current["token"],"now":5}),s
    def missing_result():
        s=Scenario(mutant); return s.reject_both("result",{"request_id":"missing"}),s
    def extra_keys():
        s=Scenario(mutant); return s.reject_both("claim",{"request_id":"extra","worker":"w","now":0,"lease_seconds":1,"extra":1}),s
    def bad_payload():
        s=Scenario(mutant); return s.reject_both("enqueue",{"request_id":"bad-payload","job_id":"x","payload_object":[]}),s
    def init_schema():
        s=Scenario(mutant); again=s.call("init",{},True); conn=sqlite3.connect(s.db); tables={row[0]:row[1] for row in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}; conn.close(); return again["data"]==env({"initialized":True}) and set(tables)=={"jobs","requests"},s
    def enqueue_delivery():
        s=Scenario(mutant); body={"request_id":"deliver-enqueue","job_id":"x","payload_object":{"v":1}}; failed=s.call("enqueue",body,False,output_mode="delivery_fail"); replay=s.call("enqueue",body,True); stored=s.call("result",{"request_id":"deliver-enqueue"},True); return failed["ok"] and replay["data"]==stored["data"] and job_from(replay["data"])["attempts"]==0,s
    def ack_delivery():
        s=Scenario(mutant); enqueue(s); current=job_from(claim(s,"deliver-claim","w",0)["data"]); body={"request_id":"deliver-ack","worker":"w","job_id":"job","token":current["token"],"now":1}; failed=s.call("ack",body,False,output_mode="delivery_fail"); replay=s.call("ack",body,True); return failed["ok"] and job_from(replay["data"])["state"]=="completed",s
    answers.extend(probe(function) for function in (raw_malformed,raw_nan,raw_duplicate,duplicate_job,changed_replay,cross_command,bool_now,overflow,expiry_ack,missing_result,extra_keys,bad_payload,init_schema,enqueue_delivery,ack_delivery))
    answers.append(uninitialized_probe(mutant,"get",{"job_id":"x","now":0}))
    answers.append(uninitialized_probe(mutant,"enqueue",{"request_id":"e","job_id":"x","payload_object":{}}))
    return all(answers)


def check_single(mutant: str) -> bool:
    answers=[]
    for count in (2,3):
        def concurrent(count=count):
            s=Scenario(mutant); enqueue(s); rows=s.concurrent_claims([{"request_id":f"c{i}","worker":f"w{i}","now":0,"lease_seconds":10} for i in range(count)]); values=[job_from(r["data"]) for r in rows if r["ok"]]; nonnull=[v for v in values if v is not None]; durable=job_from(s.call("get",{"job_id":"job","now":1},True)["data"]); return len(values)==count and len(nonnull)==1 and durable["worker"]==nonnull[0]["worker"],s
        answers.append(probe(concurrent))
    def two_jobs():
        s=Scenario(mutant); enqueue(s,"e1","a"); enqueue(s,"e2","b"); rows=s.concurrent_claims([{"request_id":"c1","worker":"w1","now":0,"lease_seconds":10},{"request_id":"c2","worker":"w2","now":0,"lease_seconds":10}]); jobs=[job_from(r["data"])["job_id"] for r in rows]; return sorted(jobs)==["a","b"],s
    answers.append(probe(two_jobs))
    def empty():
        s=Scenario(mutant); rows=s.concurrent_claims([{"request_id":"c1","worker":"w1","now":0,"lease_seconds":10},{"request_id":"c2","worker":"w2","now":0,"lease_seconds":10}]); return all(job_from(r["data"]) is None for r in rows),s
    answers.append(probe(empty))
    def sequential():
        s=Scenario(mutant); enqueue(s); first=job_from(claim(s,"c1","w1",0)["data"]); second=job_from(claim(s,"c2","w2",1)["data"]); return first is not None and second is None,s
    answers.extend([probe(sequential),probe(sequential)]); return all(answers)


def check_visibility(mutant: str) -> bool:
    answers=[]
    for now,expected in ((4,"claimed"),(5,"available"),(6,"available")):
        def boundary(now=now,expected=expected):
            s=Scenario(mutant); enqueue(s); claim(s,"c1","w",0,5); before=s.snapshot(); value=job_from(s.call("get",{"job_id":"job","now":now},True)["data"]); return value["state"]==expected and before==s.snapshot(),s
        answers.append(probe(boundary))
    def second_boundary():
        s=Scenario(mutant); enqueue(s); claim(s,"c1","w",0,10); before=s.snapshot(); value=job_from(s.call("get",{"job_id":"job","now":10},True)["data"]); return value["state"]=="available" and before==s.snapshot(),s
    answers.append(probe(second_boundary))
    for now in (5,6):
        def reclaim(now=now):
            s=Scenario(mutant); enqueue(s); claim(s,"c1","w",0,5); value=job_from(claim(s,"c2","x",now)["data"]); return value is not None and value["worker"]=="x" and value["attempts"]==2,s
        answers.append(probe(reclaim))
    return all(answers)


def check_nack(mutant: str) -> bool:
    answers=[]
    payloads=[{"nested":{"a":[1,2]},"text":"é"},{"empty":{}},{"number":7}]
    for index,payload in enumerate(payloads):
        def cycle(index=index,payload=payload):
            s=Scenario(mutant); enqueue(s,payload=payload); first=job_from(claim(s,"c1","w",0)["data"]); body={"request_id":"n1","worker":"w","job_id":"job","token":first["token"],"now":1}; n=s.call("nack",body,True); replay=s.call("nack",body,True); second=job_from(claim(s,"c2","x",2)["data"]); return n["data"]==replay["data"] and second["payload"]==payload and second["attempts"]==2,s
        answers.append(probe(cycle))
    def stale():
        s=Scenario(mutant); enqueue(s); first=job_from(claim(s,"c1","w",0)["data"]); body={"request_id":"n1","worker":"other","job_id":"job","token":first["token"],"now":1}; return s.reject_both("nack",body),s
    answers.append(probe(stale))
    def old_after():
        s=Scenario(mutant); enqueue(s); first=job_from(claim(s,"c1","w",0)["data"]); n={"request_id":"n1","worker":"w","job_id":"job","token":first["token"],"now":1}; s.call("nack",n,True); claim(s,"c2","x",2); return s.reject_both("ack",{"request_id":"a1","worker":"w","job_id":"job","token":first["token"],"now":3}),s
    answers.extend([probe(old_after),probe(old_after)])
    def delivery():
        s=Scenario(mutant); enqueue(s); first=job_from(claim(s,"deliver-claim","w",0)["data"]); body={"request_id":"deliver-nack","worker":"w","job_id":"job","token":first["token"],"now":1}; failed=s.call("nack",body,False,output_mode="delivery_fail"); replay=s.call("nack",body,True); second=job_from(claim(s,"deliver-reclaim","x",2)["data"]); return failed["ok"] and job_from(replay["data"])["state"]=="available" and second["payload"]=={"value":1} and second["attempts"]==2,s
    answers.append(probe(delivery)); return all(answers)


def check_attempts(mutant: str) -> bool:
    answers=[]
    def first():
        s=Scenario(mutant); enqueue(s); value=job_from(claim(s,"c1","w",0)["data"]); return value["attempts"]==1,s
    answers.append(probe(first))
    def timeout():
        s=Scenario(mutant); enqueue(s); claim(s,"c1","w",0,5); value=job_from(claim(s,"c2","x",6)["data"]); return value["attempts"]==2,s
    answers.append(probe(timeout))
    def nack_cycle():
        s=Scenario(mutant); enqueue(s); first=job_from(claim(s,"c1","w",0)["data"]); s.call("nack",{"request_id":"n1","worker":"w","job_id":"job","token":first["token"],"now":1},True); value=job_from(claim(s,"c2","x",2)["data"]); return value["attempts"]==2,s
    answers.append(probe(nack_cycle))
    def replay_delivery():
        s=Scenario(mutant); enqueue(s); body={"request_id":"c1","worker":"w","now":0,"lease_seconds":10}; failed=s.call("claim",body,False,output_mode="delivery_fail"); again=s.call("claim",body,True); stored=s.call("result",{"request_id":"c1"},True); value=job_from(again["data"]); return failed["ok"] and again["data"]==stored["data"] and value["attempts"]==1,s
    answers.append(probe(replay_delivery))
    def concurrent():
        s=Scenario(mutant); enqueue(s); rows=s.concurrent_claims([{"request_id":"c1","worker":"w1","now":0,"lease_seconds":10},{"request_id":"c2","worker":"w2","now":0,"lease_seconds":10}]); current=job_from(s.call("get",{"job_id":"job","now":1},True)["data"]); return current["attempts"]==1,s
    answers.append(probe(concurrent))
    def no_jobs():
        s=Scenario(mutant); result=job_from(claim(s,"c1","w",0)["data"]); return result is None and s.snapshot()[0]==[],s
    answers.append(probe(no_jobs)); return all(answers)


FUNCTIONS={"ack_stale_worker_rejected":check_stale,"ack_single_claim":check_single,"ack_visibility_timeout":check_visibility,"ack_nack_requeues":check_nack,"ack_attempt_accounting":check_attempts}

def evaluate(mutant=""):
    global PROBE_COUNTER; checks={}; counts={}
    for name in CHECKS:
        PROBE_COUNTER=0; functional=FUNCTIONS[name](mutant); counts[name]=PROBE_COUNTER; checks[name]=functional and counts[name]==PROBE_COUNTS[name]
    return {"implementation":mutant or "reference","passed":[k for k,v in checks.items() if v],"failed":[k for k,v in checks.items() if not v],"checks":checks,"executed_probes":counts}

def main(argv=None):
    global REFERENCE
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args(argv)
    if args.workspace: REFERENCE=args.workspace.resolve(); rows=[evaluate()]; ok=rows[0]["failed"]==[]
    else:
        rows=[evaluate()]+[evaluate(name) for name in CHECKS]+[evaluate("ack_stale_toctou")]; expected={"reference":[]}|{name:[name] for name in CHECKS}|{"ack_stale_toctou":["ack_stale_worker_rejected"]}; ok=all(row["failed"]==expected[row["implementation"]] for row in rows)
    print(json.dumps({"efficacy_cells":0,"matrix":rows,"mutant_runs":0 if args.workspace else len(CHECKS)+1,"ok":ok,"probe_counts":PROBE_COUNTS,"target_model_calls":0,"task_id":"ack-token-work-queue","total_probes_per_implementation":sum(PROBE_COUNTS.values())},sort_keys=True,separators=(",",":")))
    return 0 if ok else 1

if __name__=="__main__": raise SystemExit(main())
