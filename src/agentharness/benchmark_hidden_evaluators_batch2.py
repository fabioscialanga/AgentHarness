from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .benchmark_hidden_evaluators import (
    HiddenEvaluationObservation,
    HiddenEvaluationResult,
    _evaluation_dir,
    _finalize_hidden_evaluation,
    _interface_unreachable_result,
    _load_fastapi_app,
    _make_test_client,
    _run_python_entrypoint,
    _working_directory,
)
from .benchmark_hidden_evaluators_batch1 import (
    _cross_process_request,
    _identifier,
    _json_payload,
    _read_json,
    _read_jsonl,
    _recorder,
)


def evaluate_batch2_task(workspace: Path, task_id: str) -> HiddenEvaluationResult:
    evaluators: dict[str, Callable[[Path], HiddenEvaluationResult]] = {
        "dependency-impact-planner": _evaluate_dependency,
        "access-policy-evaluator": _evaluate_policy,
        "versioned-document-api": _evaluate_documents,
        "safe-archive-extraction": _evaluate_archive,
    }
    if task_id not in evaluators:
        raise ValueError(f"unsupported batch2 task: {task_id}")
    return evaluators[task_id](workspace)


def _finish_runtime(task_id: str, workspace: Path, check_ids: tuple[str, ...], observations: list[HiddenEvaluationObservation], passed: list[str], failed: list[str], record: Callable[[str, bool, str], None], exc: Exception) -> HiddenEvaluationResult:
    seen = {item.id for item in observations}
    for check_id in check_ids:
        if check_id not in seen:
            record(check_id, False, f"runtime evaluation failed: {exc}")
    return _finalize_hidden_evaluation(task_id=task_id, evaluation_dir=_evaluation_dir(workspace, task_id), passed_checks=passed, failed_checks=failed, observations=observations)


