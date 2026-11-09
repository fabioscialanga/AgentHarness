"""Portable, stdlib-only tests for the frozen DEP dataset validator."""

from __future__ import annotations

import copy
import json
import unittest
import zipfile

from validate_dataset import ROOT, digest, portable_basename, validate_binding


class ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads((ROOT / "m3-binding-v0.schema.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(ROOT / "fixtures/D02.zip") as archive:
            self.binding = json.loads(archive.read("repo/.agentharness/runs/D02-current/m3-binding-v0.json"))

    def test_windows_stdout_path_in_d26_on_any_platform(self) -> None:
        with zipfile.ZipFile(ROOT / "fixtures/D26.zip") as archive:
            report = json.loads(archive.read("repo/.agentharness/runs/D26-current/verify-report.json"))
            execution = report["results"][0]["audit"]["commands"][0]["reexecution"]
            source = execution["stdout_path"]
            self.assertIn("\\", source)  # Windows spelling retained in the fixture.
            filename = portable_basename(source)
            matches = [name for name in archive.namelist() if name.endswith("/" + filename)]
            self.assertEqual(len(matches), 1)
            self.assertNotEqual(digest(archive.read(matches[0])), execution["stdout_sha256"])

    def test_basename_rejects_missing_name(self) -> None:
        for value in ("", "C:\\tmp\\", "/tmp/", ".."):
            with self.subTest(value=value), self.assertRaises(ValueError):
                portable_basename(value)

    def test_binding_schema_accepts_fixture(self) -> None:
        validate_binding(self.binding, self.schema)

    def test_binding_schema_rejects_missing_extra_digest_and_timestamp(self) -> None:
        mutations = []
        missing = copy.deepcopy(self.binding)
        del missing["state"]
        mutations.append(missing)
        extra = copy.deepcopy(self.binding)
        extra["unexpected"] = True
        mutations.append(extra)
        digest_bad = copy.deepcopy(self.binding)
        digest_bad["state"]["diff_sha256"] = "not-a-digest"
        mutations.append(digest_bad)
        time_bad = copy.deepcopy(self.binding)
        time_bad["evaluated_at"] = "2026-11-07T12:00:00"
        mutations.append(time_bad)
        mapping_bad = copy.deepcopy(self.binding)
        mapping_bad["check"]["mapping_id"] = "OTHER"
        mutations.append(mapping_bad)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_binding(value, self.schema)


if __name__ == "__main__":
    unittest.main()
