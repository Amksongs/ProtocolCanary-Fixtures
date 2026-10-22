"""Tests for output path collision guards and safety (F-117, issue #410).

Ensures tools/registry/generate.py and tools/release/manifest.py refuse
output targets that would overwrite input fixtures, payloads, pack directories,
or release archives, including through aliases (symlinks, hard links, .., normcase).
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_support as support

from tools.common import paths
from tools.pack import pack
from tools.registry import generate
from tools.release import manifest


class TestPathSafetyHelper(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_canonical_path_normalizes_and_resolves_symlinks(self) -> None:
        target = self.root / "sub" / ".." / "file.txt"
        canon = paths.canonical_path(target)
        self.assertEqual(canon, os.path.normcase(os.path.realpath(str(target))))

    def test_is_same_file_existing_and_nonexistent(self) -> None:
        f1 = self.root / "f1.txt"
        f1.write_text("a", encoding="utf-8")
        f2 = self.root / "sub" / ".." / "f1.txt"
        self.assertTrue(paths.is_same_file(f1, f2))

        nonexistent1 = self.root / "sub" / ".." / "new.txt"
        nonexistent2 = self.root / "new.txt"
        self.assertTrue(paths.is_same_file(nonexistent1, nonexistent2))

    def test_check_target_safety_refuses_directory(self) -> None:
        d = self.root / "somedir"
        d.mkdir()
        with self.assertRaisesRegex(ValueError, "target is a directory"):
            paths.check_target_safety(d, [])

    def test_check_target_safety_collision_message(self) -> None:
        f = self.root / "fixture.toml"
        f.write_text("content", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            paths.check_target_safety(f, [(f, "a pack fixture")])
        self.assertIn("refusing to write", str(caught.exception))
        self.assertIn("it is the same file as a pack fixture", str(caught.exception))


class TestRegistryGeneratorOutputSafety(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        # Build a valid minimal pack with a fixture and a payload
        self.pack_dir = self.root / "protocol-28"
        self.pack_dir.mkdir()
        rpc_dir = self.pack_dir / "rpc"
        rpc_dir.mkdir()

        self.payload = rpc_dir / "sample.bin"
        self.payload.write_bytes(b"payload data")

        self.fixture = rpc_dir / "p28-rpc-test.toml"
        self.fixture.write_text(
            f"""id = "p28-rpc-test"
protocol = 28
surface = "rpc"
category = "smoke"
description = "test"
source_reference = "CAP-0083"
input_file = "sample.bin"

