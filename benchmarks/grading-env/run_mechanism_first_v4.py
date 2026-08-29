from __future__ import annotations

"""Freeze-first V4 collector and provider-free production finalizer."""

import argparse, fcntl, hashlib, json, os, shutil, subprocess, sys, tempfile, traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Protocol

REPO_ROOT=Path(__file__).resolve().parents[2]; SRC_ROOT=REPO_ROOT/"src"
if str(SRC_ROOT) not in sys.path: sys.path.insert(0,str(SRC_ROOT))
from agentharness.benchmark_cells import AGENT_INVOCATION_TIMEOUT_SECONDS, AgentInvocationResult, ClassifiedCellFailure, HermesCliInvoker, build_cell_manifest, compute_solution_hash
from agentharness.benchmark_heldout_evaluator_v4 import evaluate_heldout
from agentharness.benchmark_review_evaluator_v4 import evaluate_review
from agentharness.efficacy_v4 import CALIBRATION_TASKS, CONDITION_ORDERS, CONDITIONS, EVALUATION_TASKS, OPAQUE_FINDING_IDS, PILOT_ID, calibration_admission, canonical_hash, clone_pair, finalize_results, materialize_clean_reference, materialize_controlled_start, quota_admission, tree_fingerprint, validate_marker_accounting, validate_opaque_feedback

TEMPLATE_PATH=REPO_ROOT/"benchmarks/grading-env/MECHANISM_FIRST_V4_PREREG.template.json"; PLACEHOLDER="FREEZE_REQUIRED:"
SCHEMA_VERSION=4; PROTOCOL_TAG="v4"; REPLICATE_ID="v4-r1"; RESULT_FILENAME="MECHANISM_FIRST_V4_RESULT.json"; MAX_TURNS=40
CALIBRATION_CALLS=len(CALIBRATION_TASKS); EVALUATION_CALLS=2*len(EVALUATION_TASKS); MAXIMUM_CALLS=CALIBRATION_CALLS+EVALUATION_CALLS
class V4Error(RuntimeError): exit_code=50
class IntegrityFailure(V4Error): exit_code=30
class InvocationFailure(V4Error): exit_code=13

