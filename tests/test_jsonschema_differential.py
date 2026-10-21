"""Differential testing for tools/validate/jsonschema_lite.py (F-073 / issue #347).

``tools/validate/jsonschema_lite.py`` is the standard-library JSON Schema
validator this repository ships with, because CI runs on a bare interpreter.
This module compares it against the reference Draft 2020-12 implementation
(the pinned ``jsonschema`` development dependency) so that a divergence in
keyword behaviour is noticed instead of assumed away.

What it does:

* builds the instances from the repository's own outputs -- the registry that
  ``tools/registry/generate.py`` produces for ``protocol-28``, the manifest
  that ``tools/release/manifest.py`` produces for the archive built from that
  pack, and the checked-in ``upstream-matrix.json``;
* mutates those instances one fault at a time, deterministically, from a fixed
  seed, and compares the two verdicts on every mutant;
* adds hand-written edge cases for the keywords the issue names: ``pattern``,
  ``uniqueItems``, numeric bounds, booleans against integers, and
  ``additionalProperties``;
* checks that every schema designated in scope uses only keywords
  ``jsonschema_lite`` implements;
* reports a mismatch with the schema name, the JSON Pointer of the instance
  node, the instance, both verdicts and the seed;
* keeps the differences that are known and reviewed in ``KNOWN_DIFFERENCES``.
  Any difference that is not in that list fails the test, so a new difference
  has to be looked at and recorded rather than tolerated;
* demonstrates that a deliberately introduced validator bug is caught, using a
  scratch copy of the validator. The production file is never modified.

The default test suite stays free of third-party packages: everything here
skips with a clear message when ``jsonschema`` is not importable. The
opt-in workflow ``.github/workflows/schema-differential.yml`` installs the
pinned dependency and runs this module.

Run with: python3 -m unittest tests.test_jsonschema_differential
"""

from __future__ import annotations

import copy
import importlib.util
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
LITE_RELATIVE = "tools/validate/jsonschema_lite.py"

# The seed of the deterministic mutation generator. It is fixed so that a
# failure can be reproduced from the report alone, and it is printed with
# every mismatch.
SEED = 20260921

# How many mutants of one repository instance are compared. The sites are
# shuffled with the seeded generator first, so the same subset is compared on
# every run and on every machine.
MUTANTS_PER_INSTANCE = 220

# A full 40-character lowercase git commit hash: tools/release/manifest.py
# requires one and rejects anything shorter.
REVISION = "0123456789abcdef0123456789abcdef01234567"

# The schemas the comparison runs on. Every keyword they use is implemented
# by jsonschema_lite; the other schemas in schemas/ use keywords the lite
# validator deliberately refuses (if/then/else in fixture-v1 and
# verification-v1, format in verification-v1) and are out of scope.
IN_SCOPE_SCHEMAS = {
    "registry-v1": REPO_ROOT / "schemas" / "registry-v1.schema.json",
    "release-manifest-v1": REPO_ROOT / "schemas" / "release-manifest-v1.schema.json",
    "upstream-matrix": REPO_ROOT / "schemas" / "upstream-matrix.json",
    "simulation-resource-estimate": (
        REPO_ROOT / "schemas" / "proposed" / "simulation-resource-estimate.expect.json"
    ),
}


# ---------------------------------------------------------------- loading


