"""Tests for tools/validate/check_changelog.py (Rule [F-055]).

All tests run completely offline and standard-library-only.
Verifies that pull requests modifying fixtures, schemas, or tools require a CHANGELOG entry,
and that exemptions (docs, tests, workflows, no-changelog opt-out label) are honored.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.validate.check_changelog import (
    OPT_OUT_LABEL,
    RULE_ID,
    ChangelogCheckResult,
    build_markdown_summary,
    check_changelog,
    extract_labels_from_event,
    get_git_diff_files,
    is_changelog_file,
    is_governed_path,
    main,
    normalize_path,
    parse_changed_file_line,
    parse_labels_string,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_CHANGELOG_PATH = REPO_ROOT / "tools" / "validate" / "check_changelog.py"


class TestPathClassification(unittest.TestCase):
    """Test path normalization, changelog detection, and governed path classification."""

    def test_normalize_path(self) -> None:
        self.assertEqual(normalize_path("protocol-28/xdr/foo.toml"), "protocol-28/xdr/foo.toml")
        self.assertEqual(normalize_path("./protocol-28/xdr/foo.toml"), "protocol-28/xdr/foo.toml")
        self.assertEqual(normalize_path(".\\protocol-28\\xdr\\foo.toml"), "protocol-28/xdr/foo.toml")
        self.assertEqual(normalize_path("tools/validate/../validate/foo.py"), "tools/validate/foo.py")
        self.assertEqual(normalize_path('"schemas/fixture-v1.schema.json"'), "schemas/fixture-v1.schema.json")
        self.assertEqual(normalize_path(""), "")

    def test_normalize_path_absolute(self) -> None:
        cwd = Path.cwd()
        target = cwd / "tools" / "foo.py"
        # Relative to explicit repo_root
        self.assertEqual(normalize_path(str(target), repo_root=cwd), "tools/foo.py")
        # Relative to cwd when repo_root is None
        self.assertEqual(normalize_path(str(target), repo_root=None), "tools/foo.py")

        # ValueError fallback when relpath fails with explicit repo_root
        with patch("os.path.relpath", side_effect=ValueError("cross-device")):
            res1 = normalize_path("/abs/path/to/file.txt", repo_root=cwd)
            self.assertEqual(res1, "abs/path/to/file.txt")

        # ValueError fallback when relpath fails with repo_root=None
        with patch("os.path.relpath", side_effect=ValueError("cross-device")):
            res2 = normalize_path("/abs/path/to/file.txt", repo_root=None)
            self.assertEqual(res2, "abs/path/to/file.txt")

    def test_is_changelog_file(self) -> None:
        self.assertTrue(is_changelog_file("CHANGELOG.md"))
        self.assertTrue(is_changelog_file("./CHANGELOG.md"))
        self.assertTrue(is_changelog_file("changelog.md"))
        self.assertTrue(is_changelog_file("CHANGELOG.markdown"))
        self.assertFalse(is_changelog_file("docs/CHANGELOG.md"))
        self.assertFalse(is_changelog_file("protocol-28/CHANGELOG.md"))
        self.assertFalse(is_changelog_file("README.md"))

    def test_is_governed_path_fixtures(self) -> None:
        self.assertTrue(is_governed_path("protocol-28/xdr/p28-xdr-cap83.toml"))
        self.assertTrue(is_governed_path("./protocol-28/soroban/sim.toml"))
        self.assertTrue(is_governed_path("protocol-27/README.md"))
        self.assertTrue(is_governed_path("protocol-29/evidence/testnet/get-network.json"))
        self.assertTrue(is_governed_path("protocol-custom/fixtures/test.toml"))
        self.assertTrue(is_governed_path("protocol-28"))
        self.assertTrue(is_governed_path("protocol-28/"))

    def test_is_governed_path_schemas(self) -> None:
        self.assertTrue(is_governed_path("schemas/fixture-v1.schema.json"))
        self.assertTrue(is_governed_path("./schemas/registry-v1.schema.json"))
        self.assertTrue(is_governed_path("schemas/proposed/resource-estimate.json"))
        self.assertTrue(is_governed_path("schemas/"))
        self.assertTrue(is_governed_path("schemas"))

    def test_is_governed_path_tools(self) -> None:
        self.assertTrue(is_governed_path("tools/validate/validate.py"))
        self.assertTrue(is_governed_path("tools/badge/badge.py"))
        self.assertTrue(is_governed_path("tools/pack/pack.py"))
        self.assertTrue(is_governed_path("./tools/registry/generate.py"))
        self.assertTrue(is_governed_path("tools/"))
        self.assertTrue(is_governed_path("tools"))

    def test_is_exempt_paths(self) -> None:
        # Empty path
        self.assertFalse(is_governed_path(""))
        self.assertFalse(is_governed_path("   "))

        # Documentation
        self.assertFalse(is_governed_path("docs/protocol-28.md"))
        self.assertFalse(is_governed_path("README.md"))
        self.assertFalse(is_governed_path("CONTRIBUTING.md"))
        self.assertFalse(is_governed_path("SECURITY.md"))
        self.assertFalse(is_governed_path("LICENSE"))

        # Tests
        self.assertFalse(is_governed_path("tests/test_validate.py"))
        self.assertFalse(is_governed_path("tests/scval_xdr.py"))
        self.assertFalse(is_governed_path("tests/fixtures/protocol-28/mock.toml"))
        self.assertFalse(is_governed_path("tests/vectors/scval_parity/scval_parity.json"))

        # Workflows & CI
        self.assertFalse(is_governed_path(".github/workflows/validate.yml"))
        self.assertFalse(is_governed_path(".github/dependabot.yml"))

        # Root build / meta
        self.assertFalse(is_governed_path("Makefile"))
        self.assertFalse(is_governed_path(".gitignore"))
        self.assertFalse(is_governed_path(".gitattributes"))

        # CHANGELOG itself is not a governed fixture/tool/schema
        self.assertFalse(is_governed_path("CHANGELOG.md"))

        # Root files with deceptive names
        self.assertFalse(is_governed_path("protocol-notes.txt"))
        self.assertFalse(is_governed_path("schemas-readme.md"))
        self.assertFalse(is_governed_path("tools-list.txt"))


class TestCheckChangelogCoreRules(unittest.TestCase):
    """Test core business rules for CHANGELOG validation."""

    def test_fixture_change_without_changelog_fails(self) -> None:
        res = check_changelog(["protocol-28/xdr/p28-xdr-cap83.toml"])
        self.assertFalse(res.passed)
        self.assertIn("protocol-28/xdr/p28-xdr-cap83.toml", res.governed_files)
        self.assertIn(RULE_ID, res.message)
        self.assertIn(OPT_OUT_LABEL, res.message)
        self.assertIn("protocol-28/xdr/p28-xdr-cap83.toml", res.message)

    def test_schema_change_without_changelog_fails(self) -> None:
        res = check_changelog(["schemas/fixture-v1.schema.json"])
        self.assertFalse(res.passed)
        self.assertIn("schemas/fixture-v1.schema.json", res.governed_files)
        self.assertIn(RULE_ID, res.message)
        self.assertIn(OPT_OUT_LABEL, res.message)

    def test_tool_change_without_changelog_fails(self) -> None:
        res = check_changelog(["tools/validate/validate.py"])
        self.assertFalse(res.passed)
        self.assertIn("tools/validate/validate.py", res.governed_files)
        self.assertIn(RULE_ID, res.message)
        self.assertIn(OPT_OUT_LABEL, res.message)

    def test_governed_changes_with_changelog_passes(self) -> None:
        # Fixture + CHANGELOG.md
        res1 = check_changelog(["protocol-28/xdr/new_fixture.toml", "CHANGELOG.md"])
        self.assertTrue(res1.passed)
        self.assertTrue(res1.has_changelog)
        self.assertIn("CHANGELOG.md has been updated", res1.message)

        # Schema + CHANGELOG.md
        res2 = check_changelog(["schemas/fixture-v1.schema.json", "./CHANGELOG.md"])
        self.assertTrue(res2.passed)
        self.assertTrue(res2.has_changelog)

        # Tool + CHANGELOG.md
        res3 = check_changelog(["tools/pack/pack.py", "CHANGELOG.md"])
        self.assertTrue(res3.passed)
        self.assertTrue(res3.has_changelog)

    def test_exempt_changes_only_pass_without_changelog(self) -> None:
        # Documentation only
        res1 = check_changelog(["docs/protocol-28.md", "README.md", "CONTRIBUTING.md"])
        self.assertTrue(res1.passed)
        self.assertEqual(res1.governed_files, [])
        self.assertIn("CHANGELOG.md is not required", res1.message)

        # Tests only
        res2 = check_changelog(["tests/test_validate.py", "tests/scval_xdr.py"])
        self.assertTrue(res2.passed)
        self.assertEqual(res2.governed_files, [])

        # Workflows only
        res3 = check_changelog([".github/workflows/validate.yml"])
        self.assertTrue(res3.passed)

        # Mixed exempt files
        res4 = check_changelog(["docs/contracts.md", "tests/test_badge.py", "Makefile", ".gitignore"])
        self.assertTrue(res4.passed)

    def test_empty_diff_passes(self) -> None:
        res = check_changelog([])
        self.assertTrue(res.passed)
        self.assertEqual(res.governed_files, [])

    def test_duplicate_file_inputs_deduplicated(self) -> None:
        res = check_changelog(["tools/foo.py", "tools/foo.py", "./tools/foo.py"])
        self.assertFalse(res.passed)
        self.assertEqual(res.governed_files, ["tools/foo.py"])

    def test_pr_number_not_required(self) -> None:
        # Acceptance criteria: do not require the changelog entry to contain the PR number
        res = check_changelog(["tools/badge/badge.py", "CHANGELOG.md"])
        self.assertTrue(res.passed)


class TestOptOutLabel(unittest.TestCase):
    """Test opt-out label ('no-changelog') bypassing the requirement."""

    def test_opt_out_label_bypasses_fixture_changes(self) -> None:
        res = check_changelog(
            ["protocol-28/xdr/p28-xdr-cap83.toml"],
            labels=["no-changelog"],
        )
        self.assertTrue(res.passed)
        self.assertTrue(res.has_opt_out)
        self.assertIn("bypassed by 'no-changelog' label", res.message)

    def test_opt_out_label_case_insensitive(self) -> None:
        res1 = check_changelog(["schemas/fixture-v1.schema.json"], labels=["NO-CHANGELOG"])
        self.assertTrue(res1.passed)
        self.assertTrue(res1.has_opt_out)

        res2 = check_changelog(["tools/pack/pack.py"], labels=["No-Changelog", "enhancement"])
        self.assertTrue(res2.passed)
        self.assertTrue(res2.has_opt_out)

    def test_other_labels_do_not_opt_out(self) -> None:
        res = check_changelog(
            ["protocol-28/xdr/p28-xdr-cap83.toml"],
            labels=["bug", "documentation", "dependencies"],
        )
        self.assertFalse(res.passed)
        self.assertFalse(res.has_opt_out)

    def test_parse_labels_string(self) -> None:
        self.assertEqual(parse_labels_string("no-changelog"), {"no-changelog"})
        self.assertEqual(parse_labels_string("bug, no-changelog, doc"), {"bug", "no-changelog", "doc"})
        self.assertEqual(
            parse_labels_string('["bug", "no-changelog", "", 123]'),
            {"bug", "no-changelog", "123"},
        )
        self.assertEqual(parse_labels_string(""), set())
        # Invalid JSON fallback
        self.assertEqual(parse_labels_string("[not valid json]"), {"[not", "valid", "json]"})
        # Mock json.loads returning non-list
        with patch("json.loads", return_value=123):
            self.assertEqual(parse_labels_string("[123]"), {"[123]"})

    def test_extract_labels_from_github_event_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_file = Path(tmpdir) / "event.json"

            # PR event with dict labels
            payload = {
                "pull_request": {
                    "number": 123,
                    "labels": [
                        {"name": "documentation"},
                        {"name": "no-changelog"},
                        {"other": "missing name"},
                    ],
                }
            }
            event_file.write_text(json.dumps(payload), encoding="utf-8")
            labels = extract_labels_from_event(event_file)
            self.assertIn("no-changelog", labels)
            self.assertIn("documentation", labels)

            # PR event with string labels
            payload_str = {
                "pull_request": {
                    "labels": ["no-changelog", "bug"],
                }
            }
            event_file.write_text(json.dumps(payload_str), encoding="utf-8")
            labels_str = extract_labels_from_event(event_file)
            self.assertEqual(labels_str, {"no-changelog", "bug"})

            # Event without no-changelog
            payload_no_opt = {
                "pull_request": {
                    "labels": [{"name": "bug"}],
                }
            }
            event_file.write_text(json.dumps(payload_no_opt), encoding="utf-8")
            labels_no_opt = extract_labels_from_event(event_file)
            self.assertEqual(labels_no_opt, {"bug"})

            # Non-dict pull_request or non-list labels
            event_file.write_text(json.dumps({"pull_request": "not_a_dict"}), encoding="utf-8")
            self.assertEqual(extract_labels_from_event(event_file), set())
            event_file.write_text(json.dumps({"pull_request": {"labels": "not_a_list"}}), encoding="utf-8")
            self.assertEqual(extract_labels_from_event(event_file), set())

            # Non-existent or invalid file
            self.assertEqual(extract_labels_from_event(Path(tmpdir) / "nonexistent.json"), set())
            bad_file = Path(tmpdir) / "bad.json"
            bad_file.write_text("invalid json", encoding="utf-8")
            self.assertEqual(extract_labels_from_event(bad_file), set())


class TestEdgeCases(unittest.TestCase):
    """Test renames, deletions, line parsing, and restricted paths."""

    def test_file_deletion_governed_path(self) -> None:
        # Deleting a fixture without changelog must fail
        res = check_changelog(["D\tprotocol-28/xdr/old_fixture.toml"])
        self.assertFalse(res.passed)
        self.assertIn("protocol-28/xdr/old_fixture.toml", res.governed_files)

        # Deleting a fixture with changelog passes
        res_with = check_changelog(["D\tprotocol-28/xdr/old_fixture.toml", "CHANGELOG.md"])
        self.assertTrue(res_with.passed)

        # Deleting an exempt file passes without changelog
        res_doc = check_changelog(["D\tdocs/old_guide.md"])
        self.assertTrue(res_doc.passed)

    def test_file_renames(self) -> None:
        # Git diff status line with rename
        res1 = check_changelog(["R100\ttools/old.py\ttools/new.py"])
        self.assertFalse(res1.passed)
        self.assertIn("tools/old.py", res1.governed_files)
        self.assertIn("tools/new.py", res1.governed_files)

        # Arrow rename syntax
        res2 = check_changelog(["protocol-28/xdr/a.toml -> protocol-28/xdr/b.toml"])
        self.assertFalse(res2.passed)
        self.assertIn("protocol-28/xdr/a.toml", res2.governed_files)
        self.assertIn("protocol-28/xdr/b.toml", res2.governed_files)

        # Rename with changelog passes
        res3 = check_changelog(
            ["protocol-28/xdr/a.toml -> protocol-28/xdr/b.toml", "CHANGELOG.md"]
        )
        self.assertTrue(res3.passed)

        # Rename from exempt to governed
        res4 = check_changelog(["tests/helper.py -> tools/helper.py"])
        self.assertFalse(res4.passed)
        self.assertIn("tools/helper.py", res4.governed_files)

    def test_parse_changed_file_line(self) -> None:
        self.assertEqual(
            parse_changed_file_line("M\tprotocol-28/xdr/foo.toml"),
            ["protocol-28/xdr/foo.toml"],
        )
        self.assertEqual(
            parse_changed_file_line("A\tschemas/new.schema.json"),
            ["schemas/new.schema.json"],
        )
        self.assertEqual(
            parse_changed_file_line("D\ttools/old.py"),
            ["tools/old.py"],
        )
        self.assertEqual(
            parse_changed_file_line("R100\ttools/a.py\ttools/b.py"),
            ["tools/a.py", "tools/b.py"],
        )
        self.assertEqual(
            parse_changed_file_line("nonstatus\ttools/b.py"),
            ["nonstatus", "tools/b.py"],
        )
        self.assertEqual(
            parse_changed_file_line("tools/a.py -> tools/b.py"),
            ["tools/a.py", "tools/b.py"],
        )
        self.assertEqual(
            parse_changed_file_line("simple/file/path.txt"),
            ["simple/file/path.txt"],
        )
        self.assertEqual(parse_changed_file_line("# comment line"), [])
        self.assertEqual(parse_changed_file_line("   "), [])

    def test_restricted_and_nested_paths(self) -> None:
        # Deeply nested governed file
        self.assertTrue(
            is_governed_path("protocol-28/xdr/cap-0083/p28-xdr-cap83-empty-tx-set.toml")
        )
        self.assertTrue(
            is_governed_path("protocol-29/evidence/testnet/get-latest-ledger.json")
        )
        self.assertTrue(
            is_governed_path("schemas/proposed/simulation-resource-estimate.expect.json")
        )
        self.assertTrue(
            is_governed_path("tools/validate/portable_names.py")
        )

        # Deceptive prefixes under exempt directories
        self.assertFalse(
            is_governed_path("tests/fixtures/protocol-28/sample.toml")
        )
        self.assertFalse(
            is_governed_path("docs/tools/overview.md")
        )
        self.assertFalse(
            is_governed_path("docs/schemas/spec.md")
        )


class TestGitDiffHelper(unittest.TestCase):
    """Test get_git_diff_files under various git conditions."""

    def test_get_git_diff_files_real_repo(self) -> None:
        # Diff against HEAD should succeed and return empty list
        files = get_git_diff_files("HEAD")
        self.assertIsInstance(files, list)

    def test_get_git_diff_files_with_origin_prefix_fallback(self) -> None:
        mock_res = MagicMock(returncode=0, stdout="CHANGELOG.md\n")
        with patch("subprocess.run", return_value=mock_res):
            files = get_git_diff_files("origin/HEAD")
            self.assertEqual(files, ["CHANGELOG.md"])

    def test_get_git_diff_files_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as ctx:
                get_git_diff_files("HEAD")
            self.assertIn("git executable not found", str(ctx.exception))

    def test_get_git_diff_files_all_fail(self) -> None:
        mock_res = MagicMock(returncode=1, stderr="fatal: bad revision")
        with patch("subprocess.run", return_value=mock_res):
            with self.assertRaises(RuntimeError) as ctx:
                get_git_diff_files("nonexistent_ref_12345")
            self.assertIn("git diff failed for base ref", str(ctx.exception))


class TestCliInterface(unittest.TestCase):
    """Test CLI invocation, stdin handling, and summary file output."""

    def setUp(self) -> None:
        self._env_patcher = patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop("PR_LABELS", None)
        os.environ.pop("GITHUB_EVENT_PATH", None)

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_cli_positional_arguments_governed_fail(self) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = main(["protocol-28/xdr/test.toml"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR: [F-055]", stderr.getvalue())

    def test_cli_positional_arguments_governed_with_changelog_pass(self) -> None:
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["protocol-28/xdr/test.toml", "CHANGELOG.md"])
        self.assertEqual(code, 0)
        self.assertIn("CHANGELOG.md has been updated", stdout.getvalue())

    def test_cli_flag_files(self) -> None:
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["--files", "tools/badge/badge.py", "CHANGELOG.md"])
        self.assertEqual(code, 0)
        self.assertIn("CHANGELOG.md has been updated", stdout.getvalue())

    def test_cli_with_opt_out_label_flag(self) -> None:
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["protocol-28/xdr/test.toml", "--label", "no-changelog"])
        self.assertEqual(code, 0)
        self.assertIn("bypassed by 'no-changelog' label", stdout.getvalue())

    def test_cli_with_labels_str_flag(self) -> None:
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["protocol-28/xdr/test.toml", "--labels", "documentation,no-changelog"])
        self.assertEqual(code, 0)
        self.assertIn("bypassed by 'no-changelog' label", stdout.getvalue())

    def test_cli_with_event_path_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_file = Path(tmpdir) / "event.json"
            event_file.write_text(json.dumps({"pull_request": {"labels": [{"name": "no-changelog"}]}}), encoding="utf-8")
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["protocol-28/xdr/test.toml", "--event-path", str(event_file)])
            self.assertEqual(code, 0)
            self.assertIn("bypassed by 'no-changelog' label", stdout.getvalue())

    def test_cli_with_stdin_dash(self) -> None:
        stdin = io.StringIO("tools/validate/validate.py\n\nCHANGELOG.md\n")
        stdout = io.StringIO()
        with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            code = main(["-"])
        self.assertEqual(code, 0)
        self.assertIn("CHANGELOG.md has been updated", stdout.getvalue())

    def test_cli_with_stdin_flag(self) -> None:
        stdin = io.StringIO("tools/validate/validate.py\nCHANGELOG.md\n")
        stdout = io.StringIO()
        with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            code = main(["--stdin"])
        self.assertEqual(code, 0)
        self.assertIn("CHANGELOG.md has been updated", stdout.getvalue())

    def test_cli_with_piped_stdin(self) -> None:
        stdin = io.StringIO("tools/validate/validate.py\n\nCHANGELOG.md\n")
        stdout = io.StringIO()
        with patch("sys.stdin", stdin), patch("sys.stdout", stdout), patch("sys.stdin.isatty", return_value=False):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("CHANGELOG.md has been updated", stdout.getvalue())

    def test_cli_with_base_flag_success(self) -> None:
        stdout = io.StringIO()
        with patch("tools.validate.check_changelog.get_git_diff_files", return_value=["CHANGELOG.md"]):
            with patch("sys.stdout", stdout):
                code = main(["--base", "HEAD"])
        self.assertEqual(code, 0)

    def test_cli_with_base_flag_git_error(self) -> None:
        stderr = io.StringIO()
        with patch("tools.validate.check_changelog.get_git_diff_files", side_effect=RuntimeError("fatal diff")):
            with patch("sys.stderr", stderr):
                code = main(["--base", "invalid_ref"])
        self.assertEqual(code, 2)
        self.assertIn("Error determining changed files via git", stderr.getvalue())

    def test_cli_with_base_flag_called_process_error(self) -> None:
        stderr = io.StringIO()
        with patch(
            "tools.validate.check_changelog.get_git_diff_files",
            side_effect=subprocess.CalledProcessError(2, ["git", "diff"], stderr="bad revision"),
        ):
            with patch("sys.stderr", stderr):
                code = main(["--base", "invalid_ref"])
        self.assertEqual(code, 2)
        self.assertIn("Error determining changed files via git", stderr.getvalue())

    def test_cli_no_args_fallback_git_diff(self) -> None:
        stdout = io.StringIO()
        with patch("tools.validate.check_changelog.get_git_diff_files", return_value=[]):
            with patch("sys.stdout", stdout):
                code = main([])
        self.assertEqual(code, 0)

    def test_cli_no_args_fallback_git_diff_raises(self) -> None:
        stdout = io.StringIO()
        with patch("tools.validate.check_changelog.get_git_diff_files", side_effect=Exception("error")):
            with patch("sys.stdout", stdout):
                code = main([])
        self.assertEqual(code, 0)

    def test_cli_with_pr_labels_env(self) -> None:
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PR_LABELS": "no-changelog"}):
            with patch("sys.stdout", stdout):
                code = main(["schemas/fixture-v1.schema.json"])
        self.assertEqual(code, 0)
        self.assertIn("bypassed by 'no-changelog' label", stdout.getvalue())

    def test_cli_summary_file_written_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "summary.md"
            main([
                "protocol-28/xdr/test.toml",
                "--label", "no-changelog",
                "--summary-file", str(summary_file),
            ])
            self.assertTrue(summary_file.exists())
            content = summary_file.read_text(encoding="utf-8")
            self.assertIn("CHANGELOG Validation [F-055]", content)
            self.assertIn("PASSED", content)

    def test_cli_summary_file_written_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "summary.md"
            with patch("sys.stderr", io.StringIO()):
                main([
                    "protocol-28/xdr/test.toml",
                    "--summary-file", str(summary_file),
                ])
            self.assertTrue(summary_file.exists())
            content = summary_file.read_text(encoding="utf-8")
            self.assertIn("FAILED", content)
            self.assertIn("protocol-28/xdr/test.toml", content)

    def test_cli_summary_file_write_error(self) -> None:
        stderr = io.StringIO()
        with patch("tools.validate.check_changelog.build_markdown_summary", side_effect=OSError("disk full")):
            with patch("sys.stderr", stderr):
                main([
                    "docs/README.md",
                    "--summary-file", "/some/path/summary.md",
                ])
        self.assertIn("Warning: could not write summary file", stderr.getvalue())

    def test_build_markdown_summary_failure(self) -> None:
        result = ChangelogCheckResult(
            passed=False,
            governed_files=["protocol-28/xdr/foo.toml"],
            has_changelog=False,
            has_opt_out=False,
            message="Error message",
        )
        md = build_markdown_summary(result)
        self.assertIn("FAILED", md)
        self.assertIn("protocol-28/xdr/foo.toml", md)
        self.assertIn("no-changelog", md)

    def test_module_executed_as_main(self) -> None:
        old_argv = sys.argv
        sys.argv = ["check_changelog.py", "docs/protocol-28.md"]
        self.addCleanup(setattr, sys, "argv", old_argv)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(CHECK_CHANGELOG_PATH), run_name="__main__")
            self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
