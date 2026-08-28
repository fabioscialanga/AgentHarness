from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=ROOT/"benchmarks/grading-env/mechanism-first-v5.1/references/context-complete-authorization-cache"
CHECKS=("auth_cache_resource_identity","auth_cache_tenant","auth_cache_subject","auth_cache_action","auth_cache_policy_revision")
PROBES={name:10 for name in CHECKS}
MUTANTS=list(CHECKS); NEAR="auth_cache_resource_alias_near_miss"

def load(root:Path):
    for name in list(sys.modules):
        if name=="decision_cache" or name.startswith("decision_cache."): del sys.modules[name]
    sys.path.insert(0,str(root))
    try:
        package=importlib.import_module("decision_cache"); return package.create_app,package.PolicySnapshot
    finally: sys.path.pop(0)

class Clock:
    def __init__(self): self.value=100; self.calls=0; self.mode="ok"
    def now(self):
        self.calls+=1
        if self.mode=="raise": raise RuntimeError("clock")
        if self.mode=="bool": return True
        if self.mode=="zero": return 0
        if self.mode=="high": return 9223372036854775808
        if self.mode=="float": return 100.0
        return self.value

class Store:
    def __init__(self,snapshot_type):
        self.snapshot_type=snapshot_type; self.policies={}; self.tokens={}; self.snapshot_calls=0; self.evaluate_calls=0; self.snapshot_mode="ok"; self.evaluate_mode="ok"; self.last_evaluated_snapshot=None; self.last_snapshot=None
    def set(self,tenant,subject,revision,allowed): self.policies[(tenant,subject)]=(revision,set(allowed))
    def snapshot(self,tenant,subject):
        self.snapshot_calls+=1
        if self.snapshot_mode=="raise": raise RuntimeError("snapshot")
        if self.snapshot_mode=="wrong": return object()
        revision,allowed=self.policies.get((tenant,subject),(1,set())); token=object(); snap=self.snapshot_type(revision,token); self.tokens[token]=(tenant,subject,revision,allowed); self.last_snapshot=snap
        if self.snapshot_mode=="bad_revision": return self.snapshot_type(True,token)
        if self.snapshot_mode=="zero_revision": return self.snapshot_type(0,token)
        if self.snapshot_mode=="high_revision": return self.snapshot_type(9223372036854775808,token)
        if self.snapshot_mode=="float_revision": return self.snapshot_type(7.0,token)
        if self.snapshot_mode=="none_token": return self.snapshot_type(revision,None)
        return snap
    def evaluate(self,snapshot,resource,action):
        self.evaluate_calls+=1; self.last_evaluated_snapshot=snapshot
        if snapshot is not self.last_snapshot: raise RuntimeError("snapshot identity changed")
        if self.evaluate_mode=="raise": raise RuntimeError("evaluate")
        if self.evaluate_mode=="nonbool": return 1
        _,_,revision,allowed=self.tokens[snapshot.evaluation_token]
        return (resource,action) in allowed

class Scenario:
    def __init__(self,impl:Path,ttl=60):
        create,snapshot_type=load(impl); self.create=create; self.clock=Clock(); self.store=Store(snapshot_type); self.store.set("tenant-a","alice",7,{("doc-a","read"),("report","read")}); self.app=create(self.store,self.clock,ttl); self.client=TestClient(self.app,raise_server_exceptions=False)
    def close(self): self.client.close()
    def body(self,tenant="tenant-a",subject="alice",resource="doc-a",action="read"): return {"tenant":tenant,"subject":subject,"resource_id":resource,"action":action}
    def post(self,**kwargs): return self.client.post("/authorize",json=self.body(**kwargs))

def probe(impl,fn):
    s=Scenario(impl)
    try: return bool(fn(s))
    except Exception: return False
    finally: s.close()