def load_lite(path: Path | None = None, name: str = "canary_jsonschema_lite"):
    """Import ``tools/validate/jsonschema_lite.py`` (or a copy of it)."""
    target = path or (REPO_ROOT / LITE_RELATIVE)
    spec = importlib.util.spec_from_file_location(name, target)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_reference():
    """Return the reference Draft 2020-12 validator class, or None."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return None
    return Draft202012Validator


REFERENCE = load_reference()
SKIP_REASON = (
    None
    if REFERENCE is not None
    else "the reference 'jsonschema' package is not installed; install it with "
    "'python3 -m pip install --require-hashes -r requirements-differential.txt' "
    "to run the differential comparison"
)

LITE = load_lite()


# ---------------------------------------------------------------- verdicts


@dataclass(frozen=True)
class Verdict:
    """What one validator said about one document."""

    valid: bool
    errors: tuple[str, ...] = ()
    pointers: tuple[str, ...] = ()

    def summary(self) -> str:
        state = "valid" if self.valid else "invalid"
        if self.valid:
            return state
        first = self.errors[0] if self.errors else ""
        return f"{state}: {first}"


def _pointer(segments) -> str:
    """A JSON Pointer (RFC 6901) for a list of path segments."""
    if not segments:
        return "/"
    out = []
    for segment in segments:
        text = str(segment)
        out.append("/" + text.replace("~", "~0").replace("/", "~1"))
    return "".join(out)


def _pointer_segments(pointer: str) -> list[str]:
    if pointer in ("", "/"):
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


# jsonschema_lite writes its paths as "$.fixtures[0].sha256"; the reference
# implementation reports a list of path parts. Both are turned into JSON
# Pointers so that a mismatch can be located in the instance.
_LITE_PATH = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")


def _lite_pointer(message: str) -> str:
    head = message.split(":", 1)[0]
    segments: list[str] = []
    for match in _LITE_PATH.finditer(head):
        if match.group(1) is not None:
            segments.append(match.group(1))
        else:
            segments.append(match.group(2))
    return _pointer(segments)


def lite_verdict(lite, document: Any, schema: dict) -> Verdict:
    """Run the standard-library validator."""
    errors = lite.validate(document, schema)
    return Verdict(
        valid=not errors,
        errors=tuple(errors),
        pointers=tuple(_lite_pointer(error) for error in errors),
    )


def reference_verdict(document: Any, schema: dict) -> Verdict:
    """Run the reference Draft 2020-12 validator."""
    assert REFERENCE is not None, "the reference validator is not available"
    validator = REFERENCE(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    return Verdict(
        valid=not errors,
        errors=tuple(error.message for error in errors),
        pointers=tuple(_pointer(error.absolute_path) for error in errors),
    )


# ---------------------------------------------------------------- schema walking


# The places a JSON Schema document can hold a sub-schema. A keyword that is
# not in this table never contains a sub-schema, so its value is a plain
# value and not a schema.
_SUB_SCHEMA_MAP = ("properties", "patternProperties", "$defs", "definitions")
_SUB_SCHEMA_LIST = ("prefixItems", "allOf", "anyOf", "oneOf")
_SUB_SCHEMA_SINGLE = (
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "contains",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
    "additionalItems",
    "unevaluatedItems",
)


def schema_keywords(schema: Any, found: set[str] | None = None) -> set[str]:
    """Every keyword used by ``schema``, including inside sub-schemas."""
    if found is None:
        found = set()
    if isinstance(schema, bool):
        return found
    if not isinstance(schema, dict):
        return found
    for key, value in schema.items():
        found.add(key)
        if key in _SUB_SCHEMA_MAP and isinstance(value, dict):
            for sub in value.values():
                schema_keywords(sub, found)
        elif key in _SUB_SCHEMA_LIST and isinstance(value, list):
            for sub in value:
                schema_keywords(sub, found)
        elif key in _SUB_SCHEMA_SINGLE:
            schema_keywords(value, found)
        elif key == "dependentSchemas" and isinstance(value, dict):
            for sub in value.values():
                schema_keywords(sub, found)
    return found


def _descend(node: Any, segment: str) -> Any:
    """The sub-schema that governs the property or item named ``segment``."""
    if not isinstance(node, dict):
        return {}
    if segment.isdigit() and isinstance(node.get("items"), dict):
        return node["items"]
    properties = node.get("properties")
    if isinstance(properties, dict) and segment in properties:
        return properties[segment]
    patterns = node.get("patternProperties")
    if isinstance(patterns, dict):
        for pattern, sub in patterns.items():
            if re.search(pattern, segment):
                return sub
    extra = node.get("additionalProperties")
    if isinstance(extra, dict):
        return extra
    return {}


def governing_subschema(schema: dict, pointer: str) -> dict:
    """The sub-schema that governs the instance node at ``pointer``."""
    node: Any = schema
    for segment in _pointer_segments(pointer):
        node = _descend(node, segment)
    return node if isinstance(node, dict) else {}


def node_at(document: Any, pointer: str) -> Any:
    """The instance node at ``pointer``."""
    node = document
    for segment in _pointer_segments(pointer):
        if isinstance(node, dict):
            node = node.get(segment)
        elif isinstance(node, list) and segment.isdigit():
            index = int(segment)
            node = node[index] if index < len(node) else None
        else:
            return None
    return node


# ---------------------------------------------------------------- known differences

# The keywords whose implementation differs between jsonschema_lite and the
# reference implementation. Every other keyword lite implements behaves the
# same way in both, so a difference that cannot be traced to one of these is a
# bug rather than a documented difference.
DIVERGENT_KEYWORDS = frozenset({"type", "const", "enum", "uniqueItems"})


@dataclass(frozen=True)
class KnownDifference:
    """A difference between the two validators that has been reviewed.

    ``explains`` says whether a concrete finding is this difference: it gets
    the instance node and the sub-schema that governs it, and returns True
    only for the exact situation the difference describes.
    """

    identifier: str
    keywords: frozenset[str]
    lite_valid: bool
    reference_valid: bool
    why: str
    explains: Callable[[Any, dict], bool]


def _explains_integer_number(node: Any, subschema: dict) -> bool:
    """JSON Schema 2020-12 calls 1.0 an integer; jsonschema_lite does not."""
    if isinstance(node, bool) or not isinstance(node, float):
        return False
    if not node.is_integer():
        return False
    wanted = subschema.get("type")
    if wanted is None:
        return False
    names = wanted if isinstance(wanted, list) else [wanted]
    return "integer" in names


def _explains_const_number(node: Any, subschema: dict) -> bool:
    """JSON Schema compares const by value; jsonschema_lite by type name."""
    if "const" not in subschema or "type" in subschema:
        return False
    expected = subschema["const"]
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return False
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return False
    return node == expected and type(node) is not type(expected)


def _explains_enum_boolean(node: Any, subschema: dict) -> bool:
    """JSON Schema keeps true and 1 apart; jsonschema_lite uses Python's ==."""
    if "enum" not in subschema or not isinstance(node, bool):
        return False
    for member in subschema["enum"]:
        if isinstance(member, bool):
            continue
        if isinstance(member, (int, float)) and member == node:
            return True
    return False


