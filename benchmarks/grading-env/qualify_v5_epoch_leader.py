from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from materialize_v5_crypto_mutants import materialize_mutant

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=Path(os.environ.get("V5_EPOCH_LEADER_REFERENCE",ROOT/"benchmarks/grading-env/mechanism-first-v5/references/epoch-guarded-leader-heartbeat")).resolve()
CHECKS=("leader_stale_epoch_publish","leader_epoch_monotonic","leader_one_winner","leader_expiry_boundary","leader_publication_order")
PROBE_COUNTS={"leader_stale_epoch_publish":24,"leader_epoch_monotonic":7,"leader_one_winner":6,"leader_expiry_boundary":8,"leader_publication_order":9}
PROBE_COUNTER=0
WAIT_DRIVER=r'''
import os,sys,time
from pathlib import Path
ready=Path(os.environ["LEADER_READY"]); barrier=Path(os.environ["LEADER_BARRIER"]); ready.write_text("ready")
while not barrier.exists(): time.sleep(0.005)
os.execv(sys.executable,[sys.executable,"-m","epoch_leader.cli",*sys.argv[1:]])
'''
BASE=datetime(2026,1,1,tzinfo=UTC)


def ts(seconds: int) -> str: return (BASE+timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
def canon(value: Any) -> bytes: return (json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()
def env(value: Any) -> bytes: return canon({"result":value,"status":"ok"})
def parsed(data: bytes) -> Any:
    value=json.loads(data)
    if data!=canon(value) or not isinstance(value,dict) or set(value)!={"result","status"} or value["status"]!="ok": raise AssertionError("noncanonical envelope")
    return value["result"]


class Scenario:
    def __init__(self,mutant: str="",initialize: bool=True):
        self.temp=tempfile.TemporaryDirectory(prefix="v5-leader-"); self.root=Path(self.temp.name); self.db=self.root/"leader.sqlite3"; self.impl=REFERENCE
        if mutant: self.impl=materialize_mutant(REFERENCE,"epoch-guarded-leader-heartbeat",mutant,self.root/"implementation")
        if initialize:
            first=self.call("acquire",{"request_id":"initial","campaign_id":"campaign","ttl_seconds":10,"leader_id":"A","now":ts(0)},True)
            if parsed(first["data"])["epoch"]!=1: raise RuntimeError(first)
    def close(self): self.temp.cleanup()
    def paths(self,tag: str,body: Any):
        req=self.root/f"{tag}-{os.urandom(3).hex()}.json"; out=self.root/f"{tag}-{os.urandom(3).hex()}.out"; req.write_bytes(canon(body)); return req,out
    def call(self,command: str,body: Any,success: bool,tag="call",mode="absent") -> dict[str,Any]:
        req,out=self.paths(tag,body); sentinel=b"preserve\n"
        if mode=="existing": out.write_bytes(sentinel)
        if mode=="delivery_fail": out.mkdir()
        run=subprocess.run([sys.executable,"-m","epoch_leader.cli",command,"--db",str(self.db),"--request",str(req),"--output",str(out)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl),"PYTHONHASHSEED":"97"},capture_output=True,timeout=30)
        if success:
            return {"ok":run.returncode==0 and not run.stdout and not run.stderr and out.is_file(),"data":out.read_bytes() if out.is_file() else b"","stderr":run.stderr}
        preserved=out.is_dir() if mode=="delivery_fail" else (out.read_bytes()==sentinel if mode=="existing" else not out.exists())
        return {"ok":run.returncode!=0 and not run.stdout and run.stderr.count(b"\n")==1 and b"Traceback" not in run.stderr and preserved,"stderr":run.stderr}
    def reject(self,command: str,body: Any) -> bool:
        before=self.snapshot(); one=self.call(command,body,False,mode="existing"); middle=self.snapshot(); two=self.call(command,body,False,mode="absent"); return one["ok"] and two["ok"] and before==middle==self.snapshot()
    def raw_reject(self,text: str) -> bool:
        before=self.snapshot(); answers=[]
        for existing in (False,True):
            req=self.root/f"raw-{os.urandom(3).hex()}.json"; out=self.root/f"raw-{os.urandom(3).hex()}.out"; req.write_text(text); sentinel=b"preserve\n"
            if existing: out.write_bytes(sentinel)
            run=subprocess.run([sys.executable,"-m","epoch_leader.cli","heartbeat","--db",str(self.db),"--request",str(req),"--output",str(out)],cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl)},capture_output=True,timeout=30)
            answers.append(run.returncode!=0 and not run.stdout and run.stderr.count(b"\n")==1 and (out.read_bytes()==sentinel if existing else not out.exists()) and self.snapshot()==before)
        return all(answers)
    def snapshot(self):
        if not self.db.exists(): return None
        conn=sqlite3.connect(self.db); result=(conn.execute("SELECT * FROM campaign").fetchall(),conn.execute("SELECT * FROM publications ORDER BY sequence").fetchall(),conn.execute("SELECT request_id,request_hash,envelope FROM requests ORDER BY request_id").fetchall()); conn.close(); return result
    def status(self,now: int) -> dict[str,Any]: return parsed(self.call("status",{"now":ts(now)},True)["data"])
    def acquire(self,request_id: str,leader: str,now: int,success=True): return self.call("acquire",{"request_id":request_id,"campaign_id":"campaign","ttl_seconds":10,"leader_id":leader,"now":ts(now)},success)
    def heartbeat(self,request_id: str,leader: str,epoch: int,now: int,success=True): return self.call("heartbeat",{"request_id":request_id,"leader_id":leader,"epoch":epoch,"now":ts(now)},success)
    def publish(self,request_id: str,leader: str,epoch: int,now: int,payload=None,success=True,mode="absent"):
        return self.call("publish",{"request_id":request_id,"leader_id":leader,"epoch":epoch,"now":ts(now),"payload_object":payload if payload is not None else {"v":request_id}},success,mode=mode)
    def concurrent(self,command: str,bodies: list[dict[str,Any]]) -> list[dict[str,Any]]:
        barrier=self.root/f"barrier-{os.urandom(3).hex()}"; procs=[]; outputs=[]; ready=[]
        for i,body in enumerate(bodies):
            req,out=self.paths(f"parallel-{i}",body); mark=self.root/f"ready-{i}-{os.urandom(2).hex()}"; ready.append(mark); outputs.append(out)
            args=[sys.executable,"-c",WAIT_DRIVER,command,"--db",str(self.db),"--request",str(req),"--output",str(out)]
            procs.append(subprocess.Popen(args,cwd=self.root,env={**os.environ,"PYTHONPATH":str(self.impl),"LEADER_READY":str(mark),"LEADER_BARRIER":str(barrier)},stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        deadline=time.monotonic()+10
        while not all(p.exists() for p in ready):
            if time.monotonic()>deadline: raise RuntimeError("barrier timeout")
            time.sleep(.005)
        barrier.write_text("go")
        rows=[]
        for proc,out in zip(procs,outputs):
            stdout,stderr=proc.communicate(timeout=30); rows.append({"ok":proc.returncode==0 and not stdout and not stderr and out.is_file(),"rejected":proc.returncode!=0 and not stdout and stderr.count(b"\n")==1 and b"Traceback" not in stderr and not out.exists(),"data":out.read_bytes() if out.is_file() else b"","stderr":stderr})
        return rows


def probe(mutant: str,function: Callable[[Scenario],bool],initialize=True) -> bool:
    global PROBE_COUNTER; PROBE_COUNTER+=1; s=Scenario(mutant,initialize)
    try: return function(s)
    finally:s.close()


def check_stale(mutant: str) -> bool:
    answers=[]
    answers.append(probe(mutant,lambda s: parsed(s.heartbeat("h","A",1,1)["data"])["epoch"]==1 and parsed(s.publish("p","A",1,2)["data"])["sequence"]==1))
    def old_heartbeat(s): s.acquire("take","A",11); return s.reject("heartbeat",{"request_id":"old-h","leader_id":"A","epoch":1,"now":ts(12)})
    def old_publish(s): s.acquire("take","A",11); return s.reject("publish",{"request_id":"old-p","leader_id":"A","epoch":1,"now":ts(12),"payload_object":{"x":1}})
    answers.extend(probe(mutant,old_heartbeat) for _ in range(2)); answers.extend(probe(mutant,old_publish) for _ in range(3))
    def wrong(s): return s.reject("publish",{"request_id":"wrong","leader_id":"B","epoch":1,"now":ts(1),"payload_object":{}})
    def expired(s): return s.reject("heartbeat",{"request_id":"expired","leader_id":"A","epoch":1,"now":ts(10)})
    answers.extend([probe(mutant,wrong),probe(mutant,expired)])
    def delivery(s):
        body={"request_id":"deliver","leader_id":"A","epoch":1,"now":ts(1),"payload_object":{"x":1}}; failed=s.call("publish",body,False,mode="delivery_fail"); replay=s.call("publish",body,True); return failed["ok"] and parsed(replay["data"])["sequence"]==1 and len(s.status(2)["publications"])==1
    answers.append(probe(mutant,delivery))
    guards=[lambda s:s.raw_reject("{"),lambda s:s.raw_reject('{"request_id":"x","request_id":"y"}'),lambda s:s.raw_reject('{"request_id":"x","leader_id":"A","epoch":NaN,"now":"x"}'),lambda s:s.reject("heartbeat",{"request_id":"x","leader_id":"A","epoch":True,"now":ts(1)}),lambda s:s.reject("heartbeat",{"request_id":"x","leader_id":" A","epoch":1,"now":ts(1)}),lambda s:s.reject("heartbeat",{"request_id":"x","leader_id":"A","epoch":1,"now":"2026-01-01T00:00:00"}),lambda s:s.reject("publish",{"request_id":"x","leader_id":"A","epoch":1,"now":ts(1),"payload_object":[]}),lambda s:s.reject("heartbeat",{"request_id":"initial","leader_id":"A","epoch":1,"now":ts(1)})]
    invalid_times=["20260101T000000Z","2026-01-01T00Z","2026-W01-4T00:00:00Z","2026-01-01T00:00:00,5Z"]
    guards.extend(lambda s,value=value:s.reject("heartbeat",{"request_id":f"time-{len(value)}-{value[-1]}","leader_id":"A","epoch":1,"now":value}) for value in invalid_times)
    answers.extend(probe(mutant,g) for g in guards)
    def schema_guard(s):
        conn=sqlite3.connect(s.db); tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}; mode=conn.execute("PRAGMA journal_mode").fetchone()[0]; conn.close(); return tables=={"campaign","publications","requests"} and mode=="wal"
    answers.append(probe(mutant,schema_guard))
    def ancient(s):
        body={"request_id":"ancient","campaign_id":"campaign","ttl_seconds":10,"leader_id":"A","now":"0001-01-01T00:00:00Z"}; return parsed(s.call("acquire",body,True)["data"])["expires_at"].startswith("0001-01-01T00:00:10")
    answers.append(probe(mutant,ancient,False))
    def empty_db(s):
        sqlite3.connect(s.db).close(); before=s.db.read_bytes(); call=s.call("heartbeat",{"request_id":"empty","leader_id":"A","epoch":1,"now":ts(1)},False); conn=sqlite3.connect(s.db); tables=conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(); mode=conn.execute("PRAGMA journal_mode").fetchone()[0]; conn.close(); return call["ok"] and s.db.read_bytes()==before and tables==[] and mode=="delete"
    answers.append(probe(mutant,empty_db,False)); return all(answers)


def check_epoch(mutant: str) -> bool:
    answers=[]
    def chain(s): return [parsed(s.acquire(f"a{i}","A",i*11)["data"])["epoch"] for i in (1,2,3)]==[2,3,4]
    answers.extend(probe(mutant,chain) for _ in range(2))
    def alternating(s): return parsed(s.acquire("b", "B",11)["data"])["epoch"]==2 and parsed(s.acquire("a","A",22)["data"])["epoch"]==3
    answers.append(probe(mutant,alternating))
    def failed(s): before=s.snapshot(); bad=s.acquire("early","B",9,False); middle=s.snapshot(); good=parsed(s.acquire("boundary","B",11)["data"]); return bad["ok"] and before==middle and good["epoch"]==2
    answers.extend(probe(mutant,failed) for _ in range(2))
    def restart(s): s.acquire("b","B",11); return s.status(12)["leader"]["epoch"]==2
    answers.append(probe(mutant,restart))
    def mismatch(s): return s.reject("acquire",{"request_id":"bad","campaign_id":"other","ttl_seconds":10,"leader_id":"B","now":ts(10)})
    answers.append(probe(mutant,mismatch)); return all(answers)


def check_winner(mutant: str) -> bool:
    answers=[]
    def race(s,count=2):
        bodies=[{"request_id":f"r{i}","campaign_id":"campaign","ttl_seconds":10,"leader_id":f"L{i}","now":ts(11)} for i in range(count)]; rows=s.concurrent("acquire",bodies); winners=[parsed(r["data"]) for r in rows if r["ok"]]; state=s.status(12)["leader"]; return len(winners)==1 and all(r["ok"] or r["rejected"] for r in rows) and winners[0]["leader_id"]==state["leader_id"]
    answers.extend(probe(mutant,lambda s:race(s,2)) for _ in range(2)); answers.extend(probe(mutant,lambda s:race(s,3)) for _ in range(2))
    def same(s):
        bodies=[{"request_id":f"s{i}","campaign_id":"campaign","ttl_seconds":10,"leader_id":"A","now":ts(11)} for i in range(2)]; rows=s.concurrent("acquire",bodies); return sum(r["ok"] for r in rows)==1 and all(r["ok"] or r["rejected"] for r in rows)
    answers.append(probe(mutant,same))
    def initial(s):
        bodies=[{"request_id":f"i{i}","campaign_id":"campaign","ttl_seconds":10,"leader_id":f"L{i}","now":ts(0)} for i in range(2)]; rows=s.concurrent("acquire",bodies); return sum(r["ok"] for r in rows)==1 and all(r["ok"] or r["rejected"] for r in rows)
    answers.append(probe(mutant,initial,False)); return all(answers)


def check_expiry(mutant: str) -> bool:
    answers=[]
    for now,success in ((9,False),(10,True),(11,True)):
        def boundary(s,now=now,success=success):
            if success: return parsed(s.acquire("next","B",now)["data"])["leader_id"]=="B"
            return s.acquire("early","B",now,False)["ok"] and s.status(now)["leader"]["leader_id"]=="A"
        answers.append(probe(mutant,boundary))
    def active(s,now,expected): return s.status(now)["leader"]["active"] is expected
    answers.extend([probe(mutant,lambda s:active(s,9,True)),probe(mutant,lambda s:active(s,10,False))])
    def heartbeat_edge(s): return s.heartbeat("edge","A",1,10,False)["ok"]
    answers.extend(probe(mutant,heartbeat_edge) for _ in range(2))
    def offset(s):
        body={"request_id":"offset","campaign_id":"campaign","ttl_seconds":10,"leader_id":"B","now":"2026-01-01T01:00:10+01:00"}; return parsed(s.call("acquire",body,True)["data"])["leader_id"]=="B"
    answers.append(probe(mutant,offset)); return all(answers)


def check_order(mutant: str) -> bool:
    answers=[]
    def sequential(s): return [parsed(s.publish(f"p{i}","A",1,i)["data"])["sequence"] for i in (1,2,3)]==[1,2,3]
    answers.append(probe(mutant,sequential))
    def concurrent(s,count=3):
        bodies=[{"request_id":f"p{i}","leader_id":"A","epoch":1,"now":ts(1),"payload_object":{"i":i}} for i in range(count)]; rows=s.concurrent("publish",bodies); seq=sorted(parsed(r["data"])["sequence"] for r in rows if r["ok"]); return len(seq)==count and seq==list(range(1,count+1)) and [p["sequence"] for p in s.status(2)["publications"]]==seq
    answers.extend(probe(mutant,lambda s:concurrent(s,3)) for _ in range(2)); answers.append(probe(mutant,lambda s:concurrent(s,5)))
    def rejected(s): before=s.snapshot(); assert s.publish("bad","B",1,1,success=False)["ok"]; after=s.snapshot(); good=parsed(s.publish("good","A",1,2)["data"]); return before==after and good["sequence"]==1
    answers.append(probe(mutant,rejected))
    def delivery(s): failed=s.publish("p","A",1,1,mode="delivery_fail",success=False); replay=s.publish("p","A",1,1); return failed["ok"] and parsed(replay["data"])["sequence"]==1 and len(s.status(2)["publications"])==1
    answers.append(probe(mutant,delivery))
    def digest_probe(s):
        payload={"z":"é","a":[1,2]}; result=parsed(s.publish("p","A",1,1,payload)["data"]); expected=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(); return result["payload_sha256"]==expected and s.status(2)["publications"][0]["payload"]==payload
    answers.append(probe(mutant,digest_probe))
    def takeover(s): s.publish("p1","A",1,1); leader=parsed(s.acquire("take","B",11)["data"]); return parsed(s.publish("p2","B",leader["epoch"],12)["data"])["sequence"]==2
    answers.append(probe(mutant,takeover))
    def rollback_after_allocation(s):
        conn=sqlite3.connect(s.db); conn.execute("CREATE TRIGGER fail_request BEFORE INSERT ON requests WHEN NEW.request_id='force-fail' BEGIN SELECT RAISE(ABORT,'forced'); END"); conn.commit(); conn.close(); before=s.snapshot(); failed=s.publish("force-fail","A",1,1,success=False); after=s.snapshot(); conn=sqlite3.connect(s.db); conn.execute("DROP TRIGGER fail_request"); conn.commit(); conn.close(); good=parsed(s.publish("after","A",1,2)["data"]); return failed["ok"] and before==after and good["sequence"]==1
    answers.append(probe(mutant,rollback_after_allocation)); return all(answers)


FUNCTIONS={"leader_stale_epoch_publish":check_stale,"leader_epoch_monotonic":check_epoch,"leader_one_winner":check_winner,"leader_expiry_boundary":check_expiry,"leader_publication_order":check_order}
def evaluate(mutant=""):
    global PROBE_COUNTER; checks={}; counts={}
    for name in CHECKS:
        PROBE_COUNTER=0
        try: functional=FUNCTIONS[name](mutant)
        except Exception: functional=False
        counts[name]=PROBE_COUNTER; checks[name]=functional and counts[name]==PROBE_COUNTS[name]
    return {"implementation":mutant or "reference","passed":[k for k,v in checks.items() if v],"failed":[k for k,v in checks.items() if not v],"checks":checks,"executed_probes":counts}
def main(argv=None):
    global REFERENCE
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args(argv)
    if args.workspace: REFERENCE=args.workspace.resolve(); rows=[evaluate()]; ok=not rows[0]["failed"]
    else:
        rows=[evaluate()]+[evaluate(name) for name in CHECKS]+[evaluate("leader_epoch_heartbeat_near_miss")]; expected={"reference":[]}|{name:[name] for name in CHECKS}|{"leader_epoch_heartbeat_near_miss":["leader_stale_epoch_publish"]}; ok=all(row["failed"]==expected[row["implementation"]] for row in rows)
    print(json.dumps({"efficacy_cells":0,"matrix":rows,"mutant_runs":0 if args.workspace else len(CHECKS)+1,"ok":ok,"probe_counts":PROBE_COUNTS,"target_model_calls":0,"task_id":"epoch-guarded-leader-heartbeat","total_probes_per_implementation":sum(PROBE_COUNTS.values())},sort_keys=True,separators=(",",":"))); return 0 if ok else 1
if __name__=="__main__": raise SystemExit(main())
