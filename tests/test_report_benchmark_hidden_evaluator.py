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
TASK_ID = 'report-export-job'

GOOD_APP = inspect.cleandoc(
    '''
    from __future__ import annotations

    import argparse
    import csv
    import json
    import os
    import sqlite3
    from collections import defaultdict
    from datetime import datetime
    from pathlib import Path

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument('--date', required=True)
        parser.add_argument('--out-dir', required=True)
        args = parser.parse_args()

        try:
            datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            raise SystemExit(2)

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get('REPORT_DB_PATH', 'report.db'))

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT merchant_id, payout_amount, refund_amount FROM records WHERE record_date = ? ORDER BY merchant_id ASC',
                (args.date,),
            ).fetchall()
        finally:
            connection.close()

        aggregates: dict[str, dict[str, float | int]] = defaultdict(lambda: {'gross_payout': 0.0, 'refund_total': 0.0, 'transaction_count': 0})
        for merchant_id, payout_amount, refund_amount in rows:
            item = aggregates[merchant_id]
            item['gross_payout'] += float(payout_amount)
            item['refund_total'] += float(refund_amount)
            item['transaction_count'] += 1

        csv_rows = []
        for merchant_id in sorted(aggregates):
            item = aggregates[merchant_id]
            gross = float(item['gross_payout'])
            refunds = float(item['refund_total'])
            net = gross - refunds
            csv_rows.append(
                {
                    'merchant_id': merchant_id,
                    'gross_payout': f'{gross:.2f}',
                    'refund_total': f'{refunds:.2f}',
                    'net_payout': f'{net:.2f}',
                    'transaction_count': str(item['transaction_count']),
                }
            )

        with (out_dir / 'report.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['merchant_id', 'gross_payout', 'refund_total', 'net_payout', 'transaction_count'])
            writer.writeheader()
            writer.writerows(csv_rows)

        summary = {
            'export_date': args.date,
            'merchant_count': len(csv_rows),
            'total_gross': round(sum(float(row['gross_payout']) for row in csv_rows), 2),
            'total_refunds': round(sum(float(row['refund_total']) for row in csv_rows), 2),
            'total_net': round(sum(float(row['net_payout']) for row in csv_rows), 2),
        }
        (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\\n', encoding='utf-8')
        return 0

    if __name__ == '__main__':
        raise SystemExit(main())
    '''
).strip() + '\n'

SPEC_ALIGNED_GOOD_APP = inspect.cleandoc(
    '''
    from __future__ import annotations

    import argparse
    import csv
    import json
    import os
    import sqlite3
    from collections import defaultdict
    from datetime import datetime
    from pathlib import Path

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument('--date', required=True)
        parser.add_argument('--out-dir', required=True)
        args = parser.parse_args()

        try:
            datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            raise SystemExit(2)

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get('REPORT_DB_PATH', 'report.db'))

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT merchant_id, payout_amount, refund_amount FROM records WHERE date = ? ORDER BY merchant_id ASC',
                (args.date,),
            ).fetchall()
        finally:
            connection.close()

        aggregates: dict[str, dict[str, float | int]] = defaultdict(lambda: {'gross_payout': 0.0, 'refund_total': 0.0, 'transaction_count': 0})
        for merchant_id, payout_amount, refund_amount in rows:
            item = aggregates[merchant_id]
            item['gross_payout'] += float(payout_amount)
            item['refund_total'] += float(refund_amount)
            item['transaction_count'] += 1

        csv_rows = []
        for merchant_id in sorted(aggregates):
            item = aggregates[merchant_id]
            gross = float(item['gross_payout'])
            refunds = float(item['refund_total'])
            net = gross - refunds
            csv_rows.append(
                {
                    'merchant_id': merchant_id,
                    'gross_payout': f'{gross:.2f}',
                    'refund_total': f'{refunds:.2f}',
                    'net_payout': f'{net:.2f}',
                    'transaction_count': str(item['transaction_count']),
                }
            )

        with (out_dir / 'report.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['merchant_id', 'gross_payout', 'refund_total', 'net_payout', 'transaction_count'])
            writer.writeheader()
            writer.writerows(csv_rows)

        summary = {
            'date': args.date,
            'merchant_count': len(csv_rows),
            'total_gross': round(sum(float(row['gross_payout']) for row in csv_rows), 2),
            'total_refunds': round(sum(float(row['refund_total']) for row in csv_rows), 2),
            'total_net': round(sum(float(row['net_payout']) for row in csv_rows), 2),
        }
        (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\\n', encoding='utf-8')
        return 0

    if __name__ == '__main__':
        raise SystemExit(main())
    '''
).strip() + '\n'

