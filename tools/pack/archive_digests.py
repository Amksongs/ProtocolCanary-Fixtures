#!/usr/bin/env python3
r"""Measure the pack archive's digests, and compare them across cells (#365).

The release archive is a gzip stream, so it has two digests, and they answer
different questions:

* the **compressed** digest (SHA-256 of the ``.tar.gz``) is what a consumer
  pins, but the compressed bytes depend on the zlib implementation in the
  Python build that produced them, so it is not guaranteed to be the same on
  every operating system or Python version;
* the **uncompressed** digest (SHA-256 of the tar stream inside the gzip
  wrapper) is produced entirely by this repository's own code -- fixed
  metadata, sorted entries, ``mtime`` 0 -- and does not depend on the
  compression library.

The first digest is informational. The second one is the invariant this
repository can justify: a difference there is a defect in the repository's own
determinism, or a platform-dependent path in its code, and it is reported
rather than explained away. See ``docs/archive-reproducibility.md``.

This module never changes the archive: it builds one with
``tools/pack/pack.py`` and only reads the bytes back.

Usage:
    python3 tools/pack/archive_digests.py build --pack protocol-28 --version 0.0.0
        [--output digests.json] [--stream stream.tar]
    python3 tools/pack/archive_digests.py compare --results DIR
        [--expected-cell CELL]... [--summary-file PATH]

``build`` prints one JSON document with both digests and the environment they
were produced in (``sys.version``, ``zlib.ZLIB_VERSION``,
``zlib.ZLIB_RUNTIME_VERSION``). ``compare`` reads the JSON documents of several
cells, prints a table, and fails when the *uncompressed* digests differ; a
difference in the compressed digests is reported as an observation and never
fails the run.

Requires Python 3.11+ and nothing outside the standard library.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.pack import pack as pack_tool

# The name of the uncompressed tar stream written next to a result document,
# so the comparison job can point at the exact byte that differs.
STREAM_NAME = "stream.tar"


class DigestError(Exception):
    """The digests cannot be measured. The message says why."""


def uncompressed_stream(archive: Path) -> bytes:
    """The tar stream inside ``archive``.

    Only the file passed in is read; nothing else in the repository is
    consulted, so the digest describes exactly the bytes of that archive.
    """
    try:
        compressed = archive.read_bytes()
    except OSError as error:
        raise DigestError(f"could not read {archive}: {error}") from None
    try:
        return gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as error:
        raise DigestError(f"{archive} is not a readable gzip stream: {error}") from None


def digests_of(archive: Path) -> dict:
    """Both digests of one archive, read only from that file."""
    compressed = archive.read_bytes()
    stream = uncompressed_stream(archive)
    return {
        "compressedSha256": hashlib.sha256(compressed).hexdigest(),
        "uncompressedSha256": hashlib.sha256(stream).hexdigest(),
        "compressedBytes": len(compressed),
        "uncompressedBytes": len(stream),
        "gzipOsByte": compressed[9] if len(compressed) > 9 else None,
    }


def environment() -> dict:
    """The interpreter and compression library the measurement was made with."""
    return {
        "pythonVersion": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
        "pythonFullVersion": sys.version.replace("\n", " "),
        "zlibVersion": zlib.ZLIB_VERSION,
        "zlibRuntimeVersion": zlib.ZLIB_RUNTIME_VERSION,
        "platform": platform.system(),
        "machine": platform.machine(),
        "runnerOs": os.environ.get("RUNNER_OS", ""),
        "runnerArch": os.environ.get("RUNNER_ARCH", ""),
    }


def cell_name(environment_: dict) -> str:
    """A stable name for the cell a measurement was made in."""
    os_name = environment_["runnerOs"] or environment_["platform"]
    return f"{os_name}-python{environment_['pythonVersion']}"


def matrix_cell_names(matrix: dict) -> list[str]:
    """The cell names a matrix declares, in the order the matrix lists them.

    The name is ``<runner os>-py<python version>``, the same name the build
    step passes with ``--cell``, so the comparison job can tell a cell that
    never ran from a cell whose digest differs.
    """
    names: list[str] = []
    for os_name in matrix.get("os", []):
        for python_version in matrix.get("python", []):
            names.append(f"{os_name}-py{python_version}")
    return names


def build_result(
    pack_dir: Path,
    version: str,
    output_dir: Path | None = None,
    cell: str | None = None,
) -> tuple[dict, bytes]:
    """Build the archive and return its result document and tar stream."""
    with tempfile.TemporaryDirectory(prefix="archive-digests-") as scratch:
        target = Path(output_dir) if output_dir is not None else Path(scratch)
        try:
            info = pack_tool.build_archive(pack_dir, target, version)
        except pack_tool.PackError as error:
            raise DigestError(str(error)) from None
        except OSError as error:
            raise DigestError(f"could not write the archive: {error}") from None
        measured = digests_of(info.path)
        stream = uncompressed_stream(info.path)
    result = {
        "archive": info.path.name,
        "packDigest": info.pack_digest,
        "protocol": info.protocol,
        "entries": info.entries,
    }
    result.update(measured)
    result.update(environment())
    result["cell"] = cell if cell else cell_name(result)
    return result, stream


def tar_members(stream: bytes) -> list[tuple[str, int, int]]:
    """``(name, data offset, size)`` for every member of a tar stream."""
    members: list[tuple[str, int, int]] = []
    offset = 0
    while offset + 512 <= len(stream):
        header = stream[offset : offset + 512]
        if header == b"\0" * 512:
            break
        name = header[0:100].split(b"\0", 1)[0].decode("utf-8", "replace")
        size_field = header[124:136].split(b"\0", 1)[0].strip()
        try:
            size = int(size_field or b"0", 8)
        except ValueError:
            size = 0
        members.append((name, offset + 512, size))
        offset += 512 + ((size + 511) // 512) * 512
    return members


def member_at_offset(stream: bytes, offset: int) -> str:
    """The tar member that contains ``offset``, described for a report."""
    for name, start, size in tar_members(stream):
        padded = ((size + 511) // 512) * 512
        entry_start = start - 512
        entry_end = start + padded
        if not entry_start <= offset < entry_end:
            continue
        if start <= offset < start + size:
            return f"{name} (data at byte {offset}, {size} byte(s) of data)"
        if offset < start:
            return f"{name} (header at byte {entry_start})"
        return f"{name} (padding after {size} byte(s) of data, at byte {offset})"
    return f"byte {offset} (outside every tar member)"


def first_difference(left: bytes, right: bytes) -> int | None:
    """The offset of the first byte where two streams differ."""
    limit = min(len(left), len(right))
    for offset in range(limit):
        if left[offset] != right[offset]:
            return offset
    if len(left) != len(right):
        return limit
    return None


def compare_streams(reference: bytes, other: bytes) -> str:
    """A one-line description of the first difference between two streams."""
    offset = first_difference(reference, other)
    if offset is None:
        return "the tar streams are identical"
    detail = f"first difference at byte {offset}: {member_at_offset(reference, offset)}"
    if len(reference) != len(other):
        detail += (
            f"; lengths differ ({len(reference)} vs {len(other)} bytes)"
        )
    return detail


def load_results(results_dir: Path) -> list[dict]:
    """Every result document under ``results_dir``, sorted by cell name."""
    results: list[dict] = []
    for path in sorted(results_dir.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DigestError(f"{path} is not a readable result document: {error}") from None
        if not isinstance(document, dict) or "uncompressedSha256" not in document:
            raise DigestError(f"{path} is not an archive-digest result document")
        document["_path"] = str(path)
        results.append(document)
    return sorted(results, key=lambda d: (d.get("cell", ""), d["_path"]))


def render_table(results: list[dict]) -> str:
    """The markdown table of cells and digests."""
    lines = [
        "| cell | platform | python | zlib | compressed sha256 (informational) | uncompressed sha256 (enforced) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| {cell} | {platform} | {python} | {zlib} | {compressed} | {uncompressed} |".format(
                cell=result.get("cell", "?"),
                platform=result.get("platform", "?"),
                python=result.get("pythonVersion", "?"),
                zlib=result.get("zlibRuntimeVersion", "?"),
                compressed=result.get("compressedSha256", "?"),
                uncompressed=result.get("uncompressedSha256", "?"),
            )
        )
    return "\n".join(lines)


def run_compare(
    results_dir: Path,
    expected_cells: list[str],
    summary_file: Path | None = None,
) -> int:
    """Compare the cells. Returns the process exit code."""
    results = load_results(results_dir)
    present = {result.get("cell", "") for result in results}
    missing = [cell for cell in expected_cells if cell not in present]

    report: list[str] = ["## Cross-platform archive digests", ""]
    report.append(render_table(results) if results else "_no cell produced a digest_")
    report.append("")

    failures: list[str] = []

    if missing:
        failures.append(
            "cell failure, not a digest difference: "
            + ", ".join(missing)
            + " produced no digest document (the build or the artifact upload failed)"
        )
    if expected_cells and len(results) > len(expected_cells):
        failures.append(
            f"inconsistency: the run produced {len(results)} cells but the matrix declares "
            f"{len(expected_cells)}; the matrix and the cell list do not agree"
        )

    uncompressed = {result.get("uncompressedSha256") for result in results}
    if len(uncompressed) > 1:
        reference = results[0]
        details: list[str] = []
        for result in results[1:]:
            if result["uncompressedSha256"] == reference["uncompressedSha256"]:
                continue
            reference_stream = _stream_of(results_dir, reference)
            other_stream = _stream_of(results_dir, result)
            if reference_stream is not None and other_stream is not None:
                details.append(
                    f"{result.get('cell', '?')} vs {reference.get('cell', '?')}: "
                    + compare_streams(reference_stream, other_stream)
                )
            else:
                details.append(
                    f"{result.get('cell', '?')} vs {reference.get('cell', '?')}: "
                    f"{result['uncompressedSha256']} != {reference['uncompressedSha256']}"
                )
        failures.append(
            "the uncompressed tar-stream digest differs between cells: "
            + "; ".join(details)
        )
    elif results:
        report.append(
            f"The uncompressed tar-stream digest is identical in all {len(results)} cell(s). "
            "That is the invariant this repository enforces."
        )
        report.append("")

    compressed = {result.get("compressedSha256") for result in results}
    if len(compressed) > 1:
        report.append(
            "Observation (not a failure): the compressed archive digest differs between "
            f"{len(compressed)} of {len(results)} cell(s). The compressed bytes depend on the "
            "zlib implementation in each Python build, so this is reported and never enforced."
        )
    elif results:
        report.append(
            "Observation: the compressed archive digest is identical in every cell of this run."
        )
    report.append("")

    for failure in failures:
        report.append(f"**{failure}**")
        report.append("")

    text = "\n".join(report)
    print(text)
    if summary_file is not None:
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(text + "\n", encoding="utf-8")

    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    return 0


def _stream_of(results_dir: Path, result: dict) -> bytes | None:
    """The uncompressed tar stream of one cell, when it was uploaded."""
    path = Path(result["_path"])
    candidate = path.parent / STREAM_NAME
    if not candidate.is_file():
        return None
    try:
        return candidate.read_bytes()
    except OSError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archive_digests.py",
        description=(
            "Measure the pack archive's compressed and uncompressed digests, and "
            "compare the digests of several cells (issue #365)."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser("build", help="build the archive and print both digests")
    build.add_argument("--pack", type=Path, default=Path("protocol-28"), help="pack directory")
    build.add_argument("--version", default="0.0.0", help="release version used to name the archive")
    build.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="also write the result document here (default: stdout only)",
    )
    build.add_argument(
        "--stream",
        type=Path,
        metavar="PATH",
        help=f"also write the uncompressed tar stream here (default: {STREAM_NAME} next to --output)",
    )
    build.add_argument(
        "--cell",
        metavar="NAME",
        help="the name of the cell this measurement was made in (default: the platform and Python version)",
    )

    compare = subcommands.add_parser("compare", help="compare the digests of several cells")
    compare.add_argument(
        "--results",
        type=Path,
        required=True,
        metavar="DIR",
        help="directory holding the result documents of the cells",
    )
    compare.add_argument(
        "--expected-cell",
        action="append",
        default=[],
        metavar="CELL",
        help="a cell that must be present; may be given more than once",
    )
    compare.add_argument(
        "--expected-matrix",
        metavar="JSON",
        help=(
            "the matrix the cells come from, as JSON: "
            '{"os": [...], "python": [...]}; every cell it names must be present'
        ),
    )
    compare.add_argument(
        "--summary-file",
        type=Path,
        metavar="PATH",
        help="also write the report here (for example $GITHUB_STEP_SUMMARY)",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        try:
            result, stream = build_result(args.pack, args.version, cell=args.cell)
        except DigestError as error:
            print(f"error: {error}", file=sys.stderr)
            print("FAILED: no digests computed", file=sys.stderr)
            return 1
        document = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        sys.stdout.write(document)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(document, encoding="utf-8")
        stream_path = args.stream
        if stream_path is None and args.output is not None:
            stream_path = args.output.parent / STREAM_NAME
        if stream_path is not None:
            stream_path.parent.mkdir(parents=True, exist_ok=True)
            stream_path.write_bytes(stream)
        return 0

    expected = list(args.expected_cell)
    if args.expected_matrix:
        try:
            matrix = json.loads(args.expected_matrix)
        except json.JSONDecodeError as error:
            print(f"error: --expected-matrix is not valid JSON: {error}", file=sys.stderr)
            return 2
        if not isinstance(matrix, dict):
            print("error: --expected-matrix must be a JSON object", file=sys.stderr)
            return 2
        expected.extend(matrix_cell_names(matrix))
    try:
        return run_compare(args.results, expected, args.summary_file)
    except DigestError as error:
        print(f"error: {error}", file=sys.stderr)
        print("FAILED: the cells could not be compared", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
