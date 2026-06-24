from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from agentharness.benchmark_hidden_evaluators import evaluate_benchmark_task
from agentharness.benchmarking import write_rendered_json_template
from agentharness.evaluation import evaluate_run

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
TASK_ID = "incident-escalation-api"

GOOD_APP = textwrap.dedent(
    '''
    from __future__ import annotations

    from copy import deepcopy
    from datetime import datetime, timezone

    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class IncidentCreate(BaseModel):
        service: str
        severity: str
        opened_at: datetime
        summary: str

    class AckPayload(BaseModel):
        responder: str
        acknowledged_at: datetime

    class ResolvePayload(BaseModel):
        resolution_note: str
        resolved_at: datetime

    incidents: dict[int, dict] = {}
    next_id = 1

    def iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

    def clone(item: dict) -> dict:
        return deepcopy(item)

    @app.post('/incidents', status_code=201)
    def create_incident(payload: IncidentCreate):
        global next_id
        if payload.severity not in {'sev1', 'sev2', 'sev3'}:
            raise HTTPException(status_code=422, detail='invalid severity')
        record = {
            'id': next_id,
            'service': payload.service,
            'severity': payload.severity,
            'opened_at': iso(payload.opened_at),
            'summary': payload.summary,
            'acknowledged_at': None,
            'responder': None,
            'resolved_at': None,
            'resolution_note': None,
        }
        incidents[next_id] = record
        next_id += 1
        return clone(record)

    @app.post('/incidents/{incident_id}/acknowledge')
    def acknowledge_incident(incident_id: int, payload: AckPayload):
        item = incidents.get(incident_id)
        if item is None:
            raise HTTPException(status_code=404, detail='not found')
        item['acknowledged_at'] = iso(payload.acknowledged_at)
        item['responder'] = payload.responder
        return clone(item)

    @app.post('/incidents/{incident_id}/resolve')
    def resolve_incident(incident_id: int, payload: ResolvePayload):
        item = incidents.get(incident_id)
        if item is None:
            raise HTTPException(status_code=404, detail='not found')
        item['resolved_at'] = iso(payload.resolved_at)
        item['resolution_note'] = payload.resolution_note
        return clone(item)

    @app.get('/incidents/{incident_id}/escalation')
    def escalation_status(incident_id: int, as_of: str):
        item = incidents.get(incident_id)
        if item is None:
            raise HTTPException(status_code=404, detail='not found')
        try:
            as_of_dt = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail='invalid as_of') from exc
        if item['resolved_at'] is not None:
            return {'incident_id': incident_id, 'escalated': False, 'reason': 'resolved'}
        if item['acknowledged_at'] is not None:
            return {'incident_id': incident_id, 'escalated': False, 'reason': 'acknowledged'}
        opened_at = datetime.fromisoformat(item['opened_at'].replace('Z', '+00:00'))
        age_minutes = (as_of_dt - opened_at).total_seconds() / 60
        if item['severity'] == 'sev1':
            escalated = age_minutes >= 15
        elif item['severity'] == 'sev2':
            escalated = age_minutes >= 60
        else:
            escalated = False
        return {'incident_id': incident_id, 'escalated': escalated, 'reason': 'threshold' if escalated else 'within_policy'}
    '''
).strip() + "\n"

BUGGY_APP = (
    GOOD_APP.replace('escalated = age_minutes >= 15', 'escalated = age_minutes >= 30  # BUG: sev1 escalates too late')
    .replace("return {'incident_id': incident_id, 'escalated': False, 'reason': 'acknowledged'}", "pass  # BUG: acknowledgement does not stop escalation")
    .replace("return {'incident_id': incident_id, 'escalated': False, 'reason': 'resolved'}", "pass  # BUG: resolution does not stop escalation")
    .replace('escalated = False', 'escalated = age_minutes >= 5  # BUG: sev3 can auto-escalate', 1)
    .replace("raise HTTPException(status_code=422, detail='invalid as_of')", "as_of_dt = datetime.now(timezone.utc)  # BUG: invalid as_of accepted")
)


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / 'app'
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / '__init__.py').write_text('', encoding='utf-8')
    (app_dir / 'main.py').write_text(app_source, encoding='utf-8')
    (workspace / 'README.md').write_text('# Incident escalation API\n', encoding='utf-8')
    (workspace / 'pyproject.toml').write_text('[project]\nname = "incident-escalation-api"\nversion = "0.1.0"\ndependencies = ["fastapi", "pydantic"]\n', encoding='utf-8')


