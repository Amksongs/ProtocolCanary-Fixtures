#!/usr/bin/env python3
r"""Compare two fixture registries and report what changed between them.

``tools/registry/generate.py`` writes a ``registry-v1.json`` for a pack. There
is no tool to compare two of them, so the changelog for a new pack release is
written by hand from ``git log``. Which fixtures were added, removed or
changed -- the same id with a different file hash -- is exactly what the
registry data already answers, and a consumer that pins a fixture needs to
know when the fixture it depends on changed.

The tool compares two registry files and prints three sorted lists -- added,
removed and changed -- keyed by fixture id, with the old and new file hash
for a changed fixture and the pack digest of each registry. A fixture whose
content did not change but whose path did is reported separately, as moved,
so that a changed fixture always carries two different hashes. Nothing is
executed and no fixture is read: only the two registry files are opened.

Both inputs are validated against ``schemas/registry-v1.schema.json`` before
they are compared, and the rules a schema cannot express -- a duplicate
fixture id, an empty fixtures list -- are checked here. Comparing registries
of different protocols is refused unless ``--allow-protocol-mismatch`` is
given, because a difference between two packs of different protocols is not a
change of a pack.

Usage:
    python3 tools/registry/diff.py OLD NEW [--format text|json|markdown]
                                           [--allow-protocol-mismatch]

Exit codes:
    0   the registries were compared; there may or may not be differences
    2   unusable input: a missing or unreadable file, a file that is not
        valid JSON, a registry that does not conform to the registry schema,
        a duplicate fixture id, an empty fixtures list, a protocol mismatch
        without ``--allow-protocol-mismatch``, or a command-line error

Requires Python 3.11+ and nothing outside the standard library.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.common.json_strict import JSONInputError, load_json

SCHEMA_PATH = REPO_ROOT / "schemas" / "registry-v1.schema.json"

FORMATS = ("text", "json", "markdown")


class DiffError(Exception):
    """An input cannot be compared. Never repaired, never ignored."""


def _load_schema_validator():
    """Import tools/validate/jsonschema_lite.py without needing a package."""
    name = "canary_jsonschema_lite_diff"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    path = REPO_ROOT / "tools" / "validate" / "jsonschema_lite.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _utf8_key(text: str) -> bytes:
    return text.encode("utf-8")


# ---------------------------------------------------------------- loading


def load_registry(path: Path) -> dict:
    """Read and validate one registry file, or raise DiffError."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise DiffError(f"{path}: no such file") from None
    except IsADirectoryError:
        raise DiffError(f"{path}: is a directory, not a registry file") from None
    except OSError as error:
        raise DiffError(f"{path}: could not be read: {error}") from None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DiffError(f"{path}: is not valid UTF-8: {error}") from None

    try:
        registry = load_json(text, str(path))
    except JSONInputError as error:
        raise DiffError(str(error)) from None

    problems = check_registry(registry)
    if problems:
        raise DiffError(
            f"{path}: is not a usable registry (checked against {SCHEMA_PATH.name}):\n"
            "  - " + "\n  - ".join(problems)
        )
    return registry


def check_registry(registry: object) -> list[str]:
    """Every reason this registry cannot be compared, in a stable order."""
    problems: list[str] = []

    if not isinstance(registry, dict):
        return ["a registry must be a JSON object"]

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    problems.extend(_load_schema_validator().validate(registry, schema))

    fixtures = registry.get("fixtures")
    if isinstance(fixtures, list):
        seen: set[str] = set()
        for entry in fixtures:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("id")
            if not isinstance(identifier, str):
                continue
            if identifier in seen:
                problems.append(f"the fixture id {identifier!r} appears twice")
            seen.add(identifier)
        if not fixtures:
            problems.append("the fixtures list is empty")

    return problems


# ---------------------------------------------------------------- comparing


def _by_id(registry: dict) -> dict[str, dict]:
    """The registry's fixtures keyed by id."""
    return {entry["id"]: entry for entry in registry["fixtures"]}


def diff_registries(old: dict, new: dict) -> dict:
    """Compare two registries and return the difference.

    The result holds three lists -- added, removed and changed -- keyed by
    fixture id and sorted by id, plus the number of unchanged fixtures. A
    fixture is *changed* when its id is in both registries but its file hash
    differs; the old and new hashes and the old and new path are reported.
    A fixture whose content did not change but whose path did is *moved*,
    and is reported separately so that a changed fixture always carries two
    different hashes.
    """
    old_fixtures = _by_id(old)
    new_fixtures = _by_id(new)

    added = []
    removed = []
    changed = []
    moved = []
    unchanged = 0

    for identifier in sorted(set(old_fixtures) | set(new_fixtures), key=_utf8_key):
        before = old_fixtures.get(identifier)
        after = new_fixtures.get(identifier)
        if before is None:
            added.append(
                {
                    "id": identifier,
                    "path": after["path"],
                    "sha256": after["sha256"],
                    "surface": after["surface"],
                }
            )
        elif after is None:
            removed.append(
                {
                    "id": identifier,
                    "path": before["path"],
                    "sha256": before["sha256"],
                    "surface": before["surface"],
                }
            )
        elif before["sha256"] != after["sha256"]:
            changed.append(
                {
                    "id": identifier,
                    "old_path": before["path"],
                    "new_path": after["path"],
                    "old_sha256": before["sha256"],
                    "new_sha256": after["sha256"],
                }
            )
        elif before["path"] != after["path"]:
            moved.append(
                {
                    "id": identifier,
                    "old_path": before["path"],
                    "new_path": after["path"],
                    "sha256": after["sha256"],
                }
            )
        else:
            unchanged += 1

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "moved": moved,
        "unchanged": unchanged,
    }


