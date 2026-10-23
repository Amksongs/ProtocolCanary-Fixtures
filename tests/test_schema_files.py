"""Meta-tests for the JSON Schema files under ``schemas/`` (issue #350).

Nothing in the repository checks the schema files themselves. A schema can
parse, validate every fixture it is given and still be unusable as a schema:
it can declare no ``$id``, reuse another schema's ``$id``, point a ``$ref``
at a JSON pointer that does not exist, or use a keyword that the validator
silently ignores -- so the schema looks like it constrains something while it
constrains nothing.

These tests check the schema files as files:

* every ``*.json`` under ``schemas/`` (including ``schemas/proposed/``)
  parses, is a JSON object, declares a non-empty ``title`` and a ``$id`` that
  no other schema under ``schemas/`` reuses;
* a top-level schema declares ``$schema``
  ``https://json-schema.org/draft/2020-12/schema``; a file under
  ``schemas/proposed/`` is a proposal and may declare another draft, but it
  must declare some draft;
* every local ``$ref`` (one that starts with ``#``) resolves to a JSON
  pointer inside the same file;
* every keyword a schema uses is implemented by
  ``tools/validate/jsonschema_lite.py`` -- but only for the schemas that
  validator is actually used with. The other two schemas use ``allOf``,
  ``if``/``then`` and ``format``, which the validator does not implement, so
  they are validated by other means; they are listed as such below rather
  than skipped silently.

Every failure names the file and the rule that was broken.

Run with: python3 -m unittest tests/test_schema_files.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "schemas"

_spec = importlib.util.spec_from_file_location(
    "jsonschema_lite_schema_files", REPO_ROOT / "tools" / "validate" / "jsonschema_lite.py"
)
lite = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["jsonschema_lite_schema_files"] = lite
_spec.loader.exec_module(lite)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

# The schemas that tools/validate/jsonschema_lite.py is used with, and the
# module that loads each one. This list is not a guess: the test below
# re-derives it from the repository (every module under tools/ and tests/ that
# loads jsonschema_lite and refers to a schema file) and fails when the two
# disagree, so a schema that starts being validated cannot slip past.
JAVASCRIPT_LITE_SCOPE = {
    # tools/registry/generate.py loads the registry schema and validates the
    # registry it writes against it.
    "registry-v1.schema.json": "tools/registry/generate.py",
    # tests/test_release_manifest.py loads the release-manifest schema and
    # validates every manifest it writes against it.
    "release-manifest-v1.schema.json": "tests/test_release_manifest.py",
    # tests/test_matrix.py loads the matrix schema and validates
    # upstream-matrix.json against it.
    "upstream-matrix.json": "tests/test_matrix.py",
    # tests/test_sim_resource_fixtures.py loads the proposed simulation
    # schema and validates every proposed [expect] block against it.
    "proposed/simulation-resource-estimate.expect.json": (
        "tests/test_sim_resource_fixtures.py"
    ),
    # tests/test_run_record_schema.py validates every run record against the
    # run-record schema with jsonschema_lite, so the reader and the schema
    # stay pinned together (issue #367).
    "run-record-v1.schema.json": "tests/test_run_record_schema.py",
}

# The schemas jsonschema_lite is never used with as-is, and what validates
# them instead. They are listed here so that "not covered by the keyword
# rule" is a decision the test states, not a silent skip.
VALIDATED_BY_OTHER_MEANS = {
    # tools/validate/schema_sync.py compares the schema's declared enums and
    # required-field lists with the constants in tools/validate/validate.py.
    # The schema uses allOf/if/then, which jsonschema_lite does not
    # implement, so it cannot validate the schema itself.
    "fixture-v1.schema.json": "tools/validate/schema_sync.py",
    # The verification-record rules are checked by the verification-record
    # validator in tools/validate/validate.py and by
    # tests/test_verification_schema.py. The schema uses allOf/if/then and
    # format, which jsonschema_lite does not implement.
    "verification-v1.schema.json": "tools/validate/validate.py",
}

# Keywords whose value is a single subschema.
_SUBSCHEMA_KEYWORDS = (
    "additionalItems",
    "additionalProperties",
    "contains",
    "contentSchema",
    "else",
    "if",
    "not",
    "propertyNames",
    "then",
)
# Keywords whose value is a mapping of name -> subschema.
_SUBSCHEMA_MAP_KEYWORDS = (
    "$defs",
    "definitions",
    "dependentSchemas",
    "patternProperties",
    "properties",
)
# Keywords whose value is a list of subschemas.
_SUBSCHEMA_LIST_KEYWORDS = ("allOf", "anyOf", "oneOf", "prefixItems")


def schema_files() -> list[Path]:
    """Every JSON file under schemas/, proposed/ included, in a stable order."""
    return sorted(SCHEMA_ROOT.rglob("*.json"))


def relative_name(path: Path) -> str:
    """The name of a schema file relative to schemas/, e.g. 'proposed/x.json'."""
    return path.relative_to(SCHEMA_ROOT).as_posix()


def load_schema(path: Path) -> dict:
    """Parse a schema file; a parse error is reported as a rule failure."""
    return json.loads(path.read_text(encoding="utf-8"))


def schema_positions(schema: object, pointer: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], dict]]:
    """Every subschema in `schema`, with the JSON pointer that reaches it.

    A subschema is a dictionary that stands in the place of a schema. The
    keys of "properties", "$defs" and friends are names, not keywords, so
    they are walked into rather than reported as keywords.
    """
    found: list[tuple[tuple[str, ...], dict]] = []
    if isinstance(schema, bool):
        return found
    if not isinstance(schema, dict):
        return found
    found.append((pointer, schema))
    for keyword, value in schema.items():
        if keyword in _SUBSCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for name, subschema in value.items():
                found.extend(schema_positions(subschema, pointer + (keyword, str(name))))
        elif keyword in _SUBSCHEMA_LIST_KEYWORDS and isinstance(value, list):
            for index, subschema in enumerate(value):
                found.extend(schema_positions(subschema, pointer + (keyword, str(index))))
        elif keyword == "items":
            if isinstance(value, list):
                for index, subschema in enumerate(value):
                    found.extend(schema_positions(subschema, pointer + (keyword, str(index))))
            else:
                found.extend(schema_positions(value, pointer + (keyword,)))
        elif keyword in _SUBSCHEMA_KEYWORDS:
            found.extend(schema_positions(value, pointer + (keyword,)))
    return found


def used_keywords(schema: object) -> set[str]:
    """Every keyword the schema uses, annotations included."""
    keywords: set[str] = set()
    for _, subschema in schema_positions(schema):
        keywords.update(subschema)
    return keywords


def local_refs(schema: object) -> list[tuple[str, object]]:
    """Every '$ref' in the schema, with the JSON pointer of the subschema."""
    refs: list[tuple[str, object]] = []
    for pointer, subschema in schema_positions(schema):
        if "$ref" in subschema:
            refs.append(("/" + "/".join(pointer) if pointer else "/", subschema["$ref"]))
    return refs


def resolve_pointer(document: object, pointer: str) -> tuple[bool, object]:
    """Resolve a local JSON pointer; returns (found, value)."""
    if not pointer.startswith("#"):
        return False, None
    node = document
    for raw in pointer[1:].split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return False, None
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return False, None
            node = node[int(token)]
        else:
            return False, None
    return True, node


def check_document(name: str, document: object, *, proposed: bool) -> list[str]:
    """The rules that apply to every schema file, whatever else validates it."""
    problems: list[str] = []
    if not isinstance(document, dict):
        return [f"{name}: rule 'object': a schema must be a JSON object"]

    title = document.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append(f"{name}: rule 'title': a schema must declare a non-empty title")

    identifier = document.get("$id")
    if not isinstance(identifier, str) or not identifier.strip():
        problems.append(f"{name}: rule '$id': a schema must declare a non-empty $id")

    declared = document.get("$schema")
    if not isinstance(declared, str) or not declared.strip():
        problems.append(f"{name}: rule '$schema': a schema must declare a $schema")
    elif not proposed and declared != DRAFT_2020_12:
        problems.append(
            f"{name}: rule '$schema': a top-level schema must declare "
            f"$schema {DRAFT_2020_12!r}, got {declared!r}"
        )
    return problems


def check_unique_ids(documents: list[tuple[str, object]]) -> list[str]:
    """No two schemas under schemas/ may declare the same $id."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for name, document in documents:
        if not isinstance(document, dict):
            continue
        identifier = document.get("$id")
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        if identifier in seen:
            problems.append(
                f"{name}: rule '$id': $id {identifier!r} is already used by {seen[identifier]}"
            )
        else:
            seen[identifier] = name
    return problems


