from __future__ import annotations

import importlib.util, json, tempfile
from types import SimpleNamespace
from pathlib import Path
import pytest

import agentharness.benchmark_heldout_evaluator_v4 as heldout_v4
from agentharness.benchmark_heldout_evaluator_v4 import evaluate_heldout
from agentharness.benchmark_review_evaluator_v4 import evaluate_review
from agentharness.efficacy_v4 import CALIBRATION_TASKS, CONDITION_ORDERS, CONDITIONS, EVALUATION_TASKS, TASKS, calibration_admission, canonical_hash, finalize_results, leakage_scan, materialize_clean_reference, materialize_controlled_start, quota_admission, validate_marker_accounting, validate_opaque_feedback

REPO=Path(__file__).resolve().parents[1]; RUNNER=REPO/"benchmarks/grading-env/run_mechanism_first_v4.py"; TEMPLATE=REPO/"benchmarks/grading-env/MECHANISM_FIRST_V4_PREREG.template.json"
SPEC=importlib.util.spec_from_file_location("v4_runner",RUNNER); assert SPEC and SPEC.loader
runner=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(runner)

def frozen(path:Path)->Path:
    m=json.loads(TEMPLATE.read_text()); m.update(preregistration_status="frozen",frozen_at="test",repository_commit=runner.git("rev-parse","HEAD"),execution_mode="qualification")
    for rel in m["frozen_file_sha256"]: m["frozen_file_sha256"][rel]=runner.sha256_file(REPO/rel)
    m["hermes_command_sha256"]=runner.sha256_file(Path(m["hermes_command"])); m.pop("manifest_payload_sha256",None); m["manifest_payload_sha256"]=canonical_hash(m); runner.atomic_write(path,m,exclusive=True); return path

def endpoint(task:str,condition:str,passed:bool=True):
    return {"task_id":task,"condition":condition,"invocation_valid":True,"heldout_valid":True,"target_evaluated":True,"guards_evaluated":True,"target_passed":passed,"guards_passed":True,"feedback_delivered":condition=="B-agentharness","feedback_immutable":True,"feedback_accounted":True}

def test_manifest_protocol_is_frozen_and_counterbalanced():
    m=json.loads(TEMPLATE.read_text()); runner.validate_manifest_shape(m)
    assert [tuple(x["condition_order"]) for x in m["evaluation_blocks"]]==list(CONDITION_ORDERS)
    assert sum(order[0]=="A-baseline" for order in CONDITION_ORDERS)==3
    assert m["maximum_provider_calls"]==14 and m["expected_initial_provider_calls"]==0

def test_eight_references_green_and_controlled_exact_target_failure_guards_green():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for task in TASKS:
            clean=root/f"{task}-clean"; controlled=root/f"{task}-controlled"
            materialize_clean_reference(task_id=task,repo_root=REPO,destination=clean)
            materialize_controlled_start(task_id=task,repo_root=REPO,destination=controlled)
            assert leakage_scan(clean)==leakage_scan(controlled)==[]
            assert evaluate_heldout(clean,task)["binary_endpoint"]==1
            got=evaluate_heldout(controlled,task)
            assert got["target_passed"] is False and got["guards_passed"] is True
            if task in EVALUATION_TASKS:
                feedback=evaluate_review(controlled,task); assert validate_opaque_feedback(feedback,task_id=task).startswith("finding-v4-")

def test_forbidden_leakage_tokens_are_absent():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/"controlled"; materialize_controlled_start(task_id=TASKS[0],repo_root=REPO,destination=root)
        text="\n".join(p.read_text(errors="ignore") for p in root.rglob("*") if p.is_file()).lower()
        assert "mutant" not in text and "agentharness_mutant" not in text and "dependency_reverse_impact" not in text

def test_calibration_gate_thresholds_quota_and_exact_markers():
    rows=[endpoint(task,"A-baseline",True) for task in CALIBRATION_TASKS]
    assert calibration_admission(rows)=="CEILING"; rows[0]["target_passed"]=False; assert calibration_admission(rows)=="ADMIT"
    assert quota_admission(70,70)==(True,76.0); assert quota_admission(70.1,70.1)[0] is False
    with pytest.raises(ValueError,match="telemetry"): quota_admission(30,20)
    markers=[{"phase":"repair","initial_provider_call":False,"task_id":t,"condition":"A-baseline"} for t in CALIBRATION_TASKS]
    validate_marker_accounting(markers,evaluation_admitted=False)
    markers += [{"phase":"repair","initial_provider_call":False,"task_id":t,"condition":c} for t in EVALUATION_TASKS for c in CONDITIONS]
    validate_marker_accounting(markers,evaluation_admitted=True); assert len(markers)==14

