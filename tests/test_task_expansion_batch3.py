from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agentharness.benchmark_hidden_evaluators import evaluate_benchmark_task

REPO=Path(__file__).resolve().parents[1]
BENCH=REPO/"benchmarks"
OUT=BENCH/"grading-env"/"task-expansion-batch3"
REFS=OUT/"references"
FREEZE=json.loads((OUT/"BATCH3_PREBUILD_FREEZE.json").read_text())
SENS=json.loads((OUT/"MUTATION_SENSITIVITY.json").read_text())["tasks"]
TASK_CHECKS={task:[check["id"] for check in value["checks"]] for task,value in FREEZE["tasks"].items()}
PACKAGES={"signed-artifact-verifier":"artifact_verifier","pii-redaction-pipeline":"pii_redactor","lease-coordination-api":"lease_api","double-entry-ledger-api":"ledger_api"}


def evaluate_copy(task:str,mutant:str="",seed:str="17"):
    temp=tempfile.TemporaryDirectory(prefix=f"batch3-{task}-")
    workspace=Path(temp.name)/task; shutil.copytree(REFS/task,workspace)
    run=Path(temp.name)/"run.json"
    run.write_text(json.dumps({"run_id":f"{task}-{mutant or 'positive'}-{seed}","workspace":str(workspace),"artifacts":{"changed_files":[f"{PACKAGES[task]}/{'main.py' if task.endswith('-api') else ('verify.py' if task.startswith('signed') else 'redact.py')}","README.md","pyproject.toml"],"commands":[{"cmd":"pytest -q","exit_code":0}],"outputs":[{"type":"file","path":"README.md"},{"type":"file","path":"pyproject.toml"}]}}))
    with mock.patch.dict(os.environ,{"AGENTHARNESS_MUTANT":mutant,"PYTHONHASHSEED":seed},clear=False):
        result=evaluate_benchmark_task(run,task)
    return temp,result


class Batch3Tests(unittest.TestCase):
    def test_canonical_acceptance_auditor_quick_from_any_cwd(self):
        auditor=BENCH/"grading-env"/"audit_task_expansion_batch3.py"
        with tempfile.TemporaryDirectory(prefix="batch3-auditor-cwd-") as cwd:
            done=subprocess.run([sys.executable,str(auditor),"--quick"],cwd=cwd,capture_output=True,text=True)
        self.assertEqual(done.returncode,0,msg=done.stdout+done.stderr)
        report=json.loads((OUT/"BATCH3_ACCEPTANCE_REPORT.json").read_text())
        self.assertEqual(report["mode"],"quick"); self.assertFalse(report["go"])
        self.assertTrue(report["static"]["ok"]); self.assertEqual(report["efficacy_cells"],0)
        self.assertEqual(report["operations"]["generator"]["command"][0],sys.executable)
        self.assertEqual(report["dynamic"]["command"][0],sys.executable)
        self.assertFalse(report["independent_review"]["claimed"])
        self.assertIsNotNone(datetime.fromisoformat(report["generated_at"].replace("Z","+00:00")))

    def test_normative_diversity_and_mutation_contract_shape(self):
        self.assertEqual(len(FREEZE["all_prior_overlap_matrix"]),64)
        self.assertEqual(len(FREEZE["nearest_check_matrix"]),20)
        self.assertEqual(len(FREEZE["new_task_pairwise_matrix"]),6)
        self.assertEqual(sum(len(rows) for rows in SENS.values()),20)
        for task,checks in TASK_CHECKS.items():
            for check in checks:
                self.assertEqual(SENS[task][check]["expected_failed_checks"],[check])
                self.assertEqual(SENS[task][check]["expected_passed_checks"],[item for item in checks if item != check])

    def test_generator_and_visible_shape(self):
        expected={
            "signed-artifact-verifier":{"SPEC.md","CLAIMS_CONTRACT.template.json","README.md","pyproject.toml","artifact_verifier/__init__.py","artifact_verifier/verify.py"},
            "pii-redaction-pipeline":{"SPEC.md","CLAIMS_CONTRACT.template.json","README.md","pyproject.toml","pii_redactor/__init__.py","pii_redactor/redact.py"},
            "lease-coordination-api":{"SPEC.md","CLAIMS_CONTRACT.template.json","README.md","pyproject.toml","lease_api/__init__.py","lease_api/main.py"},
            "double-entry-ledger-api":{"SPEC.md","CLAIMS_CONTRACT.template.json","README.md","pyproject.toml","ledger_api/__init__.py","ledger_api/main.py"},
        }
        paths=[p for task in TASK_CHECKS for p in (BENCH/task).rglob("*") if p.is_file()]
        before={p:p.read_bytes() for p in paths}
        done=subprocess.run([sys.executable,str(BENCH/"grading-env"/"build_task_expansion_batch3.py")],cwd=REPO,capture_output=True,text=True,check=True)
        self.assertEqual({p:p.read_bytes() for p in paths},before)
        for task,names in expected.items():
            self.assertEqual({p.relative_to(BENCH/task).as_posix() for p in (BENCH/task).rglob("*") if p.is_file()},names)
            self.assertEqual(len(TASK_CHECKS[task]),5)

    def test_positive_references(self):
        for task,checks in TASK_CHECKS.items():
            with self.subTest(task=task):
                temp,result=evaluate_copy(task)
                try:
                    self.assertEqual(result.execution_status,"valid"); self.assertTrue(result.critical_ok)
                    self.assertEqual(result.passed_checks,checks); self.assertEqual(result.failed_checks,[]); self.assertEqual(len(result.observations),5)
                finally: temp.cleanup()

    def test_exact_twenty_mutation_failure_sets(self):
        count=0
        for task,checks in TASK_CHECKS.items():
            for mutant in checks:
                count+=1
                with self.subTest(task=task,mutant=mutant):
                    temp,result=evaluate_copy(task,mutant)
                    try:
                        row=SENS[task][mutant]
                        self.assertEqual(result.failed_checks,row["expected_failed_checks"])
                        self.assertEqual(result.passed_checks,row["expected_passed_checks"])
                    finally: temp.cleanup()
        self.assertEqual(count,20)

    def test_clean_room_copies(self):
        for task,checks in TASK_CHECKS.items():
            signatures=[]
            for seed in ("13","47","89"):
                temp,result=evaluate_copy(task,seed=seed)
                try:
                    signatures.append((result.execution_status,result.outcome_status,result.critical_ok,tuple(result.passed_checks),tuple(result.failed_checks),tuple((o.id,o.status) for o in result.observations)))
                finally: temp.cleanup()
            self.assertEqual(signatures,[signatures[0]]*3)
            self.assertEqual(list(signatures[0][3]),checks)


if __name__=="__main__": unittest.main()