def check_refs(name: str, document: object) -> list[str]:
    """Every local $ref must resolve to a JSON pointer inside the same file."""
    problems: list[str] = []
    for pointer, ref in local_refs(document):
        if not isinstance(ref, str):
            problems.append(f"{name}: rule '$ref': the $ref at {pointer} must be a string")
            continue
        if not ref.startswith("#"):
            # A reference to another document is out of scope for this rule.
            continue
        found, _ = resolve_pointer(document, ref)
        if not found:
            problems.append(
                f"{name}: rule '$ref': $ref {ref!r} does not resolve to a JSON "
                "pointer inside this file"
            )
    return problems


def check_keywords(name: str, document: object) -> list[str]:
    """Every keyword used must be one jsonschema_lite implements."""
    allowed = lite.SUPPORTED_KEYWORDS | lite.ANNOTATION_KEYWORDS
    problems: list[str] = []
    for keyword in sorted(used_keywords(document)):
        if keyword not in allowed:
            problems.append(
                f"{name}: rule 'keywords': keyword {keyword!r} is not implemented "
                "by tools/validate/jsonschema_lite.py"
            )
    return problems


def python_sources() -> list[Path]:
    """Every Python module under tools/ and tests/."""
    sources: list[Path] = []
    for root in (REPO_ROOT / "tools", REPO_ROOT / "tests"):
        sources.extend(sorted(root.rglob("*.py")))
    return sources


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def modules_using_jsonschema_lite() -> list[Path]:
    """The modules that load tools/validate/jsonschema_lite.py.

    This file is excluded: it names the schemas itself, so counting it would
    make the derived scope agree with the declared one no matter what the
    repository does.
    """
    this_file = Path(__file__).resolve()
    return [
        path
        for path in python_sources()
        if "jsonschema_lite" in read_text(path) and path.resolve() != this_file
    ]


