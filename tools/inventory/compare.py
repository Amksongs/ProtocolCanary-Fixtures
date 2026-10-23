#!/usr/bin/env python3
r"""Compare the engine's fixture inventory with a pack registry (F-014).

``stellar-canary fixtures --format json`` (CA-02) prints the fixtures the
engine's own loader discovered: an ``inventoryVersion 1`` document holding
one entry per fixture of the requested protocol, sorted by id, with the
fixture's ``surface`` and ``category``. ``tools/registry/generate.py`` writes
the other half: ``registry-v1.json``, the pack's own manifest (CF-02).

Nothing in the repository compares the two, so a fixture can be present in the
registry and invisible to the engine (a file the loader skips, a protocol
mismatch, a directory the engine does not descend into) -- or the engine can
load a fixture the registry never lists -- and both tools keep reporting
success. This tool closes that gap: it parses both documents and asserts that
the two inventories hold exactly the same fixture ids, each with the same
``surface`` and ``category``.

It reads the two JSON documents and nothing else. No fixture is opened, no
directory is scanned, and nothing is executed, so it can run against an
inventory captured from the engine on a machine that has no fixture pack.

Usage:
    python3 tools/inventory/compare.py INVENTORY REGISTRY [--format text|json]

``INVENTORY`` is the JSON document ``stellar-canary fixtures --format json``
printed, or ``-`` to read it from standard input; ``REGISTRY`` is a
``registry-v1.json``. ``--format text`` (the default) prints the
human-readable report; ``--format json`` prints one deterministic JSON
document (two-space indent, UTF-8, one trailing newline) for a CI job to
ingest.

The registry is validated against ``schemas/registry-v1.schema.json`` plus the
rules a schema cannot express (no duplicate fixture id). The engine's
inventory is validated against the parts this comparison depends on: the
document version, the protocol, ``directoryFound``, the fixture entries and
their agreement with ``counts.total``. An input that cannot be compared --
missing, not UTF-8, not JSON, wrong version, duplicated id, or a registry and
an inventory for different protocols -- is reported and never repaired.

An empty fixtures list is a legitimate answer on either side: the empty
baseline pack (``protocol-29/registry-v1.json``) ships with ``fixtures: []``,
which the registry schema's ``minItems: 1`` cannot express, so that one floor
is relaxed here for an empty list only. Comparing an empty registry with a
non-empty inventory is therefore a real difference (every engine fixture is
reported as absent from the registry), not an unusable input.

Exit codes:
    0   the inventories match: the same ids, the same surfaces, the same
        categories
    1   the inventories differ; the missing, extra and mismatched entries are
        printed
    2   unusable input: a missing or unreadable file, a document that is not
        valid UTF-8 or valid JSON, an inventory or registry this tool cannot
        compare, or a command-line error

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

FORMATS = ("text", "json")

# The document versions this tool understands. A newer inventory could rename
# a field or change a meaning, so comparing it with these rules would be a
# guess; it is refused instead.
INVENTORY_VERSION = 1
FIXTURE_FORMAT = 1
REGISTRY_VERSION = 1

SURFACES = ("xdr", "rpc", "soroban")

# The attributes compared for a fixture that is in both inventories, in the
# order a text report lists them.
COMPARED_FIELDS = ("surface", "category")

# The registry schema's minimum for `fixtures`. The generator's documented
# `--allow-empty` baseline (protocol-29) writes `fixtures: []`, so an empty
# list is accepted here and compared as a real, empty inventory.
EMPTY_LIST_EXCEPTION = "fewer than 1"


class CompareError(Exception):
    """An input cannot be compared. Never repaired, never ignored."""


def _load_schema_validator():
    """Import tools/validate/jsonschema_lite.py without needing a package."""
    name = "canary_jsonschema_lite_inventory"
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


def _read_bytes(path: Path, label: str) -> bytes:
    """Read one input file, or raise CompareError naming what went wrong."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise CompareError(f"{path}: no such {label} file") from None
    except IsADirectoryError:
        raise CompareError(f"{path}: is a directory, not a {label} file") from None
    except OSError as error:
        raise CompareError(f"{path}: could not be read: {error}") from None