def _write_run(run_path: Path, workspace: Path, run_id: str) -> None:
    run_path.write_text(
        json.dumps(
            {
                'run_id': run_id,
                'workspace': str(workspace),
                'artifacts': {
                    'changed_files': ['app/main.py', 'README.md', 'pyproject.toml'],
                    'commands': [{'cmd': 'pytest -q', 'exit_code': 0}],
                    'outputs': [
                        {'type': 'file', 'path': 'README.md'},
                        {'type': 'file', 'path': 'pyproject.toml'},
                    ],
                },
            },
            indent=2,
        )
        + '\n',
        encoding='utf-8',
    )


class IncidentBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, 'incident_good_001')

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / '.agentharness' / 'evaluation' / TASK_ID / 'summary.txt').read_text(encoding='utf-8')
            self.assertIn('sev1_escalates_on_time=pass', summary_text)
            self.assertIn('ack_stops_escalation=pass', summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = 'incident_cli_good_001'
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / 'HELDOUT_EVALUATION_SUITE.template.json'
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / 'suite.json')

            hidden_eval = subprocess.run(
                [sys.executable, '-m', 'agentharness', 'benchmark-evaluate-task', '--run', str(run_path), '--task-id', TASK_ID, '--json'],
                cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(hidden_eval.returncode, 0, hidden_eval.stderr)
            self.assertTrue(json.loads(hidden_eval.stdout)['critical_ok'])

            completed = subprocess.run(
                [sys.executable, '-m', 'agentharness', 'evaluate', '--run', str(run_path), '--suite', str(suite_path), '--json'],
                cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload['ok'])
            self.assertEqual(payload['summary']['failed'], 0)
            self.assertGreaterEqual(payload['summary']['passed'], 6)

    def test_cli_evaluate_fails_for_buggy_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, BUGGY_APP)
            run_id = 'incident_cli_buggy_001'
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / 'HELDOUT_EVALUATION_SUITE.template.json'
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / 'suite.json')

            hidden_eval = subprocess.run(
                [sys.executable, '-m', 'agentharness', 'benchmark-evaluate-task', '--run', str(run_path), '--task-id', TASK_ID, '--json'],
                cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(hidden_eval.returncode, 1, hidden_eval.stdout)
            hidden_payload = json.loads(hidden_eval.stdout)
            self.assertFalse(hidden_payload['critical_ok'])
            self.assertIn('sev1_escalates_on_time', hidden_payload['failed_checks'])
            self.assertIn('ack_stops_escalation', hidden_payload['failed_checks'])
            self.assertIn('resolved_stops_escalation', hidden_payload['failed_checks'])
            self.assertIn('sev3_not_auto_escalated', hidden_payload['failed_checks'])
            self.assertIn('invalid_as_of_rejected', hidden_payload['failed_checks'])

            completed = subprocess.run(
                [sys.executable, '-m', 'agentharness', 'evaluate', '--run', str(run_path), '--suite', str(suite_path), '--json'],
                cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload['ok'])
            self.assertGreaterEqual(payload['summary']['failed'], 4)

    def test_library_evaluator_integrates_with_evaluate_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = 'incident_evalrun_good_001'
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, run_id)
            template_path = BENCHMARKS_DIR / TASK_ID / 'HELDOUT_EVALUATION_SUITE.template.json'
            suite_path = write_rendered_json_template(template_path, run_id=run_id, output_path=temp_root / 'suite.json')

            evaluate_benchmark_task(run_path, TASK_ID)
            result = evaluate_run(run_path, suite_path)
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.summary['failed'], 0)
            self.assertGreaterEqual(result.summary['passed'], 6)


if __name__ == '__main__':
    unittest.main()
