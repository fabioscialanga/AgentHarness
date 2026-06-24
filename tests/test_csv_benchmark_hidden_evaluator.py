from __future__ import annotations

import inspect
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
BENCHMARKS_DIR = REPO_ROOT / 'benchmarks'
TASK_ID = 'csv-member-import'

GOOD_APP = inspect.cleandoc(
    '''
    from __future__ import annotations

    import argparse
    import csv
    import json
    from pathlib import Path

    ALLOWED_ROLES = {'admin', 'member', 'viewer'}

    def is_valid_email(value: str) -> bool:
        return '@' in value and '.' in value.split('@')[-1]

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument('--input', required=True)
        parser.add_argument('--out-dir', required=True)
        args = parser.parse_args()

        input_path = Path(args.input)
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        accepted = []
        rejected = []
        seen_emails = set()
        duplicate_count = 0

        with input_path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                normalized_email = row['email'].strip().lower()
                role = row['role'].strip()
                if not is_valid_email(normalized_email):
                    rejected.append({**row, 'reason': 'invalid email'})
                    continue
                if role not in ALLOWED_ROLES:
                    rejected.append({**row, 'reason': 'invalid role'})
                    continue
                if normalized_email in seen_emails:
                    duplicate_count += 1
                    rejected.append({**row, 'reason': 'duplicate email'})
                    continue
                seen_emails.add(normalized_email)
                accepted.append({'name': row['name'].strip(), 'email': normalized_email, 'role': role})

        (out_dir / 'accepted.json').write_text(json.dumps(accepted, indent=2) + '\\n', encoding='utf-8')
        with (out_dir / 'rejected.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['name', 'email', 'role', 'reason'])
            writer.writeheader()
            writer.writerows(rejected)
        (out_dir / 'summary.json').write_text(
            json.dumps(
                {
                    'accepted_count': len(accepted),
                    'rejected_count': len(rejected),
                    'duplicate_count': duplicate_count,
                    'processed_count': len(accepted) + len(rejected),
                },
                indent=2,
            )
            + '\\n',
            encoding='utf-8',
        )
        return 0

    if __name__ == '__main__':
        raise SystemExit(main())
    '''
).strip() + '\n'

BUGGY_APP = inspect.cleandoc(
    '''
    from __future__ import annotations

    import argparse
    import csv
    import json
    from pathlib import Path

    ALLOWED_ROLES = {'admin', 'member', 'viewer'}

    def is_valid_email(value: str) -> bool:
        return '@' in value

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument('--input', required=True)
        parser.add_argument('--out-dir', required=True)
        args = parser.parse_args()

        input_path = Path(args.input)
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        accepted = []
        rejected = []
        seen_emails = set()
        duplicate_count = 0

        with input_path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                raw_email = row['email']
                role = row['role']
                if raw_email in seen_emails:
                    duplicate_count += 0  # BUG: duplicate count never increments
                else:
                    seen_emails.add(raw_email)
                if role not in ALLOWED_ROLES:
                    rejected.append({**row, 'reason': ''})  # BUG: blank reason
                    continue
                accepted.append({'name': row['name'], 'email': raw_email, 'role': role})  # BUG: no normalization

        (out_dir / 'accepted.json').write_text(json.dumps(accepted, indent=2) + '\\n', encoding='utf-8')
        with (out_dir / 'rejected.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['name', 'email', 'role', 'reason'])
            writer.writeheader()
            writer.writerows(rejected)
        (out_dir / 'summary.json').write_text(
            json.dumps(
                {
                    'accepted_count': len(accepted) + 1,  # BUG: wrong count
                    'rejected_count': len(rejected),
                    'duplicate_count': duplicate_count,
                    'processed_count': len(accepted),  # BUG: wrong count
                },
                indent=2,
            )
            + '\\n',
            encoding='utf-8',
        )
        return 0

    if __name__ == '__main__':
        raise SystemExit(main())
    '''
).strip() + '\n'


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / 'app'
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / '__init__.py').write_text('', encoding='utf-8')
    (app_dir / 'import_members.py').write_text(app_source, encoding='utf-8')
    (workspace / 'README.md').write_text('# CSV member import\n', encoding='utf-8')
    (workspace / 'pyproject.toml').write_text('[project]\nname = "csv-member-import"\nversion = "0.1.0"\n', encoding='utf-8')


def _write_run(run_path: Path, workspace: Path, run_id: str) -> None:
    run_path.write_text(
        json.dumps(
            {
                'run_id': run_id,
                'workspace': str(workspace),
                'artifacts': {
                    'changed_files': ['app/import_members.py', 'README.md', 'pyproject.toml'],
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


class CsvBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, 'csv_good_001')

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / '.agentharness' / 'evaluation' / TASK_ID / 'summary.txt').read_text(encoding='utf-8')
            self.assertIn('valid_rows_normalized=pass', summary_text)
            self.assertIn('summary_counts_correct=pass', summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = 'csv_cli_good_001'
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
            run_id = 'csv_cli_buggy_001'
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
            self.assertIn('valid_rows_normalized', hidden_payload['failed_checks'])
            self.assertIn('duplicate_handling_correct', hidden_payload['failed_checks'])
            self.assertIn('invalid_rows_rejected_with_reason', hidden_payload['failed_checks'])
            self.assertIn('summary_counts_correct', hidden_payload['failed_checks'])

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
            run_id = 'csv_evalrun_good_001'
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
