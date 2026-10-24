"""Unit tests for tools/validate/check_root_files.py (F-054, issue #328).

All tests run completely offline and use stubbed file lists and temporary
directories to verify that root file checking behaves deterministically.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.validate.check_root_files import (
    DEFAULT_ALLOWLIST,
    check_root_entries,
    extract_root_entry,
    get_root_entries,
    is_allowed,
    main,
)


class TestCheckRootFiles(unittest.TestCase):
    """Tests for root-level file validation logic."""

    def test_extract_root_entry(self) -> None:
        """extract_root_entry returns the top-level name across path formats."""
        self.assertEqual(extract_root_entry("README.md"), "README.md")
        self.assertEqual(extract_root_entry("./README.md"), "README.md")
        self.assertEqual(extract_root_entry("tools/validate/validate.py"), "tools")
        self.assertEqual(extract_root_entry("tools/"), "tools")
        self.assertEqual(extract_root_entry(".github/workflows/validate.yml"), ".github")
        self.assertEqual(extract_root_entry("tests\\test_check_root_files.py"), "tests")
        self.assertEqual(extract_root_entry(""), "")
        self.assertEqual(extract_root_entry("///"), "")

    def test_is_allowed_for_legitimate_files(self) -> None:
        """Legitimate repository root files and directories are permitted."""
        for entry in DEFAULT_ALLOWLIST:
            self.assertTrue(is_allowed(entry), f"{entry} should be allowed")
            self.assertTrue(is_allowed(f"{entry}/"), f"{entry}/ with slash should be allowed")

    def test_is_allowed_for_protocol_packs(self) -> None:
        """Protocol pack directories matching protocol-\\d+ are permitted."""
        self.assertTrue(is_allowed("protocol-28"))
        self.assertTrue(is_allowed("protocol-29"))
        self.assertTrue(is_allowed("protocol-30"))
        self.assertTrue(is_allowed("protocol-999"))

    def test_is_allowed_rejects_stray_files(self) -> None:
        """Stray files and unexpected directories are rejected."""
        self.assertFalse(is_allowed("diff.txt"))
        self.assertFalse(is_allowed("PR_DESCRIPTION.md"))
        self.assertFalse(is_allowed("main_CONTRIBUTING.md"))
        self.assertFalse(is_allowed("stray.py"))
        self.assertFalse(is_allowed("protocol-unknown-name"))

    def test_check_root_entries_success_with_stubbed_list(self) -> None:
        """Validation succeeds when all stubbed entries match the allow-list."""
        stubbed_files = [
            "README.md",
            "CONTRIBUTING.md",
            "Makefile",
            ".gitignore",
            ".gitattributes",
            "tools/validate/validate.py",
            "tests/test_validate.py",
            "protocol-28/README.md",
            ".github/workflows/validate.yml",
        ]
        unexpected = check_root_entries(stubbed_files)
        self.assertEqual(unexpected, [])

    def test_check_root_entries_fails_and_names_stray_file(self) -> None:
        """Validation fails and names the exact stray file when present."""
        stubbed_files = [
            "README.md",
            "CONTRIBUTING.md",
            "diff.txt",
        ]
        unexpected = check_root_entries(stubbed_files)
        self.assertEqual(unexpected, ["diff.txt"])

    def test_check_root_entries_fails_with_multiple_stray_files(self) -> None:
        """Validation names all unexpected files sorted alphabetically."""
        stubbed_files = [
            "README.md",
            "PR_DESCRIPTION.md",
            "diff.txt",
            "main_CONTRIBUTING.md",
            "arbitrary_file.json",
        ]
        unexpected = check_root_entries(stubbed_files)
        self.assertEqual(
            unexpected,
            ["PR_DESCRIPTION.md", "arbitrary_file.json", "diff.txt", "main_CONTRIBUTING.md"],
        )

    def test_check_root_entries_with_custom_allowlist(self) -> None:
        """check_root_entries respects a user-provided custom allow-list."""
        custom_allowlist = frozenset({"README.md", "src"})
        self.assertEqual(check_root_entries(["README.md", "src/main.py"], allowlist=custom_allowlist), [])
        self.assertEqual(
            check_root_entries(["README.md", "Makefile"], allowlist=custom_allowlist),
            ["Makefile"],
        )

    def test_get_root_entries_fs_fallback(self) -> None:
        """get_root_entries falls back to filesystem scanning when git is not used."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "README.md").write_text("Hello\n", encoding="utf-8")
            (temp_path / "Makefile").write_text("all:\n", encoding="utf-8")
            (temp_path / "docs").mkdir()
            (temp_path / ".git").mkdir()

            with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
                entries = get_root_entries(temp_path)

            self.assertIn("README.md", entries)
            self.assertIn("Makefile", entries)
            self.assertIn("docs", entries)
            self.assertNotIn(".git", entries)

    def test_main_clean_repo_succeeds(self) -> None:
        """main exits 0 on the current clean repository."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf), patch("sys.stderr", stderr_buf):
            exit_code = main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("OK: all root entries match allow-list", stdout_buf.getvalue())
        self.assertEqual(stderr_buf.getvalue(), "")

    def test_main_failure_reports_stray_files_to_stderr(self) -> None:
        """main exits 1 and writes unexpected files to stderr when found."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with (
            patch("tools.validate.check_root_files.get_root_entries", return_value=["README.md", "diff.txt"]),
            patch("sys.stdout", stdout_buf),
            patch("sys.stderr", stderr_buf),
        ):
            exit_code = main([])
        self.assertEqual(exit_code, 1)
        self.assertIn("ERROR: Unexpected file(s) found in repository root:", stderr_buf.getvalue())
        self.assertIn("diff.txt", stderr_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
