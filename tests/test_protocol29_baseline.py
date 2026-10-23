"""Tests for the Protocol 29 baseline directory and registry (F-033, #290).

The ``protocol-29/`` pack ships with a generated registry and fixture files
under ``rpc/``, ``xdr/`` and ``soroban/``. Its registry must describe the
current pack exactly, and the fixture count is real compatibility coverage.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = REPO_ROOT / "protocol-29"
REGISTRY_PATH = PACK_DIR / "registry-v1.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "registry-v1.schema.json"

VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate_for_protocol29", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_for_protocol29"] = validate
_spec.loader.exec_module(validate)

LITE_PATH = REPO_ROOT / "tools" / "validate" / "jsonschema_lite.py"
_lite_spec = importlib.util.spec_from_file_location("lite_for_protocol29", LITE_PATH)
lite = importlib.util.module_from_spec(_lite_spec)
assert _lite_spec.loader is not None
sys.modules["lite_for_protocol29"] = lite
_lite_spec.loader.exec_module(lite)

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check_baseline(record: dict) -> list[str]:
    """Problems in the protocol-29 baseline manifest, empty when conforming.

    Everything the schema checks comes from ``jsonschema_lite``; on top of
    it, the pack binding asserts what the schema cannot: the directory name
    and the manifest's ``protocol`` value agree (``protocol-29/`` declares
    ``protocol = 29``).
    """
    problems = lite.validate(record, SCHEMA)
    version = record.get("registryVersion")
    if type(version) is not int or version != 1:
        problems.append(f"registryVersion must be the integer 1, got {version!r}")
    protocol = record.get("protocol")
    if type(protocol) is not int or protocol != 29:
        problems.append(
            f"a protocol-29/ manifest must declare protocol = 29 as an integer, got {protocol!r}"
        )
    if not record.get("fixtures") and list(PACK_DIR.rglob("*.toml")):
        problems.append("registry lists no fixtures but the pack contains *.toml fixture files")
    return problems


class Protocol29BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def test_pack_subdirectories_exist(self) -> None:
        for name in ("rpc", "xdr", "soroban"):
            with self.subTest(directory=name):
                self.assertTrue((PACK_DIR / name).is_dir())

    def test_registry_describes_the_protocol_29_mismatch_fixture(self) -> None:
        integer_protocol = self.registry["protocol"]
        self.assertIs(type(integer_protocol), int, "protocol must be an integer, not a bool")
        self.assertEqual(integer_protocol, 29)
        self.assertEqual(self.registry["registryVersion"], 1)
        fixture_ids = [fixture["id"] for fixture in self.registry["fixtures"]]
        self.assertIn("p29-rpc-network-mismatch", fixture_ids)

    def test_registry_conforms_to_the_registry_schema(self) -> None:
        problems = lite.validate(self.registry, SCHEMA)
        self.assertEqual(problems, [])

    def test_registry_uses_the_canonical_encoding(self) -> None:
        # CF-02 section 3: UTF-8, LF, two-space indent, one trailing newline.
        expected = json.dumps(self.registry, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(REGISTRY_PATH.read_text(encoding="utf-8"), expected)

    def test_pack_digest_matches_the_protocol_29_fixture_files(self) -> None:
        files = {}
        for fixture in self.registry["fixtures"]:
            paths = [fixture["path"]] + [payload["path"] for payload in fixture["payloads"]]
            for name in paths:
                files[name] = (PACK_DIR / name).read_bytes()
        lines = ["canary-pack-v1\n"]
        for name in sorted(files, key=lambda path: path.encode("utf-8")):
            data = files[name]
            lines.append(f"{hashlib.sha256(data).hexdigest()} {len(data)} {name}\n")
        expected = "sha256:" + hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
        self.assertEqual(self.registry["packDigest"], expected)

    def test_protocol_29_fixture_is_reported_as_coverage(self) -> None:
        fixture_paths = {fixture["path"] for fixture in self.registry["fixtures"]}
        self.assertIn("rpc/p29-rpc-network-mismatch.toml", fixture_paths)
        self.assertTrue((PACK_DIR / "rpc" / "p29-rpc-network-mismatch.toml").is_file())

    def test_baseline_manifest_passes_the_pack_checks(self) -> None:
        self.assertEqual(check_baseline(self.registry), [])

    def test_other_protocol_numbers_fail_the_pack_checks(self) -> None:
        for wrong in (28, 30, "29", True):
            with self.subTest(protocol=wrong):
                mutated = dict(self.registry, protocol=wrong)
                problems = check_baseline(mutated)
                self.assertTrue(problems, f"protocol {wrong!r} was accepted")

    def test_validator_accepts_the_protocol_29_directory(self) -> None:
        report = validate.validate_directory(PACK_DIR)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_default_scan_discovers_protocol_29(self) -> None:
        # The CLI's default roots glob protocol-*/; protocol-29/ must be
        # among them and contribute no diagnostics (F-033 acceptance).
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = validate.main(["--format", "json"])
        document = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertTrue(document["valid"])
        self.assertEqual(document["warnings"], [])
        roots = [Path(root) for root in document["summary"]["roots"]]
        self.assertIn(PACK_DIR, roots, roots)

    def test_generator_tool_reproduces_protocol_29_registry_byte_for_byte(self) -> None:
        # The generator output must reproduce the committed registry byte for byte.
        generate_path = REPO_ROOT / "tools" / "registry" / "generate.py"
        spec = importlib.util.spec_from_file_location("generate_for_protocol29", generate_path)
        gen = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules["generate_for_protocol29"] = gen
        spec.loader.exec_module(gen)

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = gen.main([str(PACK_DIR), "--stdout"])
        self.assertEqual(code, 0, stderr.getvalue())
        committed = REGISTRY_PATH.read_text(encoding="utf-8")
        self.assertEqual(stdout.getvalue(), committed)


if __name__ == "__main__":
    unittest.main()