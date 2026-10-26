"""Builders for the hostile-archive corpus (F-070 / issue #346).

Standard library only, so the `validate` job in CI can build every input
locally; nothing is downloaded. The corpus starts from the real
``protocol-28`` pack: the members are the ones ``tools/pack/pack.py`` would
archive, and each hostile case damages exactly one thing about them.

Every builder is deterministic: the same input gives the same bytes on every
run, so the corpus can be regenerated and compared.

This module is not a test module: `unittest discover` ignores it because its
name does not start with `test`.
"""
from __future__ import annotations

import gzip
import io
import sys
import tarfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pack_support as support  # noqa: E402

pack = support.pack

# The pack the corpus is built from. The archive content of every case is the
# membership of this pack, so a case isolates one attack from the others.
PACK = REPO_ROOT / "protocol-28"

# The three exit codes of tools/pack/verify_archive.py.
EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2

# How a case is classified once its behaviour is known.
REJECTED = "rejected"
ACCEPTED = "accepted"
POLICY_DECISION = "policy-decision"

CLASSIFICATIONS = (REJECTED, ACCEPTED, POLICY_DECISION)


@dataclass(frozen=True)
class HostileCase:
    """One hostile archive, and what the contract says about it."""

    name: str
    description: str
    clauses: tuple[str, ...]
    classification: str
    exit_code: int
    build: Callable[[Path], Path]
    note: str = ""
    required_follow_up: str = ""


# ---------------------------------------------------------------- members


_MEMBERS: dict[str, bytes] | None = None


def protocol28_members() -> dict[str, bytes]:
    """The archive members of the real protocol-28 pack, including registry.json."""
    global _MEMBERS
    if _MEMBERS is None:
        members, _, _ = pack.collect_members(PACK)
        _MEMBERS = members
    return _MEMBERS


def tar_info(
    name: str,
    size: int = 0,
    *,
    mode: int = 0o644,
    typeflag: bytes = tarfile.REGTYPE,
    linkname: str = "",
    pax_headers: dict[str, str] | None = None,
) -> tarfile.TarInfo:
    """A deterministic member header: mtime 0, no owner names."""
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.mtime = 0
    info.type = typeflag
    info.linkname = linkname
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    if pax_headers:
        info.pax_headers = pax_headers
    return info


def base_entries() -> list[tuple[tarfile.TarInfo, bytes | None]]:
    """The real pack as archive entries, in sorted path order."""
    members = protocol28_members()
    return [
        (tar_info(name, len(data)), data)
        for name, data in sorted(members.items())
    ]


