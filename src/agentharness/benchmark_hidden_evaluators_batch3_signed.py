from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import shutil
import socket
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

TASK_ID = "signed-artifact-verifier"
CHECKS = (
    "signed_manifest_authenticity",
    "signed_manifest_inventory",
    "signed_manifest_content_integrity",
    "signed_manifest_trust_window",
    "signed_manifest_atomic_report",
)
ENTRYPOINTS = ["artifact_verifier/verify.py", "src/artifact_verifier/verify.py"]
SECRET = bytes.fromhex("37" * 32)
DECOY_SECRET = bytes.fromhex("a4" * 16)
SENTINEL = b"pre-existing report: preserve exactly\n\x00"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _controlled(result: Any) -> bool:
    return result.returncode != 0 and bool(result.stderr.strip()) and "Traceback" not in result.stderr


class _Fixture:
    def __init__(self, root: Path, workspace: Path) -> None:
        self.root = root
        self.workspace = workspace
        self.artifacts = root / "artifacts"
        self.manifest_path = root / "manifest.json"
        self.keyring_path = root / "keyring.json"
        self.report = root / "report.json"
        self.files: dict[str, bytes] = {
            "dír/β.txt": "snowman: ☃\n".encode("utf-8"),
            "z.bin": b"\x00\xffz",
        }
        self.manifest: dict[str, Any] = {}
        self.keyring: dict[str, Any] = {}
        self.reset()

    def reset(self) -> None:
        if self.artifacts.exists() or self.artifacts.is_symlink():
            if self.artifacts.is_dir() and not self.artifacts.is_symlink():
                shutil.rmtree(self.artifacts)
            else:
                self.artifacts.unlink()
        self.artifacts.mkdir()
        for name, data in self.files.items():
            target = self.artifacts / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if self.report.exists() or self.report.is_symlink():
            if self.report.is_dir() and not self.report.is_symlink():
                shutil.rmtree(self.report)
            else:
                self.report.unlink()
        self.keyring = {
            "schema_version": 1,
            "keys": [
                {
                    "key_id": "decoy-key",
                    "secret_hex": DECOY_SECRET.hex(),
                    "valid_from": "2020-01-01T00:00:00Z",
                    "valid_until": "2021-01-01T00:00:00Z",
                },
                {
                    "key_id": "selected.key-1",
                    "secret_hex": SECRET.hex(),
                    "valid_from": "2030-01-01T00:00:00Z",
                    "valid_until": "2040-01-01T00:00:00Z",
                },
            ],
        }
        self.manifest = {
            "schema_version": 1,
            "key_id": "selected.key-1",
            "valid_from": "2031-01-01T00:00:00Z",
            "valid_until": "2039-01-01T00:00:00Z",
            "files": [
                {"path": name, "size": len(data), "sha256": _digest(data)}
                for name, data in reversed(list(self.files.items()))
            ],
        }
        self.write_keyring()
        self.sign()

    def write_keyring(self, raw: str | None = None) -> None:
        self.keyring_path.write_text(
            raw if raw is not None else json.dumps(self.keyring, ensure_ascii=True, indent=1),
            encoding="utf-8",
        )

    def sign(self, secret: bytes = SECRET, raw: str | None = None) -> None:
        if raw is not None:
            self.manifest_path.write_text(raw, encoding="utf-8")
            return
        payload = copy.deepcopy(self.manifest)
        payload.pop("signature", None)
        self.manifest["signature"] = hmac.new(secret, _canonical(payload), hashlib.sha256).hexdigest()
        # Deliberately non-canonical source bytes prove that signing canonicalizes the parsed payload.
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    def run(
        self,
        as_of: str = "2035-06-01T12:00:00Z",
        output: Path | None = None,
        env: dict[str, str] | None = None,
        artifact_root: Path | None = None,
    ) -> Any:
        return _run_python_entrypoint(
            self.workspace,
            ENTRYPOINTS,
            [
                "--manifest", str(self.manifest_path),
                "--keyring", str(self.keyring_path),
                "--artifact-root", str(artifact_root or self.artifacts),
                "--as-of", as_of,
                "--output", str(output or self.report),
            ],
            env=env,
        )


def _expected_report(fx: _Fixture) -> dict[str, Any]:
    files = [
        {"path": path, "size": len(data), "sha256": _digest(data)}
        for path, data in sorted(fx.files.items())
    ]
    return {
        "ok": True,
        "key_id": "selected.key-1",
        "manifest_sha256": _digest(fx.manifest_path.read_bytes()),
        "file_count": len(files),
        "total_bytes": sum(len(data) for data in fx.files.values()),
        "files": files,
    }


