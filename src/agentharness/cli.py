from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import BootstrapOptions, bootstrap_project
from .generation import generate_framework_outputs
from .validation import validate_project_directory


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
