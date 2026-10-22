"""Tests for tools/pack/archive_digests.py (issue #365, F-092).

The helper measures two digests of one archive: the compressed one, which
depends on the zlib build, and the uncompressed tar-stream one, which is
produced by this repository's own code. Only the second is enforced across
cells, so these tests pin what each digest is computed from and how a
difference is reported.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.pack import archive_digests as digests
from tools.pack import pack as pack_tool

sys.path.insert(0, str(REPO_ROOT / "tests"))
from pack_support import write_pack  # noqa: E402


def build_archive_bytes(root: Path) -> bytes:
    """The compressed archive bytes of the golden pack."""
    members, _, _ = pack_tool.collect_members(write_pack(root))
    return pack_tool.render_archive(members)


def build_tar_stream(root: Path) -> bytes:
    """The uncompressed tar stream inside the golden pack's archive."""
    return gzip.decompress(build_archive_bytes(root))


class DigestMeasurementTests(unittest.TestCase):
    """What each digest is computed from."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.archive = self.root / "protocolcanary-fixtures-0.0.0.tar.gz"
        self.archive.write_bytes(build_archive_bytes(self.root))

    def test_uncompressed_digest_is_deterministic(self) -> None:
        """The same pack bytes give the same uncompressed digest, every time."""
        first = digests.digests_of(self.archive)
        second = digests.digests_of(self.archive)
        self.assertEqual(
            first["uncompressedSha256"],
            second["uncompressedSha256"],
            "the uncompressed tar-stream digest is not deterministic",
        )
        self.assertEqual(
            first["uncompressedSha256"],
            hashlib.sha256(gzip.decompress(self.archive.read_bytes())).hexdigest(),
        )

    def test_compressed_and_uncompressed_digests_differ(self) -> None:
        """The two digests are of different bytes, so they are never equal."""
        measured = digests.digests_of(self.archive)
        self.assertNotEqual(
            measured["compressedSha256"],
            measured["uncompressedSha256"],
        )
        self.assertEqual(
            measured["compressedSha256"],
            hashlib.sha256(self.archive.read_bytes()).hexdigest(),
        )

    def test_helper_reads_only_the_archive_passed_to_it(self) -> None:
        """The digest describes the file it was given, not the pack."""
        other = self.root / "other.tar.gz"
        other.write_bytes(gzip.compress(b"a different archive"))
        before = digests.digests_of(self.archive)
        digests.digests_of(other)
        after = digests.digests_of(self.archive)
        self.assertEqual(before, after, "the measurement changed when another archive was read")

        # A pack that changed after the archive was built does not change the
        # digest of the archive: the helper never reads the pack.
        (self.root / "pack" / "xdr" / "a.toml").write_bytes(b"id = \"changed\"\n")
        self.assertEqual(before, digests.digests_of(self.archive))

    def test_a_file_that_is_not_a_gzip_stream_is_refused(self) -> None:
        broken = self.root / "broken.tar.gz"
        broken.write_bytes(b"not a gzip stream")
        with self.assertRaises(digests.DigestError):
            digests.digests_of(broken)


class BuildResultTests(unittest.TestCase):
    """The result document one cell produces."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_result_reports_both_digests_and_the_environment(self) -> None:
        pack_dir = write_pack(self.root)
        result, stream = digests.build_result(pack_dir, "0.0.0", output_dir=self.root / "out")
        self.assertEqual(len(result["compressedSha256"]), 64)
        self.assertEqual(len(result["uncompressedSha256"]), 64)
        self.assertEqual(
            result["uncompressedSha256"], hashlib.sha256(stream).hexdigest()
        )
        self.assertTrue(result["pythonVersion"])
        self.assertTrue(result["zlibVersion"])
        self.assertTrue(result["zlibRuntimeVersion"])
        self.assertEqual(result["cell"], digests.cell_name(result))

    def test_the_cell_name_can_be_given(self) -> None:
        pack_dir = write_pack(self.root)
        result, _ = digests.build_result(
            pack_dir, "0.0.0", output_dir=self.root / "out", cell="ubuntu-latest-py3.11"
        )
        self.assertEqual(result["cell"], "ubuntu-latest-py3.11")

    def test_matrix_names_match_the_cells_the_workflow_builds(self) -> None:
        matrix = {"os": ["ubuntu-latest", "macos-latest"], "python": ["3.11", "3.12"]}
        self.assertEqual(
            digests.matrix_cell_names(matrix),
            [
                "ubuntu-latest-py3.11",
                "ubuntu-latest-py3.12",
                "macos-latest-py3.11",
                "macos-latest-py3.12",
            ],
        )


