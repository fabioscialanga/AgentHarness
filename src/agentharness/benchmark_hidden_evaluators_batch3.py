from __future__ import annotations

from pathlib import Path

from .benchmark_hidden_evaluators import HiddenEvaluationResult
from .benchmark_hidden_evaluators_batch3_lease import evaluate_lease
from .benchmark_hidden_evaluators_batch3_ledger import evaluate_ledger
from .benchmark_hidden_evaluators_batch3_pii import evaluate_pii
from .benchmark_hidden_evaluators_batch3_signed import evaluate_signed


def evaluate_batch3_task(workspace: Path, task_id: str) -> HiddenEvaluationResult:
    evaluators = {
        "signed-artifact-verifier": evaluate_signed,
        "pii-redaction-pipeline": evaluate_pii,
        "lease-coordination-api": evaluate_lease,
        "double-entry-ledger-api": evaluate_ledger,
    }
    try:
        evaluator = evaluators[task_id]
    except KeyError as exc:
        raise ValueError(f"unsupported batch3 task: {task_id}") from exc
    return evaluator(workspace)