def _parse_json(raw: bytes, path: Path, label: str) -> object:
    """Decode ``raw`` as UTF-8 JSON, or raise CompareError."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompareError(f"{path}: is not valid UTF-8: {error}") from None
    try:
        return load_json(text, str(path))
    except JSONInputError as error:
        raise CompareError(str(error)) from None


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------- inventory


def check_inventory(inventory: object) -> list[str]:
    """Every reason this engine inventory cannot be compared, in a stable order."""
    problems: list[str] = []
    if not isinstance(inventory, dict):
        return ["an engine inventory must be a JSON object"]

    version = inventory.get("inventoryVersion")
    if not _is_integer(version):
        problems.append("missing or non-integer 'inventoryVersion'")
    elif version != INVENTORY_VERSION:
        problems.append(
            f"'inventoryVersion' is {version}; this tool compares version "
            f"{INVENTORY_VERSION} only, so a newer document is refused rather "
            "than read with the wrong rules"
        )

    fixture_format = inventory.get("fixtureFormat")
    if not _is_integer(fixture_format):
        problems.append("missing or non-integer 'fixtureFormat'")
    elif fixture_format != FIXTURE_FORMAT:
        problems.append(
            f"'fixtureFormat' is {fixture_format}; this tool compares fixture "
            f"format {FIXTURE_FORMAT} only"
        )

    protocol = inventory.get("protocol")
    if not _is_integer(protocol) or protocol < 1:
        problems.append("'protocol' must be a positive integer")

    directory_found = inventory.get("directoryFound")
    if not isinstance(directory_found, bool):
        problems.append("'directoryFound' must be true or false")
    elif not directory_found:
        problems.append(
            "'directoryFound' is false: the engine did not find the fixtures "
            "directory, so it discovered nothing to compare"
        )

    fixtures = inventory.get("fixtures")
    if not isinstance(fixtures, list):
        problems.append("'fixtures' must be an array")
        fixtures = []

    counts = inventory.get("counts")
    if not isinstance(counts, dict):
        problems.append("'counts' must be an object")
    else:
        total = counts.get("total")
        if not _is_integer(total):
            problems.append("'counts.total' must be an integer")
        elif total != len(fixtures):
            problems.append(
                f"'counts.total' is {total} but the document lists "
                f"{len(fixtures)} fixture(s); the inventory contradicts itself"
            )

    seen: set[str] = set()
    for index, entry in enumerate(fixtures):
        where = f"fixtures[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where} must be an object")
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            problems.append(f"{where}.id must be a non-empty string")
        elif identifier in seen:
            problems.append(f"the fixture id {identifier!r} appears twice")
        else:
            seen.add(identifier)
        surface = entry.get("surface")
        if surface not in SURFACES:
            problems.append(
                f"{where}.surface must be one of {list(SURFACES)}, got {surface!r}"
            )
        category = entry.get("category")
        if not isinstance(category, str) or not category:
            problems.append(f"{where}.category must be a non-empty string")
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            problems.append(f"{where}.path must be a non-empty string")

    return problems


def load_inventory(source: str) -> dict:
    """Read and validate the engine inventory from ``source`` ('-' is stdin)."""
    if source == "-":
        try:
            raw = sys.stdin.buffer.read()
        except (AttributeError, OSError) as error:
            raise CompareError(f"standard input could not be read: {error}") from None
        inventory = _parse_json(raw, Path("-"), "engine inventory")
    else:
        path = Path(source)
        inventory = _parse_json(_read_bytes(path, "engine inventory"), path, "engine inventory")

    problems = check_inventory(inventory)
    if problems:
        raise CompareError(_problem_message(source, "engine inventory", problems))
    return inventory


# ---------------------------------------------------------------- registry


def check_registry(registry: object) -> list[str]:
    """Every reason this registry cannot be compared, in a stable order."""
    if not isinstance(registry, dict):
        return ["a registry must be a JSON object"]

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    problems = _load_schema_validator().validate(registry, schema)

    fixtures = registry.get("fixtures")
    if isinstance(fixtures, list):
        if not fixtures:
            # The documented empty baseline (generator --allow-empty). The
            # schema cannot express "empty is allowed here and nowhere else",
            # so that one message is dropped and the empty list is compared.
            problems = [p for p in problems if EMPTY_LIST_EXCEPTION not in p]
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

    version = registry.get("registryVersion")
    if _is_integer(version) and version != REGISTRY_VERSION:
        problems.append(
            f"'registryVersion' is {version}; this tool compares version "
            f"{REGISTRY_VERSION} only"
        )

    return problems


def load_registry(path: Path) -> dict:
    """Read and validate one registry file, or raise CompareError."""
    registry = _parse_json(_read_bytes(path, "registry"), path, "registry")
    problems = check_registry(registry)
    if problems:
        raise CompareError(_problem_message(str(path), "registry", problems))
    return registry


def _problem_message(source: str, label: str, problems: list[str]) -> str:
    return (
        f"{source}: is not a usable {label}:\n  - " + "\n  - ".join(problems)
    )


# ---------------------------------------------------------------- comparing


def _by_id(fixtures: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in fixtures}


def compare_inventories(inventory: dict, registry: dict) -> dict:
    """Compare the engine inventory with the registry.

    The result holds the number of fixtures that agree, the fixtures only the
    registry knows (``missing``: the engine did not discover them), the
    fixtures only the engine discovered (``extra``: the registry does not list
    them), and one entry per differing attribute of a fixture that is in both
    (``mismatched``). All three lists are sorted by fixture id, comparing
    UTF-8 bytes, and a fixture's mismatches by field name, so two runs over
    the same inputs are byte-identical.
    """
    engine_fixtures = _by_id(inventory["fixtures"])
    registry_fixtures = _by_id(registry["fixtures"])

    missing = []
    extra = []
    mismatched = []
    matched = 0

    for identifier in sorted(set(engine_fixtures) | set(registry_fixtures), key=_utf8_key):
        engine = engine_fixtures.get(identifier)
        listing = registry_fixtures.get(identifier)
        if listing is None:
            extra.append(
                {
                    "id": identifier,
                    "path": engine["path"],
                    "surface": engine["surface"],
                    "category": engine["category"],
                }
            )
        elif engine is None:
            missing.append(
                {
                    "id": identifier,
                    "path": listing["path"],
                    "surface": listing["surface"],
                    "category": listing["category"],
                }
            )
        else:
            differs = False
            for field in COMPARED_FIELDS:
                if engine[field] != listing[field]:
                    differs = True
                    mismatched.append(
                        {
                            "id": identifier,
                            "field": field,
                            "inventory": engine[field],
                            "registry": listing[field],
                        }
                    )
            if not differs:
                matched += 1

    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "match": not (missing or extra or mismatched),
    }


def _summary_inventory(source: str, inventory: dict) -> dict:
    return {
        "path": source,
        "protocol": inventory["protocol"],
        "inventoryVersion": inventory["inventoryVersion"],
        "fixtureCount": len(inventory["fixtures"]),
    }


def _summary_registry(path: Path, registry: dict) -> dict:
    return {
        "path": str(path),
        "protocol": registry["protocol"],
        "registryVersion": registry["registryVersion"],
        "fixtureCount": len(registry["fixtures"]),
    }


# ---------------------------------------------------------------- rendering


def render_text(result: dict, inventory: dict, registry: dict) -> str:
    """The human-readable report."""
    lines = [
        f"engine inventory: {inventory['path']} (protocol {inventory['protocol']}, "
        f"inventory version {inventory['inventoryVersion']}, "
        f"{inventory['fixtureCount']} fixture(s))",
        f"registry:         {registry['path']} (protocol {registry['protocol']}, "
        f"registry version {registry['registryVersion']}, "
        f"{registry['fixtureCount']} fixture(s))",
        "",
    ]

    if result["match"]:
        lines.append(
            f"OK: both inventories hold the same {result['matched']} fixture(s) "
            "with matching ids, surfaces and categories."
        )
        return "\n".join(lines) + "\n"

    differences = (
        len(result["missing"]) + len(result["extra"]) + len(result["mismatched"])
    )
    lines.append(
        f"FAILED: {differences} difference(s) between the engine inventory and "
        "the registry."
    )
    lines.append("")
    lines.append(
        f"missing from the engine inventory ({len(result['missing'])}) "
        "-- in the registry, not discovered by the engine:"
    )
    for entry in result["missing"]:
        lines.append(
            f"  {entry['id']}  ({entry['surface']}, {entry['category']})  "
            f"registry path: {entry['path']}"
        )
    lines.append("")
    lines.append(
        f"extra in the engine inventory ({len(result['extra'])}) "
        "-- discovered by the engine, not in the registry:"
    )
    for entry in result["extra"]:
        lines.append(
            f"  {entry['id']}  ({entry['surface']}, {entry['category']})  "
            f"engine path: {entry['path']}"
        )
    lines.append("")
    lines.append(f"attribute mismatches ({len(result['mismatched'])}):")
    for entry in result["mismatched"]:
        lines.append(
            f"  {entry['id']}  {entry['field']}  engine={entry['inventory']!r} "
            f"registry={entry['registry']!r}"
        )
    lines.append("")
    lines.append(f"matched: {result['matched']} fixture(s)")
    return "\n".join(lines) + "\n"


def render_json(result: dict, inventory: dict, registry: dict) -> str:
    """The machine-readable report (key order is part of the format)."""
    document = {
        "inventory": inventory,
        "registry": registry,
        "matched": result["matched"],
        "missing": result["missing"],
        "extra": result["extra"],
        "mismatched": result["mismatched"],
        "match": result["match"],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare.py",
        description=(
            "Compare `stellar-canary fixtures --format json` output with a "
            "pack's registry-v1.json and assert that the engine discovered "
            "exactly the fixtures the registry lists, with the same surfaces "
            "and categories. Reads the two documents, never executes anything."
        ),
        epilog=(
            "Exit codes: 0 the inventories match, 1 they differ (the missing, "
            "extra and mismatched entries are printed), 2 unusable input "
            "(missing/unreadable file, not valid UTF-8 or JSON, an inventory "
            "or registry this tool cannot compare, protocol mismatch, or a "
            "command-line error)."
        ),
    )
    parser.add_argument(
        "inventory",
        type=str,
        metavar="INVENTORY",
        help="the engine inventory JSON file, or '-' to read standard input",
    )
    parser.add_argument(
        "registry", type=Path, metavar="REGISTRY", help="the pack's registry-v1.json"
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="text",
        help="output format (default: text)",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    try:
        inventory = load_inventory(args.inventory)
        registry = load_registry(args.registry)
    except CompareError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if inventory["protocol"] != registry["protocol"]:
        print(
            f"error: {args.inventory} is an inventory of protocol "
            f"{inventory['protocol']} and {args.registry} is a registry of "
            f"protocol {registry['protocol']}; comparing them would report "
            "every fixture as missing or extra",
            file=sys.stderr,
        )
        return 2

    result = compare_inventories(inventory, registry)
    inventory_summary = _summary_inventory(args.inventory, inventory)
    registry_summary = _summary_registry(args.registry, registry)
    if args.format == "json":
        sys.stdout.write(render_json(result, inventory_summary, registry_summary))
    else:
        sys.stdout.write(render_text(result, inventory_summary, registry_summary))
    return 0 if result["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
