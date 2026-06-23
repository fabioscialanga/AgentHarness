from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .checks import evaluate_claim
from .models import ClaimResult, ClaimsDocument, RunRecord, VerifyRunResult
from .observability import EventLogger, default_trace_path
from .reexecution import ExecutionPolicy, default_execution_policy


def load_run(path: str | Path) -> RunRecord:
    run_path = Path(path).resolve()
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    workspace = Path(payload.get("workspace", "."))
    if not workspace.is_absolute():
        payload["workspace"] = str((run_path.parent / workspace).resolve())
    return RunRecord.from_dict(payload)


def load_claims(path: str | Path) -> ClaimsDocument:
    claims_path = Path(path).resolve()
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


def _validate_run_documents(run: RunRecord, claims_document: ClaimsDocument) -> list[str]:
    errors: list[str] = []

    if not run.run_id.strip():
        errors.append("Run artifact is missing a non-empty run_id.")
    if not claims_document.run_id.strip():
        errors.append("Claims document is missing a non-empty run_id.")
    if not claims_document.claims:
        errors.append("Claims document must contain at least one claim.")

    if run.run_id.strip() and claims_document.run_id.strip() and claims_document.run_id != run.run_id:
        errors.append(
            "Claims document run_id does not match run artifact run_id; "
            "verification is rejected because the claims are bound to a different run."
        )

    if run.run_id.strip() and not _is_safe_run_namespace(run.run_id):
        errors.append(
            "Run artifact run_id must be a path-safe evidence namespace without separators or traversal segments."
        )
    if claims_document.run_id.strip() and not _is_safe_run_namespace(claims_document.run_id):
        errors.append(
            "Claims document run_id must be a path-safe evidence namespace without separators or traversal segments."
        )

    seen_claim_ids: set[str] = set()
    duplicate_claim_ids: set[str] = set()
    for claim in claims_document.claims:
        if claim.id in seen_claim_ids:
            duplicate_claim_ids.add(claim.id)
        seen_claim_ids.add(claim.id)
    if duplicate_claim_ids:
        errors.append(
            "Claims document contains duplicate claim ids: " + ", ".join(sorted(duplicate_claim_ids))
        )

    blank_changed_files = [index for index, path in enumerate(run.changed_files, start=1) if not path.strip()]
    if blank_changed_files:
        errors.append(
            "Run artifact contains blank changed_files entries at positions: "
            + ", ".join(str(index) for index in blank_changed_files)
        )

    blank_command_slots = [index for index, command in enumerate(run.commands, start=1) if not command.cmd.strip()]
    if blank_command_slots:
        errors.append(
            "Run artifact contains commands with empty cmd fields at positions: "
            + ", ".join(str(index) for index in blank_command_slots)
        )

    blank_output_slots = [index for index, output in enumerate(run.outputs, start=1) if not output.path.strip()]
    if blank_output_slots:
        errors.append(
            "Run artifact contains outputs with empty path fields at positions: "
            + ", ".join(str(index) for index in blank_output_slots)
        )

    return errors


def _is_safe_run_namespace(run_id: str) -> bool:
    candidate = run_id.strip()
    if not candidate or candidate in {".", ".."}:
        return False
    if "/" in candidate or "\\" in candidate:
        return False
    return True


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(
    run_path: str | Path,
    claims_path: str | Path,
    *,
    write_report: bool = False,
    report_path: str | Path | None = None,
    reexecute_mode: str = "auto",
    reexecution_timeout: int = 60,
    execution_policy: ExecutionPolicy | None = None,
    trace_path: str | Path | None = None,
) -> VerifyRunResult:
    resolved_run_path = Path(run_path).resolve()
    resolved_claims_path = Path(claims_path).resolve()

    run_sha256 = _sha256_file(resolved_run_path)
    claims_sha256 = _sha256_file(resolved_claims_path)
    run = load_run(resolved_run_path)
    claims_document = load_claims(resolved_claims_path)
    policy = execution_policy or default_execution_policy(
        mode=reexecute_mode,
        timeout_seconds=reexecution_timeout,
    )
    logger: EventLogger | None = None
    if trace_path:
        logger = EventLogger.create(output_path=trace_path, run_id=run.run_id)
    elif run.workspace.exists():
        logger = EventLogger.create(output_path=default_trace_path(run.workspace, "verify-run"), run_id=run.run_id)

    results = []
    gating_errors = _validate_run_documents(run, claims_document)
    notes = list(gating_errors)

    if logger:
        logger.emit(
            "verify_run_started",
            run_path=str(resolved_run_path),
            claims_path=str(resolved_claims_path),
            policy=policy.to_dict(),
        )

    if gating_errors:
        results = [
            ClaimResult(
                claim_id=claim.id,
                claim_type=claim.type,
                statement=claim.statement,
                status="invalid",
                reason="Verification aborted because the run or claims envelope failed gating checks",
                truth_source="none",
                audit={"gating_errors": gating_errors},
            )
            for claim in claims_document.claims
        ]
    else:
        for claim in claims_document.claims:
            claim_result = evaluate_claim(run, claim, execution_policy=policy)
            results.append(claim_result)
            if logger:
                logger.emit(
                    "verify_run_claim_finished",
                    claim_id=claim.id,
                    claim_type=claim.type,
                    status=claim_result.status,
                    reason=claim_result.reason,
                    truth_source=claim_result.truth_source,
                    evidence=claim_result.evidence,
                )

    result = VerifyRunResult(
        run_id=run.run_id,
        run_path=resolved_run_path,
        claims_path=resolved_claims_path,
        results=results,
        run_sha256=run_sha256,
        claims_sha256=claims_sha256,
        tool_version=__version__,
        evaluated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        notes=notes,
        gating_errors=gating_errors,
        trace_path=str(logger.output_path) if logger else None,
        audit_trail={
            "policy": policy.to_dict(),
            "run_sha256": run_sha256,
            "claims_sha256": claims_sha256,
        },
    )

    if logger:
        logger.emit(
            "verify_run_finished",
            ok=result.ok,
            summary=result.summary,
            blocking_claim_ids=result.blocking_claim_ids,
        )

    if write_report:
        written_path = write_verify_run_report(result, report_path)
        result.report_written = str(written_path)

    return result
