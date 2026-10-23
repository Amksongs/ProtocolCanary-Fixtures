#!/usr/bin/env python3
r"""Verify a fixture-pack archive by extracting it safely and validating it.

The consumer side of ``tools/pack/pack.py`` (CF-06 sections 5 and 6). In order,
stopping at the first failure:

1. the archive's SHA-256 matches ``--sha256`` or the manifest, when given;
2. the archive is extracted into a fresh temporary directory under the safe
   extraction rules: only regular files and directories, no absolute path,
   ``..`` segment, backslash or NUL, no duplicate path (also after Unicode case
   folding), no setuid, setgid or sticky bit, and the D-06 limits (2,000
   entries, 16 MiB in total, 1 MiB per file, depth 8). The whole archive is
   refused at the first violation; nothing is executed;
3. ``registry.json`` conforms to ``schemas/registry-v1.schema.json``;
4. the pack digest recomputed over the extracted files equals the registry's
   ``packDigest`` (and the manifest's, when given), and the registry equals the
   one generated from the extracted tree;
5. every extracted fixture passes ``tools/validate/validate.py``;
6. when a manifest is given, the facts it states about the archive match the
   archive: its file name, its size, its entry count, its uncompressed bytes,
   the version in its name, the pack name, the manifest version, and the
   protocols and the registry version of the archived ``registry.json``. Every
   difference is reported, with the field, the value the manifest states and
   the value the archive gives.

The temporary directory is always removed, on success and on failure.

Exit codes: 0 valid, 1 verification failed, 2 unusable input (a malformed
``--sha256`` or ``--manifest``, or an archive that could not be read at all).

Usage:
    python3 tools/pack/verify_archive.py ARCHIVE [--sha256 HEX] [--manifest PATH]

Requires Python 3.11+ and nothing outside the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.common.json_strict import JSONInputError, load_json

REGISTRY_NAME = "registry.json"

MAX_ENTRIES = 2000
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_DEPTH = 8
_SPECIAL_BITS = 0o7000

_SHA256_LENGTH = 64
_DIGEST_PREFIX = "sha256:"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _is_sha256(value: object) -> bool:
    """True for a SHA-256 value: 64 hexadecimal characters, in either case."""
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in _HEX_DIGITS for character in value)
    )


def _load(name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


generate = _load("registry_generate", "tools/registry/generate.py")
validator = _load("fixture_validate", "tools/validate/validate.py")
portable_names = _load("canary_portable_names", "tools/validate/portable_names.py")
release_manifest = _load("release_manifest", "tools/release/manifest.py")


class ArchiveError(Exception):
    """The archive is invalid. The message names the first problem found."""


class UnreadableArchive(ArchiveError):
    """The archive could not be opened or decoded at all."""


@dataclass
class Result:
    problems: list[str] = field(default_factory=list)
    files: int = 0
    fixtures: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_member_path(name: str) -> None:
    """The CF-02 path rules, plus the archive-only ones, for one entry."""
    if name.startswith("/"):
        raise ArchiveError(f"{name!r} is an absolute path")
    if "\\" in name:
        raise ArchiveError(f"{name!r} contains a backslash")
    if "\0" in name:
        raise ArchiveError("an entry name contains a NUL character")
    parts = name.split("/")
    if any(part == "" for part in parts):
        raise ArchiveError(f"{name!r} has an empty path segment")
    if any(part in (".", "..") for part in parts):
        raise ArchiveError(f"{name!r} has a '.' or '..' path segment")
    if len(parts) > MAX_DEPTH:
        raise ArchiveError(f"{name!r} is deeper than {MAX_DEPTH} path segments")
    try:
        portable_names.check_path(name)
    except portable_names.PortableNameError as error:
        raise ArchiveError(f"{name!r}: {error}") from None
    try:
        generate.check_pack_path(name)
    except generate.PackError as error:
        raise ArchiveError(f"{name!r}: {error}") from None


def extract_safely(archive: Path, destination: Path) -> int:
    """Extract ``archive`` into the empty directory ``destination``.

    Returns the number of regular files written. Raises ``ArchiveError`` at
    the first entry that breaks a rule, and ``UnreadableArchive`` when the
    gzip or tar stream is damaged. Entries are created exclusively, so an
    entry can never overwrite or write through a link.
    """
    seen: dict[str, str] = {}
    folded: dict[str, str] = {}
    entries = 0
    total = 0
    written = 0
    try:
        with tarfile.open(archive, mode="r|gz") as stream:
            for member in stream:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise ArchiveError(f"more than {MAX_ENTRIES} entries")
                name = member.name
                _check_member_path(name)
                if not (member.isfile() or member.isdir()):
                    kind = (
                        "a symbolic link" if member.issym()
                        else "a hard link" if member.islnk()
                        else "a special file"
                    )
                    raise ArchiveError(f"{name!r} is {kind}; only files and directories are allowed")
                if member.mode & _SPECIAL_BITS:
                    raise ArchiveError(f"{name!r} sets a setuid, setgid or sticky bit")
                if name in seen:
                    raise ArchiveError(f"{name!r} appears more than once")
                key = name.casefold()
                if key in folded:
                    raise ArchiveError(
                        f"{folded[key]!r} and {name!r} differ only by letter case"
                    )
                seen[name] = name
                folded[key] = name

                target = destination.joinpath(*name.split("/"))
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.size > MAX_FILE_BYTES:
                    raise ArchiveError(
                        f"{name!r} is {member.size} bytes, over the {MAX_FILE_BYTES}-byte limit"
                    )
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise ArchiveError(
                        f"the archive holds more than {MAX_TOTAL_BYTES} bytes uncompressed"
                    )
                source = stream.extractfile(member)
                if source is None:
                    raise ArchiveError(f"{name!r} could not be read")
                target.parent.mkdir(parents=True, exist_ok=True)
                # "xb": fail rather than overwrite or follow an existing link.
                with open(target, "xb") as out:
                    out.write(source.read(member.size + 1))
                os.chmod(target, 0o644)
                written += 1
    except ArchiveError:
        raise
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as error:
        raise UnreadableArchive(f"cannot read the archive: {error}") from None
    return written


def verify_extracted(root: Path, expected_digest: str | None) -> Result:
    """Checks 3 to 5 on an extracted tree."""
    result = Result()
    registry_path = root / REGISTRY_NAME
    if not registry_path.is_file():
        result.problems.append(f"the archive has no {REGISTRY_NAME} at its root")
        return result
    registry_bytes = registry_path.read_bytes()
    try:
        registry = load_json(registry_bytes.decode("utf-8"), REGISTRY_NAME)
    except (UnicodeDecodeError, JSONInputError) as error:
        if isinstance(error, JSONInputError) and error.json_error is not None:
            message = f"{REGISTRY_NAME} is not valid JSON: {error.json_error}"
        else:
            message = f"{REGISTRY_NAME} is not valid JSON: {error}"
        result.problems.append(message)
        return result

    try:
        generate.check_against_schema(registry)
    except generate.PackError as error:
        result.problems.append(str(error))
        return result

    # Recompute from the extracted tree. The registry itself is not a pack
    # member, so it is set aside while the tree is scanned.
    try:
        scanned = generate.scan_pack(root)
        scanned.pop(REGISTRY_NAME, None)
        rebuilt = generate.build_registry(scanned)
    except generate.PackError as error:
        result.problems.append(f"the extracted pack is invalid: {error}")
        return result

    if rebuilt["packDigest"] != registry.get("packDigest"):
        result.problems.append(
            f"{REGISTRY_NAME} declares packDigest {registry.get('packDigest')} but the "
            f"extracted files hash to {rebuilt['packDigest']}"
        )
    if expected_digest is not None and rebuilt["packDigest"] != expected_digest:
        result.problems.append(
            f"the extracted pack digest {rebuilt['packDigest']} does not match the "
            f"expected {expected_digest}"
        )
    if generate.render_registry(rebuilt).encode("utf-8") != registry_bytes:
        result.problems.append(
            f"{REGISTRY_NAME} is not the registry generated from the archived fixtures"
        )

    report = validator.validate_directory(root)
    result.problems.extend(report.errors)
    result.fixtures = len(rebuilt["fixtures"])
    result.files = len(scanned)
    return result


def verify_archive(
    archive: Path,
    *,
    expected_sha256: str | None = None,
    expected_digest: str | None = None,
) -> Result:
    """Run the whole CF-06 section 5 sequence on ``archive``."""
    result = Result()
    if not archive.is_file():
        raise UnreadableArchive(f"archive not found: {archive}")
    if expected_sha256 is not None:
        actual = sha256_file(archive)
        if actual != expected_sha256.lower():
            result.problems.append(
                f"archive SHA-256 {actual} does not match the expected {expected_sha256}"
            )
            return result
    with tempfile.TemporaryDirectory(prefix="canary-pack-verify-") as directory:
        root = Path(directory)
        try:
            extract_safely(archive, root)
        except UnreadableArchive:
            raise
        except ArchiveError as error:
            result.problems.append(f"unsafe or invalid archive: {error}")
            return result
        return verify_extracted(root, expected_digest)


def _manifest_expectations(path: Path) -> tuple[str, str, dict]:
    """Read the archive hash, the pack digest and the document of a manifest.

    Every problem with the manifest is unusable input: the message names the
    manifest path and the field at fault, never a Python exception text.
    The document itself is returned so that the facts it states about the
    archive can be checked against the archive.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise UnreadableArchive(
            f"cannot use manifest {path}: {error.strerror or error}"
        ) from None
    except UnicodeDecodeError:
        raise UnreadableArchive(
            f"cannot use manifest {path}: the file is not valid UTF-8"
        ) from None

    if not text.strip():
        raise UnreadableArchive(f"cannot use manifest {path}: the file is empty")

    try:
        document = load_json(text, f"manifest {path}")
    except JSONInputError as error:
        if error.json_error is not None:
            raise UnreadableArchive(
                f"cannot use manifest {path}: the file is not valid JSON "
                f"(line {error.json_error.lineno}, column {error.json_error.colno})"
            ) from None
        raise UnreadableArchive(
            f"cannot use manifest {path}: {error}"
        ) from None

    if not isinstance(document, dict):
        raise UnreadableArchive(
            f"cannot use manifest {path}: the manifest must be a JSON object"
        )

    archive = document.get("archive")
    if not isinstance(archive, dict):
        raise UnreadableArchive(
            f"cannot use manifest {path}: archive must be a JSON object"
        )

    sha256 = archive.get("sha256")
    if not isinstance(sha256, str):
        raise UnreadableArchive(
            f"cannot use manifest {path}: archive.sha256 must be a string"
        )
    if not _is_sha256(sha256):
        raise UnreadableArchive(
            f"cannot use manifest {path}: archive.sha256 must be 64 hexadecimal characters"
        )

    digest = document.get("packDigest")
    if not isinstance(digest, str):
        raise UnreadableArchive(
            f"cannot use manifest {path}: packDigest must be a string"
        )
    if not digest.startswith(_DIGEST_PREFIX) or not _is_sha256(
        digest[len(_DIGEST_PREFIX) :]
    ):
        raise UnreadableArchive(
            f"cannot use manifest {path}: packDigest must be '{_DIGEST_PREFIX}' "
            "followed by 64 hexadecimal characters"
        )

    return sha256.lower(), digest, document


