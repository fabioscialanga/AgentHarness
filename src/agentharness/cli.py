from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import BootstrapOptions, bootstrap_project
from .evaluation import evaluate_run
from .generation import generate_framework_outputs
from .resilience import run_resilience_plan
from .validation import validate_project_directory
from .verification import verify_project_directory
from .verify import verify_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentharness",
        description="Work with AgentHarness-style project definitions",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a project directory containing project.yaml and related artifacts",
    )
    validate_parser.add_argument("path", type=Path, help="Path to the project directory")
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the validation result as JSON",
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate .framework outputs from project.yaml",
    )
    generate_parser.add_argument("path", type=Path, help="Path to the project directory")
    generate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the generation result as JSON",
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify a project directory for semantic contract consistency and drift in generated .framework artifacts",
    )
    verify_parser.add_argument("path", type=Path, help="Path to the project directory")
    verify_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the verification result as JSON",
    )
    verify_parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write .framework/verification-report.json with the verification result",
    )

    verify_run_parser = subparsers.add_parser(
        "verify-run",
        help="Verify claim-based agent run evidence against explicit claims",
    )
    verify_run_parser.add_argument("--run", type=Path, required=True, help="Path to the run JSON artifact")
    verify_run_parser.add_argument("--claims", type=Path, required=True, help="Path to the claims JSON document")
    verify_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the claim verification result as JSON",
    )
    verify_run_parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write a verify-run report next to the run artifact unless --report-path is set",
    )
    verify_run_parser.add_argument(
        "--report-path",
        type=Path,
        help="Optional explicit output path for the verify-run report JSON",
    )
    verify_run_parser.add_argument(
        "--reexecute-tests",
        choices=("auto", "never"),
        default="auto",
        help="How verify-run should establish test truth: auto prefers controlled reexecution for allowed pytest wrappers (pytest, python -m pytest, uv run pytest), never disables reexecution and relies on parsed evidence only",
    )
    verify_run_parser.add_argument(
        "--reexecution-timeout",
        type=int,
        default=60,
        help="Timeout in seconds for controlled test command reexecution",
    )
    verify_run_parser.add_argument(
        "--trace-jsonl",
        type=Path,
        help="Optional JSONL trace path for structured verify-run events",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Run deterministic evaluation cases against a run artifact and its workspace outputs",
    )
    evaluate_parser.add_argument("--run", type=Path, required=True, help="Path to the run JSON artifact")
    evaluate_parser.add_argument("--suite", type=Path, required=True, help="Path to the evaluation suite JSON")
    evaluate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the evaluation result as JSON",
    )
    evaluate_parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write an evaluation report next to the run artifact unless --report-path is set",
    )
    evaluate_parser.add_argument(
        "--report-path",
        type=Path,
        help="Optional explicit output path for the evaluation report JSON",
    )
    evaluate_parser.add_argument(
        "--trace-jsonl",
        type=Path,
        help="Optional JSONL trace path for structured evaluation events",
    )

    resilient_run_parser = subparsers.add_parser(
        "run-plan",
        help="Execute a retry-aware plan with fallback targets and audit trail artifacts",
    )
    resilient_run_parser.add_argument("--plan", type=Path, required=True, help="Path to the resilience plan JSON")
    resilient_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the resilient execution result as JSON",
    )
    resilient_run_parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write a resilience report next to the plan unless --report-path is set",
    )
    resilient_run_parser.add_argument(
        "--report-path",
        type=Path,
        help="Optional explicit output path for the resilience report JSON",
    )
    resilient_run_parser.add_argument(
        "--trace-jsonl",
        type=Path,
        help="Optional JSONL trace path for structured resilience events",
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Scaffold a new AgentHarness project from a minimal contract",
    )
    bootstrap_parser.add_argument("path", type=Path, help="Target project directory to create")
    bootstrap_parser.add_argument("--project-name", required=True, help="Human-readable project name")
    bootstrap_parser.add_argument("--project-slug", required=True, help="Stable lowercase project slug")
    bootstrap_parser.add_argument("--project-type", default="open_source_web_api", help="Project type label")
    bootstrap_parser.add_argument("--language", default="python", help="Primary implementation language")
    bootstrap_parser.add_argument("--framework", default="fastapi", help="Primary framework")
    bootstrap_parser.add_argument("--database", default="postgres", help="Primary database")
    bootstrap_parser.add_argument("--package-manager", default="uv", help="Package manager")
    bootstrap_parser.add_argument("--license", dest="license_name", default="MIT", help="License name")
    bootstrap_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the bootstrap result as JSON",
    )
    return parser


def _print_validation_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] {result.project_dir}")
    if result.errors:
        print("Errors:")
        for item in result.errors:
            print(f"- {item}")
    if result.warnings:
        print("Warnings:")
        for item in result.warnings:
            print(f"- {item}")
    if result.notes:
        print("Notes:")
        for item in result.notes:
            print(f"- {item}")


def _print_generation_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"[OK] {result.project_dir}")
    print("Files written:")
    for item in result.files_written:
        print(f"- {item}")
    print("Generated checks:")
    for item in result.generated_checks:
        print(f"- {item}")


def _print_verification_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] {result.project_dir}")
    print("Compared generated files:")
    for item in result.compared_files:
        print(f"- {item}")
    if result.errors:
        print("Errors:")
        for item in result.errors:
            print(f"- {item}")
    if result.notes:
        print("Notes:")
        for item in result.notes:
            print(f"- {item}")
    if result.report_written:
        print(f"Report written: {result.report_written}")