def _explains_unique_items_boolean(node: Any, subschema: dict) -> bool:
    """JSON Schema keeps true and 1 apart; jsonschema_lite uses Python's ==."""
    if subschema.get("uniqueItems") is not True or not isinstance(node, list):
        return False
    numbers = [v for v in node if isinstance(v, (int, float)) and not isinstance(v, bool)]
    booleans = [v for v in node if isinstance(v, bool)]
    return any(flag == number for flag in booleans for number in numbers)


KNOWN_DIFFERENCES = (
    KnownDifference(
        identifier="integer-is-a-number",
        keywords=frozenset({"type"}),
        lite_valid=False,
        reference_valid=True,
        why=(
            "JSON Schema 2020-12 says a number with a zero fractional part is an "
            "integer, so 1.0 satisfies 'type: integer'. jsonschema_lite requires a "
            "Python int, so it rejects 1.0. jsonschema_lite is the stricter of the "
            "two: a document the reference accepts is refused, never the other way "
            "round."
        ),
        explains=_explains_integer_number,
    ),
    KnownDifference(
        identifier="const-is-compared-by-value",
        keywords=frozenset({"const"}),
        lite_valid=False,
        reference_valid=True,
        why=(
            "JSON Schema compares const by value, so 'const: 1' matches 1.0. "
            "jsonschema_lite also requires the same JSON type name, so it rejects "
            "1.0. jsonschema_lite is the stricter of the two."
        ),
        explains=_explains_const_number,
    ),
    KnownDifference(
        identifier="enum-separates-true-from-one",
        keywords=frozenset({"enum"}),
        lite_valid=True,
        reference_valid=False,
        why=(
            "JSON Schema keeps the boolean true and the number 1 apart, so "
            "'enum: [1]' does not match true. jsonschema_lite compares with Python's "
            "'in', where True == 1, so it accepts true. This is the one documented "
            "difference where jsonschema_lite is the more permissive of the two: a "
            "document the reference rejects is accepted. No schema in scope uses "
            "enum with a numeric member, so no repository document is affected."
        ),
        explains=_explains_enum_boolean,
    ),
    KnownDifference(
        identifier="unique-items-separates-true-from-one",
        keywords=frozenset({"uniqueItems"}),
        lite_valid=False,
        reference_valid=True,
        why=(
            "JSON Schema keeps the boolean true and the number 1 apart, so "
            "[true, 1] has unique items. jsonschema_lite compares with Python's "
            "'in', where True == 1, so it reports a repeated item. jsonschema_lite "
            "is the stricter of the two. No schema in scope uses uniqueItems."
        ),
        explains=_explains_unique_items_boolean,
    ),
)


