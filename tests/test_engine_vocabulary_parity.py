"""Parity between the engine's accepted vocabulary and this repository's.

Issue #364: the Python validator kept its own copies of the vocabulary the
engine accepts, and the two drifted apart. A fixture the validator accepted
but the engine rejected (or the other way round) was only discovered when a
run failed, far from the change that caused it.

``tests/fixtures/engine-vocabulary.json`` is the shared vector: the exact
sets of names ``Protocol-Canary``'s parsers accept, read from the engine's
own source at one pinned commit. This test compares each list with the
validator's constant and with the schema's enum, and prints the differences
by name, so drift is a failing test with an obvious remedy.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
SCHEMA_PATH = REPO_ROOT / "schemas" / "fixture-v1.schema.json"
VECTOR_PATH = REPO_ROOT / "tests" / "fixtures" / "engine-vocabulary.json"
TOOLS_DIR = REPO_ROOT / "tools"

_spec = importlib.util.spec_from_file_location("validate_engine_vocabulary", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_engine_vocabulary"] = validate
_spec.loader.exec_module(validate)

# A full commit SHA: 40 lowercase hexadecimal characters. Anything shorter,
# longer or not hexadecimal is a branch name, a tag or a typo, not the commit
# the lists were read from.
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Each vocabulary: the vector's key, the validator constant that holds the
# same set, and where the schema declares the same enum.
#   (vector key, validator constant, schema surface, path inside the surface)
VOCABULARIES = (
    ("xdrTypes", "XDR_TYPES", "xdr", ("properties", "type")),
    ("xdrKinds", "XDR_KINDS", "xdr", ("properties", "kind")),
    ("rpcMethods", "RPC_METHODS", "rpc", ("properties", "method")),
    (
        "rpcAssertKinds",
        "RPC_ASSERT_KINDS",
        "rpc",
        ("properties", "assert", "items", "properties", "kind"),
    ),
    (
        "sorobanExpectKinds",
        "SOROBAN_EXPECT_KINDS",
        "soroban",
        ("properties", "expect", "properties", "kind"),
    ),
)

# The surfaces are not per-surface: the schema declares them once, at the top
# level, and the validator holds them in SURFACES.
SURFACES_VECTOR_KEY = "surfaces"
SURFACES_CONSTANT = "SURFACES"


class VectorError(ValueError):
    """The engine-vocabulary vector is not usable as written."""


def surface_block(schema: dict, surface: str) -> dict:
    """The schema's `then` block for `surface`, or an empty dict."""
    for block in schema.get("allOf", []):
        condition = block.get("if", {}).get("properties", {}).get("surface", {})
        if condition.get("const") == surface:
            return block.get("then", {})
    return {}


def schema_enum(schema: dict, vocabulary: str) -> list:
    """The names the schema's enum for `vocabulary` allows."""
    if vocabulary == SURFACES_VECTOR_KEY:
        node = schema.get("properties", {}).get("surface", {})
        return list(node.get("enum", []))
    for key, _constant, surface, path in VOCABULARIES:
        if key != vocabulary:
            continue
        node: object = surface_block(schema, surface)
        for step in path:
            if not isinstance(node, dict):
                return []
            node = node.get(step, {})
        if not isinstance(node, dict):
            return []
        return list(node.get("enum", []))
    return []


