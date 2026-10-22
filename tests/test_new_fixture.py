"""Tests for fixture scaffolding tool tools/scaffold/new_fixture.py (issue #353)."""
from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.scaffold import new_fixture
from tools.validate import validate


class NewFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generates_untouched_skeletons_for_each_surface_and_fails_validation(self) -> None:
        surfaces = [
            ("xdr", "p28-xdr-scaffold-test", "cap-0083"),
            ("rpc", "p28-rpc-scaffold-test", "ledger"),
            ("soroban", "p28-soroban-scaffold-test", "smoke"),
        ]

        sections = [
            "# What this tests:",
            "# Why it matters:",
            "# Introduced in:",
            "# Expected result and where it comes from:",
            "# Determinism:",
        ]

        for surface, fid, cat in surfaces:
            argv = [
                "--surface", surface,
                "--protocol", "28",
                "--id", fid,
                "--category", cat,
                "--output-dir", self.temp_dir,
            ]
            exit_code = new_fixture.main(argv)
            self.assertEqual(exit_code, 0)

            # Find generated file
            files = list(Path(self.temp_dir).rglob(f"{fid}.toml"))
            self.assertEqual(len(files), 1)
            target = files[0]

            content = target.read_text(encoding="utf-8")

            # Check header sections
            for sec in sections:
                self.assertIn(sec, content)
            self.assertEqual(content.count("# TODO:"), 5)

            # Check no fabricated content: no URL, no base64, no date
            self.assertNotRegex(content, r"https?://")
            self.assertNotRegex(content, r"\d{4}-\d{2}-\d{2}")
            self.assertNotIn("ERERERER", content)

            # Check placeholders start with TODO
            for line in content.splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = [part.strip() for part in line.split("=", 1)]
                    if k in ("id", "protocol", "surface", "category"):
                        continue
                    self.assertTrue(
                        "TODO" in v,
                        f"Field {k}={v} must carry a TODO placeholder",
                    )

            # Untouched skeleton fails validator
            report = validate.validate_directory(Path(self.temp_dir) / "protocol-28")
            self.assertTrue(len(report.errors) > 0)

    def test_xdr_category_cap_creates_cap_subdirectory(self) -> None:
        argv = [
            "--surface", "xdr",
            "--protocol", "28",
            "--id", "p28-xdr-cap83-demo",
            "--category", "cap-0083",
            "--output-dir", self.temp_dir,
        ]
        exit_code = new_fixture.main(argv)
        self.assertEqual(exit_code, 0)

        expected_path = Path(self.temp_dir) / "protocol-28" / "xdr" / "cap-0083" / "p28-xdr-cap83-demo.toml"
        self.assertTrue(expected_path.is_file())

    def test_refuses_to_overwrite_existing_file(self) -> None:
        argv = [
            "--surface", "rpc",
            "--protocol", "28",
            "--id", "p28-rpc-duplicate",
            "--category", "ledger",
            "--output-dir", self.temp_dir,
        ]
        exit_code_1 = new_fixture.main(argv)
        self.assertEqual(exit_code_1, 0)

        exit_code_2 = new_fixture.main(argv)
        self.assertNotEqual(exit_code_2, 0)

    def test_dangling_symlink_is_refused_without_creating_its_target(self) -> None:
        target = Path(self.temp_dir) / "outside.toml"
        link = Path(self.temp_dir) / "protocol-28" / "rpc" / "p28-rpc-sym.toml"
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest("symbolic links are unavailable")
        code = new_fixture.main([
            "--surface", "rpc", "--protocol", "28", "--id", "p28-rpc-sym",
            "--category", "ledger", "--output-dir", self.temp_dir,
        ])
        self.assertEqual(code, 1)
        self.assertTrue(link.is_symlink())
        self.assertFalse(target.exists())

    def test_rejects_invalid_id(self) -> None:
        cases = [
            "P28-XDR-UPPER",
            "p28 xdr spaces",
            "p28:xdr:colon",
            "",
            "con",
        ]
        for bad_id in cases:
            argv = [
                "--surface", "xdr",
                "--protocol", "28",
                "--id", bad_id,
                "--category", "cap-0083",
                "--output-dir", self.temp_dir,
            ]
            exit_code = new_fixture.main(argv)
            self.assertNotEqual(exit_code, 0, f"Expected {bad_id} to be rejected")

    def test_rejects_protocol_0_or_negative(self) -> None:
        for proto in ["0", "-1"]:
            argv = [
                "--surface", "xdr",
                "--protocol", proto,
                "--id", "p28-xdr-test",
                "--category", "cap-0083",
                "--output-dir", self.temp_dir,
            ]
            exit_code = new_fixture.main(argv)
            self.assertNotEqual(exit_code, 0)

    def test_rejects_unknown_surface(self) -> None:
        argv = [
            "--surface", "unknown_surface",
            "--protocol", "28",
            "--id", "p28-xdr-test",
            "--category", "cap-0083",
            "--output-dir", self.temp_dir,
        ]
        exit_code = new_fixture.main(argv)
        self.assertNotEqual(exit_code, 0)

    def test_replaced_placeholders_pass_validator(self) -> None:
        # Generate XDR skeleton
        argv = [
            "--surface", "xdr",
            "--protocol", "28",
            "--id", "p28-xdr-filled",
            "--category", "cap-0083",
            "--output-dir", self.temp_dir,
        ]
        self.assertEqual(new_fixture.main(argv), 0)

        path = Path(self.temp_dir) / "protocol-28" / "xdr" / "cap-0083" / "p28-xdr-filled.toml"
        content = path.read_text(encoding="utf-8")

        # Replace placeholders with valid values taken from existing fixture
        content = content.replace("TODO: Brief description of the fixture", "Valid description")
        content = content.replace("TODO-REPLACE-WITH-CHECKED-SOURCE", "CAP-0083")
        content = content.replace("TODO-XDR-TYPE", "StellarValue")
        content = content.replace("TODO-XDR-KIND", "roundtrip")
        content = content.replace("TODO-BASE64-PAYLOAD", "EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA")

        path.write_text(content, encoding="utf-8")

        report = validate.validate_directory(Path(self.temp_dir) / "protocol-28")
        self.assertEqual(report.errors, [])


if __name__ == "__main__":
    unittest.main()