def tar_bytes(entries, *, fmt: int = tarfile.PAX_FORMAT) -> bytes:
    """The uncompressed tar stream for ``entries``."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=fmt, encoding="utf-8") as archive:
        for info, data in entries:
            archive.addfile(info, io.BytesIO(data) if data is not None else None)
    return raw.getvalue()


def gzip_bytes(data: bytes) -> bytes:
    """A gzip stream with no name and no timestamp, so it is reproducible."""
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as stream:
        stream.write(data)
    return raw.getvalue()


def fix_checksum(raw: bytearray, offset: int = 0) -> None:
    """Recompute the tar header checksum at ``offset``, in place.

    A header whose checksum does not match is rejected before anything else
    is looked at, so a case that wants to exercise a different header field
    has to repair the checksum first.
    """
    block = bytearray(raw[offset : offset + 512])
    block[148:156] = b"        "
    raw[offset + 148 : offset + 156] = (f"{sum(block):06o}\x00 ").encode("ascii")


# ---------------------------------------------------------------- builders


def _plain(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(gzip_bytes(tar_bytes(base_entries())))
    return path


def _with_entries(
    directory: Path,
    name: str,
    entries,
    *,
    fmt: int = tarfile.PAX_FORMAT,
) -> Path:
    path = directory / name
    path.write_bytes(gzip_bytes(tar_bytes(entries, fmt=fmt)))
    return path


def _patched_header(
    directory: Path,
    name: str,
    patch: Callable[[bytearray], None],
) -> Path:
    """The pack archive with the first header block changed by ``patch``."""
    raw = bytearray(tar_bytes(base_entries()))
    patch(raw)
    path = directory / name
    path.write_bytes(gzip_bytes(bytes(raw)))
    return path


# ---------------------------------------------------------------- the corpus


def _case_valid(directory: Path) -> Path:
    return _plain(directory, "valid.tar.gz")


def _case_bad_checksum(directory: Path) -> Path:
    raw = bytearray(tar_bytes(base_entries()))
    raw[148:156] = b"0000000\x00"
    path = directory / "bad-checksum.tar.gz"
    path.write_bytes(gzip_bytes(bytes(raw)))
    return path


def _case_bad_magic(directory: Path) -> Path:
    def patch(raw: bytearray) -> None:
        raw[257:263] = b"XXXXX\x00"
        fix_checksum(raw)

    return _patched_header(directory, "bad-magic.tar.gz", patch)


def _case_unknown_type_flag(directory: Path) -> Path:
    def patch(raw: bytearray) -> None:
        raw[156:157] = b"Z"
        fix_checksum(raw)

    return _patched_header(directory, "unknown-type-flag.tar.gz", patch)


def _case_oversized_size_field(directory: Path) -> Path:
    def patch(raw: bytearray) -> None:
        raw[124:136] = b"77777777777\x00"
        fix_checksum(raw)

    return _patched_header(directory, "oversized-size-field.tar.gz", patch)


def _case_invalid_utf8_name(directory: Path) -> Path:
    def patch(raw: bytearray) -> None:
        raw[0:100] = b"xdr/\xff\xfe-invalid.toml" + b"\x00" * 84
        fix_checksum(raw)

    return _patched_header(directory, "invalid-utf8-name.tar.gz", patch)


def _case_nul_in_ustar_name(directory: Path) -> Path:
    def patch(raw: bytearray) -> None:
        raw[0:100] = b"xdr/a\x00b.toml" + b"\x00" * 89
        fix_checksum(raw)

    return _patched_header(directory, "nul-in-name-field.tar.gz", patch)


def _case_pax_absolute(directory: Path) -> Path:
    entries = base_entries()
    entries.insert(
        0,
        (
            tar_info(
                "PaxHeaders/0",
                typeflag=tarfile.XHDTYPE,
                pax_headers={"path": "/etc/shadow"},
            ),
            None,
        ),
    )
    return _with_entries(directory, "pax-absolute-path.tar.gz", entries)


def _case_pax_dot_dot(directory: Path) -> Path:
    entries = base_entries()
    entries.insert(
        0,
        (
            tar_info(
                "PaxHeaders/0",
                typeflag=tarfile.XHDTYPE,
                pax_headers={"path": "../escape.toml"},
            ),
            None,
        ),
    )
    return _with_entries(directory, "pax-dot-dot-path.tar.gz", entries)


def _case_pax_nul(directory: Path) -> Path:
    entries = base_entries()
    entries.insert(
        0,
        (
            tar_info(
                "PaxHeaders/0",
                typeflag=tarfile.XHDTYPE,
                pax_headers={"path": "xdr/a\x00b.toml"},
            ),
            None,
        ),
    )
    return _with_entries(directory, "pax-nul-in-path.tar.gz", entries)


def _case_fifo(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("xdr/fifo.toml", typeflag=tarfile.FIFOTYPE), None))
    return _with_entries(directory, "fifo-entry.tar.gz", entries)


def _case_symlink(directory: Path) -> Path:
    entries = base_entries()
    entries.append(
        (
            tar_info("xdr/link.toml", typeflag=tarfile.SYMTYPE, linkname="/etc/passwd"),
            None,
        )
    )
    return _with_entries(directory, "symlink-entry.tar.gz", entries)


def _case_hardlink(directory: Path) -> Path:
    entries = base_entries()
    entries.append(
        (
            tar_info("xdr/hard.toml", typeflag=tarfile.LNKTYPE, linkname="registry.json"),
            None,
        )
    )
    return _with_entries(directory, "hard-link-entry.tar.gz", entries)


def _case_setuid(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("xdr/setuid.toml", 5, mode=0o4755), b"extra"))
    return _with_entries(directory, "setuid-bit.tar.gz", entries)


def _case_absolute_path(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("/etc/passwd", 5), b"extra"))
    return _with_entries(directory, "absolute-path.tar.gz", entries)


def _case_dot_dot_path(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("../escape.toml", 5), b"extra"))
    return _with_entries(directory, "dot-dot-path.tar.gz", entries)


def _case_duplicate_path(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("registry.json", 5), b"extra"))
    return _with_entries(directory, "duplicate-path.tar.gz", entries)


def _case_case_fold_duplicate(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("REGISTRY.JSON", 5), b"extra"))
    return _with_entries(directory, "case-fold-duplicate.tar.gz", entries)


def _case_gnu_long_name_reserved(directory: Path) -> Path:
    entries = base_entries()
    entries.append(
        (tar_info("xdr/CON" + "a" * 150 + ".toml", 4), b"data")
    )
    return _with_entries(
        directory, "gnu-long-name-reserved.tar.gz", entries, fmt=tarfile.GNU_FORMAT
    )


def _case_gnu_long_name_dot_dot(directory: Path) -> Path:
    entries = base_entries()
    entries.append(
        (tar_info("xdr/" + "b" * 120 + "/../escape.toml", 4), b"data")
    )
    return _with_entries(
        directory, "gnu-long-name-dot-dot.tar.gz", entries, fmt=tarfile.GNU_FORMAT
    )


def _case_sparse_entry(directory: Path) -> Path:
    def patch(raw: bytearray) -> None:
        raw[156:157] = b"S"
        fix_checksum(raw)

    return _patched_header(directory, "gnu-sparse-entry.tar.gz", patch)


def _case_truncated_data(directory: Path) -> Path:
    data = tar_bytes(base_entries())
    path = directory / "truncated-member-data.tar.gz"
    path.write_bytes(gzip_bytes(data[: 512 + 100]))
    return path


def _case_truncated_header(directory: Path) -> Path:
    data = tar_bytes(base_entries())
    path = directory / "truncated-header.tar.gz"
    path.write_bytes(gzip_bytes(data[:200]))
    return path


def _case_truncated_gzip(directory: Path) -> Path:
    tar = tar_bytes(base_entries())
    compressed = gzip_bytes(tar)
    # Cut the compressed stream inside a member's data, not at a guessed
    # fraction of the file. The cut has to land mid-member: a cut that
    # lands exactly on a member boundary, or inside the next member's
    # header, makes tarfile stop the stream cleanly and the verifier would
    # then classify the truncated stream as a complete one -- and whether
    # a plain "half" lands there depends on the pack's size, so halving
    # was fragile. The cut is found by feeding the gzip one compressed byte
    # at a time and stopping as soon as the decompressed prefix reaches
    # the middle of a member's data: one byte of deflate input yields at
    # most one match (258 bytes) of output, so the step that crosses a
    # member's data start always lands inside that data (members are
    # bigger than that), where a short data read raises "unexpected end of
    # data". The result depends only on the pack's membership, so the case
    # keeps its meaning as the pack grows.
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        target = next(member for member in archive if member.size > 300)
    start = target.offset_data
    stop = target.offset_data + target.size
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    produced = 0
    cut = None
    for index in range(len(compressed)):
        produced += len(decompressor.decompress(compressed[index : index + 1]))
        if start < produced < stop:
            cut = index + 1
            break
    if cut is None:
        raise AssertionError("no cut point inside a member's data was found")
    path = directory / "truncated-gzip.tar.gz"
    path.write_bytes(compressed[:cut])
    return path


def _case_concatenated_gzip(directory: Path) -> Path:
    data = gzip_bytes(tar_bytes(base_entries()))
    path = directory / "concatenated-gzip.tar.gz"
    path.write_bytes(data + gzip_bytes(b""))
    return path


def _case_concatenated_gzip_with_data(directory: Path) -> Path:
    data = gzip_bytes(tar_bytes(base_entries()))
    path = directory / "concatenated-gzip-with-data.tar.gz"
    path.write_bytes(data + gzip_bytes(b"\x00" * 100))
    return path


def _case_trailing_bytes(directory: Path) -> Path:
    data = tar_bytes(base_entries())
    path = directory / "trailing-bytes.tar.gz"
    path.write_bytes(gzip_bytes(data + b"\x00" * 100))
    return path


def _case_extra_root_file(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("extra.txt", 5), b"extra"))
    return _with_entries(directory, "extra-root-file.tar.gz", entries)


def _case_extra_file_in_pack(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("xdr/extra.txt", 5), b"extra"))
    return _with_entries(directory, "extra-file-in-pack.tar.gz", entries)


def _case_extra_toml(directory: Path) -> Path:
    entries = base_entries()
    entries.append((tar_info("xdr/extra.toml", 5), b"extra"))
    return _with_entries(directory, "extra-toml-file.tar.gz", entries)


# The corpus. The exit code is the one tools/pack/verify_archive.py returns
# for the archive as it is built today; the classification says what that
# means against CF-06.
CASES: tuple[HostileCase, ...] = (
    HostileCase(
        name="valid-pack",
        description="the unmodified protocol-28 archive",
        clauses=("CF-06 section 5", "CF-06 section 6"),
        classification=ACCEPTED,
        exit_code=EXIT_VALID,
        build=_case_valid,
        note="the baseline the corpus is compared against: it must verify.",
    ),
    HostileCase(
        name="malformed-header-bad-checksum",
        description="a tar header whose checksum does not match its bytes",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_UNREADABLE,
        build=_case_bad_checksum,
        note="the header is refused before any entry is looked at.",
    ),
    HostileCase(
        name="malformed-header-bad-magic",
        description="a tar header with a wrong magic but a repaired checksum",
        clauses=("CF-06 section 6",),
        classification=ACCEPTED,
        exit_code=EXIT_VALID,
        build=_case_bad_magic,
        note=(
            "tarfile does not look at the magic once the checksum is valid, and "
            "CF-06 section 6 makes container conformance, not entry content, no "
            "reason to refuse an archive."
        ),
    ),
    HostileCase(
        name="malformed-header-unknown-type-flag",
        description="a tar header with a type flag tarfile does not know",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_unknown_type_flag,
        note="the entry is not a regular file or a directory, so it is refused.",
    ),
    HostileCase(
        name="malformed-header-oversized-size",
        description="a tar header whose size field is far above the file limit",
        clauses=("CF-06 section 6", "CF-06 D-06"),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_oversized_size_field,
        note="the declared size is over the 1 MiB per-file limit, so it is refused.",
    ),
    HostileCase(
        name="invalid-utf8-name",
        description="an entry whose name is not valid UTF-8",
        clauses=("CF-06 section 6", "CF-02 section 2"),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_invalid_utf8_name,
        note="the name is outside the CF-02 path rules, so it is refused.",
    ),
    HostileCase(
        name="nul-in-ustar-name",
        description="a NUL inside the fixed-width name field of a tar header",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_nul_in_ustar_name,
        note=(
            "the name field is NUL terminated, so the entry is renamed rather "
            "than carrying the NUL; the archive no longer describes the pack "
            "and is refused."
        ),
    ),
    HostileCase(
        name="pax-path-override-absolute",
        description="a PAX extended header that overrides the path with an absolute one",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_pax_absolute,
        note="the override is applied and then refused as an absolute path.",
    ),
    HostileCase(
        name="pax-path-override-dot-dot",
        description="a PAX extended header that overrides the path with a '..' segment",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_pax_dot_dot,
        note="the override is applied and then refused as a '..' path segment.",
    ),
    HostileCase(
        name="pax-path-override-nul",
        description="a PAX extended header whose path contains a NUL",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_pax_nul,
        note="the NUL survives the PAX record and is refused by the path rules.",
    ),
    HostileCase(
        name="fifo-entry",
        description="a FIFO instead of a regular file",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_fifo,
        note="only regular files and directories are allowed.",
    ),
    HostileCase(
        name="symlink-entry",
        description="a symbolic link to a file outside the archive",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_symlink,
        note="only regular files and directories are allowed.",
    ),
    HostileCase(
        name="hard-link-entry",
        description="a hard link to another member",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_hardlink,
        note="only regular files and directories are allowed.",
    ),
    HostileCase(
        name="setuid-bit",
        description="a member whose mode sets the setuid bit",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_setuid,
        note="setuid, setgid and sticky bits are refused; modes are ignored.",
    ),
    HostileCase(
        name="absolute-path",
        description="a member with an absolute path",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_absolute_path,
        note="an absolute path is refused.",
    ),
    HostileCase(
        name="dot-dot-path",
        description="a member with a '..' path segment",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_dot_dot_path,
        note="a '..' segment is refused.",
    ),
    HostileCase(
        name="duplicate-path",
        description="a member whose path another member already uses",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_duplicate_path,
        note="a repeated path is refused.",
    ),
    HostileCase(
        name="case-fold-duplicate",
        description="a member whose path differs from another only by letter case",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_case_fold_duplicate,
        note="a path that collides after Unicode case folding is refused.",
    ),
    HostileCase(
        name="gnu-long-name-reserved",
        description="a GNU long-name record naming a Windows reserved device",
        clauses=("CF-06 section 6", "CF-02 section 2"),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_gnu_long_name_reserved,
        note=(
            "the long name is read and then refused by the portable-name rule, "
            "so a long name cannot smuggle a reserved name past the check."
        ),
    ),
    HostileCase(
        name="gnu-long-name-dot-dot",
        description="a GNU long-name record naming a path with a '..' segment",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_gnu_long_name_dot_dot,
        note="the long name is read and then refused by the path rules.",
    ),
    HostileCase(
        name="gnu-sparse-entry",
        description="a GNU sparse entry, whose payload is not a plain file",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_sparse_entry,
        note="the sparse entry does not carry the registry, so the archive is refused.",
    ),
    HostileCase(
        name="truncated-member-data",
        description="a tar stream cut inside a member's data",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_UNREADABLE,
        build=_case_truncated_data,
        note="the archive cannot be read at all, which is exit code 2.",
    ),
    HostileCase(
        name="truncated-header",
        description="a tar stream cut inside a header block",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_UNREADABLE,
        build=_case_truncated_header,
        note="the archive cannot be read at all, which is exit code 2.",
    ),
    HostileCase(
        name="truncated-gzip",
        description="the compressed stream cut inside a member's data",
        clauses=("CF-06 section 6",),
        classification=REJECTED,
        exit_code=EXIT_UNREADABLE,
        build=_case_truncated_gzip,
        note="the archive cannot be read at all, which is exit code 2.",
    ),
    HostileCase(
        name="concatenated-gzip-member",
        description="a second, empty gzip member after the archive",
        clauses=("CF-06 section 6",),
        classification=POLICY_DECISION,
        exit_code=EXIT_VALID,
        build=_case_concatenated_gzip,
        required_follow_up=(
            "Clarify whether concatenated gzip streams are permitted; the "
            "verifier reads them as one stream and ignores the empty member."
        ),
    ),
    HostileCase(
        name="concatenated-gzip-member-with-data",
        description="a second gzip member carrying data after the archive",
        clauses=("CF-06 section 6",),
        classification=POLICY_DECISION,
        exit_code=EXIT_VALID,
        build=_case_concatenated_gzip_with_data,
        required_follow_up=(
            "Clarify whether concatenated gzip streams are permitted; the "
            "verifier reads them as one stream and ignores the trailing data."
        ),
    ),
    HostileCase(
        name="trailing-bytes",
        description="bytes after the tar end-of-archive marker",
        clauses=("CF-06 section 6",),
        classification=POLICY_DECISION,
        exit_code=EXIT_VALID,
        build=_case_trailing_bytes,
        required_follow_up=(
            "Clarify whether trailing data after the tar end markers is "
            "permitted; the verifier stops at the end-of-archive marker."
        ),
    ),
    HostileCase(
        name="extra-root-file",
        description="a file at the archive root that is not part of the pack",
        clauses=("CF-06 section 2",),
        classification=POLICY_DECISION,
        exit_code=EXIT_VALID,
        build=_case_extra_root_file,
        required_follow_up=(
            "Reconcile with the exact-pack-membership requirement of CF-06 "
            "section 2: the file is not in the pack digest, so it is not "
            "noticed."
        ),
    ),
    HostileCase(
        name="extra-file-in-pack",
        description="a file inside the pack directory that is not part of the pack",
        clauses=("CF-06 section 2",),
        classification=POLICY_DECISION,
        exit_code=EXIT_VALID,
        build=_case_extra_file_in_pack,
        required_follow_up=(
            "Reconcile with the exact-pack-membership requirement of CF-06 "
            "section 2: the file is not in the pack digest, so it is not "
            "noticed."
        ),
    ),
    HostileCase(
        name="extra-toml-file",
        description="a fixture file inside the pack directory that is not in the registry",
        clauses=("CF-06 section 2", "CF-02 section 3"),
        classification=REJECTED,
        exit_code=EXIT_INVALID,
        build=_case_extra_toml,
        note=(
            "a *.toml file is pack membership, so it changes the pack digest "
            "and the registry no longer describes the archive."
        ),
    ),
)


# The cases whose behaviour CF-06 does not settle. A maintainer has to
# decide what the contract says about them; see the required_follow_up of
# each case.
POLICY_DECISION_CASES = tuple(
    case for case in CASES if case.classification == POLICY_DECISION
)


# The attack shapes the issue names. The corpus has to cover every one of
# them, so the list is checked by the test module.
REQUIRED_SHAPES = (
    "malformed-header",
    "invalid-utf8-name",
    "pax-path-override",
    "fifo-entry",
    "truncated",
    "concatenated-gzip",
    "gnu-long-name",
    "gnu-sparse-entry",
    "trailing-bytes",
    "nul-in-ustar-name",
    "extra-",
)