@dataclass(frozen=True)
class Mismatch:
    """One instance on which the two validators disagreed."""

    schema_name: str
    schema: dict
    document: Any
    pointer: str
    lite: Verdict
    reference: Verdict
    origin: str
    seed: int = SEED

    @property
    def node(self) -> Any:
        return node_at(self.document, self.pointer)

    def describe(self) -> str:
        """The report a maintainer reads: what, where, and how each side said."""
        return "\n".join(
            [
                f"schema    : {self.schema_name}",
                f"pointer   : {self.pointer}",
                f"instance  : {json.dumps(self.node, default=repr, sort_keys=True)}",
                f"lite      : {self.lite.summary()}",
                f"reference : {self.reference.summary()}",
                f"origin    : {self.origin}",
                f"seed      : {self.seed}",
            ]
        )


def known_difference_for(mismatch: Mismatch) -> KnownDifference | None:
    """The reviewed difference that explains ``mismatch``, if there is one."""
    subschema = governing_subschema(mismatch.schema, mismatch.pointer)
    divergent = {key for key in DIVERGENT_KEYWORDS if key in subschema}
    node = mismatch.node
    for known in KNOWN_DIFFERENCES:
        if known.lite_valid != mismatch.lite.valid:
            continue
        if known.reference_valid != mismatch.reference.valid:
            continue
        if not (divergent & known.keywords):
            continue
        if not known.explains(node, subschema):
            continue
        return known
    return None


def compare(
    lite,
    schema_name: str,
    schema: dict,
    document: Any,
    origin: str,
) -> list[Mismatch]:
    """Compare the two validators on one document."""
    lite_result = lite_verdict(lite, document, schema)
    reference_result = reference_verdict(document, schema)
    if lite_result.valid == reference_result.valid:
        return []
    if lite_result.valid:
        pointer = reference_result.pointers[0] if reference_result.pointers else "/"
    else:
        pointer = lite_result.pointers[0] if lite_result.pointers else "/"
    return [
        Mismatch(
            schema_name=schema_name,
            schema=schema,
            document=document,
            pointer=pointer,
            lite=lite_result,
            reference=reference_result,
            origin=origin,
        )
    ]


# ---------------------------------------------------------------- instances