def _evaluate_dependency(workspace: Path) -> HiddenEvaluationResult:
    task_id = "dependency-impact-planner"
    checks = ("dependency_graph_validation", "dependency_reverse_impact", "dependency_parallel_levels", "dependency_deterministic_output", "dependency_cycle_atomic")
    observations, passed, failed, record = _recorder()
    candidates = ["app/plan_dependencies.py", "plan_dependencies.py", "src/app/plan_dependencies.py"]
    try:
        with tempfile.TemporaryDirectory(prefix="ah-dependency-") as tmp:
            root = Path(tmp)
            graph = {"components": [
                {"id": "api", "depends_on": ["core"]}, {"id": "core", "depends_on": []},
                {"id": "worker", "depends_on": ["core"]}, {"id": "ui", "depends_on": ["api"]},
                {"id": "docs", "depends_on": []}, {"id": "ops", "depends_on": ["worker", "api"]},
            ]}
            manifest, changed = root / "graph.json", root / "changed.json"
            manifest.write_text(json.dumps(graph), encoding="utf-8"); changed.write_text('["core","docs"]', encoding="utf-8")
            out1, out2 = root / "out1", root / "out2"
            run1 = _run_python_entrypoint(workspace, candidates, ["--manifest", str(manifest), "--changed", str(changed), "--out-dir", str(out1)], env={"PYTHONHASHSEED": "17"})
            if run1.returncode != 0: raise RuntimeError(f"planner exit={run1.returncode}: {run1.stderr}")
            plan = _read_json(out1 / "plan.json")
            record(checks[1], plan.get("changed")==["core","docs"] and plan.get("impacted") == ["api", "core", "docs", "ops", "ui", "worker"], f"changed={plan.get('changed')}; impacted={plan.get('impacted')}")
            levels = plan.get("levels")
            record(checks[2], levels == [["core", "docs"], ["api", "worker"], ["ops", "ui"]], f"levels={levels}")
            shuffled = {"components": [{**item,"depends_on":list(reversed(item["depends_on"]))} for item in reversed(graph["components"])]}; manifest.write_text(json.dumps(shuffled), encoding="utf-8"); changed.write_text('["docs","core"]',encoding="utf-8")
            run2 = _run_python_entrypoint(workspace, candidates, ["--manifest", str(manifest), "--changed", str(changed), "--out-dir", str(out2)], env={"PYTHONHASHSEED": "91"})
            raw_plan=(out1/"plan.json").read_text(); key_sorted=raw_plan.find('"changed"')<raw_plan.find('"impacted"')<raw_plan.find('"levels"')
            deterministic = run2.returncode == 0 and (out1 / "plan.json").read_bytes() == (out2 / "plan.json").read_bytes() and key_sorted
            record(checks[3], deterministic, f"second_exit={run2.returncode}; byte_equal={(out1/'plan.json').read_bytes()==(out2/'plan.json').read_bytes()}; key_sorted={key_sorted}")
            validation_cases = [
                ({"components":[{"id":"a","depends_on":[]},{"id":"a","depends_on":[]}]}, '["a"]'),
                ({"components":[{"id":"a","depends_on":["missing"]}]}, '["a"]'),
                ({"components":[{"id":"a","depends_on":["a"]}]}, '["a"]'),
                ({"components":[{"id":"a","depends_on":[]}]}, '["missing"]'),
                ("{malformed-json", '["a"]'),
                ({"components":[{"id":7,"depends_on":[]}]}, '[7]'),
                ({"components":[{"id":"a","depends_on":[]}]}, '[7]'),
                ({"components":[{"id":"","depends_on":[]}]}, '[""]'),
                ({"components":[{"id":"a","depends_on":"b"}]}, '["a"]'),
                ({"components":[{"id":"a","depends_on":[7]}]}, '["a"]'),
                ([], '["a"]'),
                ({}, '["a"]'),
                ({"components":{}}, '["a"]'),
                ({"components":["a"]}, '["a"]'),
                ({"components":[{"id":"a","depends_on":[]}]}, '{malformed-json'),
                ({"components":[{"id":"a","depends_on":[]}]}, '{"not":"an-array"}'),
            ]
            validation_ok=True; validation_details=[]
            for index,(bad_manifest,bad_changed) in enumerate(validation_cases):
                manifest.write_text(bad_manifest if isinstance(bad_manifest,str) else json.dumps(bad_manifest),encoding="utf-8"); changed.write_text(bad_changed,encoding="utf-8"); bad_out=root/f"bad-{index}"; bad_out.mkdir(); (bad_out/"plan.json").write_bytes(b"preserve-me")
                bad=_run_python_entrypoint(workspace,candidates,["--manifest",str(manifest),"--changed",str(changed),"--out-dir",str(bad_out)])
                case_ok=bad.returncode!=0 and (bad_out/"plan.json").read_bytes()==b"preserve-me" and "Traceback" not in bad.stderr
                validation_ok=validation_ok and case_ok; validation_details.append((index,bad.returncode,case_ok))
            record(checks[0],validation_ok,f"cases={validation_details}")
            cycle = {"components": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]}
            manifest.write_text(json.dumps(cycle), encoding="utf-8"); changed.write_text('["a"]', encoding="utf-8"); cycle_out = root / "cycle"; cycle_out.mkdir(); (cycle_out/"plan.json").write_bytes(b"preserve-cycle")
            cyc = _run_python_entrypoint(workspace, candidates, ["--manifest", str(manifest), "--changed", str(changed), "--out-dir", str(cycle_out)])
            record(checks[4], cyc.returncode != 0 and (cycle_out/"plan.json").read_bytes()==b"preserve-cycle" and "Traceback" not in cyc.stderr, f"exit={cyc.returncode}; preserved={(cycle_out/'plan.json').read_bytes()==b'preserve-cycle'}")
    except FileNotFoundError as exc:
        return _interface_unreachable_result(task_id=task_id, evaluation_dir=_evaluation_dir(workspace, task_id), passed_checks=passed, failed_checks=failed, observations=observations, check_ids=checks, detail=str(exc), reason="interface_unreachable:cli_or_output_missing")
    except Exception as exc: return _finish_runtime(task_id, workspace, checks, observations, passed, failed, record, exc)
    return _finalize_hidden_evaluation(task_id=task_id, evaluation_dir=_evaluation_dir(workspace, task_id), passed_checks=passed, failed_checks=failed, observations=observations)


