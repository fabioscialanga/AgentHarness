from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from pathlib import Path
from typing import Any

from .benchmark_hidden_evaluators import (
    HiddenEvaluationResult,
    _evaluation_dir,
    _finalize_hidden_evaluation,
    _interface_unreachable_result,
    _run_python_entrypoint,
)
from .benchmark_hidden_evaluators_batch1 import _recorder
from .benchmark_hidden_evaluators_batch2 import _finish_runtime

_TASK = "pii-redaction-pipeline"
_CHECKS = (
    "pii_selector_resolution",
    "pii_redaction_actions",
    "pii_structure_preservation",
    "pii_rule_precedence",
    "pii_atomic_audit",
)
_CANDIDATES = ["pii_redactor/redact.py", "src/pii_redactor/redact.py"]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _pseudonym(secret_hex: str, value: Any) -> str:
    return "hmac-sha256:" + hmac.new(
        bytes.fromhex(secret_hex), _canonical(value), hashlib.sha256
    ).hexdigest()


def _rules(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "rules": items}


def _audit(
    path: str, rule_id: str, selector: str, action: str
) -> dict[str, str]:
    return {
        "path": path,
        "rule_id": rule_id,
        "selector": selector,
        "action": action,
    }


def evaluate_pii(workspace: Path) -> HiddenEvaluationResult:
    """Black-box evaluator for the batch-3 PII redaction CLI."""

    observations, passed, failed, record = _recorder()
    try:
        with tempfile.TemporaryDirectory(prefix="ah-pii-complete-") as td:
            root = Path(td)
            input_path = root / "input.json"
            rules_path = root / "rules.json"
            key_path = root / "key.json"
            output_path = root / "bundle.json"

            def write_value(path: Path, value: Any) -> None:
                path.write_bytes(_canonical(value))

            def invoke(
                document: Any,
                rule_document: Any,
                key_document: Any = None,
                *,
                raw_input: bytes | None = None,
                raw_rules: bytes | None = None,
                raw_key: bytes | None = None,
            ):
                if raw_input is None:
                    write_value(input_path, document)
                else:
                    input_path.write_bytes(raw_input)
                if raw_rules is None:
                    write_value(rules_path, rule_document)
                else:
                    rules_path.write_bytes(raw_rules)
                if raw_key is None:
                    write_value(
                        key_path,
                        {"secret_hex": "00112233445566778899aabbccddeeff"}
                        if key_document is None
                        else key_document,
                    )
                else:
                    key_path.write_bytes(raw_key)
                return _run_python_entrypoint(
                    workspace,
                    _CANDIDATES,
                    [
                        "--input",
                        str(input_path),
                        "--rules",
                        str(rules_path),
                        "--key",
                        str(key_path),
                        "--output-bundle",
                        str(output_path),
                    ],
                )

            def successful(document: Any, items: list[dict[str, Any]], key=None):
                run = invoke(document, _rules(items), key)
                if run.returncode != 0:
                    return run, None
                try:
                    return run, json.loads(output_path.read_bytes())
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    return run, None

            def rejection(
                label: str,
                document: Any,
                rule_document: Any,
                key_document: Any = None,
                **raw: Any,
            ) -> tuple[bool, str]:
                sentinel = ("preserve:" + label).encode("utf-8")
                output_path.write_bytes(sentinel)
                before_names = {p.name for p in root.iterdir()}
                run = invoke(
                    document,
                    rule_document,
                    key_document,
                    raw_input=raw.get("raw_input"),
                    raw_rules=raw.get("raw_rules"),
                    raw_key=raw.get("raw_key"),
                )
                after_names = {p.name for p in root.iterdir()}
                staged = [
                    p.name
                    for p in root.iterdir()
                    if p.name not in before_names
                    or (p.name.startswith(f".{output_path.name}.") and p.is_file())
                ]
                ok = (
                    run.returncode != 0
                    and output_path.read_bytes() == sentinel
                    and not staged
                    and before_names == after_names
                    and "Traceback" not in run.stderr
                )
                return ok, (
                    f"{label}:exit={run.returncode},preserved="
                    f"{output_path.read_bytes() == sentinel},staging={staged},"
                    f"controlled={'Traceback' not in run.stderr}"
                )

            # Selector resolution: escaped tokens, exact array indexes, middle and
            # terminal object wildcards, unmatched no-ops, and no fuzzy indexes.
            selector_doc = [
                {
                    "a/b": {"~key": "slash-tilde"},
                    "arr": [10, 20],
                    "star": {"*": "literal-star"},
                },
                {"a/b": {"~key": "middle-wildcard"}, "other": {"plain": 1}},
            ]
            selector_rules = [
                {"id": "escape", "selector": "/0/a~1b/~0key", "action": "redact", "replacement": "E"},
                {"id": "index", "selector": "/0/arr/1", "action": "redact", "replacement": "I"},
                {"id": "middle", "selector": "/1/*/~0key", "action": "redact", "replacement": "M"},
                {"id": "object-star", "selector": "/0/star/*", "action": "redact", "replacement": "W"},
                {"id": "no-fuzzy", "selector": "/0/arr/01", "action": "redact", "replacement": "BAD"},
                {"id": "unmatched", "selector": "/9/missing", "action": "remove"},
            ]
            selector_run, selector_bundle = successful(selector_doc, selector_rules)
            selector_expected = [
                {"a/b": {"~key": "E"}, "arr": [10, "I"], "star": {"*": "W"}},
                {"a/b": {"~key": "M"}, "other": {"plain": 1}},
            ]
            invalid_selectors = []
            for label, selector in (
                ("root", ""),
                ("relative", "users/0"),
                ("bad-escape", "/a~2b"),
                ("short-escape", "/a~"),
            ):
                invalid_selectors.append(
                    rejection(
                        label,
                        selector_doc,
                        _rules([
                            {"id": label, "selector": selector, "action": "remove"}
                        ]),
                    )
                )
            selector_ok = (
                selector_run.returncode == 0
                and isinstance(selector_bundle, dict)
                and selector_bundle.get("redacted") == selector_expected
                and all(ok for ok, _ in invalid_selectors)
            )
            middle_wildcard_supported = (
                selector_run.returncode == 0
                and isinstance(selector_bundle, dict)
                and isinstance(selector_bundle.get("redacted"), list)
                and selector_bundle["redacted"][1]["a/b"]["~key"] == "M"
            )
            record(
                _CHECKS[0],
                selector_ok,
                f"exit={selector_run.returncode}; redacted="
                f"{selector_bundle.get('redacted') if isinstance(selector_bundle, dict) else None}; "
                f"invalid={[detail for _, detail in invalid_selectors]}",
            )

            # All actions apply to scalar and composite JSON. HMAC input is
            # canonical JSON and changing the key must change the pseudonym.
            action_doc = ["scalar", 42, True, None, {"z": 1, "a": [True, None]}, [3, 2, 1]]
            redact_items = [
                {"id": f"r{i}", "selector": f"/{i}", "action": "redact", "replacement": f"R{i}"}
                for i in range(len(action_doc))
            ]
            redact_run, redact_bundle = successful(action_doc, redact_items)
            pseudo_items = [
                {"id": f"p{i}", "selector": f"/{i}", "action": "pseudonymize"}
                for i in range(len(action_doc))
            ]
            key_a = {"secret_hex": "01020304"}
            key_b = {"secret_hex": "a1a2a3a4"}
            pseudo_a_run, pseudo_a = successful(action_doc, pseudo_items, key_a)
            pseudo_b_run, pseudo_b = successful(action_doc, pseudo_items, key_b)
            pseudo_expected = [_pseudonym(key_a["secret_hex"], x) for x in action_doc]
            remove_doc = {
                "values": {
                    "string": "s", "number": 1, "boolean": True, "null": None,
                    "object": {"nested": 1}, "array": [1, 2],
                },
                "adjacent": ["a", "b", "c", "d"],
            }
            remove_items = [
                {"id": "all-types", "selector": "/values/*", "action": "remove"},
                {"id": "array-one", "selector": "/adjacent/1", "action": "remove"},
                {"id": "array-two", "selector": "/adjacent/2", "action": "remove"},
            ]
            remove_run, remove_bundle = successful(remove_doc, remove_items)
            actions_ok = (
                redact_run.returncode == 0
                and redact_bundle is not None
                and redact_bundle.get("redacted") == [f"R{i}" for i in range(len(action_doc))]
                and pseudo_a_run.returncode == pseudo_b_run.returncode == 0
                and pseudo_a is not None
                and pseudo_b is not None
                and pseudo_a.get("redacted") == pseudo_expected
                and pseudo_b.get("redacted")
                == [_pseudonym(key_b["secret_hex"], x) for x in action_doc]
                and pseudo_a.get("redacted") != pseudo_b.get("redacted")
                and remove_run.returncode == 0
                and remove_bundle is not None
                and remove_bundle.get("redacted") == {"values": {}, "adjacent": ["a", "d"]}
            )
            record(
                _CHECKS[1],
                actions_ok,
                f"redact={redact_bundle}; pseudo_a="
                f"{pseudo_a.get('redacted') if isinstance(pseudo_a, dict) else None}; "
                f"pseudo_b={pseudo_b.get('redacted') if isinstance(pseudo_b, dict) else None}; "
                f"remove={remove_bundle}",
            )

            # Untouched values and JSON types survive exactly. Descendant work is
            # based on original paths; an ancestor transformation has the final say.
            structure_doc = {
                "branch": {"secret": {"deep": "value"}, "keep": [1, None, False]},
                "array": [{"secret": "first", "keep": 1}, {"secret": "second"}],
                "untouched": {"unicode": "café", "number": 1.25},
            }
            structure_items = [
                {"id": "deep", "selector": "/branch/secret/deep", "action": "redact", "replacement": "deep-redacted"},
                {"id": "ancestor", "selector": "/branch/secret", "action": "redact", "replacement": "ancestor-redacted"},
                {"id": "child-before-remove", "selector": "/array/0/secret", "action": "redact", "replacement": "hidden"},
                {"id": "remove-ancestor", "selector": "/array/0", "action": "remove"},
            ]
            structure_run, structure_bundle = successful(structure_doc, structure_items)
            structure_expected = {
                "branch": {"secret": "ancestor-redacted", "keep": [1, None, False]},
                "array": [{"secret": "second"}],
                "untouched": {"unicode": "café", "number": 1.25},
            }
            structure_ok = (
                structure_run.returncode == 0
                and structure_bundle is not None
                and structure_bundle.get("redacted") == structure_expected
            )
            record(
                _CHECKS[2],
                structure_ok,
                f"exit={structure_run.returncode}; redacted="
                f"{structure_bundle.get('redacted') if isinstance(structure_bundle, dict) else None}",
            )

            # Exact beats wildcard. Identical rule semantics at equal specificity
            # are accepted; any semantic difference (including selector) rejects.
            precedence_doc = [{"v": "secret", "w": "other"}]
            precedence_items = [
                {"id": "wild", "selector": "/0/*", "action": "redact", "replacement": "W"},
                {"id": "exact", "selector": "/0/v", "action": "redact", "replacement": "E"},
            ]
            precedence_run, precedence_bundle = successful(precedence_doc, precedence_items)
            identical_items = [
                {"id": "z", "selector": "/0/v", "action": "redact", "replacement": "SAME"},
                {"id": "a", "selector": "/0/v", "action": "redact", "replacement": "SAME"},
            ]
            identical_run, identical_bundle = successful(precedence_doc, identical_items)
            conflict_cases = [
                (
                    "different-replacement",
                    [
                        {"id": "a", "selector": "/0/v", "action": "redact", "replacement": "A"},
                        {"id": "b", "selector": "/0/v", "action": "redact", "replacement": "B"},
                    ],
                ),
                (
                    "different-action",
                    [
                        {"id": "a", "selector": "/0/v", "action": "redact", "replacement": "A"},
                        {"id": "b", "selector": "/0/v", "action": "remove"},
                    ],
                ),
                (
                    "different-selector",
                    [
                        {"id": "a", "selector": "/0/*", "action": "redact", "replacement": "A"},
                        {"id": "b", "selector": "/*/v", "action": "redact", "replacement": "A"},
                    ],
                ),
                (
                    "duplicate-id",
                    [
                        {"id": "dup", "selector": "/0/v", "action": "remove"},
                        {"id": "dup", "selector": "/0/w", "action": "remove"},
                    ],
                ),
            ]
            conflict_results = [
                rejection(label, precedence_doc, _rules(items))
                for label, items in conflict_cases
            ]
            # The different-selector overlap depends on middle-wildcard resolution.
            # Do not cascade a broken selector implementation into this check.
            conflicts_ok = (
                all(ok for ok, _ in conflict_results[:2])
                and (conflict_results[2][0] or not middle_wildcard_supported)
                and conflict_results[3][0]
            )
            # Rule and object-member permutations must not alter output bytes.
            perm_doc_a = {"b": {"x": 2}, "a": {"v": "one"}}
            perm_doc_b = {"a": {"v": "one"}, "b": {"x": 2}}
            perm_items_a = [
                {"id": "b", "selector": "/b/x", "action": "redact", "replacement": "X"},
                {"id": "a", "selector": "/a/v", "action": "redact", "replacement": "V"},
            ]
            perm_run_a, _ = successful(perm_doc_a, perm_items_a)
            perm_bytes_a = output_path.read_bytes() if perm_run_a.returncode == 0 else b""
            perm_run_b, _ = successful(perm_doc_b, list(reversed(perm_items_a)))
            perm_bytes_b = output_path.read_bytes() if perm_run_b.returncode == 0 else b"!"
            precedence_ok = (
                precedence_run.returncode == 0
                and precedence_bundle is not None
                and precedence_bundle.get("redacted") == [{"v": "E", "w": "W"}]
                and identical_run.returncode == 0
                and identical_bundle is not None
                and identical_bundle.get("redacted") == [{"v": "SAME", "w": "other"}]
                and conflicts_ok
                and perm_run_a.returncode == perm_run_b.returncode == 0
                and perm_bytes_a == perm_bytes_b
            )
            record(
                _CHECKS[3],
                precedence_ok,
                f"precedence={precedence_bundle}; identical_exit={identical_run.returncode}; "
                f"conflicts={[detail for _, detail in conflict_results]}; "
                f"permutation_bytes={perm_bytes_a == perm_bytes_b}",
            )

            # Exact bundle/audit schemas, values, correspondence and canonical path
            # order, plus deterministic bytes and byte-preserving controlled errors.
            audit_doc_a = [
                {"a/b": "slash", "z": "last"},
                {"til~de": "tilde", "remove": "gone"},
            ]
            audit_doc_b = [
                {"z": "last", "a/b": "slash"},
                {"remove": "gone", "til~de": "tilde"},
            ]
            audit_items = [
                {"id": "slash", "selector": "/0/a~1b", "action": "redact", "replacement": "S"},
                {"id": "zulu", "selector": "/0/z", "action": "redact", "replacement": "Z"},
                {"id": "tilde", "selector": "/1/til~0de", "action": "redact", "replacement": "T"},
                {"id": "remove", "selector": "/1/remove", "action": "remove"},
            ]
            audit_run_a, audit_bundle = successful(audit_doc_a, audit_items)
            audit_bytes_a = output_path.read_bytes() if audit_run_a.returncode == 0 else b""
            audit_run_b, audit_bundle_b = successful(audit_doc_b, list(reversed(audit_items)))
            audit_bytes_b = output_path.read_bytes() if audit_run_b.returncode == 0 else b"!"
            expected_audit = [
                _audit("/0/a~1b", "slash", "/0/a~1b", "redact"),
                _audit("/0/z", "zulu", "/0/z", "redact"),
                _audit("/1/remove", "remove", "/1/remove", "remove"),
                _audit("/1/til~0de", "tilde", "/1/til~0de", "redact"),
            ]
            expected_redacted = [{"a/b": "S", "z": "Z"}, {"til~de": "T"}]
            malformed_cases = [
                ("malformed-input", None, _rules([]), None, {"raw_input": b"{bad"}),
                ("scalar-input", 7, _rules([]), None, {}),
                ("malformed-rules", {}, None, None, {"raw_rules": b"[bad"}),
                ("rules-extra", {}, {"schema_version": 1, "rules": [], "extra": 1}, None, {}),
                ("rule-extra", {}, _rules([{"id": "x", "selector": "/x", "action": "remove", "extra": 1}]), None, {}),
                ("bad-action", {}, _rules([{"id": "x", "selector": "/x", "action": "hash"}]), None, {}),
                ("missing-replacement", {}, _rules([{"id": "x", "selector": "/x", "action": "redact"}]), None, {}),
                ("extra-replacement", {}, _rules([{"id": "x", "selector": "/x", "action": "remove", "replacement": "x"}]), None, {}),
                ("malformed-key", {}, _rules([]), None, {"raw_key": b"{bad"}),
                ("key-extra", {}, _rules([]), {"secret_hex": "00", "extra": 1}, {}),
                ("key-empty", {}, _rules([]), {"secret_hex": ""}, {}),
                ("key-odd", {}, _rules([]), {"secret_hex": "abc"}, {}),
                ("key-nonhex", {}, _rules([]), {"secret_hex": "zz"}, {}),
            ]
            malformed_results = [
                rejection(label, document, rule_doc, key_doc, **raw)
                for label, document, rule_doc, key_doc, raw in malformed_cases
            ]
            audit_schema = (
                isinstance(audit_bundle, dict)
                and set(audit_bundle) == {"redacted", "audit"}
                and isinstance(audit_bundle.get("audit"), list)
                and all(
                    isinstance(row, dict)
                    and set(row) == {"path", "rule_id", "selector", "action"}
                    and all(isinstance(value, str) for value in row.values())
                    for row in audit_bundle.get("audit", [])
                )
            )
            audit_redacted = (
                audit_bundle.get("redacted") if isinstance(audit_bundle, dict) else None
            )
            audit_rows = audit_bundle.get("audit") if isinstance(audit_bundle, dict) else None
            atomic_ok = (
                audit_run_a.returncode == audit_run_b.returncode == 0
                and audit_schema
                and audit_redacted == expected_redacted
                and audit_rows == expected_audit
                and audit_bundle_b == audit_bundle
                and audit_bytes_a == audit_bytes_b
                and audit_bytes_a == _canonical(audit_bundle) + b"\n"
                and all(ok for ok, _ in malformed_results)
            )
            record(
                _CHECKS[4],
                atomic_ok,
                f"exit={audit_run_a.returncode}/{audit_run_b.returncode}; "
                f"schema={audit_schema}; audit="
                f"{audit_bundle.get('audit') if isinstance(audit_bundle, dict) else None}; "
                f"deterministic={audit_bytes_a == audit_bytes_b}; malformed="
                f"{[detail for _, detail in malformed_results]}",
            )
    except FileNotFoundError as exc:
        return _interface_unreachable_result(
            task_id=_TASK,
            evaluation_dir=_evaluation_dir(workspace, _TASK),
            passed_checks=passed,
            failed_checks=failed,
            observations=observations,
            check_ids=_CHECKS,
            detail=str(exc),
            reason="interface_unreachable:cli_or_output_missing",
        )
    except Exception as exc:
        return _finish_runtime(
            _TASK,
            workspace,
            _CHECKS,
            observations,
            passed,
            failed,
            record,
            exc,
        )
    return _finalize_hidden_evaluation(
        task_id=_TASK,
        evaluation_dir=_evaluation_dir(workspace, _TASK),
        passed_checks=passed,
        failed_checks=failed,
        observations=observations,
    )


__all__ = ["evaluate_pii"]