@dataclass
class Instance:
    """One document to compare, and where it came from."""

    schema_name: str
    document: Any
    origin: str


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a tool with the interpreter that runs the tests."""
    return subprocess.run(
        [sys.executable, *command],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )


def repository_instances() -> list[Instance]:
    """The instances the repository itself produces."""
    instances: list[Instance] = []

    registry = _run(["tools/registry/generate.py", "protocol-28", "--stdout"])
    if registry.returncode != 0:
        raise AssertionError(f"the registry generator failed: {registry.stderr}")
    instances.append(
        Instance(
            "registry-v1",
            json.loads(registry.stdout),
            "tools/registry/generate.py protocol-28 --stdout",
        )
    )

    with tempfile.TemporaryDirectory(prefix="canary-differential-") as directory:
        root = Path(directory)
        archive_dir = root / "dist"
        packed = _run(
            [
                "tools/pack/pack.py",
                "protocol-28",
                "--version",
                "1.0.0",
                "--output-dir",
                str(archive_dir),
            ]
        )
        if packed.returncode != 0:
            raise AssertionError(f"the packer failed: {packed.stderr}")
        archive = archive_dir / "protocolcanary-fixtures-1.0.0.tar.gz"
        manifest_path = root / "manifest.json"
        manifested = _run(
            [
                "tools/release/manifest.py",
                str(archive),
                "--revision",
                REVISION,
                "--engine",
                "0.2.0",
                "--output",
                str(manifest_path),
            ]
        )
        if manifested.returncode != 0:
            raise AssertionError(f"the manifest generator failed: {manifested.stderr}")
        instances.append(
            Instance(
                "release-manifest-v1",
                json.loads(manifest_path.read_text(encoding="utf-8")),
                "tools/release/manifest.py over the protocol-28 archive",
            )
        )

    matrix = REPO_ROOT / "upstream-matrix.json"
    instances.append(
        Instance(
            "upstream-matrix",
            json.loads(matrix.read_text(encoding="utf-8")),
            "the checked-in upstream-matrix.json",
        )
    )

    return instances


# The hand-written edge cases. Each one names the keyword it exercises and
# the verdict both validators must return.
@dataclass(frozen=True)
class EdgeCase:
    """A targeted instance for one keyword."""

    schema_name: str
    document: Any
    description: str
    lite_valid: bool
    reference_valid: bool


EDGE_CASES: tuple[EdgeCase, ...] = (
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
        },
        "a well-formed registry is accepted by both",
        True,
        True,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.txt",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
        },
        "pattern: a path that does not end in .toml is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "not-a-hash",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
        },
        "pattern: a sha256 that is not 64 hex characters is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "sorboban",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
        },
        "enum: an unknown surface is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": -1,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
        },
        "minimum: a negative protocol is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
            "unexpected": True,
        },
        "additionalProperties: an unknown root property is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [],
            "packDigest": "sha256:" + "0" * 64,
        },
        "minItems: an empty fixtures array is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [],
                }
            ],
            "packDigest": "not-a-digest",
        },
        "pattern: a packDigest without the sha256: prefix is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "registry-v1",
        {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                {
                    "id": "p28-xdr-a",
                    "path": "xdr/a.toml",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "surface": "xdr",
                    "category": "cap-0083",
                    "description": "a fixture",
                    "payloads": [
                        {"path": "xdr/a.bin", "sha256": "0" * 64, "extra": 1}
                    ],
                }
            ],
            "packDigest": "sha256:" + "0" * 64,
        },
        "additionalProperties: an unknown payload property is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "simulation-resource-estimate",
        {"kind": "simulation-resource-estimate"},
        "a proposed expect block with only its kind is accepted by both",
        True,
        True,
    ),
    EdgeCase(
        "simulation-resource-estimate",
        {"kind": "simulation-resource-estimate", "min_resource_fee_at_least": 0},
        "minimum: a zero lower bound is refused by both",
        False,
        False,
    ),
    EdgeCase(
        "simulation-resource-estimate",
        {"kind": "something-else"},
        "const: another kind is refused by both",
        False,
        False,
    ),
)


# ---------------------------------------------------------------- mutations


def _replacements(value: Any) -> list[Any]:
    """The single-fault replacements tried for a node of value ``value``."""
    if isinstance(value, bool):
        return ["true", 0]
    if isinstance(value, int):
        return [float(value), str(value), -1]
    if isinstance(value, float):
        return [int(value) if value.is_integer() else value + 0.5]
    if isinstance(value, str):
        return ["", 0, None]
    if isinstance(value, list):
        return [[], {}]
    if isinstance(value, dict):
        return [{}, []]
    return [None]


@dataclass(frozen=True)
class EditSite:
    """One place in a document where a single fault can be injected."""

    kind: str
    path: tuple[Any, ...]
    key: Any


def _edit_sites(node: Any, path: tuple[Any, ...] = ()) -> list[EditSite]:
    sites: list[EditSite] = []
    if isinstance(node, dict):
        for key in sorted(node):
            child_path = path + (key,)
            sites.append(EditSite("drop-key", child_path, key))
            sites.append(EditSite("add-key", child_path, key))
            sites.extend(_edit_sites(node[key], child_path))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            child_path = path + (index,)
            sites.append(EditSite("replace", child_path, index))
            sites.extend(_edit_sites(child, child_path))
    else:
        sites.append(EditSite("replace", path, None))
    return sites


def _parent_at(document: Any, path: tuple[Any, ...]) -> Any:
    node = document
    for segment in path[:-1]:
        if isinstance(node, dict):
            node = node.get(segment)
        elif isinstance(node, list) and isinstance(segment, int):
            node = node[segment] if segment < len(node) else None
        else:
            return None
    return node


def _apply(document: Any, site: EditSite, replacement: Any) -> Any | None:
    """A copy of ``document`` with the one fault at ``site`` applied."""
    if not site.path:
        return None
    mutant = copy.deepcopy(document)
    parent = _parent_at(mutant, site.path[:-1])
    if parent is None:
        return None
    last = site.path[-1]
    try:
        if site.kind == "drop-key":
            if not isinstance(parent, dict) or last not in parent:
                return None
            del parent[last]
        elif site.kind == "add-key":
            if not isinstance(parent, dict):
                return None
            parent[f"unexpected{last}"] = 1
        else:
            if isinstance(parent, dict):
                if last not in parent:
                    return None
                parent[last] = replacement
            elif isinstance(parent, list) and isinstance(last, int):
                if last >= len(parent):
                    return None
                parent[last] = replacement
            else:
                return None
    except (KeyError, IndexError, TypeError):
        return None
    return mutant


def mutants(document: Any, seed: int, limit: int) -> list[tuple[str, Any]]:
    """Deterministic single-fault variants of ``document``."""
    sites = _edit_sites(document)
    generator = random.Random(seed)
    generator.shuffle(sites)
    produced: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for site in sites:
        if len(produced) >= limit:
            break
        if site.kind == "replace":
            original = node_at(document, _pointer(site.path))
            for replacement in _replacements(original):
                mutant = _apply(document, site, replacement)
                if mutant is None:
                    continue
                key = json.dumps(mutant, sort_keys=True, default=repr)
                if key in seen:
                    continue
                seen.add(key)
                produced.append((f"mutate {site.path!r} -> {replacement!r}", mutant))
                if len(produced) >= limit:
                    break
        else:
            mutant = _apply(document, site, None)
            if mutant is None:
                continue
            key = json.dumps(mutant, sort_keys=True, default=repr)
            if key in seen:
                continue
            seen.add(key)
            produced.append((f"mutate {site.kind} at {site.path!r}", mutant))
    return produced


# ---------------------------------------------------------------- tests


class DifferentialTestCase(unittest.TestCase):
    """Base class: skips the whole comparison when jsonschema is missing."""

    def setUp(self) -> None:
        if SKIP_REASON is not None:
            self.skipTest(SKIP_REASON)

    @staticmethod
    def load_schema(name: str) -> dict:
        return json.loads(IN_SCOPE_SCHEMAS[name].read_text(encoding="utf-8"))


class SkipBehaviourTests(unittest.TestCase):
    """The differential comparison is optional and says so when it is off."""

    def test_skip_reason_is_explicit(self) -> None:
        """The reason names the dependency and the way to install it."""
        if REFERENCE is None:
            self.assertIsNotNone(SKIP_REASON)
            self.assertIn("jsonschema", SKIP_REASON)
            self.assertIn("requirements-differential.txt", SKIP_REASON)
        else:
            self.assertIsNone(SKIP_REASON)

    def test_default_suite_needs_no_third_party_package(self) -> None:
        """No module the default suite imports may import a third-party package."""
        for name in ("tools/validate/jsonschema_lite.py",):
            source = (REPO_ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("import jsonschema", source)
        # The reference package is only imported inside load_reference(), and
        # only its absence is handled.
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("except ImportError", source)


class InScopeSchemaTests(unittest.TestCase):
    """The schemas designated in scope use only keywords lite implements."""

    def test_in_scope_schemas_use_only_supported_keywords(self) -> None:
        for name, path in IN_SCOPE_SCHEMAS.items():
            with self.subTest(schema=name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                used = schema_keywords(schema)
                unsupported = used - set(LITE.SUPPORTED_KEYWORDS) - set(
                    LITE.ANNOTATION_KEYWORDS
                )
                self.assertEqual(
                    unsupported,
                    set(),
                    f"{path.name} uses keywords jsonschema_lite does not implement: "
                    f"{sorted(unsupported)}",
                )

    def test_the_in_scope_list_is_complete(self) -> None:
        """Every schema in schemas/ is either in scope or uses an unsupported keyword."""
        declared = {path.name for path in IN_SCOPE_SCHEMAS.values()}
        for path in sorted((REPO_ROOT / "schemas").rglob("*.json")):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                used = schema_keywords(schema)
                unsupported = used - set(LITE.SUPPORTED_KEYWORDS) - set(
                    LITE.ANNOTATION_KEYWORDS
                )
                if unsupported:
                    self.assertNotIn(
                        path.name,
                        declared,
                        f"{path.name} is out of scope but listed as in scope",
                    )
                else:
                    self.assertIn(
                        path.name,
                        declared,
                        f"{path.name} uses only supported keywords and must be added "
                        "to IN_SCOPE_SCHEMAS so the comparison covers it",
                    )

    def test_out_of_scope_schemas_are_out_of_scope(self) -> None:
        """The schemas the lite validator refuses stay refused, on purpose."""
        for name in ("fixture-v1.schema.json", "verification-v1.schema.json"):
            with self.subTest(schema=name):
                path = REPO_ROOT / "schemas" / name
                schema = json.loads(path.read_text(encoding="utf-8"))
                with self.assertRaises(LITE.SchemaError):
                    LITE.validate({}, schema)


class RepositoryInstanceTests(DifferentialTestCase):
    """The documents the repository produces are validated the same way."""

    @classmethod
    def setUpClass(cls) -> None:
        if REFERENCE is None:
            return
        cls.instances = repository_instances()
        cls.schemas = {
            instance.schema_name: json.loads(
                IN_SCOPE_SCHEMAS[instance.schema_name].read_text(encoding="utf-8")
            )
            for instance in cls.instances
        }

    def test_repository_documents_are_accepted_by_both(self) -> None:
        """The registry, the manifest and the matrix are valid for both."""
        for instance in self.instances:
            with self.subTest(instance=instance.origin):
                schema = self.schemas[instance.schema_name]
                self.assertEqual(
                    LITE.validate(instance.document, schema),
                    [],
                    f"{instance.origin} does not satisfy {instance.schema_name}",
                )
                self.assertTrue(
                    reference_verdict(instance.document, schema).valid,
                    f"{instance.origin} is not valid for the reference implementation",
                )

    def test_mutants_are_compared(self) -> None:
        """Every single-fault mutant gets the same verdict from both."""
        unexplained: list[Mismatch] = []
        explained = 0
        compared = 0
        for instance in self.instances:
            schema = self.schemas[instance.schema_name]
            for origin, mutant in mutants(instance.document, SEED, MUTANTS_PER_INSTANCE):
                compared += 1
                for mismatch in compare(
                    LITE, instance.schema_name, schema, mutant, origin
                ):
                    if known_difference_for(mismatch) is None:
                        unexplained.append(mismatch)
                    else:
                        explained += 1
        self.assertGreater(compared, 0, "no mutant was compared")
        if unexplained:
            report = "\n\n".join(mismatch.describe() for mismatch in unexplained[:5])
            self.fail(
                f"{len(unexplained)} unexplained difference(s) between jsonschema_lite "
                f"and the reference implementation:\n\n{report}"
            )
        # The comparison is only meaningful if it actually reaches the
        # documented differences.
        self.assertGreater(
            explained,
            0,
            "no documented difference was reached; the mutants do not exercise the "
            "keywords where the two implementations differ",
        )


class EdgeCaseTests(DifferentialTestCase):
    """The hand-written edge cases give the same verdict in both."""

    def test_edge_cases_agree(self) -> None:
        schemas = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in IN_SCOPE_SCHEMAS.items()
        }
        for case in EDGE_CASES:
            with self.subTest(case=case.description):
                schema = schemas[case.schema_name]
                lite_result = lite_verdict(LITE, case.document, schema)
                reference_result = reference_verdict(case.document, schema)
                self.assertEqual(
                    lite_result.valid,
                    case.lite_valid,
                    f"jsonschema_lite disagreed with the expected verdict: {case.description}",
                )
                self.assertEqual(
                    reference_result.valid,
                    case.reference_valid,
                    f"the reference implementation disagreed with the expected "
                    f"verdict: {case.description}",
                )
                self.assertEqual(
                    lite_result.valid,
                    reference_result.valid,
                    f"the two implementations disagree: {case.description}",
                )


class KnownDifferenceTests(DifferentialTestCase):
    """The recorded differences are real, and they are the only ones."""

    def test_each_known_difference_is_reproducible(self) -> None:
        """Every entry in KNOWN_DIFFERENCES describes a difference that occurs."""
        seen: set[str] = set()
        for known in KNOWN_DIFFERENCES:
            with self.subTest(difference=known.identifier):
                schema, document, pointer = _reproduce(known)
                mismatch = Mismatch(
                    schema_name="probe",
                    schema=schema,
                    document=document,
                    pointer=pointer,
                    lite=lite_verdict(LITE, document, schema),
                    reference=reference_verdict(document, schema),
                    origin=f"known difference {known.identifier}",
                )
                self.assertFalse(mismatch.lite.valid == mismatch.reference.valid)
                self.assertEqual(
                    known_difference_for(mismatch),
                    known,
                    f"the recorded difference {known.identifier} does not describe "
                    "what the two implementations do",
                )
                seen.add(known.identifier)
        self.assertEqual(
            seen,
            {known.identifier for known in KNOWN_DIFFERENCES},
            "a known difference was not exercised",
        )

    def test_no_documented_difference_is_stale(self) -> None:
        """A recorded difference that no longer occurs must be removed."""
        for known in KNOWN_DIFFERENCES:
            with self.subTest(difference=known.identifier):
                schema, document, pointer = _reproduce(known)
                lite_result = lite_verdict(LITE, document, schema)
                reference_result = reference_verdict(document, schema)
                self.assertEqual(lite_result.valid, known.lite_valid)
                self.assertEqual(reference_result.valid, known.reference_valid)


def _reproduce(known: KnownDifference) -> tuple[dict, Any, str]:
    """A tiny instance that shows ``known`` happening."""
    if known.identifier == "integer-is-a-number":
        return {"type": "integer"}, 1.0, "/"
    if known.identifier == "const-is-compared-by-value":
        return {"const": 1}, 1.0, "/"
    if known.identifier == "enum-separates-true-from-one":
        return {"enum": [1]}, True, "/"
    if known.identifier == "unique-items-separates-true-from-one":
        return {"uniqueItems": True}, [True, 1], "/"
    raise AssertionError(f"no reproduction is defined for {known.identifier}")


class InjectedBugTests(DifferentialTestCase):
    """A deliberately broken validator is caught, using a scratch copy."""

    BUG = (
        'if "minLength" in schema and len(value) < schema["minLength"]:',
        'if "minLength" in schema and len(value) < 0:',
    )

    def _scratch_validator(self, directory: Path, *, inject: bool) -> Any:
        source = (REPO_ROOT / LITE_RELATIVE).read_text(encoding="utf-8")
        if inject:
            self.assertIn(self.BUG[0], source, "the injected bug no longer applies")
            source = source.replace(self.BUG[0], self.BUG[1], 1)
        target = directory / "jsonschema_lite_buggy.py"
        target.write_text(source, encoding="utf-8")
        return load_lite(target, name="canary_jsonschema_lite_buggy")

    def _unexplained(self, lite, instances, schemas) -> list[Mismatch]:
        found: list[Mismatch] = []
        for instance in instances:
            schema = schemas[instance.schema_name]
            for origin, mutant in mutants(instance.document, SEED, MUTANTS_PER_INSTANCE):
                for mismatch in compare(lite, instance.schema_name, schema, mutant, origin):
                    if known_difference_for(mismatch) is None:
                        found.append(mismatch)
        return found

    def test_injected_bug_is_caught(self) -> None:
        """The scratch copy with a broken minLength check is reported."""
        instances = repository_instances()
        schemas = {
            instance.schema_name: json.loads(
                IN_SCOPE_SCHEMAS[instance.schema_name].read_text(encoding="utf-8")
            )
            for instance in instances
        }
        with tempfile.TemporaryDirectory(prefix="canary-differential-bug-") as directory:
            buggy = self._scratch_validator(Path(directory), inject=True)
            found = self._unexplained(buggy, instances, schemas)
        self.assertTrue(
            found,
            "the injected bug was not detected: the comparison found no difference",
        )
        # The difference must be the injected one, not something else.
        min_length = [
            mismatch
            for mismatch in found
            if "minLength" in governing_subschema(mismatch.schema, mismatch.pointer)
        ]
        self.assertTrue(
            min_length,
            "the injected bug was detected, but not at a minLength keyword: "
            + "\n\n".join(mismatch.describe() for mismatch in found[:3]),
        )

    def test_the_production_validator_is_not_the_buggy_one(self) -> None:
        """The scratch copy is a copy: the production file is untouched."""
        source = (REPO_ROOT / LITE_RELATIVE).read_text(encoding="utf-8")
        self.assertIn(self.BUG[0], source)
        self.assertNotIn(self.BUG[1], source)


class DifferentialInfrastructureTests(unittest.TestCase):
    """The opt-in workflow and its pinned dependencies are in place."""

    def test_requirements_file_pins_every_dependency_with_hashes(self) -> None:
        path = REPO_ROOT / "requirements-differential.txt"
        self.assertTrue(path.is_file(), "requirements-differential.txt is missing")
        text = path.read_text(encoding="utf-8")
        requirements = [
            line
            for line in text.splitlines()
            if line and not line.startswith("#") and not line.startswith(" ")
        ]
        self.assertTrue(requirements, "requirements-differential.txt pins nothing")
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                # A requirement may end with a line continuation.
                pin = requirement.rstrip("\\").strip()
                self.assertRegex(pin, r"^[A-Za-z0-9._-]+==[0-9][A-Za-z0-9._-]*$")
                self.assertIn("--hash=sha256:", text)

    def test_workflow_only_runs_on_demand_and_on_a_schedule(self) -> None:
        path = REPO_ROOT / ".github" / "workflows" / "schema-differential.yml"
        self.assertTrue(path.is_file(), "the differential workflow is missing")
        text = path.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("schedule:", text)
        self.assertNotIn("pull_request:", text)
        self.assertNotIn("push:", text)
        self.assertIn("contents: read", text)
        for line in text.splitlines():
            if "uses:" in line:
                with self.subTest(line=line.strip()):
                    self.assertRegex(
                        line.strip(),
                        r"uses:\s+[\w.-]+/[\w.-]+@[0-9a-f]{40}",
                        "every action must be pinned to a commit SHA",
                    )


if __name__ == "__main__":
    unittest.main()
