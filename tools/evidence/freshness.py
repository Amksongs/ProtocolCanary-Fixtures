#!/usr/bin/env python3
r"""Report verification freshness and flag stale evidence records (F-007, issue #271).

Parses checkedAt ISO-8601 timestamps from verification records in evidence/,
calculating days since check date against current UTC date.
Classifies records as:
  - fresh (<30d)
  - aging (30-90d)
  - stale (>90d)

Fails with exit code 1 when --strict is passed and stale records exist.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

ISO_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


class FreshnessFormatError(Exception):
    """Raised when checkedAt timestamp is unparseable or in the future."""


@dataclass(frozen=True)
class RecordFreshness:
    path: Path
    fixture_id: str
    checked_at_str: str
    checked_at: datetime
    age_days: int
    status: str  # "fresh", "aging", "stale"


def parse_checked_at(value: object, now: datetime | None = None) -> datetime:
    """Parse checkedAt ISO-8601 string and verify it is not in the future."""
    if not isinstance(value, str) or not ISO_INSTANT_RE.fullmatch(value):
        raise FreshnessFormatError(
            f"unparseable date string: {value!r} is not an RFC 3339 UTC instant (e.g. 2026-10-22T07:00:00Z)"
        )

    # Strip Z for strptime or parse ISO
    raw = value.rstrip("Z")
    try:
        if "." in raw:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise FreshnessFormatError(f"unparseable date string: {exc}") from exc

    dt = dt.replace(tzinfo=timezone.utc)

    if now is None:
        now = datetime.now(timezone.utc)

    if dt > now:
        raise FreshnessFormatError(
            f"future timestamp: checkedAt {value!r} is after current instant {now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    return dt


def classify_freshness(age_days: int) -> str:
    """Classify age in days into fresh, aging, or stale."""
    if age_days < 30:
        return "fresh"
    elif age_days <= 90:
        return "aging"
    return "stale"


def calculate_record_freshness(
    record_path: Path, data: dict, now: datetime | None = None
) -> RecordFreshness:
    """Compute freshness for a single parsed record."""
    if now is None:
        now = datetime.now(timezone.utc)

    if "checkedAt" not in data:
        raise FreshnessFormatError(f"missing 'checkedAt' field in {record_path}")

    checked_at = parse_checked_at(data["checkedAt"], now=now)
    fixture_id = data.get("fixtureId") or record_path.stem

    # Calculate days since check date against current UTC date
    age_days = (now.date() - checked_at.date()).days

    # Clamp lower bound to 0 in case same-day clock differences arise
    if age_days < 0:
        age_days = 0

    status = classify_freshness(age_days)
    return RecordFreshness(
        path=record_path,
        fixture_id=str(fixture_id),
        checked_at_str=data["checkedAt"],
        checked_at=checked_at,
        age_days=age_days,
        status=status,
    )


def find_record_files(paths: Sequence[Path]) -> list[Path]:
    """Find all JSON evidence record files from given paths or defaults."""
    found: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".json":
            found.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*.json")):
                found.append(child)
    return found


def scan_freshness(
    paths: Sequence[Path], now: datetime | None = None
) -> tuple[list[RecordFreshness], list[tuple[Path, str]]]:
    """Scan evidence records and return classified records and format errors."""
    if now is None:
        now = datetime.now(timezone.utc)

    results: list[RecordFreshness] = []
    errors: list[tuple[Path, str]] = []

    files = find_record_files(paths)
    for file_path in files:
        try:
            content = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append((file_path, f"JSON parse error: {exc}"))
            continue

        # Check if this JSON object looks like an evidence record with checkedAt
        if isinstance(content, dict) and "checkedAt" in content:
            try:
                freshness = calculate_record_freshness(file_path, content, now=now)
                results.append(freshness)
            except FreshnessFormatError as exc:
                errors.append((file_path, str(exc)))
        elif isinstance(content, dict) and "verificationVersion" in content:
            # It's an evidence record missing checkedAt
            errors.append((file_path, "missing 'checkedAt' field"))

    return results, errors


def format_table(results: list[RecordFreshness]) -> str:
    """Format results into a summary table."""
    if not results:
        return "No evidence records evaluated."

    col1 = "Fixture ID"
    col2 = "Checked At"
    col3 = "Age (Days)"
    col4 = "Status"

    max_id_len = max(len(col1), max(len(r.fixture_id) for r in results))
    max_cat_len = max(len(col2), max(len(r.checked_at_str) for r in results))

    header = f"{col1:<{max_id_len}}  {col2:<{max_cat_len}}  {col3:>10}  {col4:<8}"
    sep = "-" * len(header)
    rows = [sep, header, sep]

    for r in sorted(results, key=lambda x: (x.status != "stale", x.status != "aging", -x.age_days, x.fixture_id)):
        rows.append(f"{r.fixture_id:<{max_id_len}}  {r.checked_at_str:<{max_cat_len}}  {r.age_days:>10}  {r.status:<8}")

    rows.append(sep)
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Directories or record files to evaluate (default: searches protocol-*/evidence/records and evidence/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any stale (>90d) records exist",
    )
    args = parser.parse_args(argv)

    search_paths: list[Path] = []
    if args.paths:
        search_paths = [Path(p) for p in args.paths]
    else:
        # Default scan locations
        for p in (REPO_ROOT).glob("protocol-*/evidence/records"):
            if p.is_dir():
                search_paths.append(p)
        top_evidence = REPO_ROOT / "evidence"
        if top_evidence.is_dir():
            search_paths.append(top_evidence)

    results, errors = scan_freshness(search_paths)

    print(format_table(results))

    fresh_count = sum(1 for r in results if r.status == "fresh")
    aging_count = sum(1 for r in results if r.status == "aging")
    stale_count = sum(1 for r in results if r.status == "stale")

    print(
        f"\nSummary: Total: {len(results)} | "
        f"Fresh: {fresh_count} | Aging: {aging_count} | Stale: {stale_count} | "
        f"Errors: {len(errors)}"
    )

    if errors:
        print("\nFormat / Validation Errors:")
        for path, err in errors:
            print(f"  {path}: {err}", file=sys.stderr)
        return 1

    if args.strict and stale_count > 0:
        print(f"\nERROR: --strict enabled and {stale_count} stale record(s) found.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
