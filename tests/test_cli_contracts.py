"""Tests for tool command-line contracts documented in docs/tools.md (issue #351)."""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

VALID_FIXTURE_TOML = """id = "p28-xdr-cli-test"
protocol = 28
surface = "xdr"
category = "cap-0083"
description = "CLI contract test fixture"
source_reference = "CAP-0083"
type = "StellarValue"
kind = "roundtrip"
value_base64 = "EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA"
"""


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.pack_dir = Path(self.temp_dir) / "protocol-28"
        self.pack_dir.mkdir(parents=True)
        (self.pack_dir / "xdr").mkdir(parents=True)
        (self.pack_dir / "xdr" / "fixture.toml").write_text(VALID_FIXTURE_TOML, encoding="utf-8")

    def tearDown(self) -> None:
        # Restore permissions if any directory was made read-only
        for p in Path(self.temp_dir).rglob("*"):
            try:
                os.chmod(p, stat.S_IRWXU)
            except OSError:
                pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_tool(self, tool_rel_path: str, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [PYTHON, str(REPO_ROOT / tool_rel_path), *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_doc_options_match_help(self) -> None:
        docs_text = (REPO_ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
        tools_with_help = [
            ("tools/pack/pack.py", "tools/pack/pack.py"),
            ("tools/pack/verify_archive.py", "tools/pack/verify_archive.py"),
            ("tools/registry/generate.py", "tools/registry/generate.py"),
            ("tools/release/manifest.py", "tools/release/manifest.py"),
            ("tools/validate/validate.py", "tools/validate/validate.py"),
        ]

        for script, section in tools_with_help:
            p = self.run_tool(script, "--help")
            help_opts = set(re.findall(r"(--[a-z0-9-]+)", p.stdout))

            sec_idx = docs_text.find(f"## `{section}`")
            self.assertNotEqual(sec_idx, -1, f"Section {section} not found in docs/tools.md")
            next_sec_idx = docs_text.find("## `tools/", sec_idx + 1)
            if next_sec_idx == -1:
                next_sec_idx = docs_text.find("## Observed Inconsistencies", sec_idx + 1)
            sec_text = docs_text[sec_idx:next_sec_idx]

            opts_idx = sec_text.find("### Options")
            exit_idx = sec_text.find("### Exit Codes")
            self.assertNotEqual(opts_idx, -1)
            self.assertNotEqual(exit_idx, -1)
            opts_section = sec_text[opts_idx:exit_idx]
            doc_opts = set(re.findall(r"(--[a-z0-9-]+)", opts_section))

            self.assertEqual(
                help_opts, doc_opts,
                f"Options mismatch for {script}: help={help_opts}, docs={doc_opts}",
            )

    # 1. tools/pack/pack.py
    def test_pack_cli(self) -> None:
        tool = "tools/pack/pack.py"
        # --help
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)
        self.assertIn("usage: pack.py", p_help.stdout)

        # Missing args
        p_noargs = self.run_tool(tool)
        self.assertEqual(p_noargs.returncode, 2)
        self.assertIn("usage: pack.py", p_noargs.stderr)

        # Missing --version
        p_no_ver = self.run_tool(tool, str(self.pack_dir))
        self.assertEqual(p_no_ver.returncode, 2)

        # Invalid semver version (PackError, exit 1)
        p_bad_ver = self.run_tool(tool, str(self.pack_dir), "--version", "invalid_ver")
        self.assertEqual(p_bad_ver.returncode, 1)

        # Nonexistent pack path with only path argument (missing --version, exit 2)
        p_nonexistent_no_ver = self.run_tool(tool, str(Path(self.temp_dir) / "nonexistent"))
        self.assertEqual(p_nonexistent_no_ver.returncode, 2)

        # Nonexistent pack path with --version (PackError, exit 1)
        p_nonexistent = self.run_tool(tool, str(Path(self.temp_dir) / "nonexistent"), "--version", "1.0.0")
        self.assertEqual(p_nonexistent.returncode, 1)

        # Valid arguments
        out_dir = Path(self.temp_dir) / "dist"
        p_valid = self.run_tool(tool, str(self.pack_dir), "--version", "1.0.0", "--output-dir", str(out_dir))
        self.assertEqual(p_valid.returncode, 0)
        self.assertIn("sha256", p_valid.stdout)

        # Idempotence: running same call returns same exit code
        p_valid_2 = self.run_tool(tool, str(self.pack_dir), "--version", "1.0.0", "--output-dir", str(out_dir))
        self.assertEqual(p_valid_2.returncode, 0)

        # Unknown option
        p_unknown = self.run_tool(tool, str(self.pack_dir), "--unknown-flag")
        self.assertEqual(p_unknown.returncode, 2)

        # Read-only output directory (exit 1)
        ro_dir = Path(self.temp_dir) / "ro_dist"
        ro_dir.mkdir(parents=True, exist_ok=True)
        ro_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        p_ro = self.run_tool(tool, str(self.pack_dir), "--version", "1.0.0", "--output-dir", str(ro_dir))
        self.assertEqual(p_ro.returncode, 1)

        # Empty pack (fails build, PackError, exit 1)
        empty_pack = Path(self.temp_dir) / "empty-pack"
        empty_pack.mkdir()
        p_empty = self.run_tool(tool, str(empty_pack), "--version", "1.0.0")
        self.assertEqual(p_empty.returncode, 1)

    # 2. tools/pack/verify_archive.py
    def test_verify_archive_cli(self) -> None:
        tool = "tools/pack/verify_archive.py"
        # First build a valid archive
        out_dir = Path(self.temp_dir) / "dist"
        self.run_tool("tools/pack/pack.py", str(self.pack_dir), "--version", "1.0.0", "--output-dir", str(out_dir))
        archive_path = out_dir / "protocolcanary-fixtures-1.0.0.tar.gz"
        self.assertTrue(archive_path.is_file())

        # --help
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)
        self.assertIn("usage: verify_archive.py", p_help.stdout)

        # No args
        p_noargs = self.run_tool(tool)
        self.assertEqual(p_noargs.returncode, 2)

        # Nonexistent archive path (observed exit code 2)
        p_nonexistent = self.run_tool(tool, str(Path(self.temp_dir) / "missing.tar.gz"))
        self.assertEqual(p_nonexistent.returncode, 2)

        # Directory instead of file (UnreadableArchive, exit 2)
        p_dir = self.run_tool(tool, str(out_dir))
        self.assertEqual(p_dir.returncode, 2)

        # Unreadable archive file (non-gzip, UnreadableArchive, exit 2)
        unreadable_tar = Path(self.temp_dir) / "unreadable.tar.gz"
        unreadable_tar.write_bytes(b"not a gzip file at all")
        p_unreadable = self.run_tool(tool, str(unreadable_tar))
        self.assertEqual(p_unreadable.returncode, 2)
        self.assertIn("cannot read the archive", p_unreadable.stderr)

        # Invalid archive missing registry.json (verification failure, exit 1)
        empty_tar = Path(self.temp_dir) / "empty.tar.gz"
        with tarfile.open(empty_tar, "w:gz") as tar:
            pass
        p_empty = self.run_tool(tool, str(empty_tar))
        self.assertEqual(p_empty.returncode, 1)
        self.assertIn("the archive has no registry.json at its root", p_empty.stderr)

        # Valid archive
        p_valid = self.run_tool(tool, str(archive_path))
        self.assertEqual(p_valid.returncode, 0)
        self.assertTrue(p_valid.stdout.startswith("OK: protocolcanary-fixtures-1.0.0.tar.gz"))
        self.assertIn("valid; registry and pack digest match", p_valid.stdout)

        # Hash mismatch (exit 1)
        bad_hash = "0" * 64
        p_bad_hash = self.run_tool(tool, "--sha256", bad_hash, str(archive_path))
        self.assertEqual(p_bad_hash.returncode, 1)

        # Unknown option
        p_unknown = self.run_tool(tool, "--bad-opt", str(archive_path))
        self.assertEqual(p_unknown.returncode, 2)

    # 3. tools/registry/generate.py
    def test_generate_cli(self) -> None:
        tool = "tools/registry/generate.py"
        # --help
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)
        self.assertIn("usage: generate.py", p_help.stdout)

        # No args
        p_noargs = self.run_tool(tool)
        self.assertEqual(p_noargs.returncode, 2)

        # Nonexistent path (observed exit code 1)
        p_nonexistent = self.run_tool(tool, str(Path(self.temp_dir) / "nonexistent"))
        self.assertEqual(p_nonexistent.returncode, 1)

        # Valid with --stdout
        p_stdout = self.run_tool(tool, "--stdout", str(self.pack_dir))
        self.assertEqual(p_stdout.returncode, 0)
        self.assertIn('"packDigest":', p_stdout.stdout)

        # Mutually exclusive options --output and --stdout (exit 2)
        p_conflict = self.run_tool(tool, "--stdout", "--output", "reg.json", str(self.pack_dir))
        self.assertEqual(p_conflict.returncode, 2)

        # Empty pack (exit 1)
        empty_pack = Path(self.temp_dir) / "empty-pack"
        empty_pack.mkdir()
        p_empty = self.run_tool(tool, "--stdout", str(empty_pack))
        self.assertEqual(p_empty.returncode, 1)

        # Empty pack with --allow-empty without --protocol (exit 1)
        p_empty_no_proto = self.run_tool(tool, "--allow-empty", "--stdout", str(empty_pack))
        self.assertEqual(p_empty_no_proto.returncode, 1)

        # Empty pack with --allow-empty and --protocol (exit 0)
        p_empty_allow = self.run_tool(tool, "--allow-empty", "--protocol", "29", "--stdout", str(empty_pack))
        self.assertEqual(p_empty_allow.returncode, 0)
        self.assertIn('"protocol": 29', p_empty_allow.stdout)
        self.assertIn('"fixtures": []', p_empty_allow.stdout)

    # 4. tools/release/manifest.py
    def test_manifest_cli(self) -> None:
        tool = "tools/release/manifest.py"
        # Build archive first
        out_dir = Path(self.temp_dir) / "dist"
        self.run_tool("tools/pack/pack.py", str(self.pack_dir), "--version", "1.0.0", "--output-dir", str(out_dir))
        archive_path = out_dir / "protocolcanary-fixtures-1.0.0.tar.gz"

        # --help
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)

        # No args (exit 2)
        p_noargs = self.run_tool(tool)
        self.assertEqual(p_noargs.returncode, 2)

        # Nonexistent archive without --revision (missing args, exit 2)
        p_nonexistent_no_rev = self.run_tool(tool, str(Path(self.temp_dir) / "missing.tar.gz"))
        self.assertEqual(p_nonexistent_no_rev.returncode, 2)

        # Nonexistent archive with --revision (ManifestError, exit 1)
        p_nonexistent = self.run_tool(tool, "--revision", "a" * 40, str(Path(self.temp_dir) / "missing.tar.gz"))
        self.assertEqual(p_nonexistent.returncode, 1)

        # Invalid revision (not 40-char hex, ManifestError, exit 1)
        p_bad_rev = self.run_tool(tool, "--revision", "not_a_sha", str(archive_path))
        self.assertEqual(p_bad_rev.returncode, 1)

        # Valid call
        manifest_out = Path(self.temp_dir) / "test.manifest.json"
        p_valid = self.run_tool(tool, "--revision", "a" * 40, "--output", str(manifest_out), str(archive_path))
        self.assertEqual(p_valid.returncode, 0)
        self.assertTrue(manifest_out.is_file())

    # 5. tools/badge/badge.py
    def test_badge_cli(self) -> None:
        tool = "tools/badge/badge.py"
        # No args (updates or confirms badge, exits 0)
        p_noargs = self.run_tool(tool)
        self.assertEqual(p_noargs.returncode, 0)

        # --check (exits 0 on clean repo)
        p_check = self.run_tool(tool, "--check")
        self.assertEqual(p_check.returncode, 0)

        # --help prints usage and exits 0 without touching README.md
        # (issue #392; the old behaviour of ignoring --help is gone)
        readme = Path(__file__).resolve().parent.parent / "README.md"
        before = readme.read_bytes()
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)
        self.assertIn("usage: badge.py", p_help.stdout)
        self.assertEqual(readme.read_bytes(), before)

        # An unknown argument prints usage to stderr and exits 2 without
        # touching README.md (issue #392)
        p_extra = self.run_tool(tool, "nonexistent_path_xyz")
        self.assertEqual(p_extra.returncode, 2)
        self.assertIn("usage: badge.py", p_extra.stderr)
        self.assertEqual(readme.read_bytes(), before)

    # 6. tools/validate/validate.py
    def test_validate_cli(self) -> None:
        tool = "tools/validate/validate.py"
        # --help
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)
        self.assertIn("usage: validate.py", p_help.stdout)

        # Valid root
        p_valid = self.run_tool(tool, str(self.pack_dir))
        self.assertEqual(p_valid.returncode, 0)
        self.assertIn("OK: 1 fixture file(s) valid", p_valid.stdout)

        # Valid with --format json
        p_json = self.run_tool(tool, "--format", "json", str(self.pack_dir))
        self.assertEqual(p_json.returncode, 0)
        self.assertIn('"valid": true', p_json.stdout)
        self.assertEqual(p_json.stderr, "")

        # Nonexistent root (observed exit code 1)
        p_nonexistent = self.run_tool(tool, str(Path(self.temp_dir) / "missing_dir"))
        self.assertEqual(p_nonexistent.returncode, 1)

        # Invalid format choice (syntax error, exit 2)
        p_bad_format = self.run_tool(tool, "--format", "invalid_fmt", str(self.pack_dir))
        self.assertEqual(p_bad_format.returncode, 2)

    # 7. tools/validate/schema_sync.py
    def test_schema_sync_cli(self) -> None:
        tool = "tools/validate/schema_sync.py"
        # No args
        p_noargs = self.run_tool(tool)
        self.assertEqual(p_noargs.returncode, 0)
        self.assertIn("OK: schemas/fixture-v1.schema.json matches", p_noargs.stdout)

        # --help prints usage and exits 0 (issue #392; the old behaviour of
        # treating --help as an unexpected argument is gone)
        p_help = self.run_tool(tool, "--help")
        self.assertEqual(p_help.returncode, 0)
        self.assertIn("usage: schema_sync.py", p_help.stdout)

        # Any extra arg exits 2
        p_extra = self.run_tool(tool, "extra_arg")
        self.assertEqual(p_extra.returncode, 2)


if __name__ == "__main__":
    unittest.main()
