"""Tests for fixture scaffolding tool tools/scaffold/new_fixture.py (issue #353)."""
from __future__ import annotations

import contextlib
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


def parse_skeleton(text: str) -> dict[str, dict[str, str]]:
    """Parse a skeleton as text: table name -> {key: raw value}.

    The untouched skeleton is deliberately not valid fixture content yet, so
    this reads it line by line rather than through ``tomllib``. The header
    (keys before any table) lives under the empty string.
    """
    tables: dict[str, dict[str, str]] = {"": {}}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[[") and stripped.endswith("]]"):
            current = stripped[2:-2].strip()
            tables.setdefault(current, {})
        elif stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            tables.setdefault(current, {})
        elif "=" in stripped:
            key, _, value = stripped.partition("=")
            tables.setdefault(current, {})[key.strip()] = value.strip()
    return tables


# Keys that belong to one surface and to no other. `kind` is deliberately
# absent: it appears in the xdr header, the rpc [[assert]] table and the
# soroban [expect] table, so it cannot distinguish a leaked surface.
SURFACE_SIGNATURE_KEYS = {
    "xdr": {"type", "value_base64"},
    "rpc": {"method", "field", "value"},
    "soroban": {"source_account", "contract_id", "function", "sequence_number"},
}


class NewFixtureSkeletonAndPathTests(unittest.TestCase):
    """F-128 (issue #447): skeleton contents, protocol minimum, directory choice."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_tool(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = new_fixture.main(list(argv))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def generate(
        self,
        surface: str,
        fixture_id: str,
        category: str,
        protocol: int = 28,
    ) -> Path:
        exit_code, _out, err = self.run_tool(
            [
                "--surface", surface,
                "--protocol", str(protocol),
                "--id", fixture_id,
                "--category", category,
                "--output-dir", str(self.temp_dir),
            ]
        )
        self.assertEqual(exit_code, 0, err)
        matches = list(self.temp_dir.rglob(f"{fixture_id}.toml"))
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def read_skeleton(
        self, surface: str, category: str = "ledger", protocol: int = 28
    ) -> dict[str, dict[str, str]]:
        fixture_id = f"p{protocol}-{surface}-skeleton"
        path = self.generate(surface, fixture_id, category, protocol)
        return parse_skeleton(path.read_text(encoding="utf-8"))

    def assert_header(
        self,
        tables: dict[str, dict[str, str]],
        surface: str,
        fixture_id: str,
        category: str,
        protocol: int = 28,
    ) -> None:
        header = tables[""]
        self.assertEqual(header["id"], f'"{fixture_id}"')
        self.assertEqual(header["protocol"], str(protocol))
        self.assertEqual(header["surface"], f'"{surface}"')
        self.assertEqual(header["category"], f'"{category}"')

    # --- protocol minimum -------------------------------------------------

    def test_protocol_one_is_accepted_and_written_under_protocol_1(self) -> None:
        path = self.generate("xdr", "p1-xdr-min", "cap-0083", protocol=1)
        self.assertEqual(
            path,
            self.temp_dir / "protocol-1" / "xdr" / "cap-0083" / "p1-xdr-min.toml",
        )

    def test_protocol_zero_and_negative_are_refused_and_write_nothing(self) -> None:
        for protocol in (0, -3):
            with self.subTest(protocol=protocol):
                exit_code, _out, err = self.run_tool(
                    [
                        "--surface", "xdr",
                        "--protocol", str(protocol),
                        "--id", "p28-xdr-min",
                        "--category", "cap-0083",
                        "--output-dir", str(self.temp_dir),
                    ]
                )
                self.assertEqual(exit_code, 1)
                self.assertIn("positive integer", err)
                self.assertEqual(list(self.temp_dir.iterdir()), [])

    # --- per-surface skeleton ---------------------------------------------

    def test_xdr_skeleton_has_the_xdr_placeholders(self) -> None:
        tables = self.read_skeleton("xdr")
        self.assert_header(tables, "xdr", "p28-xdr-skeleton", "ledger")
        for key in ("type", "kind", "value_base64"):
            with self.subTest(key=key):
                self.assertIn(key, tables[""])
                self.assertIn("TODO", tables[""][key])
        self.assertNotIn("assert", tables)
        self.assertNotIn("expect", tables)

    def test_rpc_skeleton_has_method_and_assert_placeholders(self) -> None:
        tables = self.read_skeleton("rpc")
        self.assert_header(tables, "rpc", "p28-rpc-skeleton", "ledger")
        self.assertIn("method", tables[""])
        self.assertIn("TODO", tables[""]["method"])
        self.assertIn("assert", tables)
        for key in ("kind", "field", "value"):
            with self.subTest(key=key):
                self.assertIn(key, tables["assert"])
                self.assertIn("TODO", tables["assert"][key])
        self.assertNotIn("expect", tables)

    def test_soroban_skeleton_has_invocation_and_expect_placeholders(self) -> None:
        tables = self.read_skeleton("soroban", "smoke")
        self.assert_header(
            tables, "soroban", "p28-soroban-skeleton", "smoke"
        )
        for key in (
            "source_account",
            "contract_id",
            "function",
            "sequence_number",
        ):
            with self.subTest(key=key):
                self.assertIn(key, tables[""])
                self.assertIn("TODO", tables[""][key])
        self.assertIn("expect", tables)
        self.assertIn("kind", tables["expect"])
        self.assertIn("TODO", tables["expect"]["kind"])
        self.assertNotIn("assert", tables)

    def test_no_surface_contains_another_surfaces_keys(self) -> None:
        expected_tables = {"xdr": set(), "rpc": {"assert"}, "soroban": {"expect"}}
        for surface, own_keys in SURFACE_SIGNATURE_KEYS.items():
            with self.subTest(surface=surface):
                tables = self.read_skeleton(surface)
                keys = {key for table in tables.values() for key in table}
                self.assertTrue(own_keys <= keys, own_keys - keys)
                for other, other_keys in SURFACE_SIGNATURE_KEYS.items():
                    if other == surface:
                        continue
                    self.assertEqual(
                        keys & other_keys,
                        set(),
                        f"{surface} skeleton contains {other} keys {keys & other_keys}",
                    )
                for table_name in ("assert", "expect"):
                    if table_name in expected_tables[surface]:
                        self.assertIn(table_name, tables)
                    else:
                        self.assertNotIn(table_name, tables)

    # --- directory choice -------------------------------------------------

    def test_xdr_cap_category_goes_into_cap_subdirectory(self) -> None:
        path = self.generate("xdr", "p28-xdr-cap83", "cap-0083")
        self.assertEqual(
            path,
            self.temp_dir / "protocol-28" / "xdr" / "cap-0083" / "p28-xdr-cap83.toml",
        )

    def test_xdr_non_cap_category_stays_in_the_xdr_directory(self) -> None:
        path = self.generate("xdr", "p28-xdr-ledger", "ledger")
        self.assertEqual(
            path,
            self.temp_dir / "protocol-28" / "xdr" / "p28-xdr-ledger.toml",
        )
        self.assertFalse((self.temp_dir / "protocol-28" / "xdr" / "ledger").exists())

    def test_rpc_and_soroban_cap_categories_stay_in_their_surface_directory(self) -> None:
        for surface in ("rpc", "soroban"):
            with self.subTest(surface=surface):
                fixture_id = f"p28-{surface}-cap83"
                path = self.generate(surface, fixture_id, "cap-0083")
                self.assertEqual(
                    path,
                    self.temp_dir / "protocol-28" / surface / f"{fixture_id}.toml",
                )
                self.assertFalse(
                    (self.temp_dir / "protocol-28" / surface / "cap-0083").exists()
                )

    def test_two_fixtures_in_the_same_surface_directory_both_succeed(self) -> None:
        first = self.generate("rpc", "p28-rpc-first", "ledger")
        second = self.generate("rpc", "p28-rpc-second", "ledger")
        self.assertEqual(first.parent, second.parent)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())

    # --- empty category ---------------------------------------------------

    def test_empty_category_is_refused_and_creates_nothing(self) -> None:
        exit_code, _out, err = self.run_tool(
            [
                "--surface", "xdr",
                "--protocol", "28",
                "--id", "p28-xdr-empty-category",
                "--category", "",
                "--output-dir", str(self.temp_dir),
            ]
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("category must not be empty", err)
        self.assertEqual(list(self.temp_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