def _reject(fx: _Fixture, *, as_of: str = "2035-06-01T12:00:00Z", output: Path | None = None, artifact_root: Path | None = None) -> tuple[bool, str]:
    result = fx.run(as_of=as_of, output=output, artifact_root=artifact_root)
    return _controlled(result), f"exit={result.returncode},diagnostic={bool(result.stderr.strip())},traceback={'Traceback' in result.stderr}"


def _authenticity(fx: _Fixture) -> tuple[bool, str]:
    outcomes: list[tuple[str, bool]] = []

    fx.reset()
    valid = fx.run()
    selected = False
    if valid.returncode == 0:
        try:
            selected = json.loads(fx.report.read_text(encoding="utf-8"))["key_id"] == "selected.key-1"
        except (OSError, ValueError, KeyError, TypeError):
            selected = False
    outcomes.append(("canonical_unicode_selected_key", valid.returncode == 0 and selected))

    fx.reset()
    fx.manifest["signature"] = "0" * 64
    fx.manifest_path.write_text(json.dumps(fx.manifest), encoding="utf-8")
    outcomes.append(("altered_signature", _reject(fx)[0]))

    fx.reset()
    fx.manifest["valid_until"] = "2038-12-31T23:59:59Z"  # payload alteration after signing
    fx.manifest_path.write_text(json.dumps(fx.manifest), encoding="utf-8")
    outcomes.append(("altered_payload", _reject(fx)[0]))

    fx.reset()
    fx.manifest["key_id"] = "unknown-key"
    fx.sign()
    outcomes.append(("unknown_key", _reject(fx)[0]))

    fx.reset()
    fx.keyring["keys"].append(copy.deepcopy(fx.keyring["keys"][1]))
    fx.write_keyring()
    outcomes.append(("duplicate_key", _reject(fx)[0]))

    for label, secret_hex in (("secret_too_short", "11" * 15), ("secret_too_long", "22" * 65), ("secret_odd", "1" * 33)):
        fx.reset()
        fx.keyring["keys"][1]["secret_hex"] = secret_hex
        fx.write_keyring()
        outcomes.append((label, _reject(fx)[0]))

    return all(ok for _, ok in outcomes), repr(outcomes)


def _inventory(fx: _Fixture) -> tuple[bool, str]:
    outcomes: list[tuple[str, bool]] = []

    fx.reset()
    (fx.artifacts / "z.bin").unlink()
    outcomes.append(("missing", _reject(fx)[0]))

    fx.reset()
    (fx.artifacts / "unexpected.txt").write_bytes(b"extra")
    outcomes.append(("extra", _reject(fx)[0]))

    unsafe = ["", ".", "..", "/absolute", "a/../b", "a/./b", "a//b", "back\\slash"]
    for index, path in enumerate(unsafe):
        fx.reset()
        fx.manifest["files"].append({"path": path, "size": 0, "sha256": _digest(b"")})
        fx.sign()
        outcomes.append((f"unsafe_{index}", _reject(fx)[0]))

    fx.reset()
    fx.manifest["files"].append(copy.deepcopy(fx.manifest["files"][0]))
    fx.sign()
    outcomes.append(("duplicate_path", _reject(fx)[0]))

    fx.reset()
    link = fx.artifacts / "link"
    try:
        link.symlink_to("z.bin")
        fx.manifest["files"].append({"path": "link", "size": 3, "sha256": _digest(b"\x00\xffz")})
        fx.sign()
        outcomes.append(("symlink", _reject(fx)[0]))
    except (OSError, NotImplementedError):
        outcomes.append(("symlink_unavailable", True))

    fx.reset()
    fifo = fx.artifacts / "pipe"
    try:
        os.mkfifo(fifo)
        fx.manifest["files"].append({"path": "pipe", "size": 0, "sha256": _digest(b"")})
        fx.sign()
        outcomes.append(("fifo", _reject(fx)[0]))
    except (OSError, AttributeError):
        outcomes.append(("fifo_unavailable", True))

    fx.reset()
    inside = fx.artifacts / "verification-report.json"
    # Inventory owns rejection of this boundary; whether a rejected run touched the
    # destination is assessed only by signed_manifest_atomic_report.
    outcomes.append(("output_inside_root", _reject(fx, output=inside)[0]))

    return all(ok for _, ok in outcomes), repr(outcomes)