def derived_scope() -> dict[str, list[str]]:
    """The schemas jsonschema_lite is used with, derived from the repository.

    A schema belongs to the scope when a module that loads
    tools/validate/jsonschema_lite.py refers to that schema file by name.
    """
    scope: dict[str, list[str]] = {}
    for module in modules_using_jsonschema_lite():
        text = read_text(module)
        for schema in schema_files():
            if schema.name not in text:
                continue
            scope.setdefault(relative_name(schema), []).append(
                str(module.relative_to(REPO_ROOT)).replace("\\", "/")
            )
    return scope


class SchemaFileTests(unittest.TestCase):
    """The schemas under schemas/ must be well-formed schemas."""

    def setUp(self) -> None:
        self.files = schema_files()
        self.documents = [
            (relative_name(path), load_schema(path)) for path in self.files
        ]

    def test_every_schema_file_parses(self) -> None:
        self.assertTrue(self.files, "schemas/ contains no JSON schema file")
        for path in self.files:
            with self.subTest(schema=relative_name(path)):
                try:
                    document = load_schema(path)
                except json.JSONDecodeError as error:
                    self.fail(
                        f"{relative_name(path)}: rule 'json': the file is not valid "
                        f"JSON (line {error.lineno}, column {error.colno})"
                    )
                self.assertIsInstance(document, dict)

    def test_every_schema_declares_a_title_an_id_and_a_draft(self) -> None:
        for name, document in self.documents:
            with self.subTest(schema=name):
                proposed = name.startswith("proposed/")
                self.assertEqual(check_document(name, document, proposed=proposed), [])

    def test_no_two_schemas_share_an_id(self) -> None:
        self.assertEqual(check_unique_ids(self.documents), [])

    def test_every_local_ref_resolves(self) -> None:
        for name, document in self.documents:
            with self.subTest(schema=name):
                self.assertEqual(check_refs(name, document), [])

    def test_the_schemas_jsonschema_lite_validates_use_only_supported_keywords(self) -> None:
        for name, document in self.documents:
            if name not in JAVASCRIPT_LITE_SCOPE:
                continue
            with self.subTest(schema=name):
                self.assertEqual(check_keywords(name, document), [])


