#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
BENCH=ROOT/"benchmarks"
OUT=BENCH/"grading-env"/"task-expansion-batch2"
TASK_CHECKS={
 "dependency-impact-planner":["dependency_reverse_impact","dependency_parallel_levels","dependency_deterministic_output","dependency_graph_validation","dependency_cycle_atomic"],
 "access-policy-evaluator":["policy_wildcard_matching","policy_subject_group_composition","policy_deny_default_precedence","policy_temporal_validity","policy_rejections_determinism"],
 "versioned-document-api":["document_create_etag_persistence","document_if_match_atomic","document_merge_patch","document_revision_history","document_restore_history"],
 "safe-archive-extraction":["archive_extract_manifest","archive_path_containment_atomic","archive_special_entry_rejection","archive_collision_atomic","archive_limits_corruption_atomic"],
}
PRIOR_TASKS=["support-ticket-api","csv-member-import","incident-escalation-api","inventory-adjustment-api","leave-request-api","refund-approval-api","report-export-job","webhook-ingestion-service","appointment-booking-api","shipment-event-api","jsonl-event-aggregation","invoice-payment-reconciliation"]
NEW_CONSTRUCTS={
 "dependency-impact-planner":"reverse graph closure, topological parallel levels, cycle rejection, and canonical offline planning",
 "access-policy-evaluator":"stateless wildcard policy matching, subject/group composition, deny precedence, and request-supplied temporal validity",
 "versioned-document-api":"generic JSON revision history, RFC 7396 merge patch, ETag compare-and-swap, and restore-as-new-revision",
 "safe-archive-extraction":"adversarial ZIP metadata validation, filesystem containment, namespace collision preflight, and atomic materialization",
}
NEAREST={
 "dependency-impact-planner":("jsonl-event-aggregation",{
  "dependency_reverse_impact":"reverse transitive graph closure rather than grouped record aggregation","dependency_parallel_levels":"topological parallel layers rather than sorted output groups","dependency_deterministic_output":"canonical graph plans under equivalent graph order rather than stream aggregation order","dependency_graph_validation":"referential graph integrity rather than per-line record validation","dependency_cycle_atomic":"cycle impossibility with no partial plan rather than malformed-line rejection"}),
 "access-policy-evaluator":("refund-approval-api",{
  "policy_wildcard_matching":"pattern-based action/resource interpretation rather than numeric approval routing","policy_subject_group_composition":"stateless subject/group rule composition rather than persisted workflow roles","policy_deny_default_precedence":"deny-overrides policy algebra rather than approval-state transitions","policy_temporal_validity":"request-supplied temporal rule windows rather than workflow timestamps","policy_rejections_determinism":"mixed valid/invalid policy request streaming rather than CRUD error responses"}),
 "versioned-document-api":("shipment-event-api",{
  "document_create_etag_persistence":"durable generic JSON revision plus ETag rather than shipment creation/state","document_if_match_atomic":"optimistic compare-and-swap rather than event idempotency","document_merge_patch":"RFC 7396 structural merge rather than domain event projection","document_revision_history":"immutable full JSON snapshots rather than shipment event history","document_restore_history":"historical snapshot restored as a new revision rather than lifecycle reversal"}),
 "safe-archive-extraction":("csv-member-import",{
  "archive_extract_manifest":"binary ZIP extraction with cryptographic content manifest rather than CSV row import","archive_path_containment_atomic":"adversarial filesystem path containment rather than field validation","archive_special_entry_rejection":"ZIP metadata type safety rather than data-record typing","archive_collision_atomic":"normalized filesystem namespace collision preflight rather than duplicate member records","archive_limits_corruption_atomic":"archive resource limits and binary corruption handling rather than row rejection"}),
}
PAIRWISE=[
 {"left":"dependency-impact-planner","right":"access-policy-evaluator","shared_shell":"deterministic JSON CLI","substantive_difference":"graph closure/topological layers versus policy matching and deny precedence"},
 {"left":"dependency-impact-planner","right":"versioned-document-api","shared_shell":"JSON validation and atomic failure","substantive_difference":"offline graph planning versus durable optimistic-concurrency revision service"},
 {"left":"dependency-impact-planner","right":"safe-archive-extraction","shared_shell":"preflight validation before artifact commit","substantive_difference":"graph semantics and cycles versus adversarial ZIP/filesystem containment"},
 {"left":"access-policy-evaluator","right":"versioned-document-api","shared_shell":"JSON objects and controlled invalid handling","substantive_difference":"stateless rule interpretation versus mutable versioned persistence with ETags"},
 {"left":"access-policy-evaluator","right":"safe-archive-extraction","shared_shell":"deterministic CLI outputs","substantive_difference":"authorization decision algebra versus binary archive and filesystem safety"},
 {"left":"versioned-document-api","right":"safe-archive-extraction","shared_shell":"atomic mutation/commit guarantees","substantive_difference":"revision-preserving online writes versus all-or-nothing filesystem materialization"},
]
ALLOW={"SPEC.md","CLAIMS_CONTRACT.template.json","HELDOUT_EVALUATION_SUITE.template.json","QUALITY_GATE.md"}
FORBIDDEN_NAMES={"__pycache__",".pytest_cache",".agentharness","evaluation","hidden-evaluator"}
FORBIDDEN_TEXT={"A-baseline","B-agentharness","treatment_not_delivered","AGENTHARNESS_MUTANT","expected hidden output"}

