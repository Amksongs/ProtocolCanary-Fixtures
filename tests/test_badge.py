"""Tests for tools/badge/badge.py.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
BADGE_PATH = REPO_ROOT / "tools" / "badge" / "badge.py"

_spec = importlib.util.spec_from_file_location("badge", BADGE_PATH)
badge = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["badge"] = badge
_spec.loader.exec_module(badge)


FIXTURE = """
id = "p28-xdr-example"
protocol = 28
surface = "xdr"
category = "cap-0083"
description = "example"
source_reference = "CAP-0083"

type = "StellarValue"
kind = "decode-success"
value_base64 = "AAAAAA=="
"""


def marked_readme(count: int) -> str:
    """A miniature README whose badge region reports ``count``."""
    return (
        "# Example\n\n"
        "[![Validate](https://example.invalid/badge.svg)](https://example.invalid) "
        "[![License: Apache-2.0](https://example.invalid/license.svg)](LICENSE) "
        f"{badge.BADGE_START}{badge.badge_markdown(count)}{badge.BADGE_END}\n\n"
        "Body text.\n"
    )


def write(root: Path, name: str, contents: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


class BadgeTests(unittest.TestCase):
    def test_counts_every_toml_under_the_protocol_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "protocol-27/README.md", "Intentionally empty.\n")
            write(root, "protocol-28/xdr/cap-0083/a.toml", FIXTURE)
            write(root, "protocol-28/xdr/cap-0083/b.toml", FIXTURE)
            write(root, "README.md", "# not a fixture\n")
            self.assertEqual(badge.count_fixtures(root), 2)

    def test_count_fixtures_returns_zero_for_pack_without_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "protocol-28/README.md", "No fixtures yet.\n")
            self.assertEqual(badge.count_fixtures(root), 0)

    def test_count_fixtures_falls_back_to_repo_root_when_no_protocol_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "fixture.toml", FIXTURE)
            write(root, "README.md", "# not a fixture\n")
            self.assertEqual(badge.count_fixtures(root), 1)

    def test_badge_markdown_links_to_the_pack_table(self) -> None:
        rendered = badge.badge_markdown(6)
        self.assertIn("https://img.shields.io/badge/fixtures-6-blue.svg", rendered)
        self.assertIn("![Fixtures: 6]", rendered)
        self.assertIn("](#protocol-packs)", rendered)

    def test_render_refreshes_a_stale_count(self) -> None:
        self.assertEqual(badge.render(marked_readme(99), 6), marked_readme(6))

    def test_render_is_idempotent(self) -> None:
        once = badge.render(marked_readme(99), 6)
        self.assertEqual(badge.render(once, 6), once)

    def test_render_leaves_surrounding_prose_untouched(self) -> None:
        updated = badge.render(marked_readme(99), 6)
        self.assertIn("[![Validate](https://example.invalid/badge.svg)]", updated)
        self.assertIn("[![License: Apache-2.0]", updated)
        self.assertTrue(updated.endswith("Body text.\n"))

    def test_render_requires_the_markers(self) -> None:
        with self.assertRaises(badge.BadgeMarkerError):
            badge.render("# No markers here\n", 6)

    def test_render_requires_markers_in_order(self) -> None:
        reversed_markers = f"{badge.BADGE_END} x {badge.BADGE_START}\n"
        with self.assertRaises(badge.BadgeMarkerError):
            badge.render(reversed_markers, 6)

    def test_readme_carries_the_generated_badge_markers(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(badge.BADGE_START, readme)
        self.assertIn(badge.BADGE_END, readme)


class BadgeMainTests(unittest.TestCase):
    def run_main(
        self, root: Path, argv: list[str]
    ) -> tuple[int, str, str]:
        readme_path = root / "README.md"
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(badge, "README_PATH", readme_path), mock.patch.object(
            badge, "REPO_ROOT", root
        ):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = badge.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_main_check_passes_when_badge_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", marked_readme(1))
            write(root, "protocol-28/xdr/cap-0083/fixture.toml", FIXTURE)
            code, out, err = self.run_main(root, ["--check"])
            self.assertEqual(code, 0)
            self.assertIn("OK: README.md fixtures badge is current (1 fixture file(s))", out)
            self.assertEqual(err, "")

    def test_main_check_fails_when_badge_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", marked_readme(99))
            write(root, "protocol-28/xdr/cap-0083/fixture.toml", FIXTURE)
            code, out, err = self.run_main(root, ["--check"])
            self.assertEqual(code, 1)
            self.assertIn("error: README.md's fixtures badge is stale", err)

    def test_main_check_does_not_rewrite_a_stale_readme(self) -> None:
        # --check is the form CI runs against a fresh checkout, so reporting a
        # stale badge must be read-only: it may exit non-zero, but it must not
        # silently "fix" README.md as a side effect of the check.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme_file = write(root, "README.md", marked_readme(99))
            write(root, "protocol-28/xdr/cap-0083/fixture.toml", FIXTURE)
            code, out, err = self.run_main(root, ["--check"])
            self.assertEqual(code, 1)
            self.assertEqual(
                readme_file.read_text(encoding="utf-8"), marked_readme(99)
            )

    def test_main_updates_stale_readme_when_not_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme_file = write(root, "README.md", marked_readme(99))
            write(root, "protocol-28/xdr/cap-0083/fixture.toml", FIXTURE)
            code, out, err = self.run_main(root, [])
            self.assertEqual(code, 0)
            self.assertIn("OK: README.md fixtures badge updated to 1 fixture file(s)", out)
            self.assertEqual(err, "")
            self.assertEqual(readme_file.read_text(encoding="utf-8"), marked_readme(1))

    def test_main_already_current_when_not_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", marked_readme(1))
            write(root, "protocol-28/xdr/cap-0083/fixture.toml", FIXTURE)
            code, out, err = self.run_main(root, [])
            self.assertEqual(code, 0)
            self.assertIn("OK: README.md fixtures badge already current (1 fixture file(s))", out)
            self.assertEqual(err, "")

    def test_main_handles_missing_markers_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", "# No markers here\n")
            code, out, err = self.run_main(root, [])
            self.assertEqual(code, 1)
            self.assertIn("error:", err)

    def test_main_handles_oserror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # README.md does not exist -> OSError when reading
            code, out, err = self.run_main(root, [])
            self.assertEqual(code, 1)
            self.assertIn("error:", err)


class BadgeArgumentTests(unittest.TestCase):
    """Real argument handling: --help and typos never touch README.md.

    These run badge.py as a subprocess, so the exit status argparse produces
    (0 for --help, 2 for an unknown or misspelt flag) and the byte-identity of
    the repository's README.md are observed exactly as CI sees them. Before
    argparse, ``--help`` and ``--chek`` both ran the write mode silently.
    """

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BADGE_PATH), *args],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

    @staticmethod
    def readme_bytes() -> bytes:
        return (REPO_ROOT / "README.md").read_bytes()

    def test_help_exits_0_with_usage_and_leaves_readme_byte_identical(self) -> None:
        before = self.readme_bytes()
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--check", result.stdout)
        self.assertEqual(self.readme_bytes(), before)

    def test_unknown_arguments_exit_2_with_usage_and_leave_readme_byte_identical(
        self,
    ) -> None:
        for arg in ("--nope", "--chek", "--ch", "extra"):
            with self.subTest(arg=arg):
                before = self.readme_bytes()
                result = self.run_cli(arg)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)
                self.assertEqual(self.readme_bytes(), before)

    def test_check_mode_is_unchanged_on_a_current_readme(self) -> None:
        before = self.readme_bytes()
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK: README.md fixtures badge is current", result.stdout)
        self.assertEqual(self.readme_bytes(), before)

    def test_default_write_mode_is_unchanged_on_a_current_readme(self) -> None:
        before = self.readme_bytes()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK: README.md fixtures badge already current", result.stdout)
        self.assertEqual(self.readme_bytes(), before)


if __name__ == "__main__":
    unittest.main()
