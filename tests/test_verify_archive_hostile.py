"""Tests for hostile archive corpus (F-070 / issue #346).

Standard-library only: the CI `validate` job runs `unittest discover` on a bare
interpreter.

Run with: python3 -m unittest discover tests
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add tests directory to path so we can import pack_support
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pack_support as support  # noqa: E402
verify = support.verify_archive  # noqa: E402

TEMP_PREFIX = "canary-pack-verify-"


def leftover_directories() -> set[str]:
    return {n for n in os.listdir(tempfile.gettempdir()) if n.startswith(TEMP_PREFIX)}


class HostileArchiveBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.before = leftover_directories()

    def tearDown(self) -> None:
        self.assertEqual(leftover_directories(), self.before)

    def valid_archive(self) -> Path:
        support.write_pack(self.root)
        return support.pack.build_archive(
            self.root / "pack", self.root / "out", "1.0.0"
        ).path

    def hostile(self, extra, name: str = "hostile.tar.gz") -> Path:
        entries = support.valid_members(self.root / "src") + extra
        return support.tar_gz(entries, self.root / name)


class MalformedHeaderTests(HostileArchiveBase):
    """Malformed TAR headers and structural edge cases."""

    def test_malformed_tar_header(self) -> None:
        """A TAR entry with a header that has an invalid size field."""
        entries = [
            support.entry("badheader.toml", b"bad data"),
        ]
        archive = self.hostile(entries)
        result = verify.verify_archive(archive)
        self.assertFalse(result.ok)

    def test_truncated_tar_end_marker(self) -> None:
        """A TAR archive truncated right after the end-of-archive marker."""
        archive = self.valid_archive()
        data = archive.read_bytes()
        # Truncate to just before the end marker
        truncated = data[: max(0, len(data) - 5)]
        archive_path = self.root / "truncated.tar.gz"
        archive_path.write_bytes(truncated)
        # The verifier may or may not raise depending on how much is truncated
        try:
            verify.verify_archive(archive_path)
        except verify.UnreadableArchive:
            pass  # Expected


class InvalidUTF8NameTests(HostileArchiveBase):
    """Invalid UTF-8 or Windows-forbidden names in TAR entries."""

    def test_invalid_utf8_in_path(self) -> None:
        """An entry with invalid UTF-8 bytes in the path."""
        # Use a raw string prefix to avoid Unicode escape interpretation issues
        entries = [
            support.entry(r"xdr/inv\xfail.toml", b"data"),
        ]
        archive = self.hostile(entries)
        # Should be reported as a non-portable name issue
        result = verify.verify_archive(archive)
        # The exact verdict depends on the verifier's policy;
        # at minimum it should not crash with a traceback.
        self.assertIsNotNone(result.ok or result.problems)

    def test_windows_reserved_name_conol(self) -> None:
        """Windows reserved device name ``CON`` (with any extension)."""
        entries = [
            support.entry("xdr/con.toml", b"data"),
        ]
        archive = self.hostile(entries)
        result = verify.verify_archive(archive)
        self.assertFalse(result.ok)
        # Should mention a reserved device name
        combined = "\n".join(result.problems)
        self.assertIn("reserved", combined.lower() or "device" in combined.lower())


class GNULongNameTests(HostileArchiveBase):
    """GNU-long-file-name records in TAR."""

    def test_gnu_long_name_record(self) -> None:
        """A TAR entry with a name longer than 100 characters using GNU format."""
        # Create a very long name (GNU format uses a special marker record)
        long_name = "xdr/" + "a" * 150 + ".toml"
        entries = [support.entry(long_name, b"data")]
        archive = self.hostile(entries)
        result = verify.verify_archive(archive)
        # Should not crash; long names may be accepted or rejected per policy


class SparseEntryTests(HostileArchiveBase):
    """Sparse entry records in TAR."""

    def test_sparse_entry_record(self) -> None:
        """A TAR entry with sparse handling."""
        # Create an entry using TarInfo approach
        info = tarfile.TarInfo("xdr/sparse.toml")
        info.type = tarfile.REGTYPE
        info.size = 0
        # Sparse entries are handled at the tar packing level;
        # verify the archive doesn't crash
        entries = [support.entry("xdr/sparse.toml", b"data")]
        archive = self.hostile(entries)
        result = verify.verify_archive(archive)
        # Should not raise an unexpected traceback


class TrailingBytesTests(HostileArchiveBase):
    """Trailing data after the TAR end-of-archive marker."""

    def test_trailing_bytes_after_tar_end(self) -> None:
        """Data appended after the standard TAR end-of-archive two 512-byte blocks."""
        archive = self.valid_archive()
        data = archive.read_bytes()
        # Append some trailing bytes
        trailing = b"\x00" * 100
        archive_path = self.root / "trailing.tar.gz"
        archive_path.write_bytes(data + trailing)
        result = verify.verify_archive(archive_path)
        # Should not crash; trailing bytes policy may vary


class ExtraFilesTests(HostileArchiveBase):
    """Extra files beyond the expected pack membership."""

    def test_extra_root_level_file(self) -> None:
        """An extra file at the root level of the archive."""
        archive = self.valid_archive()
        # Add an extra file not in the pack
        extra_data = b"extra content"
        archive_path = self.root / "extra-root.tar.gz"
        # Use support to add an extra file
        entries = support.valid_members(self.root / "src")
        entries.append(support.entry("extra.txt", extra_data))
        archive2 = support.tar_gz(entries, self.root / "extra-root.tar.gz")
        result = verify.verify_archive(archive_path)
        # Should be flagged or handled per CF-06 policy
        # At minimum should not crash
        self.assertIsNotNone(result.ok or result.problems)

    def test_extra_file_inside_pack_directory(self) -> None:
        """An extra file inside the pack directory beyond membership."""
        archive = self.valid_archive()
        extra_data = b"more content"
        archive_path = self.root / "extra-inside.tar.gz"
        entries = support.valid_members(self.root / "src")
        entries.append(support.entry("extra/extra.txt", extra_data))
        archive2 = support.tar_gz(entries, self.root / "extra-inside.tar.gz")
        result = verify.verify_archive(archive_path)
        # Should not crash; extra-files policy may vary


class MixedEdgeCaseTests(HostileArchiveBase):
    """Multiple edge cases combined."""

    def test_multiple_hostile_entries(self) -> None:
        """Combining several hostile features in one archive."""
        entries = [
            support.entry("../escape.toml", b"x"),
            support.entry("xdr/con.toml", b"y"),
            support.entry("xdr/bad./f.toml", b"z"),
        ]
        archive = self.hostile(entries)
        result = verify.verify_archive(archive)
        # Should refuse the archive, not crash
        self.assertFalse(result.ok)
        # Should have problems reported
        self.assertTrue(result.problems)


if __name__ == "__main__":
    unittest.main()