def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def result(ok:bool,detail:str)->dict[str,Any]: return {"ok":bool(ok),"detail":detail}
def objective(path:Path)->str:
 text=path.read_text()
 if "## Objective" in text: return text.split("## Objective",1)[1].split("##",1)[0].strip()
 return next((line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")),path.parent.name)

def static_audit():
 sensitivity=json.loads((OUT/"MUTATION_SENSITIVITY.json").read_text())["tasks"]; checks={}; hashes={}
 for task,ids in TASK_CHECKS.items():
  folder=BENCH/task; files={p.name for p in folder.iterdir() if p.is_file()}; visible="\n".join((folder/n).read_text(errors="replace") for n in sorted(files))
  suite=json.loads((folder/"HELDOUT_EVALUATION_SUITE.template.json").read_text()); claims=json.loads((folder/"CLAIMS_CONTRACT.template.json").read_text())
  cases=suite.get("cases",[]); sens=sensitivity.get(task,{})
  bad_nodes=[str(p.relative_to(folder)) for p in folder.rglob("*") if p.name in FORBIDDEN_NAMES or p.is_symlink()]
  task_checks={
   "visible_allowlist":result(files==ALLOW,str(sorted(files))),
   "five_plus_schema":result(len(cases)==6 and sum(x.get("kind")=="functional" for x in cases)==5 and cases[-1].get("case_id")=="evaluation_result_schema",str([x.get("case_id") for x in cases])),
   "claims_process_only":result({x.get("claim_type") for x in claims.get("claims",[])}<={"forbidden_paths","tests_executed","artifact_present"},"process claims only"),
   "hidden_ids_absent":result(not any(x in visible for x in ids),"functional IDs absent from visible bundle"),
   "forbidden_text_absent":result(not any(x.lower() in visible.lower() for x in FORBIDDEN_TEXT),"no treatment/evaluator leakage"),
   "clean_tree":result(not bad_nodes,str(bad_nodes)),
   "sensitivity_complete":result(set(sens)==set(ids) and all(v.get("expected_failed_checks")==[k] and v.get("rationale") for k,v in sens.items()),f"mutants={len(sens)}"),
   "hidden_reference_present":result((OUT/"references"/task/"pyproject.toml").is_file() and (OUT/"references"/task/"README.md").is_file(),str(OUT/"references"/task)),
   "nearest_overlap_complete":result(set(NEAREST[task][1])==set(ids),NEAREST[task][0]),
  }
  checks[task]=task_checks
 expected={tuple(sorted(x)) for x in itertools.combinations(TASK_CHECKS,2)}; observed={tuple(sorted((x["left"],x["right"]))) for x in PAIRWISE}
 prior_objectives={task:objective(BENCH/task/"SPEC.md") for task in PRIOR_TASKS}
 cross=[{"new_task":task,"prior_task":prior,"new_construct":NEW_CONSTRUCTS[task],"prior_objective":prior_objectives[prior],"substantive_difference":f"{NEW_CONSTRUCTS[task]}; unlike the prior task objective: {prior_objectives[prior]}"} for task in TASK_CHECKS for prior in PRIOR_TASKS]
 expected_cross={(new,prior) for new in TASK_CHECKS for prior in PRIOR_TASKS}; observed_cross={(x["new_task"],x["prior_task"]) for x in cross}
 checks["_batch"]={
  "pairwise_complete":result(observed==expected and len(PAIRWISE)==6 and all(x["shared_shell"] and x["substantive_difference"] for x in PAIRWISE),str(sorted(observed))),
  "all_prior_overlap_complete":result(observed_cross==expected_cross and len(cross)==48 and all(x["substantive_difference"] for x in cross),f"pairs={len(cross)}"),
 }
 bases=[*(BENCH/t for t in TASK_CHECKS),ROOT/"src/agentharness/benchmark_hidden_evaluators.py",ROOT/"src/agentharness/benchmark_hidden_evaluators_batch2.py",ROOT/"benchmarks/grading-env/audit_task_expansion_batch2.py",ROOT/"tests/test_task_expansion_batch2.py",OUT/"MUTATION_SENSITIVITY.json",OUT/"references"]
 for base in bases:
  paths=[base] if base.is_file() else [p for p in base.rglob("*") if p.is_file() and p.suffix!=".pyc" and p.name not in FORBIDDEN_NAMES]
  for p in sorted(paths): hashes[str(p.relative_to(ROOT))]=sha(p)
 return checks,hashes,cross

def dynamic():
 command=[sys.executable,"-m","pytest","-q","tests/test_task_expansion_batch2.py"]; env=dict(os.environ); env["PYTHONPATH"]="src"
 done=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=900)
 return {"ok":done.returncode==0,"command":"PYTHONPATH=src "+" ".join(command),"python_executable":sys.executable,"python_version":sys.version,"exit_code":done.returncode,"stdout":done.stdout,"stderr":done.stderr}

def main()->int:
 parser=argparse.ArgumentParser(); parser.add_argument("--run-tests",action="store_true"); args=parser.parse_args(); static,hashes,cross=static_audit(); static_ok=all(v["ok"] for group in static.values() for v in group.values()); dyn=dynamic() if args.run_tests else {"ok":False,"command":"not run","exit_code":None,"stdout":"","stderr":"dynamic tests required"}
 overlap=[{"task_id":task,"check_id":check,"nearest_existing_task":NEAREST[task][0],"substantive_difference":difference} for task in TASK_CHECKS for check,difference in NEAREST[task][1].items()]
 commit=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
 payload={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"base_commit":commit,"efficacy_cells_collected":0,"task_ids":list(TASK_CHECKS),"static_checks":static,"dynamic_tests":dyn,"overlap_matrix":overlap,"all_prior_overlap_matrix":cross,"new_task_pairwise_overlap":PAIRWISE,"artifact_sha256":hashes,"go":bool(static_ok and dyn["ok"]),"authorization":"task-pack acceptance only; no A/B or confirmatory launch"}
 OUT.mkdir(parents=True,exist_ok=True); (OUT/"TASK_EXPANSION_BATCH2_ACCEPTANCE.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
 lines=["# Task Expansion Batch 2 Acceptance","",f"- Generated: {payload['generated_at']}",f"- Base commit: `{commit}`",f"- Overall: **{'GO' if payload['go'] else 'NO-GO'}**","- Efficacy cells collected: **0**","","## Dynamic validation",dyn["stdout"].strip(),"","## Boundary","Task-pack acceptance only. No A/B run is authorized.",""]
 (OUT/"TASK_EXPANSION_BATCH2_ACCEPTANCE.md").write_text("\n".join(lines)); print(json.dumps({"go":payload["go"],"static_ok":static_ok,"dynamic_ok":dyn["ok"],"report":str(OUT/"TASK_EXPANSION_BATCH2_ACCEPTANCE.json")},indent=2)); return 0 if payload["go"] else 1
if __name__=="__main__": raise SystemExit(main())