def write_result(directory: Path, cell: str, stream: bytes, compressed: str) -> None:
    """Write one cell's result document and tar stream."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "digests.json").write_text(
        json.dumps(
            {
                "cell": cell,
                "platform": cell.split("-py")[0],
                "pythonVersion": "3.11.9",
                "zlibVersion": "1.3",
                "zlibRuntimeVersion": "1.3",
                "compressedSha256": compressed,
                "uncompressedSha256": hashlib.sha256(stream).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / digests.STREAM_NAME).write_bytes(stream)


class CompareTests(unittest.TestCase):
    """The comparison across cells."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.results = self.root / "artifacts"
        self.stream = build_tar_stream(self.root)

    def compare(self, expected: list[str], summary: Path | None = None) -> int:
        """Run the comparison with its report captured, not printed."""
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return digests.run_compare(self.results, expected, summary)

    def test_equal_uncompressed_digests_pass(self) -> None:
        write_result(self.results / "cell-a", "ubuntu-latest-py3.11", self.stream, "a" * 64)
        write_result(self.results / "cell-b", "macos-latest-py3.13", self.stream, "b" * 64)
        code = self.compare(
            ["ubuntu-latest-py3.11", "macos-latest-py3.13"],
            self.root / "summary.md",
        )
        self.assertEqual(code, 0, "equal uncompressed digests must not fail the comparison")
        summary = (self.root / "summary.md").read_text(encoding="utf-8")
        self.assertIn("ubuntu-latest-py3.11", summary)
        self.assertIn("macos-latest-py3.13", summary)
        self.assertIn("Observation", summary)

    def test_a_different_compressed_digest_is_only_an_observation(self) -> None:
        write_result(self.results / "cell-a", "ubuntu-latest-py3.11", self.stream, "a" * 64)
        write_result(self.results / "cell-b", "macos-latest-py3.13", self.stream, "b" * 64)
        code = self.compare(["ubuntu-latest-py3.11", "macos-latest-py3.13"])
        self.assertEqual(code, 0, "a compressed difference must never fail the comparison")

    def test_a_different_uncompressed_digest_fails_and_names_the_byte(self) -> None:
        changed = bytearray(self.stream)
        changed[600] ^= 0xFF
        write_result(self.results / "cell-a", "ubuntu-latest-py3.11", self.stream, "a" * 64)
        write_result(self.results / "cell-b", "macos-latest-py3.13", bytes(changed), "a" * 64)
        code = self.compare(
            ["ubuntu-latest-py3.11", "macos-latest-py3.13"],
            self.root / "summary.md",
        )
        self.assertEqual(code, 1, "a different uncompressed digest must fail the comparison")
        summary = (self.root / "summary.md").read_text(encoding="utf-8")
        self.assertIn("first difference at byte 600", summary)
        self.assertIn("registry.json", summary)
        self.assertIn("data at byte 600", summary)

    def test_a_missing_cell_is_reported_as_a_cell_failure(self) -> None:
        write_result(self.results / "cell-a", "ubuntu-latest-py3.11", self.stream, "a" * 64)
        code = self.compare(["ubuntu-latest-py3.11", "macos-latest-py3.13"])
        self.assertEqual(code, 1, "a cell that produced no digest must fail the comparison")

    def test_the_first_difference_names_the_tar_member(self) -> None:
        changed = bytearray(self.stream)
        changed[600] ^= 0xFF
        description = digests.compare_streams(self.stream, bytes(changed))
        self.assertIn("first difference at byte 600", description)
        self.assertIn(")", description)
        member = digests.member_at_offset(self.stream, 600)
        self.assertTrue(member)
        self.assertNotIn("outside every tar member", member)

    def test_identical_streams_have_no_first_difference(self) -> None:
        self.assertIsNone(digests.first_difference(self.stream, self.stream))
        self.assertIn("identical", digests.compare_streams(self.stream, self.stream))

    def test_a_result_document_that_is_not_one_is_refused(self) -> None:
        (self.results / "bad").mkdir(parents=True)
        (self.results / "bad" / "digests.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(digests.DigestError):
            digests.run_compare(self.results, [])


if __name__ == "__main__":
    unittest.main()