def pair(s,first,second,first_allowed=True,second_allowed=False):
    r1=s.post(**first); r2=s.post(**second); before=s.store.evaluate_calls; r3=s.post(**second)
    return r1.status_code==r2.status_code==r3.status_code==200 and r1.json()=={"allowed":first_allowed,"policy_revision":7,"cache":"miss"} and r2.json()=={"allowed":second_allowed,"policy_revision":7,"cache":"miss"} and r3.json()=={"allowed":second_allowed,"policy_revision":7,"cache":"hit"} and before==2 and s.store.evaluate_calls==2 and s.store.snapshot_calls==3 and s.clock.calls==3

def check_resource(impl):
    cases=[("doc-a","doc-b",True),("report","report.copy",True),("alpha","beta",True),("Case","case",True),("x","x.v2",True),("one","two",False),("invoice","invoice.old",False),("A1","A2",False),("root","root.child",False),("left","right",False)]
    def run(s,a,b,forward):
        s.store.set("tenant-a","alice",7,{(a if forward else b,"read")}); return pair(s,{"resource":a},{"resource":b},forward,not forward)
    return all(probe(impl,lambda s,a=a,b=b,f=f:run(s,a,b,f)) for a,b,f in cases)

def check_tenant(impl):
    names=["tenant-b","tenant-c","tenant-d","north","south","prod","stage","blue","green","acme"]
    def run(s,name,forward):
        s.store.set("tenant-a","alice",7,{("doc-a","read")} if forward else set()); s.store.set(name,"alice",7,set() if forward else {("doc-a","read")}); return pair(s,{"tenant":"tenant-a"},{"tenant":name},forward,not forward)
    return all(probe(impl,lambda s,n=n,f=i<5:run(s,n,f)) for i,n in enumerate(names))

def check_subject(impl):
    names=["bob","carol","dave","erin","frank","grace","heidi","ivan","judy","mallory"]
    def run(s,name,forward):
        s.store.set("tenant-a","alice",7,{("doc-a","read")} if forward else set()); s.store.set("tenant-a",name,7,set() if forward else {("doc-a","read")}); return pair(s,{"subject":"alice"},{"subject":name},forward,not forward)
    return all(probe(impl,lambda s,n=n,f=i<5:run(s,n,f)) for i,n in enumerate(names))

def check_action(impl):
    actions=["delete","write","export","share","approve","archive","restore","publish","sign","execute"]
    def run(s,action,forward):
        s.store.set("tenant-a","alice",7,{("doc-a","read" if forward else action)}); return pair(s,{"action":"read"},{"action":action},forward,not forward)
    return all(probe(impl,lambda s,a=a,f=i<5:run(s,a,f)) for i,a in enumerate(actions))

def check_revision(impl):
    revisions=[(7,8),(11,12),(20,21),(99,100),(1000,1001),(3,9),(42,84),(500,900),(1,2),(7000,7001)]
    def run(s,old,new,forward):
        s.store.set("tenant-a","alice",old,{("doc-a","read")} if forward else set()); r1=s.post(); s.store.set("tenant-a","alice",new,set() if forward else {("doc-a","read")}); r2=s.post(); r3=s.post()
        return r1.json()=={"allowed":forward,"policy_revision":old,"cache":"miss"} and r2.json()=={"allowed":not forward,"policy_revision":new,"cache":"miss"} and r3.json()=={"allowed":not forward,"policy_revision":new,"cache":"hit"} and s.store.evaluate_calls==2 and s.store.snapshot_calls==3 and s.clock.calls==3
    return all(probe(impl,lambda s,o=o,n=n,f=i<5:run(s,o,n,f)) for i,(o,n) in enumerate(revisions))

FUNCTIONS={"auth_cache_resource_identity":check_resource,"auth_cache_tenant":check_tenant,"auth_cache_subject":check_subject,"auth_cache_action":check_action,"auth_cache_policy_revision":check_revision}

