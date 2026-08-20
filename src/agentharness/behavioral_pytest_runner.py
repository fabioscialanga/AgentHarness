from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


RESULT_PREFIX = "AGENTHARNESS_BEHAVIORAL_RESULT="
IGNORED_TEST_CACHE_NAMES = frozenset({"__pycache__", ".pytest_cache"})


def _fingerprint_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        candidate
        for candidate in root.rglob("*")
        if not any(part in IGNORED_TEST_CACHE_NAMES for part in candidate.relative_to(root).parts)
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        info = path.lstat()
        digest.update((info.st_mode & 0o7777).to_bytes(4, "big"))
        if path.is_symlink():
            kind = b"symlink"
            content = os.readlink(path).encode("utf-8", errors="surrogateescape")
        elif path.is_dir():
            kind, content = b"directory", b""
        elif path.is_file():
            kind, content = b"file", path.read_bytes()
        else:
            kind, content = b"other", b""
        digest.update(len(kind).to_bytes(4, "big"))
        digest.update(kind)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class _ExactOutcomePlugin:
    def __init__(self, expected_nodeid: str, workspace: Path, test_root: Path) -> None:
        self.expected_nodeid = expected_nodeid
        self.workspace = workspace
        self.test_root = test_root
        self.collected: list[str] = []
        self.reports: list[dict[str, Any]] = []
        self.collection_failures: list[str] = []

    def pytest_collection_finish(self, session: Any) -> None:
        self.collected = [str(item.nodeid) for item in session.items]

    def pytest_runtest_logreport(self, report: Any) -> None:
        if str(report.nodeid) != self.expected_nodeid:
            return
        self.reports.append(
            {
                "nodeid": str(report.nodeid),
                "when": str(report.when),
                "outcome": str(report.outcome),
                "passed": bool(report.passed),
                "failed": bool(report.failed),
                "skipped": bool(report.skipped),
                "wasxfail": str(report.wasxfail) if hasattr(report, "wasxfail") else None,
                "longrepr": str(report.longrepr) if report.failed else None,
            }
        )

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.collection_failures.append(str(report.longrepr))

    def result(self, pytest_exit_code: int, *, bundle_integrity_ok: bool) -> dict[str, Any]:
        matching_collected = [item for item in self.collected if item == self.expected_nodeid]
        relevant = [item for item in self.reports if item["nodeid"] == self.expected_nodeid]
        call_reports = [item for item in relevant if item["when"] == "call"]
        setup_or_teardown_failures = [
            item for item in relevant if item["when"] in {"setup", "teardown"} and item["failed"]
        ]
        skipped_or_xfailed = [item for item in relevant if item["skipped"] or item["wasxfail"] is not None]

        collection_text = "\n".join(self.collection_failures)
        without_trusted_paths = collection_text.replace(str(self.test_root), "<trusted-test-root>")
        reviewed_source_caused_collection_failure = (
            bool(collection_text)
            and f"{self.workspace}{os.sep}" in without_trusted_paths
        )
        if not bundle_integrity_ok:
            status = "diagnostic"
            reason = "Trusted test bundle changed during collection or execution"
        elif len(matching_collected) != 1:
            if reviewed_source_caused_collection_failure:
                status = "failed"
                reason = "Reviewed source caused trusted-test import or collection failure"
            else:
                status = "diagnostic"
                reason = (
                    "The exact trusted test was not collected exactly once "
                    f"(expected 1, observed {len(matching_collected)})"
                )
        elif skipped_or_xfailed:
            status = "diagnostic"
            reason = "The exact trusted test was skipped or xfailed, so it did not establish the behavior"
        elif setup_or_teardown_failures:
            status = "failed"
            reason = "The exact trusted test failed during setup or teardown"
        elif len(call_reports) != 1:
            status = "diagnostic"
            reason = "The exact trusted test did not produce exactly one call-phase result"
        elif call_reports[0]["passed"] and pytest_exit_code == 0:
            status = "passed"
            reason = "The exact trusted test was collected once and passed"
        elif call_reports[0]["failed"]:
            status = "failed"
            reason = "The exact trusted test failed"
        else:
            status = "diagnostic"
            reason = "The exact trusted test did not produce an authoritative pass or fail outcome"

        return {
            "schema_version": "1.0",
            "expected_nodeid": self.expected_nodeid,
            "status": status,
            "reason": reason,
            "pytest_exit_code": pytest_exit_code,
            "collected": self.collected,
            "reports": relevant,
            "collection_failures": self.collection_failures,
            "test_bundle_integrity_ok": bundle_integrity_ok,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--nodeid", required=True)
    parser.add_argument("--test-bundle-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = Path(args.workspace).resolve()
    test_root = Path(args.test_root).resolve()
    try:
        test_root.relative_to(workspace)
    except ValueError:
        print(
            RESULT_PREFIX
            + json.dumps(
                {
                    "schema_version": "1.0",
                    "expected_nodeid": args.nodeid,
                    "status": "diagnostic",
                    "reason": "Trusted test root is not inside the review snapshot",
                    "pytest_exit_code": None,
                    "collected": [],
                    "reports": [],
                },
                sort_keys=True,
            )
        )
        return 3

    if _fingerprint_tree(test_root) != args.test_bundle_sha256:
        print(
            RESULT_PREFIX
            + json.dumps(
                {
                    "schema_version": "1.0",
                    "expected_nodeid": args.nodeid,
                    "status": "diagnostic",
                    "reason": "Trusted test bundle fingerprint did not match before collection",
                    "pytest_exit_code": None,
                    "collected": [],
                    "reports": [],
                    "test_bundle_integrity_ok": False,
                },
                sort_keys=True,
            )
        )
        return 3

    # Import pytest before making reviewed source importable. -P and the execution
    # policy keep the workspace and inherited PYTHONPATH out of interpreter startup.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest  # noqa: PLC0415

    sys.path.insert(0, str(workspace))
    os.chdir(workspace)
    expected_nodeid = f"{test_root.relative_to(workspace).as_posix()}/{args.nodeid}"
    plugin = _ExactOutcomePlugin(expected_nodeid, workspace, test_root)
    target = str(test_root / args.nodeid)
    pytest_exit_code = int(
        pytest.main(
            [
                "-q",
                "-c",
                os.devnull,
                f"--rootdir={workspace}",
                f"--confcutdir={test_root}",
                "-p",
                "no:cacheprovider",
                target,
            ],
            plugins=[plugin],
        )
    )
    payload = plugin.result(
        pytest_exit_code,
        bundle_integrity_ok=_fingerprint_tree(test_root) == args.test_bundle_sha256,
    )
    print(RESULT_PREFIX + json.dumps(payload, sort_keys=True))
    if payload["status"] == "passed":
        return 0
    if payload["status"] == "failed":
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
