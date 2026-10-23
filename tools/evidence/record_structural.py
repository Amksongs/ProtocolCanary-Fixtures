#!/usr/bin/env python3
r"""Create CF-04 verification records for the structural check (issue #366).

A verification record says exactly this: *this* fixture file, with *these*
bytes, was checked by *this* verifier, at *this* instant, and the outcome was
*this* (CF-04 section 3). This tool writes the records for the one check that
can be executed again right now: the structural check that
``tools/validate/validate.py`` performs.

What it does:

* runs the structural validation of the pack -- the same code the CI runs;
* for every fixture that passes it, writes one record holding the SHA-256 of
  the fixture file as it is on disk, ``checkedAt`` set to the instant the
  check actually ran, and ``method: "structural"``;
* writes nothing at all when a fixture does not validate, so a broken pack
  cannot produce a record that says it is fine.

What it never does (CF-04 section 3, and the rules issue #366 states):

* it never invents a record for a check that did not run;
* it never derives an instant from a date-only fixture header comment: a
  header such as ``Verified live on 2026-09-02`` names a day, not an instant,
  so no record is derived from it at all;
* it never records a live observation: a live record needs a saved capture,
  and this tool takes no capture;
* it never marks a fixture verified because a structural test passed. A
  structural record says the file is well formed. It says nothing about
  Stellar behavior, and it is not a live verification.

Where the records go is a maintainer decision that issue #366 lists as still
open. This tool writes them to ``<pack>/evidence/records/`` and takes
``--output-dir`` so the location can be changed in one place when the
decision is recorded.

Usage:
    python3 tools/evidence/record_structural.py PACK
        [--output-dir DIR] [--verifier-version VERSION] [--dry-run]

Requires Python 3.11+ and nothing outside the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.validate import validate

# The verifier that performed the check. CF-04 section 3 asks for the exact
# thing that did the work; for a structural check that is this repository's
# validator, named here and pinned to the commit it was read from.
VERIFIER_NAME = "protocolcanary-fixtures-validate"

# The default place the records go, relative to the pack. CF-04 section 3
# says a record is "stored per fixture, in the registry (CF-02) or beside the
# fixture"; issue #366 records that the final location is still a maintainer
# decision, so this is a proposal and one constant.
RECORDS_DIRNAME = "evidence/records"


class RecordError(Exception):
    """The records cannot be written. The message says why."""


def sha256_of(path: Path) -> str:
    """The SHA-256 of the file's bytes, as CF-02 hashes them."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise RecordError(f"could not read {path}: {error}") from None


def git_revision(repo_root: Path) -> str:
    """The commit the validator was read from, or ``unknown``.

    The version of a verifier has to identify the exact code that did the
    check. For the validator that is the commit it was read from; a checkout
    without git (a source archive, a vendored copy) cannot answer that, and
    says so rather than guessing.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    revision = result.stdout.strip()
    if result.returncode != 0 or len(revision) != 40:
        return "unknown"
    return revision


def structural_check(root: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    """The fixtures that pass the structural check, and the problems found.

    The check is the one the CI runs: ``validate_directory`` over the pack.
    """
    report = validate.validate_directory(root)
    problems = list(report.errors)
    fixtures: list[tuple[str, Path]] = []
    for path in validate.find_fixture_files(root):
        scratch = validate.Report()
        loaded = validate.load_fixture(path, scratch, root=root)
        fixture_id = validate.known_fixture_id(loaded) if loaded is not None else None
        if loaded is None or fixture_id is None:
            problems.extend(scratch.errors)
            continue
        fixtures.append((fixture_id, path))
    return fixtures, problems


def build_record(fixture_id: str, fixture_sha256: str, checked_at: str, version: str) -> dict:
    """One verification record for a structural check that has just run."""
    return {
        "verificationVersion": validate.EVIDENCE_VERSION,
        "fixtureId": fixture_id,
        "fixtureSha256": fixture_sha256,
        "method": "structural",
        "checkedAt": checked_at,
        "verifier": {"name": VERIFIER_NAME, "version": version},
        "outcome": "matched",
        # A structural check has no capture behind it, and saying so
        # explicitly is better than leaving the reader to guess.
        "evidenceRef": None,
    }


def render_record(record: dict) -> str:
    """UTF-8, LF, two-space indent, one trailing newline."""
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


def write_records(records: dict[str, dict], output_dir: Path) -> list[Path]:
    """Write the records, one file per fixture. Returns the paths written."""
    written: list[Path] = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RecordError(f"could not create {output_dir}: {error}") from None
    for fixture_id in sorted(records):
        path = output_dir / f"{fixture_id}.json"
        try:
            path.write_bytes(render_record(records[fixture_id]).encode("utf-8"))
        except OSError as error:
            raise RecordError(f"could not write {path}: {error}") from None
        written.append(path)
    return written


def run(
    pack: Path,
    output_dir: Path | None = None,
    version: str | None = None,
    dry_run: bool = False,
) -> tuple[list[Path], str]:
    """Check the pack and write its records. Returns the paths and the instant."""
    if not pack.is_dir():
        raise RecordError(f"pack not found: {pack}")
    fixtures, problems = structural_check(pack)
    if problems:
        raise RecordError(
            "the pack does not validate, so no record was written:\n  "
            + "\n  ".join(problems)
        )
    if not fixtures:
        raise RecordError(f"{pack} holds no fixture to record")

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verifier_version = version if version else git_revision(REPO_ROOT)
    records = {
        fixture_id: build_record(
            fixture_id, sha256_of(path), checked_at, verifier_version
        )
        for fixture_id, path in fixtures
    }

    # A record is only useful if the validator accepts it, so every record is
    # checked with the validator's own rules before it is written.
    for fixture_id, record in records.items():
        record_problems = validate.validate_evidence(record)
        if record_problems:
            raise RecordError(
                f"the record for {fixture_id!r} does not satisfy the CF-04 rules: "
                + "; ".join(record_problems)
            )

    if dry_run:
        return [], checked_at
    target = output_dir if output_dir is not None else pack / RECORDS_DIRNAME
    return write_records(records, target), checked_at


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="record_structural.py",
        description=(
            "Write CF-04 verification records for the structural check of a pack "
            "(issue #366). The check is executed by this run; nothing is derived "
            "from a header comment or from a check that did not happen."
        ),
    )
    parser.add_argument("pack", type=Path, help="the pack directory to check")
    parser.add_argument(
        "--output-dir",
        type=Path,
        metavar="DIR",
        help=f"where to write the records (default: PACK/{RECORDS_DIRNAME})",
    )
    parser.add_argument(
        "--verifier-version",
        metavar="VERSION",
        help=(
            "the version to record for the verifier (default: the commit the "
            "validator was read from)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the check and report what would be written, but write nothing",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        written, checked_at = run(
            args.pack,
            output_dir=args.output_dir,
            version=args.verifier_version,
            dry_run=args.dry_run,
        )
    except RecordError as error:
        print(f"error: {error}", file=sys.stderr)
        print("FAILED: no record written", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"OK: the pack validates; no record written (dry run at {checked_at})")
        return 0
    print(f"OK: wrote {len(written)} record(s) at {checked_at}")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