def test_finalizer_thresholds_invalid_and_no_subset_analysis():
    rows=[endpoint(t,c,c=="B-agentharness") for t in EVALUATION_TASKS for c in CONDITIONS]
    result=finalize_results(rows); assert result["verdict"]=="GO" and result["b_gt_a"]==6
    rows[0]["target_passed"]=True; rows[1]["target_passed"]=False; assert finalize_results(rows)["verdict"]=="NO-GO"
    assert finalize_results(rows[:-1])=={"schema_version":4,"verdict":"INVALID","reason":"cell_roster_incomplete"}
    rows=[endpoint(t,c,c=="B-agentharness") for t in EVALUATION_TASKS for c in CONDITIONS]; next(x for x in rows if x["condition"]=="B-agentharness")["guards_passed"]=False
    assert finalize_results(rows)["verdict"]=="NO-GO"
    rows=[endpoint(t,c,c=="B-agentharness") for t in EVALUATION_TASKS for c in CONDITIONS]
    pair=[x for x in rows if x["task_id"]==EVALUATION_TASKS[-1]]
    for row in pair: row["guards_passed"]=False
    assert finalize_results(rows)["verdict"]=="NO-GO"

def test_heldout_crash_fails_closed(monkeypatch):
    monkeypatch.setattr(heldout_v4,"_evaluate",lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with tempfile.TemporaryDirectory() as td:
        workspace=Path(td)/"w"; materialize_controlled_start(task_id=TASKS[0],repo_root=REPO,destination=workspace)
        with pytest.raises(ValueError,match="heldout_evaluator_invalid"): evaluate_heldout(workspace,TASKS[0])

def test_duplicate_evaluator_ids_and_non_boolean_endpoints_fail_closed(monkeypatch):
    task=TASKS[0]
    observations=[SimpleNamespace(id=check_id,status="pass") for check_id in heldout_v4.CHECK_ROSTERS[task]]
    observations.append(SimpleNamespace(id=observations[0].id,status="fail"))
    monkeypatch.setattr(heldout_v4,"evaluate_batch2_task",lambda *_:SimpleNamespace(execution_status="valid",observations=observations))
    with pytest.raises(ValueError,match="duplicate_check_id"): heldout_v4._evaluate(Path("/unused"),task)
    rows=[endpoint(t,c,c=="B-agentharness") for t in EVALUATION_TASKS for c in CONDITIONS]; rows[1]["target_passed"]="false"
    assert finalize_results(rows)=={"schema_version":4,"verdict":"INVALID","reason":"endpoint_type_invalid"}

def _fast_orchestration(monkeypatch,run_root:Path,calibration_repairs:int,usage_end:float=10):
    original=runner.evaluate_heldout
    events=[]
    def fake_heldout(workspace,task):
        events.append(("heldout",task))
        if task in CALIBRATION_TASKS: passed=CALIBRATION_TASKS.index(task)<calibration_repairs
        else: passed="cell-B" in workspace.as_posix()
        return {"target_evaluated":True,"guards_evaluated":True,"target_passed":passed,"guards_passed":True,"binary_endpoint":int(passed)}
    def fake_review(workspace,task): return runner.evaluate_review.__wrapped__(workspace,task) if hasattr(runner.evaluate_review,"__wrapped__") else __import__("agentharness.efficacy_v4",fromlist=["opaque_review_feedback"]).opaque_review_feedback(task,"A local invariant violation was reproduced.")
    monkeypatch.setattr(runner,"evaluate_heldout",fake_heldout); monkeypatch.setattr(runner,"evaluate_review",fake_review)
    values=iter([10.0,usage_end]); usage=lambda _:next(values)
    manifest=frozen(run_root.parent/"frozen.json"); invoker=runner.SyntheticRepairInvoker(calibration_repairs=calibration_repairs)
    result=runner.V4Pilot(manifest,run_root,invoker=invoker,usage=usage,synthetic=True).run()
    return result,invoker,events,manifest

def test_calibration_two_of_two_aborts_with_zero_evaluation_invocations(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); result,invoker,events,_=_fast_orchestration(monkeypatch,root/"run",2)
        assert result=={"status":"CEILING","evaluation_calls":0}; assert len(invoker.calls)==2
        assert all(task in CALIBRATION_TASKS for task,_ in invoker.calls)

def test_admission_exactly_twelve_evaluation_calls_fourteen_markers_and_heldout_deferred(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); run=root/"run"; result,invoker,events,manifest=_fast_orchestration(monkeypatch,run,1)
        assert result["evaluation_calls"]==12 and len(invoker.calls)==14
        assert len(list(run.rglob("provider-invocation.repair.started.json")))==14 and len(list(run.rglob("provider-invocation.repair.completed.json")))==14
        for i,task in enumerate(EVALUATION_TASKS,1):
            block=run/"private-blocks"/f"v4-eval-{i:03d}"
            assert len(list(block.glob("cell-*/provider-invocation.repair.completed.json")))==2
            for manifest_path in block.glob("cell-*/cell_manifest.json"):
                manifest_payload=json.loads(manifest_path.read_text()); origin=manifest_payload["initial_origin"]
                assert origin["solution_hash"] and origin["tree_fingerprint"] and runner.sha256_file(Path(origin["path"]))==origin["sha256"]
        assert not (run/"MECHANISM_FIRST_V4_RESULT.json").exists()
        with pytest.raises(runner.IntegrityFailure,match="rejects qualification"): runner.finalize(manifest_path=manifest,run_root=run)
        for path in run.glob("private-blocks/*/cell-B/inputs/review-feedback.json"): assert path.stat().st_mode & 0o777==0o600
        assert not list(run.glob("private-blocks/*/cell-A/**/*feedback*"))

def test_quota_rejection_has_no_evaluation_calls(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        with pytest.raises(runner.InvocationFailure,match="quota admission"):
            _fast_orchestration(monkeypatch,root/"run",1,75)
        assert not list((root/"run").glob("private-blocks/*/cell-*/provider-invocation.repair.started.json"))

def test_nonresumable_and_no_overwrite_outputs():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); state=root/"campaign-state.private.json"; runner.atomic_write(state,{"status":"collecting"}); marker=root/"x/provider-invocation.repair.started.json"; runner.atomic_write(marker,{"phase":"repair"})
        pilot=object.__new__(runner.V4Pilot); pilot.run_root=root; pilot.state_path=state
        with pytest.raises(runner.IntegrityFailure,match="non-resumable"): pilot._reconcile()
        target=root/"immutable.json"; runner.atomic_write(target,{"a":1},exclusive=True)
        with pytest.raises(FileExistsError): runner.atomic_write(target,{"a":2},exclusive=True)
        assert json.loads(target.read_text())=={"a":1}

def test_provider_artifact_pairing_and_success_are_fail_closed():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for index,task in enumerate(CALIBRATION_TASKS,1):
            cell=root/f"cal-{index}"; invocation=f"v4-cal-{index:03d}:A-baseline:repair-1"
            common={"schema_version":4,"phase":"repair","invocation_id":invocation,"task_id":task,"condition":"A-baseline"}
            runner.atomic_write(cell/"provider-invocation.repair.started.json",{**common,"initial_provider_call":False})
            runner.atomic_write(cell/"provider-invocation.repair.completed.json",{**common,"status":"succeeded","failure":None})
        runner.validate_provider_artifacts(root,evaluation_admitted=False)
        completed=next(root.rglob("provider-invocation.repair.completed.json")); payload=json.loads(completed.read_text()); payload["status"]="failed"; runner.atomic_write(completed,payload)
        with pytest.raises(runner.IntegrityFailure,match="not successful"): runner.validate_provider_artifacts(root,evaluation_admitted=False)

def test_qualification_freeze_path_and_production_rejection(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        output=Path(td)/"frozen.json"
        monkeypatch.setattr(runner,"git",lambda *args: "" if args[0]=="status" else "head")
        runner.freeze_manifest(TEMPLATE,output,execution_mode="qualification")
        assert json.loads(output.read_text())["execution_mode"]=="qualification"
        with pytest.raises(runner.IntegrityFailure,match="rejects qualification"): runner.finalize(manifest_path=output,run_root=Path(td)/"run")