def _content_integrity(fx: _Fixture) -> tuple[bool, str]:
    outcomes: list[tuple[str, bool]] = []

    fx.reset()
    (fx.artifacts / "z.bin").write_bytes(b"XYZ")  # same size, different SHA-256
    outcomes.append(("same_size_digest", _reject(fx)[0]))

    fx.reset()
    fx.manifest["files"][0]["size"] += 1
    fx.sign()
    outcomes.append(("declared_size", _reject(fx)[0]))

    fx.reset()
    (fx.artifacts / "z.bin").write_bytes(b"longer")
    outcomes.append(("observed_size", _reject(fx)[0]))

    # A socket is another non-regular object and can be created without privileges.
    fx.reset()
    sock_path = fx.artifacts / "artifact.sock"
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(sock_path))
        fx.manifest["files"].append({"path": "artifact.sock", "size": 0, "sha256": _digest(b"")})
        fx.sign()
        outcomes.append(("nonregular_socket", _reject(fx)[0]))
    except (OSError, AttributeError):
        outcomes.append(("socket_unavailable", True))
    finally:
        if sock is not None:
            sock.close()

    return all(ok for _, ok in outcomes), repr(outcomes)


def _trust_window(fx: _Fixture) -> tuple[bool, str]:
    outcomes: list[tuple[str, bool]] = []

    def intervals(key_start: str, key_end: str, manifest_start: str, manifest_end: str, as_of: str, expected_success: bool) -> None:
        fx.reset()
        fx.keyring["keys"][1]["valid_from"] = key_start
        fx.keyring["keys"][1]["valid_until"] = key_end
        fx.manifest["valid_from"] = manifest_start
        fx.manifest["valid_until"] = manifest_end
        fx.write_keyring()
        fx.sign()
        result = fx.run(as_of=as_of)
        ok = result.returncode == 0 if expected_success else _controlled(result)
        outcomes.append((f"interval_{len(outcomes)}", ok))

    intervals("2030-01-01T00:00:00Z", "2040-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "2039-01-01T00:00:00Z", "2030-01-01T00:00:00Z", True)
    intervals("2030-01-01T00:00:00Z", "2035-01-01T00:00:00Z", "2031-01-01T00:00:00Z", "2039-01-01T00:00:00Z", "2035-01-01T00:00:00Z", False)
    intervals("2030-01-01T00:00:00Z", "2040-01-01T00:00:00Z", "2031-01-01T00:00:00Z", "2035-01-01T00:00:00Z", "2035-01-01T00:00:00Z", False)
    intervals("2035-01-01T00:00:01Z", "2040-01-01T00:00:00Z", "2031-01-01T00:00:00Z", "2039-01-01T00:00:00Z", "2035-01-01T00:00:00Z", False)
    intervals("2030-01-01T00:00:00Z", "2040-01-01T00:00:00Z", "2035-01-01T00:00:01Z", "2039-01-01T00:00:00Z", "2035-01-01T00:00:00Z", False)
    intervals("2030-01-01T00:00:00+05:30", "2040-01-01T00:00:00+05:30", "2031-01-01T00:00:00-04:00", "2039-01-01T00:00:00-04:00", "2035-06-01T07:00:00-05:00", True)
    intervals("2040-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "2031-01-01T00:00:00Z", "2039-01-01T00:00:00Z", "2035-01-01T00:00:00Z", False)
    intervals("2030-01-01T00:00:00Z", "2040-01-01T00:00:00Z", "2039-01-01T00:00:00Z", "2031-01-01T00:00:00Z", "2035-01-01T00:00:00Z", False)

    for value in ("2035-01-01T00:00:00", "2035-01-01 00:00:00Z", "2035-01-01T00:00Z", "not-a-time", "2035-13-01T00:00:00Z", "2035-01-01T00:00:00+24:00"):
        fx.reset()
        outcomes.append((f"bad_as_of_{value}", _reject(fx, as_of=value)[0]))

    fx.reset()
    fx.keyring["keys"][1]["valid_from"] = "2030-01-01T00:00:00"
    fx.write_keyring()
    outcomes.append(("naive_key_time", _reject(fx)[0]))

    fx.reset()
    fx.manifest["valid_until"] = "2039-01-01 00:00:00Z"
    fx.sign()
    outcomes.append(("malformed_manifest_time", _reject(fx)[0]))

    return all(ok for _, ok in outcomes), repr(outcomes)


def _atomic_report(fx: _Fixture) -> tuple[bool, str]:
    outcomes: list[tuple[str, bool]] = []

    fx.reset()
    first = fx.run(env={"PYTHONHASHSEED": "7", "TZ": "Pacific/Honolulu"})
    expected = _canonical(_expected_report(fx)) + b"\n"
    first_bytes = fx.report.read_bytes() if fx.report.is_file() else b""
    second = fx.run(env={"PYTHONHASHSEED": "93", "TZ": "Europe/Rome"})
    second_bytes = fx.report.read_bytes() if fx.report.is_file() else b""
    outcomes.append(("exact_schema_order_hash_count_bytes", first.returncode == 0 and first_bytes == expected))
    outcomes.append(("deterministic_rerun", second.returncode == 0 and second_bytes == expected and first_bytes == second_bytes))

    manifest_cases: list[tuple[str, Any]] = [
        ("top_array", []),
        ("top_string", "manifest"),
        ("missing_field", {k: v for k, v in fx.manifest.items() if k != "files"}),
        ("extra_field", {**fx.manifest, "extra": 1}),
        ("schema_bool", {**fx.manifest, "schema_version": True}),
        ("schema_range", {**fx.manifest, "schema_version": 2}),
        ("key_id_type", {**fx.manifest, "key_id": 7}),
        ("key_id_empty", {**fx.manifest, "key_id": ""}),
        ("key_id_chars", {**fx.manifest, "key_id": "bad key"}),
        ("signature_type", {**fx.manifest, "signature": 1}),
        ("signature_upper", {**fx.manifest, "signature": "A" * 64}),
        ("signature_length", {**fx.manifest, "signature": "a" * 63}),
        ("files_type", {**fx.manifest, "files": {}}),
        ("file_type", {**fx.manifest, "files": ["z.bin"]}),
        ("file_missing", {**fx.manifest, "files": [{"path": "z.bin", "size": 3}]}),
        ("file_extra", {**fx.manifest, "files": [{"path": "z.bin", "size": 3, "sha256": _digest(b"\x00\xffz"), "x": 1}]}),
        ("size_bool", {**fx.manifest, "files": [{"path": "z.bin", "size": True, "sha256": _digest(b"\x00\xffz")}]}),
        ("size_string", {**fx.manifest, "files": [{"path": "z.bin", "size": "3", "sha256": _digest(b"\x00\xffz")}]}),
        ("size_negative", {**fx.manifest, "files": [{"path": "z.bin", "size": -1, "sha256": _digest(b"\x00\xffz")}]}),
        ("size_overflow", {**fx.manifest, "files": [{"path": "z.bin", "size": 9223372036854775808, "sha256": _digest(b"\x00\xffz")}]}),
        ("digest_type", {**fx.manifest, "files": [{"path": "z.bin", "size": 3, "sha256": None}]}),
        ("digest_upper", {**fx.manifest, "files": [{"path": "z.bin", "size": 3, "sha256": "A" * 64}]}),
    ]
    keyring_cases: list[tuple[str, Any]] = [
        ("ring_top_array", []),
        ("ring_missing", {"schema_version": 1}),
        ("ring_extra", {**fx.keyring, "extra": 1}),
        ("ring_schema_bool", {**fx.keyring, "schema_version": True}),
        ("ring_schema_range", {**fx.keyring, "schema_version": 0}),
        ("keys_type", {"schema_version": 1, "keys": {}}),
        ("key_type", {"schema_version": 1, "keys": ["key"]}),
        ("key_missing", {"schema_version": 1, "keys": [{"key_id": "x"}]}),
        ("key_extra", {"schema_version": 1, "keys": [{**fx.keyring["keys"][1], "extra": 1}]}),
        ("key_id_type", {"schema_version": 1, "keys": [{**fx.keyring["keys"][1], "key_id": False}]}),
        ("secret_nonhex", {"schema_version": 1, "keys": [{**fx.keyring["keys"][1], "secret_hex": "gg" * 16}]}),
    ]

    def atomic_case(label: str, manifest_value: Any | None = None, keyring_value: Any | None = None, raw_manifest: str | None = None, raw_keyring: str | None = None) -> None:
        fx.reset()
        if raw_manifest is not None:
            fx.manifest_path.write_text(raw_manifest, encoding="utf-8")
        elif manifest_value is not None:
            fx.manifest_path.write_text(json.dumps(manifest_value, allow_nan=True), encoding="utf-8")
        if raw_keyring is not None:
            fx.keyring_path.write_text(raw_keyring, encoding="utf-8")
        elif keyring_value is not None:
            fx.keyring_path.write_text(json.dumps(keyring_value, allow_nan=True), encoding="utf-8")
        fx.report.write_bytes(SENTINEL)
        result = fx.run()
        stages = [p.name for p in fx.root.iterdir() if p.name.startswith(f".{fx.report.name}.")]
        outcomes.append((label, _controlled(result) and fx.report.read_bytes() == SENTINEL and not stages))

    for label, value in manifest_cases:
        atomic_case(label, manifest_value=value)
    for label, value in keyring_cases:
        atomic_case(label, keyring_value=value)
    atomic_case("malformed_manifest_json", raw_manifest="{broken")
    atomic_case("malformed_keyring_json", raw_keyring="[broken")
    atomic_case("duplicate_json_member", raw_manifest='{"schema_version":1,"schema_version":1}')
    atomic_case("nonstandard_json_constant", raw_manifest='{"schema_version":NaN}')

    def atomic_current(label: str, *, as_of: str = "2035-06-01T12:00:00Z", output: Path | None = None) -> None:
        destination = output or fx.report
        destination.write_bytes(SENTINEL)
        result = fx.run(as_of=as_of, output=destination)
        stages = [p.name for p in destination.parent.iterdir() if p.name.startswith(f".{destination.name}.")]
        outcomes.append((label, _controlled(result) and destination.read_bytes() == SENTINEL and not stages))

    # One non-mutated rejection from every semantic phase proves that controlled
    # authentication, inventory, integrity, and temporal failures are atomic too.
    # These variants deliberately differ from each phase's planned mutant trigger,
    # preserving the frozen exact-one-check mutation failure sets.
    fx.reset()
    fx.manifest["key_id"] = "unknown-key"
    fx.sign()
    atomic_current("auth_failure_preserved")

    fx.reset()
    (fx.artifacts / "z.bin").unlink()
    atomic_current("inventory_failure_preserved")

    fx.reset()
    fx.manifest["files"][0]["size"] += 1
    fx.sign()
    atomic_current("integrity_failure_preserved")

    fx.reset()
    fx.manifest["valid_until"] = "2035-01-01T00:00:00Z"
    fx.sign()
    atomic_current("trust_failure_preserved")

    fx.reset()
    inside_output = fx.artifacts / "report.json"
    atomic_current("inside_root_failure_preserved", output=inside_output)

    fx.reset()
    fx.report.mkdir()
    (fx.report / "marker").write_bytes(SENTINEL)
    before = sorted((p.relative_to(fx.report).as_posix(), p.read_bytes()) for p in fx.report.rglob("*") if p.is_file())
    io_result = fx.run()
    after = sorted((p.relative_to(fx.report).as_posix(), p.read_bytes()) for p in fx.report.rglob("*") if p.is_file())
    stages = [p.name for p in fx.root.iterdir() if p.name.startswith(f".{fx.report.name}.")]
    outcomes.append(("output_io_failure_cleanup", _controlled(io_result) and before == after and not stages))

    failed = [name for name, ok in outcomes if not ok]
    return not failed, f"cases={len(outcomes)},failed={failed}"


def evaluate_signed(workspace: Path) -> HiddenEvaluationResult:
    observations, passed, failed, record = _recorder()
    try:
        with tempfile.TemporaryDirectory(prefix="ah-signed-complete-") as temporary:
            fx = _Fixture(Path(temporary), workspace)
            for check_id, probe in zip(
                CHECKS,
                (_authenticity, _inventory, _content_integrity, _trust_window, _atomic_report),
                strict=True,
            ):
                ok, detail = probe(fx)
                record(check_id, ok, detail)
    except (FileNotFoundError, RuntimeError) as exc:
        # RuntimeError is how entrypoint discovery reports an absent public CLI.
        if "entrypoint" in str(exc).lower() or "could not find" in str(exc).lower():
            return _interface_unreachable_result(
                task_id=TASK_ID,
                evaluation_dir=_evaluation_dir(workspace, TASK_ID),
                passed_checks=passed,
                failed_checks=failed,
                observations=observations,
                check_ids=CHECKS,
                detail=str(exc),
                reason="interface_unreachable:cli_or_output_missing",
            )
        return _finish_runtime(TASK_ID, workspace, CHECKS, observations, passed, failed, record, exc)
    except Exception as exc:
        return _finish_runtime(TASK_ID, workspace, CHECKS, observations, passed, failed, record, exc)
    return _finalize_hidden_evaluation(
        task_id=TASK_ID,
        evaluation_dir=_evaluation_dir(workspace, TASK_ID),
        passed_checks=passed,
        failed_checks=failed,
        observations=observations,
    )


__all__ = ["evaluate_signed"]
