#!/usr/bin/env python3
r"""Read and validate pack-by-engine run records (issue #367).

CF-06 section 3 says ``compatibleEngines[].verified`` in the release manifest
is true only when that exact engine version and that exact pack were run
together and the run is recorded. This module is the recording side of that
rule: it reads the records, checks them, and finds the one that matches an
engine and a pack.

A run record says:

* which exact engine version ran (``engineVersion`` -- never a range);
* which exact pack it ran against (``packDigest``, the CF-02 digest of the
  pack files, so the record cannot be about a different pack that happens to
  have the same version number);
* when the run happened (``checkedAt``, an RFC 3339 UTC instant);
* who ran it (``verifier``);
* how it went (``outcome``).

This module never writes a record. A record is written by whoever actually
ran the pair; the manifest tool only reads.

The format is described by ``schemas/run-record-v1.schema.json``. Where the
records live is a maintainer decision that issue #367 lists as open; this
module takes the directory as an argument, so the location is not baked in.

Requires Python 3.11+ and nothing outside the standard library.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN_RECORD_VERSION = 1
RUN_RECORD_OUTCOMES = ("passed", "failed")

REQUIRED_FIELDS = (
    "runRecordVersion",
    "engineVersion",
    "packDigest",
    "checkedAt",
    "verifier",
    "outcome",
)
OPTIONAL_FIELDS = ("evidenceRef",)

_ENGINE_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")

# A run record is written by the job that ran the pair, on another machine, so
# its clock can be a little behind. Five minutes of skew is tolerated; a
# record from the future beyond that is refused rather than believed.
CLOCK_SKEW = timedelta(minutes=5)


class RunRecordError(Exception):
    """A run record cannot be read or does not satisfy the format rules.

    The message names the file and says what is wrong, so a broken record is
    a clear error instead of a silently unverified engine.
    """


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_instant(value: object) -> str | None:
    """Problem with a timestamp, or None. RFC 3339, UTC, with a ``Z``."""
    if not isinstance(value, str) or not _INSTANT_RE.fullmatch(value):
        return "checkedAt must be an RFC 3339 UTC instant such as 2026-10-22T12:00:00Z"
    try:
        datetime.strptime(value.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return f"checkedAt {value!r} is not a real date and time"
    return None


def validate_run_record(record: object, now: datetime | None = None) -> list[str]:
    """Every problem found in one run record. An empty list means it is valid.

    ``now`` is the instant the check is made against; a record from the
    future is refused.
    """
    if not isinstance(record, dict):
        return ["a run record must be a JSON object"]

    problems: list[str] = []
    allowed = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)
    for name in REQUIRED_FIELDS:
        if name not in record:
            problems.append(f"missing required field {name!r}")
    for name in sorted(set(record) - allowed):
        problems.append(
            f"unknown field {name!r}; allowed fields are " + ", ".join(sorted(allowed))
        )

    version = record.get("runRecordVersion")
    if "runRecordVersion" in record and (
        not _is_int(version) or version != RUN_RECORD_VERSION
    ):
        problems.append(f"runRecordVersion must be {RUN_RECORD_VERSION}")

    engine = record.get("engineVersion")
    if "engineVersion" in record:
        if not isinstance(engine, str) or not _ENGINE_RE.fullmatch(engine):
            problems.append(
                "engineVersion must be an exact MAJOR.MINOR.PATCH; a range is "
                "never a verified combination"
            )

    digest = record.get("packDigest")
    if "packDigest" in record and not (
        isinstance(digest, str) and _DIGEST_RE.fullmatch(digest)
    ):
        problems.append("packDigest must be 'sha256:' followed by 64 lowercase hex characters")

    if "checkedAt" in record:
        instant_problem = check_instant(record["checkedAt"])
        if instant_problem:
            problems.append(instant_problem)
        else:
            moment = datetime.strptime(
                str(record["checkedAt"]).split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            if moment > reference + CLOCK_SKEW:
                problems.append(
                    f"checkedAt {record['checkedAt']!r} is in the future; a run "
                    "that has not happened yet cannot be recorded"
                )

    outcome = record.get("outcome")
    if "outcome" in record and outcome not in RUN_RECORD_OUTCOMES:
        problems.append(f"outcome must be one of {list(RUN_RECORD_OUTCOMES)}")

    if "verifier" in record:
        verifier = record["verifier"]
        if not isinstance(verifier, dict):
            problems.append("verifier must be an object with name and version")
        else:
            for name in ("name", "version"):
                if not _non_empty_str(verifier.get(name)):
                    problems.append(f"verifier.{name} must be a non-empty string")
            for name in sorted(set(verifier) - {"name", "version"}):
                problems.append(f"unknown field {name!r} in verifier")

    reference = record.get("evidenceRef")
    if reference is not None:
        if not _non_empty_str(reference):
            problems.append("evidenceRef must be a non-empty string or null")
        elif reference.startswith("/") or "\\" in reference or any(
            part in ("", ".", "..") for part in reference.split("/")
        ):
            problems.append("evidenceRef must be a relative path inside the repository")

    return problems


def load_run_record(path: Path, now: datetime | None = None) -> dict:
    """Read one run record. Raises ``RunRecordError`` when it is not valid."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RunRecordError(f"cannot read the run record {path}: {error}") from None
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise RunRecordError(f"{path} is not valid JSON: {error}") from None
    problems = validate_run_record(record, now=now)
    if problems:
        raise RunRecordError(f"{path} is not a valid run record: " + "; ".join(problems))
    assert isinstance(record, dict)
    return record


def load_run_records(directory: Path, now: datetime | None = None) -> list[dict]:
    """Every run record under ``directory``, sorted by file name.

    A record that cannot be read, or that breaks the format rules, stops the
    whole load: a broken record must never be read as "no record", because
    that would silently downgrade a verified engine to unverified.
    """
    if not directory.is_dir():
        raise RunRecordError(f"run record directory not found: {directory}")
    records: list[dict] = []
    for path in sorted(directory.rglob("*.json")):
        if not path.is_file():
            continue
        records.append(load_run_record(path, now=now))
    return records


def records_for_engine(records: list[dict], engine_version: str) -> list[dict]:
    """The records that name this exact engine version."""
    return [
        record for record in records if record.get("engineVersion") == engine_version
    ]


def find_record(records: list[dict], engine_version: str, pack_digest: str) -> dict | None:
    """The record of this exact engine version run against this exact pack."""
    for record in records:
        if (
            record.get("engineVersion") == engine_version
            and record.get("packDigest") == pack_digest
        ):
            return record
    return None
