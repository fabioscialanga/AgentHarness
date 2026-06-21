from __future__ import annotations

import json
from pathlib import Path

from .checks import evaluate_claim
from .models import ClaimsDocument, RunRecord, VerifyRunResult


def load_run(path: str | Path) -> RunRecord:
    run_path = Path(path).resolve()
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    workspace = Path(payload.get("workspace", "."))
    if not workspace.is_absolute():
        payload["workspace"] = str((run_path.parent / workspace).resolve())
    return RunRecord.from_dict(payload)


def load_claims(path: str | Path) -> ClaimsDocument:
    claims_path = Path(path)
    payload = json.loads(claims_path.read_text(encoding="utf-8"))
    return ClaimsDocument.from_dict(payload)


def default_verify_run_report_path(run_path: str | Path) -> Path:
    resolved_run_path = Path(run_path).resolve()
    return resolved_run_path.parent / f"{resolved_run_path.stem}.verify-report.json"


def write_verify_run_report(result: VerifyRunResult, output_path: str | Path | None = None) -> Path:
    report_path = Path(output_path) if output_path else default_verify_run_report_path(result.run_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.report_written = str(report_path)
    report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report_path


def verify_run(
    run_path: str | Path,
    claims_path: str | Path,
    *,
    write_report: bool = False,
    report_path: str | Path | None = None,
) -> VerifyRunResult:
    resolved_run_path = Path(run_path).resolve()
    resolved_claims_path = Path(claims_path).resolve()

    run = load_run(resolved_run_path)
    claims_document = load_claims(resolved_claims_path)

    results = []
    notes: list[str] = []

    if claims_document.run_id and run.run_id and claims_document.run_id != run.run_id:
        notes.append(
            "Claims document run_id does not match run artifact run_id; claims were still evaluated against the provided run."
        )

    for claim in claims_document.claims:
        results.append(evaluate_claim(run, claim))

    result = VerifyRunResult(
        run_id=run.run_id,
        run_path=resolved_run_path,
        claims_path=resolved_claims_path,
        results=results,
        notes=notes,
    )

    if write_report:
        written_path = write_verify_run_report(result, report_path)
        result.report_written = str(written_path)

    return result