def _same_value(declared: object, actual: object) -> bool:
    """Equal in value and in type: ``True`` is not ``1``."""
    if isinstance(declared, bool) != isinstance(actual, bool):
        return False
    return declared == actual


def _manifest_differences(archive: Path, document: dict) -> list[str]:
    """Compare the facts the manifest states about the archive with the archive.

    CF-06 section 3 makes every field of the manifest a fact about the
    archive, so a consumer that passes ``--manifest`` can read a green
    result as "this archive is what the manifest describes". Each difference
    is reported with the field, the value the manifest states and the value
    the archive gives, and every difference is reported, not only the first
    one.

    The entries and the uncompressed bytes are counted by the code that
    writes the manifest, so the two tools cannot disagree about them. The
    protocols and the registry version come from the archive's own
    ``registry.json``.
    """
    differences: list[str] = []
    stated = document.get("archive")
    if not isinstance(stated, dict):
        stated = {}

    try:
        content = release_manifest.inspect_archive(archive)
    except release_manifest.ManifestError as error:
        return [f"the archive could not be read to check the manifest: {error}"]

    registry: dict = {}
    registry_bytes = content["files"].get(release_manifest.REGISTRY_NAME)
    if registry_bytes is not None:
        try:
            decoded = load_json(registry_bytes.decode("utf-8"), REGISTRY_NAME)
        except (UnicodeDecodeError, JSONInputError):
            decoded = None
        if isinstance(decoded, dict):
            registry = decoded

    def compare(field: str, declared: object, actual: object) -> None:
        if _same_value(declared, actual):
            return
        differences.append(
            f"the manifest says {field} is {declared!r} but the archive gives {actual!r}"
        )

    compare("archive.file", stated.get("file"), archive.name)
    compare("archive.bytes", stated.get("bytes"), archive.stat().st_size)
    compare("archive.entries", stated.get("entries"), content["entries"])
    compare(
        "archive.uncompressedBytes",
        stated.get("uncompressedBytes"),
        content["uncompressed"],
    )
    version = release_manifest.archive_version(archive.name)
    if version is None:
        differences.append(
            f"the archive file name {archive.name!r} carries no version, so the "
            f"manifest's version {document.get('version')!r} cannot be confirmed"
        )
    else:
        compare("version", document.get("version"), version)
    compare("name", document.get("name"), release_manifest.NAME)
    compare(
        "manifestVersion",
        document.get("manifestVersion"),
        release_manifest.MANIFEST_VERSION,
    )
    protocol = registry.get("protocol")
    if isinstance(protocol, int) and not isinstance(protocol, bool):
        compare("protocols", document.get("protocols"), [protocol])
    else:
        compare("protocols", document.get("protocols"), None)
    compare("registryVersion", document.get("registryVersion"), registry.get("registryVersion"))
    return differences