def _evaluate_policy(workspace: Path) -> HiddenEvaluationResult:
    task_id = "access-policy-evaluator"
    checks = ("policy_wildcard_matching", "policy_subject_group_composition", "policy_deny_default_precedence", "policy_temporal_validity", "policy_rejections_determinism")
    observations, passed, failed, record = _recorder(); candidates = ["app/evaluate_policy.py", "evaluate_policy.py", "src/app/evaluate_policy.py"]
    policy = {"rules": [
        {"id":"allow-read","effect":"allow","groups":["readers"],"actions":["read"],"resources":["doc/*"]},
        {"id":"allow-alice","effect":"allow","subjects":["alice"],"actions":["write"],"resources":["doc/public"]},
        {"id":"deny-secret","effect":"deny","groups":["readers"],"actions":["read"],"resources":["doc/secret"]},
        {"id":"allow-audit","effect":"allow","groups":["auditors"],"actions":["read*"],"resources":["audit/exact"]},
        {"id":"deny-secure","effect":"deny","groups":["secure"],"actions":["open"],"resources":["vault/exact"]},
        {"id":"allow-secure","effect":"allow","groups":["secure"],"actions":["open"],"resources":["vault/exact"]},
        {"id":"time-rule","effect":"allow","groups":["deployers"],"actions":["deploy"],"resources":["svc/api"],"valid_from":"2035-01-01T00:00:00Z","valid_until":"2035-02-01T00:00:00Z"},
    ]}
    requests = [
        {"request_id":"r1","subject":"amy","groups":["readers"],"action":"read","resource":"doc/a","as_of":"2035-01-15T00:00:00Z"},
        {"request_id":"r2","subject":"alice","groups":[],"action":"write","resource":"doc/public","as_of":"2035-01-15T00:00:00Z"},
        {"request_id":"r3","subject":"amy","groups":["readers"],"action":"read","resource":"doc/secret","as_of":"2035-01-15T00:00:00Z"},
        {"request_id":"r4","subject":"nobody","groups":[],"action":"read","resource":"doc/a","as_of":"2035-01-15T00:00:00Z"},
        {"request_id":"r5","subject":"bob","groups":["deployers"],"action":"deploy","resource":"svc/api","as_of":"2035-01-31T19:00:00-05:00"},
        {"request_id":"r6","subject":"bob","groups":["deployers"],"action":"deploy","resource":"svc/api","as_of":"2035-01-31T18:59:59-05:00"},
        {"request_id":"r7","subject":"ava","groups":["auditors"],"action":"read:full","resource":"audit/exact","as_of":"2035-01-15T00:00:00Z"},
        {"request_id":"r8","subject":"bob","groups":["deployers"],"action":"deploy","resource":"svc/api","as_of":"2035-01-01T00:00:00Z"},
        {"request_id":"r9","subject":"sam","groups":["secure"],"action":"open","resource":"vault/exact","as_of":"2035-01-15T00:00:00Z"},
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="ah-policy-") as tmp:
            root=Path(tmp); pp=root/"policy.json"; rp=root/"requests.jsonl"; pp.write_text(json.dumps(policy),encoding="utf-8")
            lines=[json.dumps(x) for x in requests]; lines.insert(4,"{bad-json}"); lines.insert(7,json.dumps({"request_id":"bad-semantic","subject":"x","groups":[],"resource":"x","as_of":"2035-01-01T00:00:00Z"})); lines.insert(9,json.dumps({"request_id":"bad-time","subject":"x","groups":[],"action":"read","resource":"x","as_of":"not-rfc3339"})); rp.write_text("\n".join(lines)+"\n",encoding="utf-8")
            out1,out2=root/"out1",root/"out2"
            run1=_run_python_entrypoint(workspace,candidates,["--policy",str(pp),"--requests",str(rp),"--out-dir",str(out1)],env={"PYTHONHASHSEED":"11","TZ":"UTC"})
            if run1.returncode != 0: raise RuntimeError(f"policy exit={run1.returncode}: {run1.stderr}")
            decisions=_read_jsonl(out1/"decisions.jsonl"); rejected=_read_jsonl(out1/"rejected.jsonl"); summary=_read_json(out1/"summary.json"); by={x["request_id"]:x for x in decisions}
            invalid_rules=[
                [{"id":"bad","effect":"allow","groups":["g"],"actions":["re*ad"],"resources":["x"]}],
                [{"id":"bad","effect":"allow","groups":["g"],"actions":["read"],"resources":["x*y"]}],
                [{"id":"dup","effect":"allow","groups":["g"],"actions":["read"],"resources":["x"]},{"id":"dup","effect":"deny","groups":["g"],"actions":["read"],"resources":["x"]}],
                [{"id":"bad-effect","effect":"permit","groups":["g"],"actions":["read"],"resources":["x"]}],
                [{"id":"no-selector","effect":"allow","actions":["read"],"resources":["x"]}],
                [{"id":"bad-time","effect":"allow","groups":["g"],"actions":["read"],"resources":["x"],"valid_from":"not-rfc3339"}],
                [{"id":"bad-until","effect":"allow","groups":["g"],"actions":["read"],"resources":["x"],"valid_until":"not-rfc3339"}],
            ]
            invalid_statuses=[]
            for index,rules in enumerate(invalid_rules):
                invalid_policy=root/f"invalid-policy-{index}.json"; invalid_policy.write_text(json.dumps({"rules":rules}),encoding="utf-8"); invalid_out=root/f"invalid-out-{index}"
                invalid_run=_run_python_entrypoint(workspace,candidates,["--policy",str(invalid_policy),"--requests",str(rp),"--out-dir",str(invalid_out)])
                invalid_statuses.append((invalid_run.returncode,"Traceback" not in invalid_run.stderr))
            wildcard_ok=by["r1"]["decision"]=="allow" and by["r1"]["matched_rule_ids"]==["allow-read"] and by["r7"]["decision"]=="allow" and by["r7"]["matched_rule_ids"]==["allow-audit"] and all(code!=0 and controlled for code,controlled in invalid_statuses)
            record(checks[0],wildcard_ok,f"r1={by.get('r1')}; r7={by.get('r7')}; invalid={invalid_statuses}")
            record(checks[1], by["r2"]["decision"]=="allow" and by["r2"]["matched_rule_ids"]==["allow-alice"], f"r2={by.get('r2')}")
            record(checks[2], by["r9"]["decision"]=="deny" and by["r9"]["matched_rule_ids"]==["allow-secure","deny-secure"] and by["r4"]["decision"]=="deny" and by["r4"]["matched_rule_ids"]==[], f"r9={by.get('r9')}; r4={by.get('r4')}")
            record(checks[3], by["r5"]["decision"]=="deny" and by["r6"]["decision"]=="allow" and by["r8"]["decision"]=="allow", f"r5={by.get('r5')}; r6={by.get('r6')}; r8={by.get('r8')}")
            run2=_run_python_entrypoint(workspace,candidates,["--policy",str(pp),"--requests",str(rp),"--out-dir",str(out2)],env={"PYTHONHASHSEED":"99","TZ":"Pacific/Honolulu"})
            det=run2.returncode==0 and all((out1/n).read_bytes()==(out2/n).read_bytes() for n in ["decisions.jsonl","rejected.jsonl","summary.json"])
            valid_order=[f"r{i}" for i in range(1,10)]
            count_fields=["allow_count","deny_count","rejected_count","request_count"]
            types_ok=isinstance(summary,dict) and all(type(summary.get(key)) is int for key in count_fields)
            summary_ok=types_ok and summary["allow_count"]==sum(x.get("decision")=="allow" for x in decisions) and summary["deny_count"]==sum(x.get("decision")=="deny" for x in decisions) and summary["rejected_count"]==len(rejected) and summary["request_count"]==len(decisions)
            decision_schema=all(set(x)=={"request_id","decision","matched_rule_ids"} for x in decisions)
            rejection_schema=len(rejected)==3 and all(set(x)=={"line_number","reason"} and type(x.get("line_number")) is int and x["line_number"]>0 and isinstance(x.get("reason"),str) for x in rejected)
            summary_schema=isinstance(summary,dict) and set(summary)==set(count_fields)
            reject_ok=decision_schema and summary_schema and [x.get("request_id") for x in decisions]==valid_order and rejection_schema and summary_ok
            record(checks[4], det and reject_ok, f"det={det}; rejected={rejected}; summary={summary}")
    except FileNotFoundError as exc:
        return _interface_unreachable_result(task_id=task_id,evaluation_dir=_evaluation_dir(workspace,task_id),passed_checks=passed,failed_checks=failed,observations=observations,check_ids=checks,detail=str(exc),reason="interface_unreachable:cli_or_output_missing")
    except Exception as exc: return _finish_runtime(task_id,workspace,checks,observations,passed,failed,record,exc)
    return _finalize_hidden_evaluation(task_id=task_id,evaluation_dir=_evaluation_dir(workspace,task_id),passed_checks=passed,failed_checks=failed,observations=observations)


