#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"
OUTPUT_DIR = BENCHMARKS / "grading-env" / "task-expansion-batch1"
REPORT_JSON = OUTPUT_DIR / "TASK_EXPANSION_BATCH1_ACCEPTANCE.json"
REPORT_MD = OUTPUT_DIR / "TASK_EXPANSION_BATCH1_ACCEPTANCE.md"
TASKS = {
    "appointment-booking-api": {
        "family": "interval_scheduling",
        "nearest": "leave-request-api",
        "difference": "resource-scoped half-open interval allocation with atomic rescheduling and slot release, not approval workflow or leave policy",
        "checks": {
            "appointment_create_and_filters": "durable resource reservation projection across app reload plus compound filtering",
            "appointment_interval_validation": "strict timestamp interval validity with timezone normalization",
            "appointment_provider_conflicts": "resource-keyed half-open overlap semantics",
            "appointment_reschedule_atomic": "atomic replacement of a reserved interval",
            "appointment_cancel_releases_slot": "terminal cancellation coupled to capacity release",
        },
    },
    "shipment-event-api": {
        "family": "ordered_event_projection",
        "nearest": "webhook-ingestion-service",
        "difference": "ordered append-only lifecycle projection with exact next-state and temporal monotonicity, not signature validation or generic webhook ingestion",
        "checks": {
            "shipment_create_and_filters": "durable empty event projection across app reload plus shipment filters",
            "shipment_valid_transition_path": "full ordered finite-state transition path",
            "shipment_skipped_transition_atomic": "exact-next-transition rejection with immutable projection",
            "shipment_event_idempotency": "per-aggregate replay identity versus conflicting replay",
            "shipment_time_and_terminal_invariants": "monotonic event time and terminal projected state",
        },
    },
    "jsonl-event-aggregation": {
        "family": "stream_aggregation",
        "nearest": "csv-member-import",
        "difference": "multi-key UTC aggregation with unique-actor cardinality and deterministic group totals, not row import/update semantics",
        "checks": {
            "jsonl_grouped_counts": "multi-dimensional aggregate counts, cardinality, and totals",
            "jsonl_utc_date_normalization": "timezone-offset normalization before grouping",
            "jsonl_invalid_and_duplicate_handling": "first-valid stream identity and auditable rejection ordering",
            "jsonl_summary_consistency": "conservation invariants across groups and rejected records",
            "jsonl_deterministic_outputs": "byte-stable aggregate and rejection artifacts",
        },
    },
    "invoice-payment-reconciliation": {
        "family": "exact_reconciliation",
        "nearest": "report-export-job",
        "difference": "one-to-many exact-decimal matching with cutoff, overpayment, and unmatched conservation, not export formatting of precomputed records",
        "checks": {
            "reconciliation_rows_and_order": "eligibility cutoff and complete ordered ledger projection",
            "reconciliation_cutoff_and_duplicates": "as-of and first-valid payment identity semantics",
            "reconciliation_status_and_decimals": "exact decimal allocation including negative overpayment balance",
            "reconciliation_unmatched_reporting": "conserved unmatched and duplicate payment trail",
            "reconciliation_summary_and_validation": "cross-artifact financial reconciliation and atomic invalid-input failure",
        },
    },
}
PAIRWISE_NEW_TASK_OVERLAP = [
    {
        "left": "appointment-booking-api",
        "right": "shipment-event-api",
        "shared_shell": "durable FastAPI create/detail/filter surface",
        "substantive_difference": "half-open resource interval allocation and atomic rescheduling versus append-only ordered event projection and exact next-state transitions",
    },
    {
        "left": "appointment-booking-api",
        "right": "jsonl-event-aggregation",
        "shared_shell": "timestamp normalization",
        "substantive_difference": "stateful resource capacity and terminal release versus stateless deterministic multi-key stream aggregation",
    },
    {
        "left": "appointment-booking-api",
        "right": "invoice-payment-reconciliation",
        "shared_shell": "validation with atomic rejection",
        "substantive_difference": "interactive interval scheduling versus exact-decimal two-ledger cutoff reconciliation",
    },
    {
        "left": "shipment-event-api",
        "right": "jsonl-event-aggregation",
        "shared_shell": "event records with identity and timestamps",
        "substantive_difference": "per-aggregate ordered lifecycle projection versus cross-record UTC grouping and conservation totals",
    },
    {
        "left": "shipment-event-api",
        "right": "invoice-payment-reconciliation",
        "shared_shell": "identity, ordering, and auditable projections",
        "substantive_difference": "online finite-state event ingestion versus offline exact-decimal payment allocation across ledgers",
    },
    {
        "left": "jsonl-event-aggregation",
        "right": "invoice-payment-reconciliation",
        "shared_shell": "deterministic CLI artifacts and rejected/unmatched evidence",
        "substantive_difference": "single-stream multi-key aggregation versus two-input one-to-many financial reconciliation with cutoff",
    },
]
PROCESS_CLAIM_TYPES = {"forbidden_paths", "tests_executed", "artifact_present"}
VISIBLE_ALLOWLIST = {"SPEC.md", "CLAIMS_CONTRACT.template.json"}
FORBIDDEN_VISIBLE_TOKENS = {
    "A-baseline",
    "B-agentharness",
    "treatment",
    "repair guidance",
    "evaluation_result_schema",
    "=pass",
    "=fail",
    ".agentharness/evaluation",
}
CANARY_LITERALS = {
    "TRK-FLT-91",
    "TRK-PATH-37",
    "C-A17",
    "P-RESCHEDULE",
    "evt-a91",
    "evt-first-valid",
    "INV-500",
    "PAY-6",
    "2034-08-15",
}
FORBIDDEN_TREE_NAMES = {".git", ".pytest_cache", "__pycache__", ".coverage"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": bool(ok), "detail": detail}


def static_audit() -> tuple[dict[str, Any], dict[str, str]]:
    results: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    sensitivity = json.loads((OUTPUT_DIR / "MUTATION_SENSITIVITY.json").read_text(encoding="utf-8"))["tasks"]
    for task_id, cfg in TASKS.items():
        root = BENCHMARKS / task_id
        task_checks: dict[str, Any] = {}
        required = {"SPEC.md", "CLAIMS_CONTRACT.template.json", "HELDOUT_EVALUATION_SUITE.template.json", "QUALITY_GATE.md"}
        present = {path.name for path in root.iterdir()} if root.is_dir() else set()
        task_checks["required_pack_files"] = check(required <= present, f"present={sorted(present)}")
        visible_text = "\n".join((root / name).read_text(encoding="utf-8") for name in sorted(VISIBLE_ALLOWLIST) if (root / name).is_file())
        token_hits = sorted(token for token in FORBIDDEN_VISIBLE_TOKENS if token.lower() in visible_text.lower())
        canary_hits = sorted(token for token in CANARY_LITERALS if token in visible_text)
        check_id_hits = sorted(check_id for check_id in cfg["checks"] if check_id in visible_text)
        task_checks["visible_allowlist_non_leakage"] = check(not token_hits and not canary_hits and not check_id_hits, f"token_hits={token_hits}; canary_hits={canary_hits}; check_id_hits={check_id_hits}")
        claims = json.loads((root / "CLAIMS_CONTRACT.template.json").read_text(encoding="utf-8"))
        claim_types = {item.get("type") for item in claims.get("claims", [])}
        task_checks["claims_process_only"] = check(bool(claim_types) and claim_types <= PROCESS_CLAIM_TYPES, f"types={sorted(str(x) for x in claim_types)}")
        suite = json.loads((root / "HELDOUT_EVALUATION_SUITE.template.json").read_text(encoding="utf-8"))
        case_ids = [item.get("id") for item in suite.get("cases", [])]
        expected_ids = list(cfg["checks"]) + ["evaluation_result_schema"]
        task_checks["five_functional_plus_schema"] = check(case_ids == expected_ids, f"case_ids={case_ids}")
        sensitivity_rows = sensitivity.get(task_id, {})
        sensitivity_ok = set(sensitivity_rows) == set(cfg["checks"]) and all(
            isinstance(row.get("expected_failed_checks"), list)
            and check_id in row["expected_failed_checks"]
            and set(row["expected_failed_checks"]) <= set(cfg["checks"])
            and isinstance(row.get("rationale"), str)
            and bool(row["rationale"].strip())
            for check_id, row in sensitivity_rows.items()
        )
        task_checks["frozen_mutation_sensitivity"] = check(sensitivity_ok, f"mutants={sorted(sensitivity_rows)}")
        bad_nodes = []
        for path in root.rglob("*"):
            if path.is_symlink() or path.name in FORBIDDEN_TREE_NAMES or path.suffix == ".pyc":
                bad_nodes.append(str(path.relative_to(root)))
        task_checks["clean_pack_tree"] = check(not bad_nodes, f"bad_nodes={bad_nodes}")
        reference = OUTPUT_DIR / "references" / task_id
        reference_ok = reference.is_dir() and (reference / "README.md").is_file() and (reference / "pyproject.toml").is_file()
        task_checks["hidden_reference_present"] = check(reference_ok, str(reference.relative_to(REPO_ROOT)))
        results[task_id] = task_checks
    expected_pairs = {tuple(sorted(pair)) for pair in itertools.combinations(TASKS, 2)}
    observed_pairs = {tuple(sorted((row.get("left", ""), row.get("right", "")))) for row in PAIRWISE_NEW_TASK_OVERLAP}
    pairwise_ok = observed_pairs == expected_pairs and len(PAIRWISE_NEW_TASK_OVERLAP) == len(expected_pairs) and all(
        isinstance(row.get("shared_shell"), str)
        and bool(row["shared_shell"].strip())
        and isinstance(row.get("substantive_difference"), str)
        and bool(row["substantive_difference"].strip())
        for row in PAIRWISE_NEW_TASK_OVERLAP
    )
    results["_batch"] = {
        "complete_pairwise_new_task_overlap": check(pairwise_ok, f"pairs={sorted(observed_pairs)}")
    }
    for base in [*(BENCHMARKS / task_id for task_id in TASKS), REPO_ROOT / "src" / "agentharness" / "benchmark_hidden_evaluators.py", REPO_ROOT / "src" / "agentharness" / "benchmark_hidden_evaluators_batch1.py", REPO_ROOT / "benchmarks" / "grading-env" / "audit_task_expansion_batch1.py", REPO_ROOT / "tests" / "test_task_expansion_batch1.py", OUTPUT_DIR / "MUTATION_SENSITIVITY.json", OUTPUT_DIR / "references"]:
        paths = [base] if base.is_file() else sorted(path for path in base.rglob("*") if path.is_file() and path.name not in FORBIDDEN_TREE_NAMES and path.suffix != ".pyc")
        for path in paths:
            hashes[str(path.relative_to(REPO_ROOT))] = sha256(path)
    return results, hashes


def overlap_matrix() -> list[dict[str, str]]:
    rows = []
    for task_id, cfg in TASKS.items():
        for check_id, construct in cfg["checks"].items():
            rows.append({"task_id": task_id, "family": cfg["family"], "check_id": check_id, "construct": construct, "nearest_existing_task": cfg["nearest"], "substantive_difference": cfg["difference"]})
    return rows


def run_validation_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_task_expansion_batch1.py"]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900, check=False)
    return {
        "ok": completed.returncode == 0,
        "command": "PYTHONPATH=src " + " ".join(command),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Task Expansion Batch 1 Acceptance", "", f"- Generated: {payload['generated_at']}", f"- Base commit before batch artifacts: `{payload['base_commit']}`", f"- Overall: **{'GO' if payload['go'] else 'NO-GO'}**", "- Efficacy cells collected: **0**", "", "## Task gates"]
    for task_id, task_checks in payload["static_checks"].items():
        lines += ["", f"### {task_id}"]
        for name, result in task_checks.items():
            lines.append(f"- {'PASS' if result['ok'] else 'FAIL'} `{name}`: {result['detail']}")
    lines += ["", "## Dynamic validation", "", f"- {'PASS' if payload['dynamic_tests']['ok'] else 'FAIL'} `{payload['dynamic_tests']['command']}`", "", "```text", payload["dynamic_tests"]["stdout"].strip(), payload["dynamic_tests"]["stderr"].strip(), "```", "", "## Overlap matrix", "", "Each of the 20 checks has a declared nearest existing task and a substantive distinction. The machine-readable rows are in the JSON report.", "", "## Interpretation boundary", "", "This GO, if granted, accepts only task-pack construction and evaluator adequacy. It does not authorize an A/B pilot or confirmatory campaign.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()
    static_checks, hashes = static_audit()
    dynamic = run_validation_tests() if args.run_tests else {"ok": False, "command": "not run", "exit_code": None, "stdout": "", "stderr": "dynamic tests required for GO"}
    static_ok = all(item["ok"] for task in static_checks.values() for item in task.values())
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_commit": commit,
        "efficacy_cells_collected": 0,
        "task_ids": list(TASKS),
        "static_checks": static_checks,
        "dynamic_tests": dynamic,
        "overlap_matrix": overlap_matrix(),
        "new_task_pairwise_overlap": PAIRWISE_NEW_TASK_OVERLAP,
        "artifact_sha256": hashes,
        "go": bool(static_ok and dynamic["ok"]),
        "authorization": "task-pack acceptance only; no A/B or confirmatory launch",
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({"go": payload["go"], "report": str(REPORT_JSON), "static_ok": static_ok, "dynamic_ok": dynamic["ok"]}, indent=2))
    return 0 if payload["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