DESCRIPTIVE_SUMMARY_KEYS_APP = inspect.cleandoc(
    '''
    from __future__ import annotations

    import argparse
    import csv
    import json
    import os
    import sqlite3
    from collections import defaultdict
    from datetime import datetime
    from pathlib import Path

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument('--date', required=True)
        parser.add_argument('--out-dir', required=True)
        args = parser.parse_args()

        try:
            datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            raise SystemExit(2)

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get('REPORT_DB_PATH', 'report.db'))

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT merchant_id, payout_amount, refund_amount FROM records WHERE record_date = ? ORDER BY merchant_id ASC',
                (args.date,),
            ).fetchall()
        finally:
            connection.close()

        aggregates: dict[str, dict[str, float | int]] = defaultdict(lambda: {'gross_payout': 0.0, 'refund_total': 0.0, 'transaction_count': 0})
        for merchant_id, payout_amount, refund_amount in rows:
            item = aggregates[merchant_id]
            item['gross_payout'] += float(payout_amount)
            item['refund_total'] += float(refund_amount)
            item['transaction_count'] += 1

        csv_rows = []
        for merchant_id in sorted(aggregates):
            item = aggregates[merchant_id]
            gross = float(item['gross_payout'])
            refunds = float(item['refund_total'])
            net = gross - refunds
            csv_rows.append(
                {
                    'merchant_id': merchant_id,
                    'gross_payout': f'{gross:.2f}',
                    'refund_total': f'{refunds:.2f}',
                    'net_payout': f'{net:.2f}',
                    'transaction_count': str(item['transaction_count']),
                }
            )

        with (out_dir / 'report.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['merchant_id', 'gross_payout', 'refund_total', 'net_payout', 'transaction_count'])
            writer.writeheader()
            writer.writerows(csv_rows)

        summary = {
            'export_date': args.date,
            'merchant_count': len(csv_rows),
            'total_gross_payout': round(sum(float(row['gross_payout']) for row in csv_rows), 2),
            'total_refund_total': round(sum(float(row['refund_total']) for row in csv_rows), 2),
            'total_net_payout': round(sum(float(row['net_payout']) for row in csv_rows), 2),
        }
        (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\\n', encoding='utf-8')
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
    import os
    import sqlite3
    from collections import defaultdict
    from pathlib import Path

    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument('--date', required=True)
        parser.add_argument('--out-dir', required=True)
        args = parser.parse_args()

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get('REPORT_DB_PATH', 'report.db'))

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT merchant_id, payout_amount, refund_amount FROM records ORDER BY merchant_id DESC',  # BUG: ignores date filter and sorting
            ).fetchall()
        finally:
            connection.close()

        aggregates: dict[str, dict[str, float | int]] = defaultdict(lambda: {'gross_payout': 0.0, 'refund_total': 0.0, 'transaction_count': 0})
        for merchant_id, payout_amount, refund_amount in rows:
            item = aggregates[merchant_id]
            item['gross_payout'] += float(payout_amount)
            item['refund_total'] += float(refund_amount)
            item['transaction_count'] += 1

        csv_rows = []
        for merchant_id in sorted(aggregates, reverse=True):
            item = aggregates[merchant_id]
            gross = float(item['gross_payout'])
            refunds = float(item['refund_total'])
            net = gross + refunds  # BUG: wrong net formula
            csv_rows.append(
                {
                    'merchant_id': merchant_id,
                    'gross_payout': f'{gross:.2f}',
                    'refund_total': f'{refunds:.2f}',
                    'net_payout': f'{net:.2f}',
                    'transaction_count': str(item['transaction_count']),
                }
            )

        with (out_dir / 'report.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['merchant_id', 'gross_payout', 'refund_total', 'net_payout', 'transaction_count'])
            writer.writeheader()
            writer.writerows(csv_rows)

        summary = {
            'export_date': args.date,
            'merchant_count': 999,  # BUG: wrong summary
            'total_gross': 0.0,
            'total_refunds': 0.0,
            'total_net': 0.0,
        }
        (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\\n', encoding='utf-8')
        return 0

    if __name__ == '__main__':
        raise SystemExit(main())
    '''
).strip() + '\n'


def _write_workspace(workspace: Path, app_source: str) -> None:
    app_dir = workspace / 'app'
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / '__init__.py').write_text('', encoding='utf-8')
    (app_dir / 'export.py').write_text(app_source, encoding='utf-8')
    (workspace / 'README.md').write_text('# Report export job\n', encoding='utf-8')
    (workspace / 'pyproject.toml').write_text('[project]\nname = "report-export-job"\nversion = "0.1.0"\ndependencies = ["pytest"]\n', encoding='utf-8')


def _write_run(run_path: Path, workspace: Path, run_id: str) -> None:
    run_path.write_text(
        json.dumps(
            {
                'run_id': run_id,
                'workspace': str(workspace),
                'artifacts': {
                    'changed_files': ['app/export.py', 'README.md', 'pyproject.toml'],
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


class ReportBenchmarkHiddenEvaluatorTests(unittest.TestCase):
    def test_library_evaluator_writes_hidden_outputs_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, 'report_good_001')

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])
            summary_text = (workspace / '.agentharness' / 'evaluation' / TASK_ID / 'summary.txt').read_text(encoding='utf-8')
            self.assertIn('csv_rows_sorted_complete=pass', summary_text)
            self.assertIn('summary_totals_match=pass', summary_text)

    def test_cli_render_hidden_evaluate_and_evaluate_pass_for_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, GOOD_APP)
            run_id = 'report_cli_good_001'
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

    def test_library_evaluator_accepts_spec_aligned_date_column_and_summary_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, SPEC_ALIGNED_GOOD_APP)
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, 'report_spec_aligned_001')

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])

    def test_library_evaluator_accepts_descriptive_summary_total_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, DESCRIPTIVE_SUMMARY_KEYS_APP)
            run_path = temp_root / 'run.json'
            _write_run(run_path, workspace, 'report_descriptive_summary_keys_001')

            result = evaluate_benchmark_task(run_path, TASK_ID)

            self.assertTrue(result.critical_ok)
            self.assertEqual(result.failed_checks, [])

    def test_cli_evaluate_fails_for_buggy_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            workspace = temp_root / 'workspace'
            workspace.mkdir()
            _write_workspace(workspace, BUGGY_APP)
            run_id = 'report_cli_buggy_001'
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
            self.assertIn('csv_rows_sorted_complete', hidden_payload['failed_checks'])
            self.assertIn('net_totals_correct', hidden_payload['failed_checks'])
            self.assertIn('date_filter_applied', hidden_payload['failed_checks'])
            self.assertIn('summary_totals_match', hidden_payload['failed_checks'])
            self.assertIn('invalid_date_rejected', hidden_payload['failed_checks'])

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
            run_id = 'report_evalrun_good_001'
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