def _validate_pin(value: str) -> str:
    """Check the ``--sha256`` argument before the archive is touched.

    A pin that is not a SHA-256 value is unusable input, not a mismatch: a
    typo in a pinned hash must not look like a tampered download. The value
    itself is never echoed back.
    """
    if value.startswith(_DIGEST_PREFIX):
        raise UnreadableArchive(
            "--sha256 must be 64 hexadecimal characters "
            f"(got {len(value)} characters); the '{_DIGEST_PREFIX}' prefix is not accepted"
        )
    if not _is_sha256(value):
        raise UnreadableArchive(
            f"--sha256 must be 64 hexadecimal characters (got {len(value)} characters)"
        )
    return value.lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_archive.py",
        description="Extract a fixture-pack archive safely and validate its contents (CF-06).",
        epilog=(
            "Exit codes: 0 valid, 1 verification failed, 2 unusable input "
            "(a malformed --sha256 or --manifest, or an archive that cannot be read)."
        ),
    )
    parser.add_argument("archive", type=Path, help="the .tar.gz to verify")
    parser.add_argument(
        "--sha256",
        metavar="HEX",
        help="expected SHA-256 of the archive (64 hexadecimal characters)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        metavar="PATH",
        help="a release manifest whose archive hash and packDigest the archive must match",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        expected_sha = None if args.sha256 is None else _validate_pin(args.sha256)
        expected_digest = None
        manifest_document = None
        if args.manifest is not None:
            manifest_sha, expected_digest, manifest_document = _manifest_expectations(
                args.manifest
            )
            if expected_sha is not None and expected_sha != manifest_sha:
                print(
                    "error: --sha256 disagrees with the manifest; "
                    "an explicit pin wins and the manifest is not used to override it",
                    file=sys.stderr,
                )
                return 1
            expected_sha = expected_sha or manifest_sha
        result = verify_archive(
            args.archive, expected_sha256=expected_sha, expected_digest=expected_digest
        )
        if result.ok and manifest_document is not None:
            result.problems.extend(_manifest_differences(args.archive, manifest_document))
    except UnreadableArchive as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if result.ok:
        print(
            f"OK: {args.archive.name}: {result.fixtures} fixture(s), "
            f"{result.files} file(s) valid; registry and pack digest match"
        )
        return 0
    for problem in result.problems:
        print(f"error: {problem}", file=sys.stderr)
    print(f"FAILED: {len(result.problems)} problem(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