class ScopeTests(unittest.TestCase):
    """The keyword rule must cover the right schemas, and say so."""

    def test_every_schema_is_either_in_scope_or_validated_by_other_means(self) -> None:
        names = {relative_name(path) for path in schema_files()}
        declared = set(JAVASCRIPT_LITE_SCOPE) | set(VALIDATED_BY_OTHER_MEANS)
        self.assertEqual(
            names - declared,
            set(),
            "every schema must be listed, either as validated with "
            "jsonschema_lite or as validated by other means",
        )
        self.assertEqual(
            declared - names,
            set(),
            "the scope lists name a schema that does not exist",
        )
        self.assertEqual(
            set(JAVASCRIPT_LITE_SCOPE) & set(VALIDATED_BY_OTHER_MEANS),
            set(),
            "a schema cannot be both in scope and validated by other means",
        )

    def test_the_scope_is_the_one_the_repository_uses(self) -> None:
        derived = derived_scope()
        self.assertEqual(
            sorted(derived),
            sorted(set(JAVASCRIPT_LITE_SCOPE) | set(VALIDATED_BY_OTHER_MEANS)),
            "the schemas loaded with jsonschema_lite have changed; update "
            "JAVASCRIPT_LITE_SCOPE and VALIDATED_BY_OTHER_MEANS",
        )

    def test_each_in_scope_schema_is_loaded_by_the_module_named(self) -> None:
        derived = derived_scope()
        for name, module in JAVASCRIPT_LITE_SCOPE.items():
            with self.subTest(schema=name):
                path = REPO_ROOT / module
                self.assertTrue(path.is_file(), f"{module} does not exist")
                self.assertIn(name.rsplit("/", 1)[-1], read_text(path))
                self.assertIn(
                    module,
                    derived.get(name, []),
                    f"{module} does not load {name} with jsonschema_lite",
                )

    def test_the_schemas_validated_by_other_means_say_why(self) -> None:
        for name, module in VALIDATED_BY_OTHER_MEANS.items():
            with self.subTest(schema=name):
                path = REPO_ROOT / module
                self.assertTrue(path.is_file(), f"{module} does not exist")
                self.assertIn(name.rsplit("/", 1)[-1], read_text(path))

    def test_the_other_schemas_use_keywords_jsonschema_lite_does_not_implement(self) -> None:
        # The exclusion is justified by the schema itself: a schema the
        # validator could check would be in scope, not excluded.
        allowed = lite.SUPPORTED_KEYWORDS | lite.ANNOTATION_KEYWORDS
        for name in VALIDATED_BY_OTHER_MEANS:
            with self.subTest(schema=name):
                document = load_schema(SCHEMA_ROOT / name)
                self.assertTrue(
                    used_keywords(document) - allowed,
                    f"{name} uses no keyword jsonschema_lite lacks, so it "
                    "belongs in JAVASCRIPT_LITE_SCOPE",
                )