def common_controls(impl):
    results={}
    def retained_allow(s):
        first=s.post(); second=s.post()
        return [first.json()["cache"],second.json()["cache"]]==["miss","hit"] and first.json()["allowed"] is True and second.json()["allowed"] is True and s.store.evaluate_calls==1
    def retained_deny(s):
        s.store.set("tenant-a","alice",7,set()); first=s.post(); second=s.post()
        return [first.json()["cache"],second.json()["cache"]]==["miss","hit"] and first.json()["allowed"] is False and second.json()["allowed"] is False and s.store.evaluate_calls==1
    results["cache_retains_allow_and_deny"]=all([probe(impl,retained_allow) for _ in range(2)]+[probe(impl,retained_deny) for _ in range(2)])
    def ttl(s):
        a=s.post(); s.clock.value=159; b=s.post(); s.clock.value=160; c=s.post(); return [x.json()["cache"] for x in (a,b,c)]==["miss","hit","miss"] and s.store.evaluate_calls==2
    results["cache_half_open_ttl"]=all(probe(impl,ttl) for _ in range(2))
    atomic=[]
    def primed(s):
        first=s.post(); return first.status_code==200 and first.json()["cache"]=="miss" and s.store.evaluate_calls==1
    def preserved_hit(s,expected_evaluations=1):
        hit=s.post(); return hit.status_code==200 and hit.json()["cache"]=="hit" and hit.json()["allowed"] is True and s.store.evaluate_calls==expected_evaluations
    invalid_bodies=[
        {"tenant":"tenant-a"},
        {"tenant":"tenant-a","subject":"alice","resource_id":"doc-a","action":"read","extra":1},
        [],"text",None,
        {"tenant":"","subject":"alice","resource_id":"doc-a","action":"read"},
        {"tenant":"bad/slash","subject":"alice","resource_id":"doc-a","action":"read"},
        {"tenant":"tenant-a","subject":1,"resource_id":"doc-a","action":"read"},
        {"tenant":"x"*65,"subject":"alice","resource_id":"doc-a","action":"read"},
    ]
    def invalid_body_case(s,body):
        if not primed(s): return False
        before=(s.store.snapshot_calls,s.clock.calls,s.store.evaluate_calls); r=s.client.post("/authorize",json=body)
        return r.status_code==422 and r.json()=={"detail":"invalid_request"} and (s.store.snapshot_calls,s.clock.calls,s.store.evaluate_calls)==before and preserved_hit(s)
    atomic.extend(probe(impl,lambda s,b=b:invalid_body_case(s,b)) for b in invalid_bodies)
    def malformed_json(s):
        if not primed(s): return False
        before=(s.store.snapshot_calls,s.clock.calls,s.store.evaluate_calls); r=s.client.post("/authorize",content=b"{",headers={"content-type":"application/json"})
        return r.status_code==422 and r.json()=={"detail":"invalid_request"} and (s.store.snapshot_calls,s.clock.calls,s.store.evaluate_calls)==before and preserved_hit(s)
    atomic.append(probe(impl,malformed_json))
    def valid_id_boundary(s):
        value="x"*64; s.store.set(value,"alice",7,{("doc-a","read")}); r=s.post(tenant=value); return r.status_code==200 and r.json()["cache"]=="miss"
    atomic.append(probe(impl,valid_id_boundary))
    def bad_snapshot(s,mode):
        if not primed(s): return False
        s.store.snapshot_mode=mode; r=s.post(resource="uncached",action="probe"); s.store.snapshot_mode="ok"; recovery=s.post(resource="uncached",action="probe")
        return r.status_code==422 and r.json()=={"detail":"invalid_request"} and recovery.json()["cache"]=="miss" and s.store.snapshot_calls==3 and s.clock.calls==2 and s.store.evaluate_calls==2 and preserved_hit(s,2)
    atomic.extend(probe(impl,lambda s,m=m:bad_snapshot(s,m)) for m in ("raise","wrong","bad_revision","zero_revision","high_revision","float_revision","none_token"))
    def bad_clock(s,mode):
        if not primed(s): return False
        s.clock.mode=mode; r=s.post(resource="uncached",action="probe"); s.clock.mode="ok"; recovery=s.post(resource="uncached",action="probe")
        return r.status_code==422 and r.json()=={"detail":"invalid_request"} and recovery.json()["cache"]=="miss" and s.store.snapshot_calls==3 and s.clock.calls==3 and s.store.evaluate_calls==2 and preserved_hit(s,2)
    atomic.extend(probe(impl,lambda s,m=m:bad_clock(s,m)) for m in ("raise","bool","zero","high","float"))
    def bad_eval(s,mode):
        if not primed(s): return False
        s.store.evaluate_mode=mode; r=s.post(resource="uncached",action="probe"); s.store.evaluate_mode="ok"; good=s.post(resource="uncached",action="probe")
        return r.status_code==422 and r.json()=={"detail":"invalid_request"} and good.status_code==200 and good.json()["cache"]=="miss" and s.store.evaluate_calls==3 and preserved_hit(s,3)
    atomic.extend(probe(impl,lambda s,m=m:bad_eval(s,m)) for m in ("raise","nonbool"))
    def valid_numeric_boundaries(s):
        s.store.set("tenant-a","alice",9223372036854775807,{("doc-a","read")}); s.clock.value=9223372036854775807; r=s.post(); return r.status_code==200 and r.json()["policy_revision"]==9223372036854775807
    atomic.append(probe(impl,valid_numeric_boundaries))
    def valid_low_clock(s): s.clock.value=1; return s.post().status_code==200
    atomic.append(probe(impl,valid_low_clock))
    try:
        create,_=load(impl); ttl_ok=True
        for value in (True,False,0,-1,3601,1.5,"60",None):
            try: create(object(),object(),value); ttl_ok=False; break
            except ValueError: pass
        for value in (1,3600):
            scenario=Scenario(impl,ttl=value)
            try: ttl_ok=ttl_ok and scenario.post().status_code==200
            finally: scenario.close()
    except Exception: ttl_ok=False
    atomic.append(ttl_ok); results["cache_invalid_input_atomicity"]=all(atomic)
    return results,{"cache_retains_allow_and_deny":4,"cache_half_open_ttl":6,"cache_invalid_input_atomicity":len(atomic)}