def load_vector(path: Path) -> dict:
    """Load the engine-vocabulary vector and check that it is well formed.

    Raises VectorError naming the problem when the file cannot be used: a
    missing key, an `engineCommit` that is not a full commit SHA, a name that
    the vector claims the engine accepts but also lists as a name the
    contract documents describe without the parser accepting it.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VectorError(f"{path}: cannot read the vector: {exc}") from exc
    if not isinstance(raw, dict):
        raise VectorError(f"{path}: the vector must be a JSON object")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise VectorError(f"{path}: 'description' must be a non-empty string")
    commit = raw.get("engineCommit")
    if not isinstance(commit, str) or not SHA_RE.match(commit):
        raise VectorError(
            f"{path}: 'engineCommit' must be a 40-character lowercase SHA, "
            f"got {commit!r}"
        )
    repository = raw.get("engineRepository")
    if not isinstance(repository, str) or not repository.strip():
        raise VectorError(f"{path}: 'engineRepository' must be a non-empty string")

    for key, _constant, _surface, _path in VOCABULARIES:
        names = raw.get(key)
        if not isinstance(names, list) or not names:
            raise VectorError(f"{path}: '{key}' must be a non-empty array")
        if not all(isinstance(name, str) and name for name in names):
            raise VectorError(f"{path}: '{key}' must hold only non-empty strings")
        if len(set(names)) != len(names):
            raise VectorError(f"{path}: '{key}' repeats a name")
        source = raw.get(f"{key}Source")
        if not isinstance(source, dict):
            raise VectorError(
                f"{path}: '{key}Source' must be an object naming the engine source file"
            )
        source_file = source.get("file")
        if not isinstance(source_file, str) or not source_file.endswith(".rs"):
            raise VectorError(
                f"{path}: '{key}Source.file' must name the engine's source file"
            )
        symbol = source.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise VectorError(
                f"{path}: '{key}Source.symbol' must name where the list is parsed"
            )

    surfaces = raw.get(SURFACES_VECTOR_KEY)
    if not isinstance(surfaces, list) or not surfaces:
        raise VectorError(f"{path}: '{SURFACES_VECTOR_KEY}' must be a non-empty array")
    if not all(isinstance(name, str) and name for name in surfaces):
        raise VectorError(
            f"{path}: '{SURFACES_VECTOR_KEY}' must hold only non-empty strings"
        )
    if len(set(surfaces)) != len(surfaces):
        raise VectorError(f"{path}: '{SURFACES_VECTOR_KEY}' repeats a name")
    surfaces_source = raw.get(f"{SURFACES_VECTOR_KEY}Source")
    if not isinstance(surfaces_source, dict) or not isinstance(
        surfaces_source.get("file"), str
    ):
        raise VectorError(
            f"{path}: '{SURFACES_VECTOR_KEY}Source' must name the engine source file"
        )

    contract_only = raw.get("contractOnlyNotImplemented", [])
    if not isinstance(contract_only, list) or not all(
        isinstance(name, str) and name for name in contract_only
    ):
        raise VectorError(
            f"{path}: 'contractOnlyNotImplemented' must be an array of names"
        )
    accepted = accepted_names(raw)
    for name in contract_only:
        for vocabulary, names in accepted.items():
            if name in names:
                raise VectorError(
                    f"{path}: {name!r} is listed in contractOnlyNotImplemented "
                    f"but is also listed as an accepted {vocabulary} name"
                )

    engine_only = raw.get("engineOnlyNotYetAccepted", {})
    if not isinstance(engine_only, dict):
        raise VectorError(
            f"{path}: 'engineOnlyNotYetAccepted' must be an object when present"
        )
    for key, value in engine_only.items():
        if key in ("engineCommit", "note"):
            continue
        if not isinstance(value, list) or not all(
            isinstance(name, str) and name for name in value
        ):
            raise VectorError(
                f"{path}: 'engineOnlyNotYetAccepted.{key}' must be an array of names"
            )
        for name in value:
            for vocabulary, names in accepted.items():
                if name in names:
                    raise VectorError(
                        f"{path}: {name!r} is listed in engineOnlyNotYetAccepted "
                        f"but is also listed as an accepted {vocabulary} name"
                    )
    return raw


def accepted_names(vector: dict) -> dict[str, list]:
    """The vector's accepted names, keyed by vocabulary."""
    names = {key: list(vector[key]) for key, _c, _s, _p in VOCABULARIES}
    names[SURFACES_VECTOR_KEY] = list(vector[SURFACES_VECTOR_KEY])
    return names