def _summary(path: Path, registry: dict) -> dict:
    return {
        "path": str(path),
        "protocol": registry["protocol"],
        "packDigest": registry["packDigest"],
    }


# ---------------------------------------------------------------- rendering


def render_text(diff: dict, old: dict, new: dict) -> str:
    """The human-readable report."""
    lines = [
        f"old: {old['path']} (pack digest {old['packDigest']})",
        f"new: {new['path']} (pack digest {new['packDigest']})",
        "",
        f"added ({len(diff['added'])}):",
    ]
    if diff["added"]:
        lines.extend(f"  {entry['id']}  {entry['path']}" for entry in diff["added"])
    lines.append(f"removed ({len(diff['removed'])}):")
    if diff["removed"]:
        lines.extend(f"  {entry['id']}  {entry['path']}" for entry in diff["removed"])
    lines.append(f"changed ({len(diff['changed'])}):")
    if diff["changed"]:
        lines.extend(
            f"  {entry['id']}  {entry['old_path']} -> {entry['new_path']}  "
            f"sha256 {entry['old_sha256']} -> sha256 {entry['new_sha256']}"
            for entry in diff["changed"]
        )
    lines.append(f"moved ({len(diff['moved'])}):")
    if diff["moved"]:
        lines.extend(
            f"  {entry['id']}  {entry['old_path']} -> {entry['new_path']}"
            for entry in diff["moved"]
        )
    lines.append(f"unchanged ({diff['unchanged']})")
    return "\n".join(lines) + "\n"


def render_json(diff: dict, old: dict, new: dict) -> str:
    """The machine-readable report."""
    document = {
        "old": old,
        "new": new,
        "added": diff["added"],
        "removed": diff["removed"],
        "changed": diff["changed"],
        "moved": diff["moved"],
        "unchanged": diff["unchanged"],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render_markdown(diff: dict, old: dict, new: dict) -> str:
    """A Markdown block for the CHANGELOG."""
    lines: list[str] = []
    if diff["added"]:
        lines.append("### Added")
        lines.extend(
            f"- `{entry['id']}` (`{entry['path']}`)" for entry in diff["added"]
        )
        lines.append("")
    if diff["removed"]:
        lines.append("### Removed")
        lines.extend(
            f"- `{entry['id']}` (`{entry['path']}`)" for entry in diff["removed"]
        )
        lines.append("")
    if diff["changed"]:
        lines.append("### Changed")
        lines.extend(
            f"- `{entry['id']}` — sha256 `{entry['old_sha256']}` -> "
            f"`{entry['new_sha256']}`"
            for entry in diff["changed"]
        )
        lines.append("")
    if diff["moved"]:
        lines.append("### Moved")
        lines.extend(
            f"- `{entry['id']}` — `{entry['old_path']}` -> `{entry['new_path']}`"
            for entry in diff["moved"]
        )
        lines.append("")
    if not lines:
        lines.append("No fixture changed between the two registries.")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diff.py",
        description=(
            "Compare two fixture registries and report which fixtures were added, "
            "removed or changed, for the release notes of a new pack release. "
            "Reads the two registry files, never executes anything."
        ),
        epilog=(
            "Exit codes: 0 the registries were compared (there may be "
            "differences), 2 unusable input (missing or unreadable file, not "
            "valid JSON, not a usable registry, protocol mismatch without "
            "--allow-protocol-mismatch, or a command-line error)."
        ),
    )
    parser.add_argument("old", type=Path, metavar="OLD", help="the older registry file")
    parser.add_argument("new", type=Path, metavar="NEW", help="the newer registry file")
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--allow-protocol-mismatch",
        action="store_true",
        help="compare registries of different protocols instead of refusing",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        old_registry = load_registry(args.old)
        new_registry = load_registry(args.new)
    except DiffError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if (
        old_registry["protocol"] != new_registry["protocol"]
        and not args.allow_protocol_mismatch
    ):
        print(
            f"error: {args.old} is for protocol {old_registry['protocol']} and "
            f"{args.new} is for protocol {new_registry['protocol']}; pass "
            "--allow-protocol-mismatch to compare them anyway",
            file=sys.stderr,
        )
        return 2

    diff = diff_registries(old_registry, new_registry)
    old = _summary(args.old, old_registry)
    new = _summary(args.new, new_registry)
    if args.format == "json":
        sys.stdout.write(render_json(diff, old, new))
    elif args.format == "markdown":
        sys.stdout.write(render_markdown(diff, old, new))
    else:
        sys.stdout.write(render_text(diff, old, new))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
