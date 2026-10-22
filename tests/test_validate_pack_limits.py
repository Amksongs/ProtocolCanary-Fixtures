"""Tests for pack limits enforcement in validator and tools (issue #369).

Approved under decision D-06:
- MAX_FILES = 2000
- MAX_TOTAL_BYTES = 16 MiB (16,777,216 bytes)
- MAX_FILE_BYTES = 1 MiB (1,048,576 bytes)
- MAX_DEPTH = 8
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.common import pack_limits
from tools.pack import pack
from tools.registry import generate
from tools.validate import validate


def make_valid_fixture(fid: str = "p28-xdr-sample", extra_comment_bytes: int = 0) -> str:
    comment = ""
    if extra_comment_bytes > 0:
        comment = "# " + ("x" * (extra_comment_bytes - 3)) + "\n"
    base = (
        f'{comment}'
        f'id = "{fid}"\n'
        'protocol = 28\n'
        'surface = "xdr"\n'
        'category = "cap-0083"\n'
        'description = "sample fixture"\n'
        'source_reference = "CAP-0083"\n'
        'type = "StellarValue"\n'
        'kind = "roundtrip"\n'
        'value_base64 = "EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA"\n'
    )
    return base


class PackLimitsConstantTests(unittest.TestCase):
    def test_real_constant_values(self) -> None:
        self.assertEqual(pack_limits.MAX_FILES, 2000)
        self.assertEqual(pack_limits.MAX_TOTAL_BYTES, 16 * 1024 * 1024)
        self.assertEqual(pack_limits.MAX_FILE_BYTES, 1024 * 1024)
        self.assertEqual(pack_limits.MAX_DEPTH, 8)
        self.assertEqual(generate.MAX_FILES, 2000)
        self.assertEqual(generate.MAX_TOTAL_BYTES, 16 * 1024 * 1024)
        self.assertEqual(generate.MAX_FILE_BYTES, 1024 * 1024)
        self.assertEqual(generate.MAX_DEPTH, 8)
        self.assertEqual(pack.MAX_FILES, 2000)
        self.assertEqual(pack.MAX_ENTRIES, 2000)
        self.assertEqual(pack.MAX_TOTAL_BYTES, 16 * 1024 * 1024)
        self.assertEqual(pack.MAX_FILE_BYTES, 1024 * 1024)
        self.assertEqual(pack.MAX_DEPTH, 8)


class PackLimitsValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir) / "protocol-28"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_file_size_exact_1_mib_accepted_and_1_mib_plus_one_rejected(self) -> None:
        limit = pack_limits.MAX_FILE_BYTES  # 1,048,576
        ok_file = self.root / "xdr" / "ok.toml"
        ok_file.parent.mkdir(parents=True, exist_ok=True)

        # Pad to exactly 1 MiB
        template = make_valid_fixture("p28-xdr-ok")
        # Ensure exact byte length
        base_len = len(template.encode("utf-8"))
        needed_padding = limit - base_len
        padded_content = make_valid_fixture("p28-xdr-ok", extra_comment_bytes=needed_padding)
        self.assertEqual(len(padded_content.encode("utf-8")), limit)
        ok_file.write_text(padded_content, encoding="utf-8")

        report = validate.validate_directory(self.root)
        self.assertEqual(report.errors, [])

        # 1 byte over limit
        bad_file = self.root / "xdr" / "bad.toml"
        padded_bad = padded_content + " "
        self.assertEqual(len(padded_bad.encode("utf-8")), limit + 1)
        bad_file.write_text(padded_bad, encoding="utf-8")

        # Track bytes read to confirm bounded read (did not read more than limit + 1)
        real_open = open
        bytes_read = []

        def tracked_open(*args, **kwargs):
            handle = real_open(*args, **kwargs)
            orig_read = handle.read

            def wrapped_read(size=-1):
                data = orig_read(size)
                bytes_read.append(len(data))
                return data

            handle.read = wrapped_read
            return handle

        with mock.patch("builtins.open", side_effect=tracked_open):
            report_bad = validate.validate_directory(self.root)

        for read_len in bytes_read:
            self.assertLessEqual(read_len, limit + 1)

        error_messages = [e.message for e in report_bad.error_entries]
        self.assertTrue(
            any("xdr/bad.toml is 1048577 bytes, over the 1048576 byte limit for one pack file" in m for m in error_messages),
            f"Expected size error in {error_messages}",
        )

    def test_depth_8_segments_accepted_and_9_segments_rejected_identically(self) -> None:
        # 8 segments: 7 directories + 1 file
        # root is protocol-28
        segs_8 = ["d1", "d2", "d3", "d4", "d5", "d6", "d7"]
        dir_8 = self.root.joinpath(*segs_8)
        dir_8.mkdir(parents=True, exist_ok=True)
        file_8 = dir_8 / "f.toml"
        file_8.write_text(make_valid_fixture("p28-xdr-depth8"), encoding="utf-8")

        # Path relative to root: d1/d2/d3/d4/d5/d6/d7/f.toml -> 8 segments
        rel_8 = file_8.relative_to(self.root).as_posix()
        self.assertEqual(len(rel_8.split("/")), 8)

        # Validator accepts 8 segments
        report_8 = validate.validate_directory(self.root)
        depth_errors = [e for e in report_8.error_entries if "deeper than" in e.message]
        self.assertEqual(depth_errors, [])

        # Generator accepts 8 segments
        generate.check_pack_path(rel_8)

        # 9 segments: 8 directories + 1 file
        segs_9 = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"]
        dir_9 = self.root.joinpath(*segs_9)
        dir_9.mkdir(parents=True, exist_ok=True)
        file_9 = dir_9 / "deep.toml"
        file_9.write_text(make_valid_fixture("p28-xdr-depth9"), encoding="utf-8")

        rel_9 = file_9.relative_to(self.root).as_posix()
        self.assertEqual(len(rel_9.split("/")), 9)

        # Validator rejects 9 segments
        report_9 = validate.validate_directory(self.root)
        depth_9_errors = [e for e in report_9.error_entries if "deeper than" in e.message]
        self.assertEqual(len(depth_9_errors), 1)
        self.assertIn("is deeper than 8 path segments", depth_9_errors[0].message)

        # Generator rejects 9 segments identically
        with self.assertRaises(generate.PackError) as gen_caught:
            generate.check_pack_path(rel_9)
        self.assertIn("is deeper than 8 path segments", str(gen_caught.exception))

        # Pack check_limits rejects 9 segments identically
        with self.assertRaises(pack.PackError) as pack_caught:
            pack.check_limits({rel_9: b""}, [])
        self.assertIn("is deeper than 8 path segments", str(pack_caught.exception))

    def test_member_count_limit_injected(self) -> None:
        original = pack_limits.MAX_FILES
        try:
            pack_limits.MAX_FILES = 2
            # 2 files accepted
            (self.root / "f1.toml").write_text(make_valid_fixture("p28-xdr-f1"), encoding="utf-8")
            (self.root / "f2.toml").write_text(make_valid_fixture("p28-xdr-f2"), encoding="utf-8")

            report = validate.validate_directory(self.root)
            self.assertEqual(report.errors, [])

            # 3 files rejected (reported once per root)
            (self.root / "f3.toml").write_text(make_valid_fixture("p28-xdr-f3"), encoding="utf-8")
            report_3 = validate.validate_directory(self.root)
            count_errors = [e for e in report_3.error_entries if "file limit" in e.message]
            self.assertEqual(len(count_errors), 1)
            self.assertEqual(count_errors[0].path, self.root)
            self.assertIn("has 3 pack files, over the 2 file limit", count_errors[0].message)
        finally:
            pack_limits.MAX_FILES = original

    def test_total_size_limit_injected(self) -> None:
        original = pack_limits.MAX_TOTAL_BYTES
        try:
            fixture_text = make_valid_fixture("p28-xdr-sz")
            size = len(fixture_text.encode("utf-8"))
            pack_limits.MAX_TOTAL_BYTES = size

            (self.root / "f1.toml").write_text(fixture_text, encoding="utf-8")
            report = validate.validate_directory(self.root)
            self.assertEqual(report.errors, [])

            # 1 byte more
            pack_limits.MAX_TOTAL_BYTES = size - 1
            report_over = validate.validate_directory(self.root)
            size_errors = [e for e in report_over.error_entries if "over the" in e.message and "byte limit for one pack" in e.message]
            self.assertEqual(len(size_errors), 1)
            self.assertEqual(size_errors[0].path, self.root)
            self.assertIn(f"is {size} bytes, over the {size - 1} byte limit for one pack", size_errors[0].message)
        finally:
            pack_limits.MAX_TOTAL_BYTES = original

    def test_non_member_file_larger_than_limit_ignored(self) -> None:
        (self.root / "f1.toml").write_text(make_valid_fixture("p28-xdr-nonmember"), encoding="utf-8")
        # 2 MB README.md outside pack
        readme = self.root / "README.md"
        readme.write_bytes(b"#" * (2 * 1024 * 1024))

        report = validate.validate_directory(self.root)
        self.assertEqual(report.errors, [])

    def test_oversized_file_under_git_ignored(self) -> None:
        (self.root / "f1.toml").write_text(make_valid_fixture("p28-xdr-git"), encoding="utf-8")
        git_dir = self.root / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "big.bin").write_bytes(b"#" * (2 * 1024 * 1024))
        (git_dir / "fake.toml").write_bytes(b"#" * (2 * 1024 * 1024))

        report = validate.validate_directory(self.root)
        self.assertEqual(report.errors, [])

    def test_input_file_one_byte_over_limit_rejected(self) -> None:
        limit = pack_limits.MAX_FILE_BYTES
        payload = self.root / "xdr" / "input.bin"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(b"A" * (limit + 1))

        fixture = (
            'id = "p28-xdr-payload"\n'
            'protocol = 28\n'
            'surface = "xdr"\n'
            'category = "cap-0083"\n'
            'description = "fixture with payload"\n'
            'source_reference = "CAP-0083"\n'
            'type = "StellarValue"\n'
            'kind = "roundtrip"\n'
            'value_base64 = "EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA"\n'
            'input_file = "input.bin"\n'
        )
        (self.root / "xdr" / "fixture.toml").write_text(fixture, encoding="utf-8")

        report = validate.validate_directory(self.root)
        errors = [e.message for e in report.error_entries]
        self.assertTrue(
            any("xdr/input.bin is 1048577 bytes, over the 1048576 byte limit for one pack file" in m for m in errors),
            f"Expected payload size error in {errors}",
        )

    def test_path_8_segments_long_segment_accepted(self) -> None:
        long_seg = "a" * 100
        path_8 = self.root / "d1" / "d2" / "d3" / "d4" / "d5" / "d6" / long_seg / "f.toml"
        path_8.parent.mkdir(parents=True, exist_ok=True)
        path_8.write_text(make_valid_fixture("p28-xdr-longseg"), encoding="utf-8")

        report = validate.validate_directory(self.root)
        depth_errors = [e for e in report.error_entries if "deeper than" in e.message]
        self.assertEqual(depth_errors, [])

    def test_member_grows_between_stat_and_read(self) -> None:
        file_path = self.root / "xdr" / "growing.toml"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(make_valid_fixture("p28-xdr-grow"), encoding="utf-8")

        class FakeStat:
            st_size = 100
            st_mode = 0o100644

        file_path.write_bytes(b"#" * (pack_limits.MAX_FILE_BYTES + 10))

        report = validate.Report()
        with mock.patch.object(Path, "stat", return_value=FakeStat()):
            result = validate.load_fixture(file_path, report, root=self.root)

        self.assertIsNone(result)
        errors = [e.message for e in report.error_entries]
        self.assertTrue(
            any("over the 1048576 byte limit" in m for m in errors),
            f"Expected size error in {errors}",
        )

    def test_json_format_preserves_error_shape(self) -> None:
        bad_file = self.root / "xdr" / "bad.toml"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_bytes(b"#" * (pack_limits.MAX_FILE_BYTES + 1))

        report = validate.validate_directory(self.root)
        json_doc = validate.build_json_report(report, roots=[self.root], total_files=1)

        self.assertFalse(json_doc["valid"])
        self.assertEqual(len(json_doc["errors"]), 1)
        err = json_doc["errors"][0]
        self.assertIn("path", err)
        self.assertIn("id", err)
        self.assertIn("line", err)
        self.assertIn("message", err)
        self.assertIn("1048577 bytes, over the 1048576 byte limit", err["message"])


if __name__ == "__main__":
    unittest.main()