class RuleTests(unittest.TestCase):
    """The rules must reject the mistakes they exist to catch."""

    def test_a_duplicate_id_is_rejected(self) -> None:
        first = {"title": "One", "$id": "https://example.test/same", "$schema": DRAFT_2020_12}
        second = {"title": "Two", "$id": "https://example.test/same", "$schema": DRAFT_2020_12}
        problems = check_unique_ids([("a.json", first), ("b.json", second)])
        self.assertEqual(len(problems), 1)
        self.assertIn("b.json", problems[0])
        self.assertIn("$id", problems[0])
        self.assertIn("a.json", problems[0])

    def test_a_dangling_ref_is_rejected(self) -> None:
        document = {
            "title": "Dangling",
            "$id": "https://example.test/dangling",
            "$schema": DRAFT_2020_12,
            "$defs": {"present": {"type": "string"}},
            "properties": {"value": {"$ref": "#/$defs/missing"}},
        }
        problems = check_refs("dangling.json", document)
        self.assertEqual(len(problems), 1)
        self.assertIn("dangling.json", problems[0])
        self.assertIn("#/$defs/missing", problems[0])

    def test_a_ref_that_resolves_is_accepted(self) -> None:
        document = {
            "title": "Resolving",
            "$id": "https://example.test/resolving",
            "$schema": DRAFT_2020_12,
            "$defs": {"present": {"type": "string"}},
            "properties": {"value": {"$ref": "#/$defs/present"}},
        }
        self.assertEqual(check_refs("resolving.json", document), [])

    def test_a_missing_schema_declaration_is_rejected(self) -> None:
        document = {"title": "No draft", "$id": "https://example.test/no-draft"}
        problems = check_document("no-draft.json", document, proposed=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("no-draft.json", problems[0])
        self.assertIn("$schema", problems[0])

    def test_an_old_draft_is_rejected_at_the_top_level(self) -> None:
        document = {
            "title": "Old draft",
            "$id": "https://example.test/old-draft",
            "$schema": "http://json-schema.org/draft-07/schema#",
        }
        problems = check_document("old-draft.json", document, proposed=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("old-draft.json", problems[0])
        self.assertIn("draft-07", problems[0])

    def test_an_old_draft_is_accepted_under_proposed(self) -> None:
        document = {
            "title": "Proposed",
            "$id": "https://example.test/proposed",
            "$schema": "http://json-schema.org/draft-07/schema#",
        }
        self.assertEqual(check_document("proposed/old-draft.json", document, proposed=True), [])

    def test_a_missing_title_is_rejected(self) -> None:
        document = {"$id": "https://example.test/no-title", "$schema": DRAFT_2020_12}
        problems = check_document("no-title.json", document, proposed=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("no-title.json", problems[0])
        self.assertIn("title", problems[0])

    def test_an_unsupported_keyword_is_rejected(self) -> None:
        document = {
            "title": "Unsupported",
            "$id": "https://example.test/unsupported",
            "$schema": DRAFT_2020_12,
            "type": "object",
            "unevaluatedProperties": False,
        }
        problems = check_keywords("unsupported.json", document)
        self.assertEqual(len(problems), 1)
        self.assertIn("unsupported.json", problems[0])
        self.assertIn("unevaluatedProperties", problems[0])

    def test_a_supported_keyword_is_accepted(self) -> None:
        document = {
            "title": "Supported",
            "$id": "https://example.test/supported",
            "$schema": DRAFT_2020_12,
            "type": "object",
            "properties": {"value": {"type": "string", "minLength": 1}},
            "required": ["value"],
        }
        self.assertEqual(check_keywords("supported.json", document), [])

    def test_a_property_name_is_not_mistaken_for_a_keyword(self) -> None:
        # "properties" holds names, not keywords: a property called "type"
        # must not make the schema look like it uses an unsupported keyword.
        document = {
            "title": "Named",
            "$id": "https://example.test/named",
            "$schema": DRAFT_2020_12,
            "type": "object",
            "properties": {"unevaluatedProperties": {"type": "string"}},
        }
        self.assertEqual(check_keywords("named.json", document), [])


if __name__ == "__main__":
    unittest.main()