def _print_verify_run_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] run {result.run_id}")
    print(f"Run artifact: {result.run_path}")
    print(f"Claims document: {result.claims_path}")

    if result.gating_errors:
        print("Gating errors:")
        for error in result.gating_errors:
            print(f"- {error}")

    grouped = {
        "supported": [],
        "unsupported": [],
        "inconclusive": [],
        "invalid": [],
    }
    for item in result.results:
        grouped.setdefault(item.status, []).append(item)

    for group_name in ("supported", "unsupported", "inconclusive", "invalid"):
        items = grouped.get(group_name, [])
        if not items:
            continue
        print(group_name.upper())
        for item in items:
            evidence = f" | evidence: {', '.join(item.evidence)}" if item.evidence else ""
            truth_source = f" | truth: {item.truth_source}" if item.truth_source else ""
            print(f"- {item.claim_id} [{item.claim_type}]: {item.statement} -> {item.reason}{truth_source}{evidence}")

    summary = result.summary
    print(
        "Summary: "
        f"{summary.get('supported', 0)} supported, "
        f"{summary.get('unsupported', 0)} unsupported, "
        f"{summary.get('inconclusive', 0)} inconclusive, "
        f"{summary.get('invalid', 0)} invalid"
    )
    if result.blocking_claim_ids:
        print(f"Blocking claims: {', '.join(result.blocking_claim_ids)}")
    if result.notes:
        print("Notes:")
        for note in result.notes:
            print(f"- {note}")
    if result.report_written:
        print(f"Report written: {result.report_written}")
    if result.trace_path:
        print(f"Trace written: {result.trace_path}")


def _print_evaluation_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] evaluation {result.suite_id} for run {result.run_id}")
    for item in result.results:
        evidence = f" | evidence: {', '.join(item.evidence)}" if item.evidence else ""
        print(f"- {item.case_id} [{item.case_type}] -> {item.status}: {item.reason}{evidence}")
    summary = result.summary
    print(
        "Summary: "
        f"{summary.get('passed', 0)} passed, "
        f"{summary.get('failed', 0)} failed, "
        f"{summary.get('invalid', 0)} invalid"
    )
    if result.gating_errors:
        print("Gating errors:")
        for error in result.gating_errors:
            print(f"- {error}")
    if result.report_written:
        print(f"Report written: {result.report_written}")
    if result.trace_path:
        print(f"Trace written: {result.trace_path}")


def _print_resilient_run_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] plan {result.plan_id}")
    for step in result.steps:
        winner = step.winner or "none"
        print(f"- {step.step_id}: {'OK' if step.ok else 'FAIL'} | winner: {winner}")
        for attempt in step.attempts:
            retry_note = (
                f" | retry in {attempt.next_delay_seconds:.3f}s"
                if attempt.retry_scheduled and attempt.next_delay_seconds is not None
                else ""
            )
            print(
                f"  - target={attempt.target_name} attempt={attempt.attempt} exit={attempt.exit_code} cwd={attempt.cwd}{retry_note}"
            )
    if result.trace_path:
        print(f"Trace written: {result.trace_path}")


def _print_bootstrap_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"[OK] {result.project_dir}")
    print("Files written:")
    for item in result.files_written:
        print(f"- {item}")
    print(f"Validation after bootstrap: {'PASS' if result.validation_ok else 'FAIL'}")
    print("Generated checks:")
    for item in result.generated_checks:
        print(f"- {item}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        result = validate_project_directory(args.path)
        _print_validation_result(result, args.json)
        return 0 if result.ok else 1

    if args.command == "generate":
        result = generate_framework_outputs(args.path)
        _print_generation_result(result, args.json)
        return 0

    if args.command == "verify":
        result = verify_project_directory(
            args.path,
            write_report=args.write_report,
        )
        _print_verification_result(result, args.json)
        return 0 if result.ok else 1

    if args.command == "verify-run":
        result = verify_run(
            args.run,
            args.claims,
            write_report=args.write_report,
            report_path=args.report_path,
            reexecute_mode=args.reexecute_tests,
            reexecution_timeout=args.reexecution_timeout,
            trace_path=args.trace_jsonl,
        )
        _print_verify_run_result(result, args.json)
        return 0 if result.ok else 1

    if args.command == "evaluate":
        result = evaluate_run(
            args.run,
            args.suite,
            write_report=args.write_report,
            report_path=args.report_path,
            trace_path=args.trace_jsonl,
        )
        _print_evaluation_result(result, args.json)
        return 0 if result.ok else 1

    if args.command == "run-plan":
        result = run_resilience_plan(
            args.plan,
            write_report=args.write_report,
            report_path=args.report_path,
            trace_path=args.trace_jsonl,
        )
        _print_resilient_run_result(result, args.json)
        return 0 if result.ok else 1

    if args.command == "bootstrap":
        options = BootstrapOptions(
            project_name=args.project_name,
            project_slug=args.project_slug,
            project_type=args.project_type,
            language=args.language,
            framework=args.framework,
            database=args.database,
            package_manager=args.package_manager,
            license_name=args.license_name,
        )
        result = bootstrap_project(args.path, options)
        _print_bootstrap_result(result, args.json)
        return 0 if result.validation_ok else 1

    parser.error("Unknown command")
    return 2