def differences(expected, actual) -> list[str]:
    """The names two sets disagree about, missing first, then unexpected."""
    expected_set, actual_set = set(expected), set(actual)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    out = []
    if missing:
        out.append("missing: " + ", ".join(missing))
    if extra:
        out.append("unexpected: " + ", ".join(extra))
    return out


def validator_differences(vector: dict, validator_module) -> dict[str, list[str]]:
    """Per-vocabulary differences between the vector and a validator module."""
    out: dict[str, list[str]] = {}
    for key, constant, _surface, _path in VOCABULARIES:
        out[key] = differences(vector[key], getattr(validator_module, constant))
    out[SURFACES_VECTOR_KEY] = differences(
        vector[SURFACES_VECTOR_KEY], getattr(validator_module, SURFACES_CONSTANT)
    )
    return out


class VectorShapeTests(unittest.TestCase):
    """The vector itself: shape, provenance and what it may not claim."""

    def setUp(self) -> None:
        self.vector = load_vector(VECTOR_PATH)

    def test_the_shipped_vector_is_well_formed(self) -> None:
        # load_vector raises VectorError naming the problem, so reaching
        # this point without an exception is the assertion.
        self.assertEqual(self.vector["engineCommit"], "cf4d7e7a5338b1513694711796236a04a0f312b2")

    def test_engine_commit_is_a_full_commit_sha(self) -> None:
        commit = self.vector["engineCommit"]
        self.assertRegex(commit, SHA_RE)
        self.assertEqual(len(commit), 40)

    def test_every_vocabulary_names_the_engine_source_it_was_read_from(self) -> None:
        for key in list(accepted_names(self.vector)):
            with self.subTest(vocabulary=key):
                source = self.vector[f"{key}Source"]
                self.assertTrue(source["file"].endswith(".rs"))
                self.assertTrue(source["file"].startswith("crates/"))
                self.assertTrue(source["symbol"].strip())

    def test_contract_only_names_are_not_accepted(self) -> None:
        # field-range is the stale contract spelling; the parser accepts the
        # engine spelling field-number-range instead. It must not appear as an
        # accepted name.
        accepted = accepted_names(self.vector)
        for name in self.vector.get("contractOnlyNotImplemented", []):
            for vocabulary, names in accepted.items():
                with self.subTest(name=name, vocabulary=vocabulary):
                    self.assertNotIn(name, names)

    def test_engine_only_names_are_not_claimed_as_accepted(self) -> None:
        engine_only = self.vector.get("engineOnlyNotYetAccepted", {})
        accepted = accepted_names(self.vector)
        for key, value in engine_only.items():
            if key in ("engineCommit", "note"):
                continue
            for name in value:
                for vocabulary, names in accepted.items():
                    with self.subTest(name=name, vocabulary=vocabulary):
                        self.assertNotIn(name, names)

    def test_engine_only_names_are_really_absent_from_the_validator(self) -> None:
        # The gap the vector documents is real: the validator does not
        # accept the names the engine's later commit added. If this fails,
        # the validator caught up and the vector's pin has to be moved.
        engine_only = self.vector.get("engineOnlyNotYetAccepted", {})
        for key, value in engine_only.items():
            if key in ("engineCommit", "note"):
                continue
            for vocabulary, _constant, _surface, _path in VOCABULARIES:
                if key != vocabulary:
                    continue
                with self.subTest(name=key):
                    for name in value:
                        self.assertNotIn(name, getattr(validate, _constant))