def _cross_process_post_with_headers(workspace:Path,path:str,json_body:dict[str,Any])->tuple[int,Any,dict[str,str],str]:
    marker="__AGENTHARNESS_HTTP_RESPONSE__="
    script='''
import json, os
from pathlib import Path
from agentharness.benchmark_hidden_evaluators import _load_fastapi_app, _make_test_client
request=json.loads(os.environ["AGENTHARNESS_CROSS_PROCESS_REQUEST"])
_module,app=_load_fastapi_app(Path.cwd())
with _make_test_client(app) as client:
    response=client.post(request["path"],json=request["json"])
try: payload=response.json()
except Exception: payload=response.text
print("__AGENTHARNESS_HTTP_RESPONSE__="+json.dumps({"status_code":response.status_code,"payload":payload,"headers":dict(response.headers)},sort_keys=True))
'''
    env=dict(os.environ); env["AGENTHARNESS_CROSS_PROCESS_REQUEST"]=json.dumps({"path":path,"json":json_body},sort_keys=True); env["AGENTHARNESS_CROSS_PROCESS_CHILD"]="1"
    completed=subprocess.run([sys.executable,"-c",script],cwd=workspace,env=env,capture_output=True,text=True,check=False,timeout=45)
    line=next((value for value in reversed(completed.stdout.splitlines()) if value.startswith(marker)),"")
    if completed.returncode!=0 or not line:
        return 599,None,{},completed.stderr.strip() or completed.stdout.strip() or f"child exit {completed.returncode}"
    response=json.loads(line[len(marker):])
    return int(response["status_code"]),response.get("payload"),{str(k).lower():str(v) for k,v in response.get("headers",{}).items()},f"child_exit={completed.returncode}"