def utc_now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def sha256_file(path:Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def git(*args:str): return subprocess.run(["git",*args],cwd=REPO_ROOT,check=True,capture_output=True,text=True).stdout.strip()
def contains_placeholder(value:object)->bool:
    if isinstance(value,str): return value.startswith(PLACEHOLDER)
    if isinstance(value,Mapping): return any(contains_placeholder(x) for x in value.values())
    if isinstance(value,list): return any(contains_placeholder(x) for x in value)
    return False

def atomic_write(path:Path,payload:object,*,exclusive:bool=False)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    if exclusive:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as stream: json.dump(payload,stream,indent=2,sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        return
    temporary=path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("x",encoding="utf-8") as stream: json.dump(payload,stream,indent=2,sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary,path); os.chmod(path,0o600)

def validate_manifest_shape(m:Mapping[str,object])->None:
    if m.get("schema_version")!=SCHEMA_VERSION or m.get("pilot_id")!=PILOT_ID: raise IntegrityFailure("manifest identity mismatch")
    if m.get("execution_mode") not in {"real","qualification"}: raise IntegrityFailure("execution mode invalid")
    if tuple(m.get("calibration_tasks",[]))!=CALIBRATION_TASKS or tuple(m.get("evaluation_tasks",[]))!=EVALUATION_TASKS: raise IntegrityFailure("task roster mismatch")
    blocks=m.get("evaluation_blocks")
    if not isinstance(blocks,list) or len(blocks)!=len(EVALUATION_TASKS): raise IntegrityFailure("evaluation block roster mismatch")
    for i,b in enumerate(blocks):
        if not isinstance(b,Mapping) or b.get("block_id")!=f"{PROTOCOL_TAG}-eval-{i+1:03d}" or b.get("task_id")!=EVALUATION_TASKS[i] or tuple(b.get("condition_order",[]))!=CONDITION_ORDERS[i]: raise IntegrityFailure("frozen AB/BA order mismatch")
    if m.get("expected_calibration_provider_calls")!=CALIBRATION_CALLS or m.get("expected_evaluation_provider_calls")!=EVALUATION_CALLS or m.get("maximum_provider_calls")!=MAXIMUM_CALLS or m.get("expected_initial_provider_calls")!=0: raise IntegrityFailure("provider budget mismatch")
    if m.get("quota_threshold_percent")!=76 or m.get("threat_model")!="cooperative-non-adversarial" or m.get("provider_signed_receipts") is not False: raise IntegrityFailure("protocol constants mismatch")
    if m.get("provider")!="openai-codex" or m.get("model")!="gpt-5.6-sol" or m.get("toolsets")!="terminal,file" or m.get("max_turns")!=MAX_TURNS or m.get("hermes_home")!="/home/fabio/.hermes/profiles/stage2codex2": raise IntegrityFailure("runtime constants mismatch")

def freeze_manifest(template:Path,output:Path,*,execution_mode:str="real"):
    if template.resolve()!=TEMPLATE_PATH.resolve() or output.resolve().is_relative_to(REPO_ROOT.resolve()) or output.exists(): raise IntegrityFailure("new external normative freeze required")
    if git("status","--porcelain","--untracked-files=all"): raise IntegrityFailure("repository must be clean before freeze")
    m=json.loads(template.read_text()); validate_manifest_shape(m); m.update(execution_mode=execution_mode,preregistration_status="frozen",frozen_at=utc_now(),repository_commit=git("rev-parse","HEAD"))
    for rel in m["frozen_file_sha256"]: m["frozen_file_sha256"][rel]=sha256_file(REPO_ROOT/rel)
    command=Path(m["hermes_command"])
    if not command.is_file() or not os.access(command,os.X_OK): raise IntegrityFailure("Hermes wrapper unavailable")
    m["hermes_command_sha256"]=sha256_file(command); m.pop("manifest_payload_sha256",None); m["manifest_payload_sha256"]=canonical_hash(m)
    if contains_placeholder(m): raise IntegrityFailure("freeze left placeholders")
    atomic_write(output,m,exclusive=True); return {"path":str(output.resolve()),"sha256":sha256_file(output)}

def preflight(manifest_path:Path,run_root:Path,*,synthetic:bool=False):
    if manifest_path.resolve().is_relative_to(REPO_ROOT.resolve()) or run_root.resolve().is_relative_to(REPO_ROOT.resolve()): raise IntegrityFailure("manifest and run root must be external")
    m=json.loads(manifest_path.read_text()); validate_manifest_shape(m); expected_mode="qualification" if synthetic else "real"
    payload=dict(m); expected=payload.pop("manifest_payload_sha256",None)
    if m.get("execution_mode")!=expected_mode or m.get("preregistration_status")!="frozen" or contains_placeholder(m) or canonical_hash(payload)!=expected: raise IntegrityFailure("frozen manifest invalid or mode mismatch")
    if m.get("repository_commit")!=git("rev-parse","HEAD"): raise IntegrityFailure("repository commit mismatch")
    for rel,digest in m["frozen_file_sha256"].items():
        if not (REPO_ROOT/rel).is_file() or sha256_file(REPO_ROOT/rel)!=digest: raise IntegrityFailure(f"frozen file mismatch:{rel}")
    if not synthetic:
        if git("status","--porcelain","--untracked-files=all"): raise IntegrityFailure("repository must be clean")
        command=Path(m["hermes_command"])
        if not command.is_file() or sha256_file(command)!=m["hermes_command_sha256"] or os.environ.get("HERMES_HOME")!=m["hermes_home"]: raise IntegrityFailure("runtime binding mismatch")
        if AGENT_INVOCATION_TIMEOUT_SECONDS!=int(m["invocation_timeout_seconds"]): raise IntegrityFailure("timeout binding mismatch")
    return {"manifest_file_sha256":sha256_file(manifest_path),"repository_commit":m["repository_commit"],"execution_mode":m["execution_mode"]}

@contextmanager
def exclusive_lock(path:Path)->Iterator[None]:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a+") as stream:
        try: fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise IntegrityFailure("runner already active") from exc
        yield

class RepairInvoker(Protocol):
    def run_cloned_repair(self,manifest:dict[str,object],outputs_dir:Path,workspace:Path)->AgentInvocationResult: ...
class _SyntheticResult:
    def __init__(self,feedback:bool,claim:str|None):
        self.attempts=[{"attempt_name":"attempt-2-repair","exit_code":0}]
        self.treatment_delivery={"repair_invocation_succeeded":True,"treatment_prompt_immutable":True,"feedback_delivered":feedback,"feedback_immutable":True if feedback else None,"feedback_items_accounted":True,"repair_response_valid":True,"feedback_claim_ids":[claim] if claim else []}
class SyntheticRepairInvoker:
    def __init__(self,*,calibration_repairs:int=0): self.calibration_repairs=calibration_repairs; self.calls=[]
    def run_cloned_repair(self,manifest,outputs_dir,workspace):
        origin=manifest.get("initial_origin")
        if not isinstance(origin,Mapping) or origin.get("solution_hash")!=compute_solution_hash(workspace) or origin.get("tree_fingerprint")!=tree_fingerprint(workspace): raise IntegrityFailure("synthetic cloned-start origin contract invalid")
        outputs_dir.mkdir(parents=True,exist_ok=False); task=str(manifest["task_id"]); condition=str(manifest["condition"]); self.calls.append((task,condition))
        repair=(task in CALIBRATION_TASKS and CALIBRATION_TASKS.index(task)<self.calibration_repairs) or (task in EVALUATION_TASKS and condition=="B-agentharness")
        if repair:
            with tempfile.TemporaryDirectory() as td:
                clean=Path(td)/"clean"; materialize_clean_reference(task_id=task,repo_root=REPO_ROOT,destination=clean); shutil.rmtree(workspace); shutil.copytree(clean,workspace)
        feedback=condition=="B-agentharness"; claim=OPAQUE_FINDING_IDS.get(task) if feedback else None
        atomic_write(outputs_dir/"repair-response.json",{"schema_version":1,"decision":"applied" if repair else "no_change","summary":"Synthetic qualification repair.","findings":[] if not claim else [{"finding_id":claim,"source":"agentharness","disposition":"applied","reason":"Synthetic qualification.","changed_files":[]}]})
        return _SyntheticResult(feedback,claim)

def synthetic_usage(_phase:str)->float: return 10.0
def real_usage(_phase:str)->float:
    try:
        from agent.account_usage import fetch_account_usage
        usage=fetch_account_usage("openai-codex"); windows=list(getattr(usage,"windows",[]) or []) if getattr(usage,"available",False) else []
        if len(windows)!=1 or windows[0].used_percent is None: raise ValueError("window")
        value=float(windows[0].used_percent)
        if not 0<=value<=100: raise ValueError("range")
        return value
    except Exception as exc: raise InvocationFailure(f"quota telemetry unavailable:{type(exc).__name__}") from exc

def cleanup(workspace:Path,command:str)->None:
    done=subprocess.run([command,"--sandbox-cleanup"],cwd=workspace,capture_output=True,text=True,timeout=120)
    if done.returncode: raise IntegrityFailure("sandbox cleanup failed")

def accounting(result:object,condition:str,task:str):
    attempts=getattr(result,"attempts",None); delivery=getattr(result,"treatment_delivery",None)
    if not isinstance(attempts,list) or len(attempts)!=1 or not isinstance(delivery,Mapping) or any(delivery.get(k) is not True for k in ("repair_invocation_succeeded","treatment_prompt_immutable","feedback_items_accounted","repair_response_valid")): raise InvocationFailure("invocation accounting invalid")
    if condition=="B-agentharness" and (delivery.get("feedback_delivered") is not True or delivery.get("feedback_immutable") is not True or delivery.get("feedback_claim_ids")!=[OPAQUE_FINDING_IDS[task]]): raise InvocationFailure("feedback accounting invalid")
    return {"invocation_valid":True,"feedback_delivered":condition=="B-agentharness","feedback_immutable":True,"feedback_accounted":True}

def validate_provider_artifacts(run_root:Path,*,evaluation_admitted:bool)->None:
    if list(run_root.rglob("provider-invocation.initial.*.json")):
        raise IntegrityFailure("unexpected initial provider marker")
    started_paths=sorted(run_root.rglob("provider-invocation.repair.started.json")); completed_paths=sorted(run_root.rglob("provider-invocation.repair.completed.json"))
    expected=MAXIMUM_CALLS if evaluation_admitted else CALIBRATION_CALLS
    if len(started_paths)!=expected or len(completed_paths)!=expected:
        raise IntegrityFailure("provider marker count mismatch")
    starts=[json.loads(path.read_text()) for path in started_paths]; completions=[json.loads(path.read_text()) for path in completed_paths]
    validate_marker_accounting(starts,evaluation_admitted=evaluation_admitted)
    by_start={str(item.get("invocation_id")):item for item in starts}; by_complete={str(item.get("invocation_id")):item for item in completions}
    if len(by_start)!=expected or len(by_complete)!=expected or set(by_start)!=set(by_complete):
        raise IntegrityFailure("provider invocation identity mismatch")
    for invocation_id,start in by_start.items():
        done=by_complete[invocation_id]
        if done.get("status")!="succeeded" or done.get("failure") is not None:
            raise IntegrityFailure("provider completion not successful")
        for key in ("phase","task_id","condition","invocation_id"):
            if start.get(key)!=done.get(key): raise IntegrityFailure("provider marker pairing mismatch")

class V4Pilot:
    def __init__(self,manifest_path:Path,run_root:Path,*,invoker:RepairInvoker,usage:Callable[[str],float],synthetic=False):
        self.manifest_path=manifest_path.resolve(); self.run_root=run_root.resolve(); self.manifest=json.loads(self.manifest_path.read_text()); self.invoker=invoker; self.usage=usage; self.synthetic=synthetic; self.state_path=self.run_root/"campaign-state.private.json"; self.audit_path=self.run_root/"collection-audit.final.json"
    def _markers(self): return [json.loads(p.read_text()) for p in sorted(self.run_root.rglob("provider-invocation.repair.started.json"))]
    def _reconcile(self):
        if not self.state_path.exists(): return
        if self._markers(): raise IntegrityFailure("run root non-resumable after provider marker ambiguity")
        raise IntegrityFailure("incomplete run root cannot be resumed")
    def _invoke(self,block:Path,task:str,condition:str,workspace:Path,feedback:Path|None,state:dict,origin_ref:dict[str,object])->dict:
        label="A" if condition=="A-baseline" else "B"; cell=block/f"cell-{label}"; inputs=cell/"inputs"; inputs.mkdir(parents=True,exist_ok=True)
        spec=inputs/"SPEC.md"; claims=inputs/"CLAIMS_CONTRACT.template.json"; shutil.copy2(REPO_ROOT/"benchmarks"/task/"SPEC.md",spec); shutil.copy2(REPO_ROOT/"benchmarks"/task/"CLAIMS_CONTRACT.template.json",claims)
        manifest=build_cell_manifest(task_id=task,condition=condition,replicate_id=REPLICATE_ID,cell_dir=cell); manifest.update({"run_id":f"{PILOT_ID}-{block.name}-{label}","diagnostic_stage":PILOT_ID,"spec_path":str(spec),"claims_template_path":str(claims),"initial_origin":origin_ref})
        if feedback: manifest["review_feedback_path"]=str(feedback)
        elif condition=="A-baseline" and "review_feedback_path" in manifest: raise IntegrityFailure("A received feedback")
        atomic_write(cell/"cell_manifest.json",manifest)
        if not self.synthetic: cleanup(workspace,str(self.manifest["hermes_command"]))
        invocation_id=f"{block.name}:{condition}:repair-1"; started=cell/"provider-invocation.repair.started.json"; completed=cell/"provider-invocation.repair.completed.json"
        atomic_write(started,{"schema_version":SCHEMA_VERSION,"phase":"repair","invocation_id":invocation_id,"task_id":task,"condition":condition,"initial_provider_call":False,"started_at":utc_now()},exclusive=True); state["repair_calls_started"]+=1; atomic_write(self.state_path,state)
        status="failed"; failure=None
        try:
            result=self.invoker.run_cloned_repair(manifest,cell/"outputs",workspace); row=accounting(result,condition,task); status="succeeded"; return row
        except ClassifiedCellFailure as exc: failure=f"{exc.execution_status}:{exc.classification_reason}"; raise InvocationFailure(failure) from exc
        except Exception as exc: failure=f"{type(exc).__name__}:{exc}"; raise
        finally:
            atomic_write(completed,{"schema_version":SCHEMA_VERSION,"phase":"repair","invocation_id":invocation_id,"task_id":task,"condition":condition,"status":status,"failure":failure,"completed_at":utc_now()},exclusive=True); state["repair_calls_completed"]+=1; atomic_write(self.state_path,state)
            if not self.synthetic: cleanup(workspace,str(self.manifest["hermes_command"]))
    def run(self):
        binding=preflight(self.manifest_path,self.run_root,synthetic=self.synthetic)
        with exclusive_lock(self.run_root/"pilot.lock"):
            self._reconcile(); self.run_root.mkdir(parents=True,exist_ok=True); os.chmod(self.run_root,0o700); atomic_write(self.run_root/"preregistration.frozen.json",self.manifest,exclusive=True)
            state={"schema_version":SCHEMA_VERSION,"status":"collecting","provider_initial_calls":0,"repair_calls_started":0,"repair_calls_completed":0,**binding}; atomic_write(self.state_path,state)
            calibration=[]; block_hashes={}; usage_snapshots=[]
            start_usage=self.usage("calibration:before"); usage_snapshots.append({"phase":"calibration:before","used_percent":start_usage,"captured_at":utc_now()}); atomic_write(self.run_root/"quota-snapshots.private.json",usage_snapshots)
            for i,task in enumerate(CALIBRATION_TASKS,1):
                block=self.run_root/"private-calibration"/f"{PROTOCOL_TAG}-cal-{i:03d}"; workspace=block/"cell-A"/"workspace"; materialize_controlled_start(task_id=task,repo_root=REPO_ROOT,destination=workspace)
                origin={"schema_version":SCHEMA_VERSION,"task_id":task,"solution_hash":compute_solution_hash(workspace),"tree_fingerprint":tree_fingerprint(workspace),"provider_initial_call":False}
                origin_path=block/"initial-origin.json"; atomic_write(origin_path,origin,exclusive=True)
                origin_ref={"path":str(origin_path),"sha256":sha256_file(origin_path),"solution_hash":origin["solution_hash"],"tree_fingerprint":origin["tree_fingerprint"]}
                row={"task_id":task,"condition":"A-baseline",**self._invoke(block,task,"A-baseline",workspace,None,state,origin_ref)}
                # Calibration heldout is deferred until its A repair closes.
                row.update(evaluate_heldout(workspace,task)); row["heldout_valid"]=True; calibration.append(row)
                atomic_write(block/"calibration-result.private.json",{"schema_version":SCHEMA_VERSION,"row":row})
            end_usage=self.usage("calibration:after"); usage_snapshots.append({"phase":"calibration:after","used_percent":end_usage,"captured_at":utc_now()}); atomic_write(self.run_root/"quota-snapshots.private.json",usage_snapshots)
            gate=calibration_admission(calibration); atomic_write(self.run_root/"calibration-gate.private.json",{"schema_version":SCHEMA_VERSION,"decision":gate,"evaluated_anchors":CALIBRATION_CALLS,"decided_at":utc_now()},exclusive=True)
            if gate=="INVALID": raise IntegrityFailure("calibration invalid")
            if gate=="CEILING":
                validate_provider_artifacts(self.run_root,evaluation_admitted=False); state.update(status="ceiling_abort",calibration_decision="CEILING"); atomic_write(self.state_path,state)
                audit={"schema_version":SCHEMA_VERSION,"pilot_id":PILOT_ID,"collection_complete":True,"analysis_authorized":False,"terminal_status":"CEILING","execution_mode":self.manifest["execution_mode"],"provider_initial_calls":0,"repair_calls_started":CALIBRATION_CALLS,"repair_calls_completed":CALIBRATION_CALLS,**binding}; atomic_write(self.audit_path,audit,exclusive=True); return {"status":"CEILING","evaluation_calls":0}
            admitted,projected=quota_admission(start_usage,end_usage); atomic_write(self.run_root/"quota-admission.private.json",{"schema_version":SCHEMA_VERSION,"admitted":admitted,"projected_used_percent":projected,"threshold_percent":76},exclusive=True)
            if not admitted: raise InvocationFailure("quota admission rejected before evaluation")
            for i,(task,order) in enumerate(zip(EVALUATION_TASKS,CONDITION_ORDERS,strict=True),1):
                block=self.run_root/"private-blocks"/f"{PROTOCOL_TAG}-eval-{i:03d}"; seed=block/"controlled-start.private"; materialization=materialize_controlled_start(task_id=task,repo_root=REPO_ROOT,destination=seed)
                origin={"schema_version":SCHEMA_VERSION,"task_id":task,"solution_hash":compute_solution_hash(seed),"tree_fingerprint":tree_fingerprint(seed),"provider_initial_call":False}
                origin_path=block/"initial-origin.json"; atomic_write(origin_path,origin,exclusive=True)
                origin_ref={"path":str(origin_path),"sha256":sha256_file(origin_path),"solution_hash":origin["solution_hash"],"tree_fingerprint":origin["tree_fingerprint"]}
                workspaces={"A-baseline":block/"cell-A"/"workspace","B-agentharness":block/"cell-B"/"workspace"}; fingerprint=clone_pair(seed,*workspaces.values())
                feedback_payload=evaluate_review(seed,task); validate_opaque_feedback(feedback_payload,task_id=task); feedback=block/"cell-B"/"inputs"/"review-feedback.json"; atomic_write(feedback,feedback_payload,exclusive=True); feedback_hash=sha256_file(feedback)
                rows={}
                for condition in order:
                    if tree_fingerprint(workspaces[condition])!=fingerprint: raise IntegrityFailure("clone changed before invocation")
                    if not self.synthetic:
                        current_usage=self.usage(f"evaluation:{task}:{condition}:before")
                        usage_snapshots.append({"phase":f"evaluation:{task}:{condition}:before","used_percent":current_usage,"captured_at":utc_now()})
                        atomic_write(self.run_root/"quota-snapshots.private.json",usage_snapshots)
                        if current_usage>=76.0: raise InvocationFailure("quota threshold reached before evaluation invocation")
                    rows[condition]={"task_id":task,"condition":condition,**self._invoke(block,task,condition,workspaces[condition],feedback if condition=="B-agentharness" else None,state,origin_ref)}
                    if sha256_file(feedback)!=feedback_hash: raise IntegrityFailure("review feedback changed")
                # Heldout is strictly deferred until both repairs have completed.
                for condition in CONDITIONS: rows[condition].update(evaluate_heldout(workspaces[condition],task)); rows[condition]["heldout_valid"]=True
                commit=block/"block-result.commit.json"; atomic_write(commit,{"schema_version":SCHEMA_VERSION,"block_id":block.name,"task_id":task,"initial_origin_sha256":origin_ref["sha256"],"initial_solution_hash":origin["solution_hash"],"controlled_start":materialization,"clone_fingerprint":fingerprint,"cells":[rows[c] for c in CONDITIONS]},exclusive=True); block_hashes[block.name]=sha256_file(commit)
            validate_provider_artifacts(self.run_root,evaluation_admitted=True)
            if state["repair_calls_started"]!=MAXIMUM_CALLS or state["repair_calls_completed"]!=MAXIMUM_CALLS: raise IntegrityFailure("exact provider accounting failed")
            marker_hashes={p.relative_to(self.run_root).as_posix():sha256_file(p) for p in sorted(self.run_root.rglob("provider-invocation.repair.*.json"))}
            if len(marker_hashes)!=2*MAXIMUM_CALLS: raise IntegrityFailure("marker audit roster invalid")
            calibration_hashes={p.relative_to(self.run_root).as_posix():sha256_file(p) for p in sorted((self.run_root/"private-calibration").glob(f"{PROTOCOL_TAG}-cal-*/calibration-result.private.json"))}
            audit={"schema_version":SCHEMA_VERSION,"pilot_id":PILOT_ID,"collection_complete":True,"analysis_authorized":self.manifest["execution_mode"]=="real" and not self.synthetic,"terminal_status":"collection_complete","execution_mode":self.manifest["execution_mode"],"provider_initial_calls":0,"repair_calls_started":MAXIMUM_CALLS,"repair_calls_completed":MAXIMUM_CALLS,"block_commit_sha256":block_hashes,"calibration_result_sha256":calibration_hashes,"provider_marker_sha256":marker_hashes,"quota_snapshots_sha256":sha256_file(self.run_root/"quota-snapshots.private.json"),"calibration_gate_sha256":sha256_file(self.run_root/"calibration-gate.private.json"),"quota_admission_sha256":sha256_file(self.run_root/"quota-admission.private.json"),**binding}; atomic_write(self.audit_path,audit,exclusive=True); state.update(status="collection_complete",calibration_decision="ADMIT"); atomic_write(self.state_path,state); return {"status":"collection_complete","evaluation_calls":EVALUATION_CALLS}

def finalize(*,manifest_path:Path,run_root:Path):
    manifest_path=manifest_path.resolve(); run_root=run_root.resolve(); m=json.loads(manifest_path.read_text()); validate_manifest_shape(m)
    if m.get("execution_mode")!="real": raise IntegrityFailure("production finalizer rejects qualification artifacts")
    payload=dict(m); expected=payload.pop("manifest_payload_sha256",None)
    if canonical_hash(payload)!=expected or m.get("repository_commit")!=git("rev-parse","HEAD") or git("status","--porcelain","--untracked-files=all"): raise IntegrityFailure("production finalizer requires clean bound HEAD")
    for rel,digest in m["frozen_file_sha256"].items():
        if sha256_file(REPO_ROOT/rel)!=digest: raise IntegrityFailure(f"finalizer frozen file mismatch:{rel}")
    frozen=run_root/"preregistration.frozen.json"; audit_path=run_root/"collection-audit.final.json"; state_path=run_root/"campaign-state.private.json"
    if not frozen.is_file() or sha256_file(frozen)!=sha256_file(manifest_path) or not audit_path.is_file() or not state_path.is_file(): raise IntegrityFailure("collection binding missing")
    audit=json.loads(audit_path.read_text()); state=json.loads(state_path.read_text())
    if any((audit.get("schema_version")!=SCHEMA_VERSION,audit.get("pilot_id")!=PILOT_ID,audit.get("collection_complete") is not True,audit.get("analysis_authorized") is not True,audit.get("terminal_status")!="collection_complete",audit.get("execution_mode")!="real",audit.get("provider_initial_calls")!=0,audit.get("repair_calls_started")!=MAXIMUM_CALLS,audit.get("repair_calls_completed")!=MAXIMUM_CALLS,audit.get("manifest_file_sha256")!=sha256_file(manifest_path),audit.get("repository_commit")!=m["repository_commit"],state.get("status")!="collection_complete",state.get("calibration_decision")!="ADMIT")):
        raise IntegrityFailure("green production audit required")
    validate_provider_artifacts(run_root,evaluation_admitted=True)
    observed={p.relative_to(run_root).as_posix():sha256_file(p) for p in sorted(run_root.rglob("provider-invocation.repair.*.json"))}
    if observed!=audit.get("provider_marker_sha256"): raise IntegrityFailure("marker audit binding mismatch")
    for name,key in (("quota-snapshots.private.json","quota_snapshots_sha256"),("calibration-gate.private.json","calibration_gate_sha256"),("quota-admission.private.json","quota_admission_sha256")):
        if sha256_file(run_root/name)!=audit.get(key): raise IntegrityFailure(f"audit binding mismatch:{name}")
    calibration_paths=sorted((run_root/"private-calibration").glob(f"{PROTOCOL_TAG}-cal-*/calibration-result.private.json"))
    calibration_hashes={p.relative_to(run_root).as_posix():sha256_file(p) for p in calibration_paths}
    calibration_rows=[json.loads(p.read_text()).get("row") for p in calibration_paths]
    gate=json.loads((run_root/"calibration-gate.private.json").read_text()); quota=json.loads((run_root/"quota-admission.private.json").read_text()); snapshots=json.loads((run_root/"quota-snapshots.private.json").read_text())
    if calibration_hashes!=audit.get("calibration_result_sha256") or calibration_admission(calibration_rows)!="ADMIT" or gate.get("decision")!="ADMIT" or gate.get("evaluated_anchors")!=CALIBRATION_CALLS:
        raise IntegrityFailure("calibration admission binding invalid")
    if not isinstance(snapshots,list) or len(snapshots)!=2+EVALUATION_CALLS or snapshots[0].get("phase")!="calibration:before" or snapshots[1].get("phase")!="calibration:after":
        raise IntegrityFailure("quota snapshot roster invalid")
    admitted,projected=quota_admission(snapshots[0].get("used_percent"),snapshots[1].get("used_percent"))
    evaluation_usage=[x.get("used_percent") for x in snapshots[2:]]
    if admitted is not True or quota.get("admitted") is not True or quota.get("threshold_percent")!=76 or quota.get("projected_used_percent")!=projected or any(type(x) not in (int,float) or not 0<=x<76 for x in evaluation_usage):
        raise IntegrityFailure("quota admission semantics invalid")
    expected_blocks={f"{PROTOCOL_TAG}-eval-{i:03d}" for i in range(1,len(EVALUATION_TASKS)+1)}
    if set(audit.get("block_commit_sha256",{}))!=expected_blocks: raise IntegrityFailure("block audit roster invalid")
    rows=[]
    for i,task in enumerate(EVALUATION_TASKS,1):
        block_id=f"{PROTOCOL_TAG}-eval-{i:03d}"; block=run_root/"private-blocks"/block_id; path=block/"block-result.commit.json"
        if not path.is_file() or sha256_file(path)!=audit["block_commit_sha256"][block_id]: raise IntegrityFailure("block audit mismatch")
        commit=json.loads(path.read_text()); cells=commit.get("cells")
        if commit.get("schema_version")!=SCHEMA_VERSION or commit.get("block_id")!=block_id or commit.get("task_id")!=task or not isinstance(cells,list) or len(cells)!=2 or {x.get("condition") for x in cells if isinstance(x,Mapping)}!=set(CONDITIONS): raise IntegrityFailure("block semantic binding invalid")
        materialization=commit.get("controlled_start"); seed=block/"controlled-start.private"; origin_path=block/"initial-origin.json"
        if not isinstance(materialization,Mapping) or materialization.get("task_id")!=task or materialization.get("agent_visible_leakage")!=[] or tree_fingerprint(seed)!=materialization.get("controlled_fingerprint") or commit.get("clone_fingerprint")!=materialization.get("controlled_fingerprint") or sha256_file(origin_path)!=commit.get("initial_origin_sha256") or compute_solution_hash(seed)!=commit.get("initial_solution_hash"):
            raise IntegrityFailure("controlled start binding invalid")
        for cell in cells:
            if any(cell.get(k) is not True for k in ("invocation_valid","heldout_valid","target_evaluated","guards_evaluated")): raise IntegrityFailure("cell validity binding invalid")
            if cell.get("task_id")!=task: raise IntegrityFailure("cell task binding invalid")
            if cell.get("condition")=="B-agentharness" and any(cell.get(k) is not True for k in ("feedback_delivered","feedback_immutable","feedback_accounted")): raise IntegrityFailure("B treatment binding invalid")
            if cell.get("condition")=="A-baseline" and cell.get("feedback_delivered") is not False: raise IntegrityFailure("A treatment contamination")
        rows.extend(cells)
    result=finalize_results(rows)
    if result["verdict"]=="INVALID": raise IntegrityFailure(str(result.get("reason")))
    result["collection_audit_sha256"]=sha256_file(audit_path); atomic_write(run_root/RESULT_FILENAME,result,exclusive=True); return result

def main():
    p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,default=TEMPLATE_PATH); p.add_argument("--run-root",type=Path); p.add_argument("--freeze-output",type=Path); p.add_argument("--finalize",action="store_true"); p.add_argument("--preflight",action="store_true"); p.add_argument("--synthetic",action="store_true"); args=p.parse_args()
    try:
        if args.freeze_output: print(json.dumps(freeze_manifest(args.manifest,args.freeze_output,execution_mode="qualification" if args.synthetic else "real"),indent=2)); return 0
        if not args.run_root: raise IntegrityFailure("--run-root required")
        if args.finalize: print(json.dumps(finalize(manifest_path=args.manifest,run_root=args.run_root),indent=2)); return 0
        if args.preflight: print(json.dumps(preflight(args.manifest,args.run_root,synthetic=args.synthetic),indent=2)); return 0
        m=json.loads(args.manifest.read_text()); invoker=SyntheticRepairInvoker() if args.synthetic else HermesCliInvoker(hermes_command=m["hermes_command"],toolsets=m["toolsets"],max_retries=1,provider=m["provider"],model=m["model"],max_turns=int(m["max_turns"]),sandbox_cleanup_arg="--sandbox-cleanup")
        print(json.dumps(V4Pilot(args.manifest,args.run_root,invoker=invoker,usage=synthetic_usage if args.synthetic else real_usage,synthetic=args.synthetic).run(),indent=2)); return 0
    except V4Error as exc: print(json.dumps({"verdict":"INVALID","reason":str(exc)}),file=sys.stderr); return exc.exit_code
    except Exception as exc: traceback.print_exc(); print(json.dumps({"verdict":"INVALID","reason":f"unexpected:{type(exc).__name__}"}),file=sys.stderr); return 50
if __name__=="__main__": raise SystemExit(main())
