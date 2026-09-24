#!/usr/bin/env python3
"""Generate (or verify) the fixture-count badge in README.md.

The badge at the top of README.md is an ordinary static shields.io shield,
but its number is never hand-maintained: this script counts every ``*.toml``
fixture under the repository's ``protocol-*/`` packs using the same
discovery rule as ``tools/validate/validate.py``, then rewrites the marked
region of README.md in place.

Because the number is derived from the fixture tree rather than typed by
hand, it cannot drift out of date in either direction: a fixture added
without regenerating the badge (or a pack deleted without regenerating it)
is caught by the ``--check`` form, which CI runs on every push and pull
request. See README.md's "Fixtures badge" section.

Usage:
    python3 tools/badge/badge.py            # rewrite README.md in place
    python3 tools/badge/badge.py --check    # exit 1 if README.md is stale

Requires Python 3.11+ (the validator it reuses uses the stdlib ``tomllib``).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"

# Invisible markers delimiting the generated region of README.md, so the
# rewrite is a surgical, idempotent replacement of exactly one region
# instead of a heuristic line match that could touch surrounding prose.
BADGE_START = "<!-- fixtures-badge:start -->"
BADGE_END = "<!-- fixtures-badge:end -->"

BADGE_COLOR = "blue"
BADGE_LINK = "#protocol-packs"

# The validator owns the authoritative fixture-discovery rule; reuse it
# rather than reimplementing "which files count as fixtures" here.
_VALIDATE_PATH = Path(__file__).resolve().parents[1] / "validate" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate", _VALIDATE_PATH)
assert _spec is not None and _spec.loader is not None
validate = importlib.util.module_from_spec(_spec)
sys.modules["validate"] = validate
_spec.loader.exec_module(validate)


class BadgeMarkerError(RuntimeError):
    """Raised when README.md is missing the generated-region markers."""


def pack_roots(repo_root: Path) -> list[Path]:
    """Directories the fixture count is taken over, mirroring validate.py."""
    packs = sorted(p for p in repo_root.glob("protocol-*") if p.is_dir())
    return packs or [repo_root]


def count_fixtures(repo_root: Path) -> int:
    """Total number of ``*.toml`` fixture files across every protocol pack."""
    return sum(len(validate.find_fixture_files(root)) for root in pack_roots(repo_root))


def badge_markdown(count: int) -> str:
    """The shields.io markdown for a given fixture count."""
    url = f"https://img.shields.io/badge/fixtures-{count}-{BADGE_COLOR}.svg"
    return f"[![Fixtures: {count}]({url})]({BADGE_LINK})"


def render(readme: str, count: int) -> str:
    """Return ``readme`` with its badge region set to ``count``."""
    start = readme.find(BADGE_START)
    end = readme.find(BADGE_END)
    if start == -1 or end == -1 or end < start:
        raise BadgeMarkerError(
            "README.md must contain "
            f"{BADGE_START} before {BADGE_END}, around the badge it generates"
        )
    return (
        f"{readme[:start]}{BADGE_START}{badge_markdown(count)}{BADGE_END}"
        f"{readme[end + len(BADGE_END):]}"
    )


def main(argv: list[str]) -> int:
    check = "--check" in argv
    try:
        readme = README_PATH.read_text(encoding="utf-8")
        count = count_fixtures(REPO_ROOT)
        updated = render(readme, count)
    except (OSError, BadgeMarkerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if check:
        if readme != updated:
            print(
                "error: README.md's fixtures badge is stale; run "
                "`python3 tools/badge/badge.py` (or `make badge`) and commit the result",
                file=sys.stderr,
            )
            return 1
        print(f"OK: README.md fixtures badge is current ({count} fixture file(s))")
        return 0

    if readme != updated:
        README_PATH.write_text(updated, encoding="utf-8")
        print(f"OK: README.md fixtures badge updated to {count} fixture file(s)")
    else:
        print(f"OK: README.md fixtures badge already current ({count} fixture file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