class ParityTests(unittest.TestCase):
    """The vector, the validator and the schema must agree."""

    def setUp(self) -> None:
        self.vector = load_vector(VECTOR_PATH)
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_validator_constants_match_the_vector(self) -> None:
        for key, difference in validator_differences(self.vector, validate).items():
            with self.subTest(vocabulary=key):
                self.assertEqual(
                    difference,
                    [],
                    f"{key}: tools/validate/validate.py and the engine-vocabulary "
                    f"vector disagree ({'; '.join(difference)})",
                )

    def test_schema_enums_match_the_vector(self) -> None:
        for key in accepted_names(self.vector):
            with self.subTest(vocabulary=key):
                difference = differences(self.vector[key], schema_enum(self.schema, key))
                self.assertEqual(
                    difference,
                    [],
                    f"{key}: schemas/fixture-v1.schema.json and the "
                    f"engine-vocabulary vector disagree ({'; '.join(difference)})",
                )

    def test_the_vector_and_the_validator_agree_name_for_name(self) -> None:
        # The same check, spelled out, so a failure names the vocabulary and
        # the offending names rather than only the count.
        for key, _constant, _surface, _path in VOCABULARIES:
            with self.subTest(vocabulary=key):
                vector_names = set(self.vector[key])
                validator_names = set(getattr(validate, _constant))
                self.assertEqual(
                    vector_names - validator_names,
                    set(),
                    f"{key}: the validator is missing {sorted(vector_names - validator_names)}",
                )
                self.assertEqual(
                    validator_names - vector_names,
                    set(),
                    f"{key}: the validator accepts {sorted(validator_names - vector_names)}, "
                    f"which the engine's parser does not",
                )


class DriftIsDetectedTests(unittest.TestCase):
    """Negative cases: the parity check must fail when the sides drift."""

    def setUp(self) -> None:
        self.vector = load_vector(VECTOR_PATH)

    def test_a_validator_name_the_engine_does_not_accept_is_reported(self) -> None:
        accepted = set(self.vector["rpcMethods"])
        drifted = accepted | {"get-balance"}
        difference = differences(accepted, drifted)
        self.assertEqual(len(difference), 1)
        self.assertIn("get-balance", difference[0])
        self.assertIn("unexpected", difference[0])

    def test_a_schema_enum_missing_a_name_is_reported(self) -> None:
        accepted = set(self.vector["rpcMethods"])
        drifted = accepted - {"get-health"}
        difference = differences(accepted, drifted)
        self.assertEqual(len(difference), 1)
        self.assertIn("get-health", difference[0])
        self.assertIn("missing", difference[0])

    def test_a_vector_with_a_non_sha_commit_is_rejected(self) -> None:
        broken = dict(self.vector)
        broken["engineCommit"] = "94d7c79"  # a short SHA, not a full commit
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "engine-vocabulary.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(VectorError) as caught:
                load_vector(path)
        self.assertIn("engineCommit", str(caught.exception))

    def test_a_vector_claiming_a_contract_only_name_is_rejected(self) -> None:
        broken = json.loads(json.dumps(self.vector))
        broken["rpcAssertKinds"] = sorted(set(broken["rpcAssertKinds"]) | {"field-range"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "engine-vocabulary.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(VectorError) as caught:
                load_vector(path)
        self.assertIn("field-range", str(caught.exception))

    def test_a_validator_copy_without_a_constant_fails_the_parity_check(self) -> None:
        # The scratch copy of the validator is what an edit that forgets the
        # engine-vocabulary vector looks like: the constant loses a name
        # and the parity check has to say so, by name.
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "tools"
            shutil.copytree(TOOLS_DIR, scratch)
            validator_copy = scratch / "validate" / "validate.py"
            text = validator_copy.read_text(encoding="utf-8")
            self.assertIn('    "get-health",\n', text)
            validator_copy.write_text(
                text.replace('    "get-health",\n', ""), encoding="utf-8"
            )
            spec = importlib.util.spec_from_file_location(
                "validate_scratch_copy", validator_copy
            )
            assert spec is not None and spec.loader is not None
            scratch_validator = importlib.util.module_from_spec(spec)
            sys.modules["validate_scratch_copy"] = scratch_validator
            spec.loader.exec_module(scratch_validator)
            difference = validator_differences(self.vector, scratch_validator)
        self.assertNotEqual(difference["rpcMethods"], [])
        self.assertIn("get-health", "; ".join(difference["rpcMethods"]))
        self.assertIn("missing", "; ".join(difference["rpcMethods"]))


if __name__ == "__main__":
    unittest.main()
