from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentharness.benchmark_hidden_evaluators import evaluate_benchmark_task

REPO=Path(__file__).resolve().parents[1]
BENCH=REPO/"benchmarks"
REFS=BENCH/"grading-env"/"task-expansion-batch2"/"references"
SENS=json.loads((BENCH/"grading-env"/"task-expansion-batch2"/"MUTATION_SENSITIVITY.json").read_text())["tasks"]
TASK_CHECKS={
 "dependency-impact-planner":["dependency_reverse_impact","dependency_parallel_levels","dependency_deterministic_output","dependency_graph_validation","dependency_cycle_atomic"],
 "access-policy-evaluator":["policy_wildcard_matching","policy_subject_group_composition","policy_deny_default_precedence","policy_temporal_validity","policy_rejections_determinism"],
 "versioned-document-api":["document_create_etag_persistence","document_if_match_atomic","document_merge_patch","document_revision_history","document_restore_history"],
 "safe-archive-extraction":["archive_extract_manifest","archive_path_containment_atomic","archive_special_entry_rejection","archive_collision_atomic","archive_limits_corruption_atomic"],
}

def evaluate_ref(task:str,mutant:str="",seed:str="17"):
 temp=tempfile.TemporaryDirectory(prefix=f"batch2-{task}-"); workspace=Path(temp.name)/task; shutil.copytree(REFS/task,workspace)
 run=Path(temp.name)/"run.json"; run.write_text(json.dumps({"run_id":f"{task}-{mutant or 'positive'}-{seed}","workspace":str(workspace),"artifacts":{"changed_files":["app/main.py","README.md","pyproject.toml"],"commands":[{"cmd":"pytest -q","exit_code":0}],"outputs":[{"type":"file","path":"README.md"},{"type":"file","path":"pyproject.toml"}]}}))
 env={"AGENTHARNESS_MUTANT":mutant,"PYTHONHASHSEED":seed}
 with mock.patch.dict(os.environ,env,clear=False): result=evaluate_benchmark_task(run,task)
 return temp,result

class Batch2Tests(unittest.TestCase):
 def test_visible_pack_shape(self):
  for task in TASK_CHECKS:
   with self.subTest(task=task):
    files={p.name for p in (BENCH/task).iterdir() if p.is_file()}; self.assertEqual(files,{"SPEC.md","CLAIMS_CONTRACT.template.json","HELDOUT_EVALUATION_SUITE.template.json","QUALITY_GATE.md"})
    suite=json.loads((BENCH/task/"HELDOUT_EVALUATION_SUITE.template.json").read_text()); self.assertEqual(len(suite["cases"]),6); self.assertEqual(sum(x["kind"]=="functional" for x in suite["cases"]),5); self.assertEqual(suite["cases"][-1]["case_id"],"evaluation_result_schema")
 def test_generator_is_byte_stable(self):
  paths=[BENCH/task/name for task in TASK_CHECKS for name in ["SPEC.md","CLAIMS_CONTRACT.template.json","HELDOUT_EVALUATION_SUITE.template.json","QUALITY_GATE.md"]]
  before={path:path.read_bytes() for path in paths}
  subprocess.run([sys.executable,str(BENCH/"grading-env"/"build_task_expansion_batch2.py")],cwd=BENCH.parent,check=True,capture_output=True,text=True)
  self.assertEqual({path:path.read_bytes() for path in paths},before)
 def test_positive_references(self):
  for task,checks in TASK_CHECKS.items():
   with self.subTest(task=task):
    temp,result=evaluate_ref(task)
    try:
     self.assertEqual(result.execution_status,"valid"); self.assertTrue(result.critical_ok); self.assertEqual(result.passed_checks,checks); self.assertEqual(result.failed_checks,[]); self.assertEqual(len(result.observations),5)
    finally: temp.cleanup()
 def test_exact_mutation_sensitivity(self):
  for task,checks in TASK_CHECKS.items():
   for mutant in checks:
    with self.subTest(task=task,mutant=mutant):
     temp,result=evaluate_ref(task,mutant)
     try:
      expected=SENS[task][mutant]["expected_failed_checks"]; self.assertEqual(result.failed_checks,expected); self.assertEqual(result.passed_checks,[x for x in checks if x not in expected])
     finally: temp.cleanup()
 def test_clean_room_determinism(self):
  for task,checks in TASK_CHECKS.items():
   with self.subTest(task=task):
    signatures=[]
    for seed in ["13","47","89"]:
     temp,result=evaluate_ref(task,seed=seed)
     try: signatures.append((result.critical_ok,result.execution_status,result.outcome_status,result.classification_reason,tuple(result.passed_checks),tuple(result.failed_checks),tuple((x.id,x.status) for x in result.observations)))
     finally: temp.cleanup()
    self.assertEqual(signatures,[signatures[0]]*3); self.assertEqual(list(signatures[0][4]),checks)

if __name__=="__main__": unittest.main()