def _evaluate_documents(workspace: Path) -> HiddenEvaluationResult:
    task_id="versioned-document-api"; checks=("document_create_etag_persistence","document_if_match_atomic","document_merge_patch","document_revision_history","document_restore_history")
    observations,passed,failed,record=_recorder(); evaluation_dir=_evaluation_dir(workspace,task_id)
    try: module_path,app=_load_fastapi_app(workspace)
    except Exception as exc: return _interface_unreachable_result(task_id=task_id,evaluation_dir=evaluation_dir,passed_checks=passed,failed_checks=failed,observations=observations,check_ids=checks,detail=str(exc),reason="interface_unreachable:fastapi_app_not_found")
    try:
        with _working_directory(workspace), _make_test_client(app) as client:
            status,payload,post_headers,detail=_cross_process_post_with_headers(workspace,"/documents",{"document":{"title":"A","meta":{"x":1,"keep":2},"tags":["a"]}})
            doc_id=_identifier(payload,"document_id","id"); got=client.get(f"/documents/{doc_id}") if doc_id else None
            persisted=got is not None and got.status_code==200 and got.headers.get("etag")=='"v1"' and _json_payload(got).get("revision")==1
            record(checks[0],status in {200,201} and post_headers.get("etag")=='"v1"' and doc_id is not None and persisted,f"module={module_path}; child={status}; post_etag={post_headers.get('etag')}; persisted={persisted}; {detail}")
            if not persisted:
                fallback=client.post("/documents",json={"document":{"title":"A","meta":{"x":1,"keep":2},"tags":["a"]}})
                fallback_payload=_json_payload(fallback)
                doc_id=_identifier(fallback_payload,"document_id","id")
            missing=client.patch(f"/documents/{doc_id}",json={"title":"B"}); stale=client.patch(f"/documents/{doc_id}",headers={"If-Match":'"v0"'},json={"title":"B"}); after=client.get(f"/documents/{doc_id}")
            revs_after_fail=_json_payload(client.get(f"/documents/{doc_id}/revisions"))
            concurrent_doc=_json_payload(client.post("/documents",json={"document":{"title":"race","meta":{}}}))
            concurrent_id=_identifier(concurrent_doc,"document_id","id")
            def concurrent_writer(title:str)->int:
                with _make_test_client(app) as writer:
                    return writer.patch(f"/documents/{concurrent_id}",headers={"If-Match":'"v1"'},json={"title":title}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                race_statuses=sorted(pool.map(concurrent_writer,["winner-a","winner-b"]))
            race_current=_json_payload(client.get(f"/documents/{concurrent_id}")); race_revisions=_json_payload(client.get(f"/documents/{concurrent_id}/revisions"))
            cas_ok=race_statuses==[200,412] and race_current.get("revision")==2 and isinstance(race_revisions,list) and len(race_revisions)==2
            record(checks[1],missing.status_code in {428,412} and stale.status_code==412 and _json_payload(after).get("revision")==1 and isinstance(revs_after_fail,list) and len(revs_after_fail)==1 and cas_ok,f"missing={missing.status_code}; stale={stale.status_code}; revisions={len(revs_after_fail) if isinstance(revs_after_fail,list) else None}; race={race_statuses}; race_revisions={len(race_revisions) if isinstance(race_revisions,list) else None}")
            patch=client.patch(f"/documents/{doc_id}",headers={"If-Match":'"v1"'},json={"meta":{"x":9,"keep":None},"tags":["z"]})
            patched=_json_payload(patch); before_non_object=_json_payload(client.get(f"/documents/{doc_id}")); before_non_object_revs=_json_payload(client.get(f"/documents/{doc_id}/revisions")); non_object=client.patch(f"/documents/{doc_id}",headers={"If-Match":'"v2"'},json=["invalid"]); after_non_object=_json_payload(client.get(f"/documents/{doc_id}")); non_object_revs=_json_payload(client.get(f"/documents/{doc_id}/revisions"))
            merge_ok=patch.status_code==200 and patch.headers.get("etag")=='"v2"' and patched.get("document")=={"title":"A","meta":{"x":9},"tags":["z"]} and 400<=non_object.status_code<500 and after_non_object==before_non_object and non_object_revs==before_non_object_revs
            record(checks[2],merge_ok,f"patch={patched}; etag={patch.headers.get('etag')}; non_object={non_object.status_code}")
            read_only=client.get(f"/documents/{doc_id}"); failed_again=client.patch(f"/documents/{doc_id}",headers={"If-Match":'"v1"'},json={"title":"stale"}); revs=_json_payload(client.get(f"/documents/{doc_id}/revisions"))
            history_ok=isinstance(revs,list) and [r.get("revision") for r in revs]==[1,2] and revs[0].get("document",{}).get("meta")=={"x":1,"keep":2}
            record(checks[3],history_ok,f"revisions={revs}; read={read_only.status_code}; failed={failed_again.status_code}")
            before_restore=_json_payload(client.get(f"/documents/{doc_id}")); before_restore_revs=_json_payload(client.get(f"/documents/{doc_id}/revisions")); restore_missing=client.post(f"/documents/{doc_id}/restore/1"); restore_stale=client.post(f"/documents/{doc_id}/restore/1",headers={"If-Match":'"v1"'}); restore_unknown_revision=client.post(f"/documents/{doc_id}/restore/999",headers={"If-Match":'"v2"'}); restore_unknown_document=client.post("/documents/not-found/restore/1",headers={"If-Match":'"v1"'}); after_failed_restore=_json_payload(client.get(f"/documents/{doc_id}")); after_failed_restore_revs=_json_payload(client.get(f"/documents/{doc_id}/revisions"))
            negative_restore_ok=all(400<=response.status_code<500 for response in [restore_missing,restore_stale,restore_unknown_revision,restore_unknown_document]) and after_failed_restore==before_restore and after_failed_restore_revs==before_restore_revs
            restore=client.post(f"/documents/{doc_id}/restore/1",headers={"If-Match":'"v2"'}); restored=_json_payload(restore); final_revs=_json_payload(client.get(f"/documents/{doc_id}/revisions"))
            restore_ok=negative_restore_ok and restore.status_code in {200,201} and restore.headers.get("etag")=='"v3"' and restored.get("revision")==3 and restored.get("document")=={"title":"A","meta":{"x":1,"keep":2},"tags":["a"]} and sorted(r.get("revision") for r in final_revs)==[1,2,3]
            record(checks[4],restore_ok,f"negative={restore_missing.status_code},{restore_stale.status_code},{restore_unknown_revision.status_code},{restore_unknown_document.status_code}; restore={restored}; revisions={[r.get('revision') for r in final_revs] if isinstance(final_revs,list) else None}")
    except Exception as exc: return _finish_runtime(task_id,workspace,checks,observations,passed,failed,record,exc)
    return _finalize_hidden_evaluation(task_id=task_id,evaluation_dir=evaluation_dir,passed_checks=passed,failed_checks=failed,observations=observations)


def _zip(path: Path, entries: list[tuple[str, bytes, int | None]]) -> None:
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data,mode in entries:
            info=zipfile.ZipInfo(name)
            if mode is not None: info.create_system=3; info.external_attr=mode << 16
            archive.writestr(info,data)


def _evaluate_archive(workspace: Path) -> HiddenEvaluationResult:
    task_id="safe-archive-extraction"; checks=("archive_extract_manifest","archive_path_containment_atomic","archive_special_entry_rejection","archive_collision_atomic","archive_limits_corruption_atomic")
    observations,passed,failed,record=_recorder(); candidates=["app/extract_archive.py","extract_archive.py","src/app/extract_archive.py"]
    try:
        with tempfile.TemporaryDirectory(prefix="ah-archive-") as tmp:
            root=Path(tmp); good=root/"good.zip"; _zip(good,[("docs/",b"",stat.S_IFDIR|0o755),("docs/a.txt",b"alpha",stat.S_IFREG|0o644),("b.bin",b"\x00\x01",stat.S_IFREG|0o644)])
            out=root/"out"; run=_run_python_entrypoint(workspace,candidates,["--archive",str(good),"--out-dir",str(out),"--max-entries","4","--max-bytes","20"])
            manifest=_read_json(out/"manifest.json") if run.returncode==0 else None
            expected=[{"path":"b.bin","sha256":hashlib.sha256(b"\x00\x01").hexdigest(),"size":2},{"path":"docs/a.txt","sha256":hashlib.sha256(b"alpha").hexdigest(),"size":5}]
            record(checks[0],run.returncode==0 and manifest=={"files":expected,"file_count":2,"total_bytes":7} and (out/"docs/a.txt").read_bytes()==b"alpha",f"exit={run.returncode}; manifest={manifest}")
            def rejection_case(label:str,entries:list[tuple[str,bytes,Any]]|None=None,raw:bytes|None=None,max_entries:int=5,max_bytes:int=20)->tuple[bool,str]:
                archive=root/f"{label}.zip"
                if raw is not None: archive.write_bytes(raw)
                else: _zip(archive,entries or [])
                absent=root/f"{label}-absent"
                first=_run_python_entrypoint(workspace,candidates,["--archive",str(archive),"--out-dir",str(absent),"--max-entries",str(max_entries),"--max-bytes",str(max_bytes)])
                preserved=root/f"{label}-preserved"; preserved.mkdir(); (preserved/"empty-dir").mkdir(); (preserved/"sentinel.bin").write_bytes(b"unchanged")
                def snapshot(folder:Path)->list[tuple[str,str,int,bytes|None]]:
                    rows=[]
                    for path in sorted(folder.rglob("*")):
                        rows.append((path.relative_to(folder).as_posix(),"dir" if path.is_dir() else "file",stat.S_IMODE(path.stat().st_mode),None if path.is_dir() else path.read_bytes()))
                    return rows
                before=snapshot(preserved)
                second=_run_python_entrypoint(workspace,candidates,["--archive",str(archive),"--out-dir",str(preserved),"--max-entries",str(max_entries),"--max-bytes",str(max_bytes)])
                after=snapshot(preserved)
                ok=first.returncode!=0 and not absent.exists() and second.returncode!=0 and before==after and "Traceback" not in first.stderr+second.stderr
                return ok,f"{label}:{first.returncode}/{second.returncode}:{before==after}"
            path_cases=[
                ("parent",[("../escape.txt",b"bad",stat.S_IFREG|0o644)]),
                ("absolute",[("/absolute.txt",b"bad",stat.S_IFREG|0o644)]),
                ("drive",[("C:/drive.txt",b"bad",stat.S_IFREG|0o644)]),
                ("backslash",[("dir\\file.txt",b"bad",stat.S_IFREG|0o644)]),
                ("empty-normalized",[(".",b"bad",stat.S_IFREG|0o644)]),
            ]
            path_results=[rejection_case(label,entries) for label,entries in path_cases]
            path_ok=all(ok for ok,_ in path_results) and not (root/"escape.txt").exists()
            record(checks[1],path_ok,f"cases={[detail for _,detail in path_results]}; escape={(root/'escape.txt').exists()}")
            special_modes=[("symlink",stat.S_IFLNK|0o777),("fifo",stat.S_IFIFO|0o600),("char",stat.S_IFCHR|0o600),("block",stat.S_IFBLK|0o600),("socket",stat.S_IFSOCK|0o600)]
            special_results=[rejection_case(label,[(label,b"payload",mode)]) for label,mode in special_modes]
            record(checks[2],all(ok for ok,_ in special_results),f"cases={[detail for _,detail in special_results]}")
            collision_cases=[
                ("duplicate-normalized",[("a/./b",b"one",stat.S_IFREG|0o644),("a/b",b"two",stat.S_IFREG|0o644)]),
                ("prefix-conflict",[("a",b"file",stat.S_IFREG|0o644),("a/b",b"child",stat.S_IFREG|0o644)]),
            ]
            collision_results=[rejection_case(label,entries) for label,entries in collision_cases]
            record(checks[3],all(ok for ok,_ in collision_results),f"cases={[detail for _,detail in collision_results]}")
            limit_count=rejection_case("limit-count",[("a",b"1",stat.S_IFREG|0o644),("b",b"2",stat.S_IFREG|0o644)],max_entries=1,max_bytes=20)
            limit_bytes=rejection_case("limit-bytes",[("a",b"1234",stat.S_IFREG|0o644)],max_entries=5,max_bytes=3)
            invalid_limit=rejection_case("invalid-limit",[("a",b"1",stat.S_IFREG|0o644)],max_entries=0,max_bytes=3)
            corrupt=rejection_case("corrupt",raw=b"not-a-zip")
            terminal=[limit_count,limit_bytes,invalid_limit,corrupt]
            record(checks[4],all(ok for ok,_ in terminal),f"cases={[detail for _,detail in terminal]}")
    except FileNotFoundError as exc:
        return _interface_unreachable_result(task_id=task_id,evaluation_dir=_evaluation_dir(workspace,task_id),passed_checks=passed,failed_checks=failed,observations=observations,check_ids=checks,detail=str(exc),reason="interface_unreachable:cli_or_output_missing")
    except Exception as exc: return _finish_runtime(task_id,workspace,checks,observations,passed,failed,record,exc)
    return _finalize_hidden_evaluation(task_id=task_id,evaluation_dir=_evaluation_dir(workspace,task_id),passed_checks=passed,failed_checks=failed,observations=observations)