[expect]
kind = "rpc-response"
""",
            encoding="utf-8",
        )
        self.fixture_bytes = self.fixture.read_bytes()
        self.payload_bytes = self.payload.read_bytes()

    def run_generate(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = generate.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_registry_path_allowed_and_idempotent(self) -> None:
        code, out, err = self.run_generate(str(self.pack_dir))
        self.assertEqual(code, 0, err)
        default_output = self.pack_dir / "registry-v1.json"
        self.assertTrue(default_output.is_file())
        first_bytes = default_output.read_bytes()

        # Re-running over existing registry-v1.json is allowed and byte-identical
        code2, out2, err2 = self.run_generate(str(self.pack_dir))
        self.assertEqual(code2, 0, err2)
        self.assertEqual(default_output.read_bytes(), first_bytes)

    def test_output_to_fresh_path_allowed(self) -> None:
        fresh = self.root / "out" / "custom_reg.json"
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(fresh))
        self.assertEqual(code, 0, err)
        self.assertTrue(fresh.is_file())

    def test_stdout_allowed(self) -> None:
        code, out, err = self.run_generate(str(self.pack_dir), "--stdout")
        self.assertEqual(code, 0, err)
        self.assertIn('"registryVersion": 1', out)

    def test_refuses_overwriting_fixture_direct_path(self) -> None:
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(self.fixture))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as a pack fixture", err)
        self.assertIn("FAILED: no registry written", err)
        self.assertEqual(self.fixture.read_bytes(), self.fixture_bytes)

    def test_refuses_overwriting_fixture_relative_path(self) -> None:
        rel_fixture = self.pack_dir / "rpc" / ".." / "rpc" / "p28-rpc-test.toml"
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(rel_fixture))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as a pack fixture", err)
        self.assertIn("FAILED: no registry written", err)
        self.assertEqual(self.fixture.read_bytes(), self.fixture_bytes)

    def test_refuses_overwriting_fixture_via_symlink(self) -> None:
        sym = self.root / "sym_fixture.toml"
        try:
            os.symlink(self.fixture, sym)
        except (OSError, NotImplementedError):
            self.skipTest("platform does not support symlinks")
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(sym))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as a pack fixture", err)
        self.assertEqual(self.fixture.read_bytes(), self.fixture_bytes)

    def test_refuses_overwriting_fixture_via_symlink_directory(self) -> None:
        sym_dir = self.root / "sym_rpc"
        try:
            os.symlink(self.pack_dir / "rpc", sym_dir)
        except (OSError, NotImplementedError):
            self.skipTest("platform does not support directory symlinks")
        target = sym_dir / "p28-rpc-test.toml"
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(target))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as a pack fixture", err)
        self.assertEqual(self.fixture.read_bytes(), self.fixture_bytes)

    def test_refuses_overwriting_fixture_via_hardlink(self) -> None:
        hard = self.root / "hard_fixture.toml"
        try:
            os.link(self.fixture, hard)
        except (OSError, NotImplementedError):
            self.skipTest("platform does not support hard links")
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(hard))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as a pack fixture", err)
        self.assertEqual(self.fixture.read_bytes(), self.fixture_bytes)

    def test_refuses_output_equal_to_pack_directory(self) -> None:
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(self.pack_dir))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as the pack directory", err)
        self.assertTrue(self.pack_dir.is_dir())

    def test_refuses_output_equal_to_payload_file(self) -> None:
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(self.payload))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as a pack payload", err)
        self.assertEqual(self.payload.read_bytes(), self.payload_bytes)

    def test_refuses_existing_directory_target(self) -> None:
        some_dir = self.root / "existing_dir"
        some_dir.mkdir()
        code, out, err = self.run_generate(str(self.pack_dir), "--output", str(some_dir))
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("target is a directory", err)


class TestReleaseManifestOutputSafety(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        support.write_pack(self.root)
        self.info = pack.build_archive(self.root / "pack", self.root / "out", "1.4.2")
        self.archive = self.info.path
        self.archive_bytes = self.archive.read_bytes()

    def run_manifest(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = manifest.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_manifest_next_to_archive_allowed(self) -> None:
        code, out, err = self.run_manifest(str(self.archive), "--revision", support.REVISION)
        self.assertEqual(code, 0, err)
        manifest_path = self.archive.with_name("protocolcanary-fixtures-1.4.2.manifest.json")
        self.assertTrue(manifest_path.is_file())

    def test_explicit_manifest_and_different_sha256_allowed(self) -> None:
        out_manifest = self.root / "custom.manifest.json"
        out_sha = self.root / "custom.sha256"
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(out_manifest),
            "--sha256-file",
            str(out_sha),
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(out_manifest.is_file())
        self.assertTrue(out_sha.is_file())

    def test_refuses_output_equal_to_archive_direct(self) -> None:
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(self.archive),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as the release archive", err)
        self.assertIn("FAILED: no manifest written", err)
        self.assertEqual(self.archive.read_bytes(), self.archive_bytes)

    def test_refuses_output_equal_to_archive_via_symlink(self) -> None:
        sym = self.root / "sym_archive.tar.gz"
        try:
            os.symlink(self.archive, sym)
        except (OSError, NotImplementedError):
            self.skipTest("platform does not support symlinks")
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(sym),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as the release archive", err)
        self.assertEqual(self.archive.read_bytes(), self.archive_bytes)

    def test_refuses_output_equal_to_archive_via_hardlink(self) -> None:
        hard = self.root / "hard_archive.tar.gz"
        try:
            os.link(self.archive, hard)
        except (OSError, NotImplementedError):
            self.skipTest("platform does not support hard links")
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(hard),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as the release archive", err)
        self.assertEqual(self.archive.read_bytes(), self.archive_bytes)

    def test_refuses_sha256_file_equal_to_archive(self) -> None:
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--sha256-file",
            str(self.archive),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("it is the same file as the release archive", err)
        self.assertEqual(self.archive.read_bytes(), self.archive_bytes)

    def test_refuses_output_and_sha256_file_same_target(self) -> None:
        target = self.root / "same_target.txt"
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(target),
            "--sha256-file",
            str(target),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("--output and --sha256-file name the same file", err)
        self.assertFalse(target.exists())

    def test_refuses_output_and_sha256_file_via_symlink(self) -> None:
        t1 = self.root / "file1.txt"
        t1.write_text("orig", encoding="utf-8")
        sym1 = self.root / "sym1.txt"
        try:
            os.symlink(t1, sym1)
        except (OSError, NotImplementedError):
            self.skipTest("platform does not support symlinks")
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(t1),
            "--sha256-file",
            str(sym1),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("--output and --sha256-file name the same file", err)

    def test_refuses_existing_directory_target(self) -> None:
        d = self.root / "dest_dir"
        d.mkdir()
        code, out, err = self.run_manifest(
            str(self.archive),
            "--revision",
            support.REVISION,
            "--output",
            str(d),
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        self.assertIn("target is a directory", err)


if __name__ == "__main__":
    unittest.main()