def evaluate(impl,name):
    common,common_probes=common_controls(impl); checks={c:FUNCTIONS[c](impl) for c in CHECKS}; return {"implementation":name,"common_controls":common,"common_probe_counts":common_probes,"checks":checks,"failed":[c for c in CHECKS if not checks[c]],"passed":[c for c in CHECKS if checks[c]],"common_failed":[c for c,v in common.items() if not v]}

def materialize(mutant,tmp):
    sys.path.insert(0,str(ROOT/"benchmarks/grading-env"))
    try:
        from materialize_v5_crypto_mutants import materialize_mutant
        return materialize_mutant(REFERENCE,"context-complete-authorization-cache",mutant,tmp/mutant)
    finally: sys.path.pop(0)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--workspace",type=Path); args=parser.parse_args(); matrix=[]
    if args.workspace: matrix=[evaluate(args.workspace.resolve(),"candidate")]
    else:
        with tempfile.TemporaryDirectory() as raw:
            tmp=Path(raw); matrix.append(evaluate(REFERENCE,"reference"))
            for mutant in MUTANTS+[NEAR]: matrix.append(evaluate(materialize(mutant,tmp),mutant))
    if args.workspace: ok=not matrix[0]["failed"] and not matrix[0]["common_failed"]
    else: ok=not matrix[0]["failed"] and not matrix[0]["common_failed"] and all(row["failed"]==[row["implementation"]] and not row["common_failed"] for row in matrix[1:6]) and matrix[6]["failed"]==["auth_cache_resource_identity"] and not matrix[6]["common_failed"]
    print(json.dumps({"task_id":"context-complete-authorization-cache","ok":ok,"checks":list(CHECKS),"probe_counts":PROBES,"total_scored_probes_per_implementation":50,"matrix":matrix,"target_model_calls":0,"efficacy_cells":False},sort_keys=True)); return 0 if ok else 1
if __name__=="__main__": raise SystemExit(main())
