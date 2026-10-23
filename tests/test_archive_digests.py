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
    pack_dir = root / "pack"
    if not pack_dir.exists():
        pack_dir = write_pack(root)
    members, _, _ = pack_tool.collect_members(pack_dir)
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


class CommandLineTests(unittest.TestCase):
    """The two commands the workflow runs."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.pack_dir = write_pack(self.root)

    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        """Run the command line, with its output captured."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = digests.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_build_writes_the_result_document_and_the_stream(self) -> None:
        output = self.root / "out" / "digests.json"
        code, out, _ = self.run_main(
            [
                "build",
                "--pack",
                str(self.pack_dir),
                "--version",
                "0.0.0",
                "--output",
                str(output),
                "--cell",
                "ubuntu-latest-py3.11",
            ]
        )
        self.assertEqual(code, 0)
        document = json.loads(out)
        self.assertEqual(document["cell"], "ubuntu-latest-py3.11")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), document)
        stream = output.parent / digests.STREAM_NAME
        self.assertTrue(stream.is_file(), "the tar stream must be written next to the result")

    def test_build_writes_the_stream_where_it_is_asked(self) -> None:
        stream = self.root / "elsewhere" / "stream.tar"
        code, _, _ = self.run_main(
            [
                "build",
                "--pack",
                str(self.pack_dir),
                "--stream",
                str(stream),
            ]
        )
        self.assertEqual(code, 0)
        self.assertTrue(stream.is_file())

    def test_build_of_an_invalid_pack_fails(self) -> None:
        code, _, err = self.run_main(
            ["build", "--pack", str(self.pack_dir), "--version", "not-a-version"]
        )
        self.assertEqual(code, 1)
        self.assertIn("FAILED", err)

    def test_compare_reports_the_cells(self) -> None:
        results = self.root / "artifacts"
        stream = build_tar_stream(self.root)
        write_result(results / "cell-a", "ubuntu-latest-py3.11", stream, "a" * 64)
        code, out, _ = self.run_main(
            [
                "compare",
                "--results",
                str(results),
                "--expected-matrix",
                '{"os": ["ubuntu-latest"], "python": ["3.11"]}',
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("ubuntu-latest-py3.11", out)

    def test_compare_of_an_invalid_matrix_is_a_usage_error(self) -> None:
        results = self.root / "artifacts"
        results.mkdir()
        code, _, err = self.run_main(
            ["compare", "--results", str(results), "--expected-matrix", "not json"]
        )
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)

    def test_compare_with_a_matrix_that_is_not_an_object_is_a_usage_error(self) -> None:
        results = self.root / "artifacts"
        results.mkdir()
        code, _, err = self.run_main(
            ["compare", "--results", str(results), "--expected-matrix", "[1, 2]"]
        )
        self.assertEqual(code, 2)
        self.assertIn("must be a JSON object", err)

    def test_compare_of_a_broken_result_document_fails(self) -> None:
        results = self.root / "artifacts"
        (results / "cell-a").mkdir(parents=True)
        (results / "cell-a" / "digests.json").write_text("{", encoding="utf-8")
        code, _, err = self.run_main(["compare", "--results", str(results)])
        self.assertEqual(code, 1)
        self.assertIn("could not be compared", err)


class EdgeCaseTests(unittest.TestCase):
    """The corners of the measurement."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_missing_archive_is_reported(self) -> None:
        with self.assertRaises(digests.DigestError):
            digests.digests_of(self.root / "missing.tar.gz")
        with self.assertRaises(digests.DigestError):
            digests.uncompressed_stream(self.root / "missing.tar.gz")

    def test_an_invalid_pack_is_reported(self) -> None:
        empty = self.root / "empty-pack"
        empty.mkdir()
        with self.assertRaises(digests.DigestError):
            digests.build_result(empty, "0.0.0", output_dir=self.root / "out")

    def test_an_archive_that_cannot_be_written_is_reported(self) -> None:
        blocked = self.root / "not-a-directory"
        blocked.write_text("", encoding="utf-8")
        with self.assertRaises(digests.DigestError):
            digests.build_result(
                write_pack(self.root), "0.0.0", output_dir=blocked
            )

    def test_a_directory_in_the_results_is_skipped(self) -> None:
        results = self.root / "artifacts"
        (results / "not-a-document.json").mkdir(parents=True)
        stream = build_tar_stream(self.root)
        write_result(results / "cell-a", "ubuntu-latest-py3.11", stream, "a" * 64)
        code = digests.run_compare(results, ["ubuntu-latest-py3.11"])
        self.assertEqual(code, 0)

    def test_three_cells_with_two_digests_are_all_compared(self) -> None:
        results = self.root / "artifacts"
        stream = build_tar_stream(self.root)
        changed = bytearray(stream)
        changed[600] ^= 0xFF
        write_result(results / "cell-a", "ubuntu-latest-py3.11", stream, "a" * 64)
        write_result(results / "cell-b", "macos-latest-py3.12", stream, "a" * 64)
        write_result(results / "cell-c", "windows-latest-py3.13", bytes(changed), "a" * 64)
        code = digests.run_compare(
            results, ["ubuntu-latest-py3.11", "macos-latest-py3.12", "windows-latest-py3.13"]
        )
        self.assertEqual(code, 1)

    def test_the_header_of_a_member_is_named(self) -> None:
        stream = build_tar_stream(self.root)
        description = digests.member_at_offset(stream, 10)
        self.assertIn("header at byte 0", description)

    def test_the_padding_of_a_member_is_named(self) -> None:
        stream = build_tar_stream(self.root)
        name, start, size = digests.tar_members(stream)[0]
        description = digests.member_at_offset(stream, start + size)
        self.assertIn("padding", description)
        self.assertIn(name, description)

    def test_an_offset_outside_every_member_is_said_so(self) -> None:
        stream = build_tar_stream(self.root)
        self.assertIn(
            "outside every tar member",
            digests.member_at_offset(stream, len(stream) + 10),
        )

    def test_streams_of_different_length_report_the_length(self) -> None:
        stream = build_tar_stream(self.root)
        description = digests.compare_streams(stream, stream + b"tail")
        self.assertIn("lengths differ", description)

    def test_a_stream_that_is_not_a_tar_has_no_members(self) -> None:
        self.assertEqual(digests.tar_members(b"\0" * 1024), [])

    def test_a_difference_without_a_stream_is_reported_by_digest(self) -> None:
        results = self.root / "artifacts"
        write_result(results / "cell-a", "ubuntu-latest-py3.11", b"one", "a" * 64)
        write_result(results / "cell-b", "macos-latest-py3.13", b"two", "a" * 64)
        # The stream files are not written, so only the digests can be compared.
        for cell in ("cell-a", "cell-b"):
            (results / cell / digests.STREAM_NAME).unlink()
        code = digests.run_compare(results, ["ubuntu-latest-py3.11", "macos-latest-py3.13"])
        self.assertEqual(code, 1)

    def test_more_cells_than_the_matrix_declares_is_an_inconsistency(self) -> None:
        results = self.root / "artifacts"
        stream = build_tar_stream(self.root)
        write_result(results / "cell-a", "ubuntu-latest-py3.11", stream, "a" * 64)
        write_result(results / "cell-b", "macos-latest-py3.13", stream, "a" * 64)
        code = digests.run_compare(results, ["ubuntu-latest-py3.11"])
        self.assertEqual(code, 1, "a run with more cells than the matrix declares must fail")

    def test_a_run_without_any_cell_is_reported(self) -> None:
        results = self.root / "artifacts"
        results.mkdir()
        code = digests.run_compare(results, ["ubuntu-latest-py3.11"])
        self.assertEqual(code, 1)

    def test_a_header_without_a_size_field_is_read_as_empty(self) -> None:
        header = bytearray(512)
        header[0:5] = b"name\x00"
        header[124:136] = b"not-octal\x00  "
        members = digests.tar_members(bytes(header))
        self.assertEqual(members, [("name", 512, 0)])

    def test_the_gzip_header_carries_no_operating_system_name(self) -> None:
        """The gzip header names no file and no operating system."""
        archive = self.root / "archive.tar.gz"
        archive.write_bytes(build_archive_bytes(self.root))
        measured = digests.digests_of(archive)
        self.assertEqual(
            measured["gzipOsByte"],
            255,
            "the gzip header must say 'unknown', so the compressed bytes do not "
            "depend on the operating system",
        )


if __name__ == "__main__":
    unittest.main()
