"""Tests for tools/inventory/compare.py (F-014, issue #279).

The tool compares the fixture inventory the engine prints
(``stellar-canary fixtures --format json``) with a pack's
``registry-v1.json``, so that a fixture the registry lists but the engine's
loader never discovers -- or the other way round -- fails a check instead of
staying invisible.

The tests cover the comparison itself (hand-built documents), the rules that
make each input unusable (unknown document version, missing directory,
self-contradicting counts, duplicate ids, unreadable or non-JSON files), the
empty baseline registry, the command line (formats, exit codes, the protocol
guard, standard input) and a comparison against this repository's committed
``protocol-29/registry-v1.json``.

Run with: python3 -m unittest tests/test_inventory_compare.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPARE_PATH = REPO_ROOT / "tools" / "inventory" / "compare.py"
PROTOCOL29_REGISTRY = REPO_ROOT / "protocol-29" / "registry-v1.json"

_spec = importlib.util.spec_from_file_location("inventory_compare", COMPARE_PATH)
compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["inventory_compare"] = compare
_spec.loader.exec_module(compare)

SHA_A = "a" * 64
DIGEST_A = "sha256:" + "1" * 64


def engine_fixture(
    identifier: str,
    surface: str = "xdr",
    category: str = "ledger",
    path: str | None = None,
) -> dict:
    """A minimal ``fixtures[]`` entry of the engine's inventory document."""
    return {
        "id": identifier,
        "protocol": 28,
        "surface": surface,
        "category": category,
        "description": f"fixture {identifier}",
        "path": path or f"{surface}/{identifier}.toml",
        "requiredCapabilities": [],
    }


def registry_fixture(
    identifier: str,
    surface: str = "xdr",
    category: str = "ledger",
    path: str | None = None,
) -> dict:
    """A minimal ``fixtures[]`` entry of a registry document."""
    return {
        "id": identifier,
        "path": path or f"{surface}/{identifier}.toml",
        "sha256": SHA_A,
        "surface": surface,
        "category": category,
        "description": f"fixture {identifier}",
        "payloads": [],
    }


def inventory(
    fixtures: list[dict],
    protocol: int = 28,
    version: int = 1,
    fixture_format: int = 1,
    total: int | None = None,
    directory_found: bool = True,
) -> dict:
    """A minimal engine inventory document."""
    return {
        "inventoryVersion": version,
        "toolVersion": "0.2.0",
        "fixtureFormat": fixture_format,
        "protocol": protocol,
        "directoryFound": directory_found,
        "counts": {
            "total": len(fixtures) if total is None else total,
            "xdr": len([f for f in fixtures if f.get("surface") == "xdr"]),
            "rpc": len([f for f in fixtures if f.get("surface") == "rpc"]),
            "soroban": len([f for f in fixtures if f.get("surface") == "soroban"]),
        },
        "otherProtocols": {},
        "fixtures": fixtures,
    }


def registry(
    fixtures: list[dict],
    protocol: int = 28,
    version: int = 1,
    digest: str = DIGEST_A,
) -> dict:
    """A minimal registry document."""
    return {
        "registryVersion": version,
        "protocol": protocol,
        "fixtures": fixtures,
        "packDigest": digest,
    }


def write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


class ComparisonTests(unittest.TestCase):
    """The comparison reports missing, extra and mismatched fixtures."""

    def test_identical_inventories_match(self) -> None:
        fixtures = [
            registry_fixture("p28-a"),
            registry_fixture("p28-b", surface="rpc", category="network"),
        ]
        result = compare.compare_inventories(
            inventory([engine_fixture(e["id"], e["surface"], e["category"]) for e in fixtures]),
            registry(fixtures),
        )
        self.assertTrue(result["match"])
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["extra"], [])
        self.assertEqual(result["mismatched"], [])

    def test_a_fixture_in_the_registry_but_not_the_engine_is_missing(self) -> None:
        result = compare.compare_inventories(
            inventory([]),
            registry([registry_fixture("p28-only-registry", path="xdr/only.toml")]),
        )
        self.assertFalse(result["match"])
        self.assertEqual(
            result["missing"],
            [
                {
                    "id": "p28-only-registry",
                    "path": "xdr/only.toml",
                    "surface": "xdr",
                    "category": "ledger",
                }
            ],
        )
        self.assertEqual(result["extra"], [])
        self.assertEqual(result["matched"], 0)

    def test_a_fixture_the_engine_discovered_but_the_registry_lacks_is_extra(self) -> None:
        result = compare.compare_inventories(
            inventory(
                [engine_fixture("p28-only-engine", surface="rpc", path="rpc/only.toml")]
            ),
            registry([]),
        )
        self.assertFalse(result["match"])
        self.assertEqual(
            result["extra"],
            [
                {
                    "id": "p28-only-engine",
                    "path": "rpc/only.toml",
                    "surface": "rpc",
                    "category": "ledger",
                }
            ],
        )
        self.assertEqual(result["missing"], [])

    def test_a_surface_mismatch_is_reported_with_both_values(self) -> None:
        result = compare.compare_inventories(
            inventory([engine_fixture("p28-a", surface="rpc")]),
            registry([registry_fixture("p28-a", surface="xdr")]),
        )
        self.assertFalse(result["match"])
        self.assertEqual(
            result["mismatched"],
            [
                {
                    "id": "p28-a",
                    "field": "surface",
                    "inventory": "rpc",
                    "registry": "xdr",
                }
            ],
        )
        self.assertEqual(result["matched"], 0)

    def test_a_category_mismatch_is_reported(self) -> None:
        result = compare.compare_inventories(
            inventory([engine_fixture("p28-a", category="network")]),
            registry([registry_fixture("p28-a", category="ledger")]),
        )
        self.assertFalse(result["match"])
        self.assertEqual(
            result["mismatched"],
            [
                {
                    "id": "p28-a",
                    "field": "category",
                    "inventory": "network",
                    "registry": "ledger",
                }
            ],
        )

    def test_one_fixture_can_mismatch_on_both_attributes(self) -> None:
        result = compare.compare_inventories(
            inventory([engine_fixture("p28-a", surface="rpc", category="network")]),
            registry([registry_fixture("p28-a", surface="xdr", category="ledger")]),
        )
        self.assertEqual(
            [entry["field"] for entry in result["mismatched"]],
            ["surface", "category"],
        )
        self.assertEqual(result["matched"], 0)

    def test_a_fixture_with_a_mismatch_is_not_counted_as_matched(self) -> None:
        result = compare.compare_inventories(
            inventory([engine_fixture("p28-a"), engine_fixture("p28-b")]),
            registry(
                [
                    registry_fixture("p28-a", category="network"),
                    registry_fixture("p28-b"),
                ]
            ),
        )
        self.assertEqual(result["matched"], 1)
        self.assertEqual(len(result["mismatched"]), 1)

    def test_the_lists_are_sorted_by_id(self) -> None:
        result = compare.compare_inventories(
            inventory(
                [
                    engine_fixture("p28-c"),
                    engine_fixture("p28-a"),
                    engine_fixture("p28-b"),
                ]
            ),
            registry([registry_fixture("p28-c"), registry_fixture("p28-a")]),
        )
        self.assertEqual([entry["id"] for entry in result["extra"]], ["p28-b"])
        self.assertEqual([entry["id"] for entry in result["missing"]], [])

    def test_the_result_is_deterministic(self) -> None:
        first = compare.compare_inventories(
            inventory([engine_fixture("p28-b"), engine_fixture("p28-a")]),
            registry([registry_fixture("p28-a")]),
        )
        second = compare.compare_inventories(
            inventory([engine_fixture("p28-a"), engine_fixture("p28-b")]),
            registry([registry_fixture("p28-a")]),
        )
        self.assertEqual(first, second)


class InventoryValidationTests(unittest.TestCase):
    """An engine inventory this tool cannot compare is refused, not guessed."""

    def problems(self, document: object) -> list[str]:
        return compare.check_inventory(document)

    def test_a_valid_inventory_has_no_problems(self) -> None:
        self.assertEqual(
            self.problems(inventory([engine_fixture("p28-a")])),
            [],
        )

    def test_a_non_object_is_refused(self) -> None:
        self.assertEqual(
            self.problems([]), ["an engine inventory must be a JSON object"]
        )

    def test_an_unknown_inventory_version_is_refused(self) -> None:
        problems = self.problems(inventory([], version=2))
        self.assertTrue(any("inventoryVersion' is 2" in p for p in problems), problems)
        self.assertTrue(any("refused" in p for p in problems), problems)

    def test_a_non_integer_inventory_version_is_refused(self) -> None:
        problems = self.problems(inventory([], version="1"))
        self.assertTrue(any("non-integer 'inventoryVersion'" in p for p in problems))

    def test_an_unknown_fixture_format_is_refused(self) -> None:
        problems = self.problems(inventory([], fixture_format=2))
        self.assertTrue(any("fixtureFormat' is 2" in p for p in problems), problems)

    def test_a_non_integer_fixture_format_is_refused(self) -> None:
        problems = self.problems(inventory([], fixture_format=None))
        self.assertTrue(any("non-integer 'fixtureFormat'" in p for p in problems))

    def test_a_missing_protocol_is_refused(self) -> None:
        document = inventory([])
        document.pop("protocol")
        self.assertTrue(any("'protocol'" in p for p in self.problems(document)))

    def test_a_zero_protocol_is_refused(self) -> None:
        self.assertTrue(any("'protocol'" in p for p in self.problems(inventory([], protocol=0))))

    def test_a_missing_directory_is_refused(self) -> None:
        problems = self.problems(inventory([], directory_found=False))
        self.assertTrue(any("'directoryFound' is false" in p for p in problems), problems)

    def test_a_non_boolean_directory_found_is_refused(self) -> None:
        document = inventory([])
        document["directoryFound"] = "yes"
        self.assertTrue(any("'directoryFound'" in p for p in self.problems(document)))

    def test_fixtures_must_be_an_array(self) -> None:
        document = inventory([])
        document["fixtures"] = {}
        self.assertTrue(any("'fixtures' must be an array" in p for p in self.problems(document)))

    def test_counts_must_be_an_object(self) -> None:
        document = inventory([])
        document["counts"] = []
        self.assertTrue(any("'counts' must be an object" in p for p in self.problems(document)))

    def test_counts_total_must_be_an_integer(self) -> None:
        document = inventory([])
        document["counts"]["total"] = "1"
        self.assertTrue(any("'counts.total'" in p for p in self.problems(document)))

    def test_counts_total_must_match_the_fixture_list(self) -> None:
        problems = self.problems(inventory([], total=1))
        self.assertTrue(any("contradicts itself" in p for p in problems), problems)

    def test_a_fixture_entry_must_be_an_object(self) -> None:
        document = inventory([])
        document["fixtures"] = ["p28-a"]
        document["counts"]["total"] = 1
        self.assertTrue(any("fixtures[0] must be an object" in p for p in self.problems(document)))

    def test_a_fixture_needs_a_non_empty_id(self) -> None:
        for identifier in ("", 7):
            with self.subTest(identifier=identifier):
                entry = engine_fixture("p28-a")
                entry["id"] = identifier
                document = inventory([entry])
                self.assertTrue(any(".id must be" in p for p in self.problems(document)))

    def test_a_duplicate_fixture_id_is_refused(self) -> None:
        problems = self.problems(
            inventory([engine_fixture("p28-a"), engine_fixture("p28-a", surface="rpc")])
        )
        self.assertTrue(any("appears twice" in p for p in problems), problems)

    def test_an_unknown_surface_is_refused(self) -> None:
        entry = engine_fixture("p28-a")
        entry["surface"] = "jsonrpc"
        problems = self.problems(inventory([entry]))
        self.assertTrue(any(".surface must be one of" in p for p in problems), problems)

    def test_a_fixture_needs_a_non_empty_category(self) -> None:
        for category in ("", 3):
            with self.subTest(category=category):
                entry = engine_fixture("p28-a")
                entry["category"] = category
                document = inventory([entry])
                self.assertTrue(any(".category must be" in p for p in self.problems(document)))

    def test_a_fixture_needs_a_non_empty_path(self) -> None:
        for path in ("", None):
            with self.subTest(path=path):
                entry = engine_fixture("p28-a")
                entry["path"] = path
                document = inventory([entry])
                self.assertTrue(any(".path must be" in p for p in self.problems(document)))


class RegistryValidationTests(unittest.TestCase):
    """The registry is checked against its schema plus the loader-side rules."""

    def problems(self, document: object) -> list[str]:
        return compare.check_registry(document)

    def test_a_valid_registry_has_no_problems(self) -> None:
        self.assertEqual(self.problems(registry([registry_fixture("p28-a")])), [])

    def test_a_non_object_is_refused(self) -> None:
        self.assertEqual(self.problems("registry"), ["a registry must be a JSON object"])

    def test_an_empty_fixtures_list_is_the_documented_empty_baseline(self) -> None:
        # protocol-29/registry-v1.json ships with `fixtures: []`; the schema's
        # minItems floor cannot express that exception, so it is relaxed here.
        self.assertEqual(self.problems(registry([])), [])

    def test_a_duplicate_fixture_id_is_refused(self) -> None:
        problems = self.problems(
            registry([registry_fixture("p28-a"), registry_fixture("p28-a")])
        )
        self.assertTrue(any("appears twice" in p for p in problems), problems)

    def test_an_unknown_registry_version_is_refused(self) -> None:
        problems = self.problems(registry([], version=2))
        self.assertTrue(any("registryVersion' is 2" in p for p in problems), problems)

    def test_a_missing_fixtures_key_is_reported_by_the_schema(self) -> None:
        document = registry([])
        document.pop("fixtures")
        problems = self.problems(document)
        self.assertTrue(
            any("missing required property 'fixtures'" in p for p in problems), problems
        )

    def test_a_fixtures_key_that_is_not_a_list_is_reported(self) -> None:
        document = registry([])
        document["fixtures"] = {"p28-a": {}}
        problems = self.problems(document)
        self.assertTrue(any("expected array" in p for p in problems), problems)

    def test_a_fixture_entry_that_is_not_an_object_is_left_to_the_schema(self) -> None:
        document = registry([])
        document["fixtures"] = ["p28-a"]
        problems = self.problems(document)
        self.assertTrue(any("expected object" in p for p in problems), problems)

    def test_a_fixture_entry_without_a_string_id_is_left_to_the_schema(self) -> None:
        document = registry([])
        document["fixtures"] = [{"id": 7}]
        problems = self.problems(document)
        self.assertTrue(any("expected string" in p for p in problems), problems)

    def test_a_missing_fixture_field_is_reported_by_the_schema(self) -> None:
        entry = registry_fixture("p28-a")
        entry.pop("category")
        problems = self.problems(registry([entry]))
        self.assertTrue(any("missing required property 'category'" in p for p in problems))

    def test_an_extra_fixture_field_is_reported_by_the_schema(self) -> None:
        entry = registry_fixture("p28-a")
        entry["surfaceDescription"] = "rpc"
        problems = self.problems(registry([entry]))
        self.assertTrue(any("unexpected property" in p for p in problems), problems)


class CommandLineTests(unittest.TestCase):
    """Exit codes, output formats and error reporting."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="inventory-compare-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inventory_path = write_json(
            self.tmp / "inventory.json", inventory([engine_fixture("p28-a")])
        )
        self.registry_path = write_json(
            self.tmp / "registry-v1.json", registry([registry_fixture("p28-a")])
        )

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = compare.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_matching_inventories_exit_zero(self) -> None:
        code, out, err = self.run_tool(str(self.inventory_path), str(self.registry_path))
        self.assertEqual(code, 0, err)
        self.assertIn("OK: both inventories hold the same 1 fixture(s)", out)
        self.assertEqual(err, "")

    def test_the_text_report_names_both_documents(self) -> None:
        _, out, _ = self.run_tool(str(self.inventory_path), str(self.registry_path))
        self.assertIn(f"engine inventory: {self.inventory_path}", out)
        self.assertIn(f"registry:         {self.registry_path}", out)
        self.assertIn("inventory version 1", out)
        self.assertIn("registry version 1", out)

    def test_a_missing_fixture_exits_one_and_is_listed(self) -> None:
        write_json(
            self.tmp / "registry2.json",
            registry([registry_fixture("p28-a"), registry_fixture("p28-b")]),
        )
        code, out, _ = self.run_tool(str(self.inventory_path), str(self.tmp / "registry2.json"))
        self.assertEqual(code, 1)
        self.assertIn("FAILED: 1 difference(s)", out)
        self.assertIn("missing from the engine inventory (1)", out)
        self.assertIn("p28-b  (xdr, ledger)  registry path: xdr/p28-b.toml", out)

    def test_an_extra_fixture_exits_one_and_is_listed(self) -> None:
        write_json(
            self.tmp / "inventory2.json",
            inventory([engine_fixture("p28-a"), engine_fixture("p28-b")]),
        )
        code, out, _ = self.run_tool(str(self.tmp / "inventory2.json"), str(self.registry_path))
        self.assertEqual(code, 1)
        self.assertIn("extra in the engine inventory (1)", out)
        self.assertIn("p28-b  (xdr, ledger)  engine path: xdr/p28-b.toml", out)

    def test_a_mismatch_exits_one_and_names_both_values(self) -> None:
        write_json(
            self.tmp / "registry2.json",
            registry([registry_fixture("p28-a", surface="rpc", category="network")]),
        )
        code, out, _ = self.run_tool(str(self.inventory_path), str(self.tmp / "registry2.json"))
        self.assertEqual(code, 1)
        self.assertIn("attribute mismatches (2)", out)
        self.assertIn("p28-a  surface  engine='xdr' registry='rpc'", out)
        self.assertIn("p28-a  category  engine='ledger' registry='network'", out)
        self.assertIn("matched: 0 fixture(s)", out)

    def test_the_json_format_is_machine_readable(self) -> None:
        write_json(
            self.tmp / "registry2.json", registry([registry_fixture("p28-a", category="network")])
        )
        code, out, _ = self.run_tool(
            str(self.inventory_path), str(self.tmp / "registry2.json"), "--format", "json"
        )
        self.assertEqual(code, 1)
        document = json.loads(out)
        self.assertEqual(
            document["inventory"],
            {
                "path": str(self.inventory_path),
                "protocol": 28,
                "inventoryVersion": 1,
                "fixtureCount": 1,
            },
        )
        self.assertEqual(
            document["registry"],
            {
                "path": str(self.tmp / "registry2.json"),
                "protocol": 28,
                "registryVersion": 1,
                "fixtureCount": 1,
            },
        )
        self.assertFalse(document["match"])
        self.assertEqual(document["matched"], 0)
        self.assertEqual(document["missing"], [])
        self.assertEqual(document["extra"], [])
        self.assertEqual(
            document["mismatched"],
            [
                {
                    "id": "p28-a",
                    "field": "category",
                    "inventory": "ledger",
                    "registry": "network",
                }
            ],
        )

    def test_the_json_output_ends_with_one_newline(self) -> None:
        _, out, _ = self.run_tool(
            str(self.inventory_path), str(self.registry_path), "--format", "json"
        )
        self.assertTrue(out.endswith("}\n"))
        self.assertFalse(out.endswith("}\n\n"))

    def test_the_json_output_is_byte_identical_between_runs(self) -> None:
        first = self.run_tool(
            str(self.inventory_path), str(self.registry_path), "--format", "json"
        )
        second = self.run_tool(
            str(self.inventory_path),
            str(self.registry_path),
            "--format",
            "json",
        )
        self.assertEqual(first, second)

    def test_the_inventory_can_be_read_from_standard_input(self) -> None:
        payload = json.dumps(inventory([engine_fixture("p28-a")])).encode("utf-8")
        stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        out = io.StringIO()
        err = io.StringIO()
        original = sys.stdin
        sys.stdin = stdin
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = compare.main(["-", str(self.registry_path)])
        finally:
            sys.stdin = original
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("engine inventory: -", out.getvalue())

    def test_standard_input_needs_a_byte_stream(self) -> None:
        original = sys.stdin
        sys.stdin = io.StringIO("{}")
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = compare.main(["-", str(self.registry_path)])
        finally:
            sys.stdin = original
        self.assertEqual(code, 2)

    def test_a_missing_file_exits_two(self) -> None:
        code, _, err = self.run_tool(str(self.tmp / "absent.json"), str(self.registry_path))
        self.assertEqual(code, 2)
        self.assertIn("no such engine inventory file", err)

    def test_a_directory_as_inventory_exits_two(self) -> None:
        code, _, err = self.run_tool(str(self.tmp), str(self.registry_path))
        self.assertEqual(code, 2)
        self.assertIn("is a directory", err)

    def test_a_missing_registry_exits_two(self) -> None:
        code, _, err = self.run_tool(str(self.inventory_path), str(self.tmp / "absent.json"))
        self.assertEqual(code, 2)
        self.assertIn("no such registry file", err)

    def test_a_directory_as_registry_exits_two(self) -> None:
        code, _, err = self.run_tool(str(self.inventory_path), str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("is a directory", err)

    def test_an_unreadable_input_exits_two(self) -> None:
        original_read_bytes = Path.read_bytes

        def refuse(self) -> bytes:
            raise PermissionError("denied for this test")

        Path.read_bytes = refuse  # type: ignore[method-assign]
        try:
            code, _, err = self.run_tool(str(self.inventory_path), str(self.registry_path))
        finally:
            Path.read_bytes = original_read_bytes  # type: ignore[method-assign]
        self.assertEqual(code, 2)
        self.assertIn("could not be read", err)

    def test_an_input_that_is_not_utf8_exits_two(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_bytes(b'{"inventoryVersion": 1\xff}')
        code, _, err = self.run_tool(str(bad), str(self.registry_path))
        self.assertEqual(code, 2)
        self.assertIn("is not valid UTF-8", err)

    def test_an_input_that_is_not_json_exits_two(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        code, _, err = self.run_tool(str(bad), str(self.registry_path))
        self.assertEqual(code, 2)
        self.assertIn("is not valid JSON", err)

    def test_a_duplicate_json_key_exits_two(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_text(
            '{"inventoryVersion": 1, "inventoryVersion": 1}', encoding="utf-8"
        )
        code, _, err = self.run_tool(str(bad), str(self.registry_path))
        self.assertEqual(code, 2)
        self.assertIn("duplicate object key", err)

    def test_an_unusable_inventory_names_the_problem(self) -> None:
        write_json(self.tmp / "inventory2.json", inventory([], version=2))
        code, _, err = self.run_tool(str(self.tmp / "inventory2.json"), str(self.registry_path))
        self.assertEqual(code, 2)
        self.assertIn("is not a usable engine inventory", err)
        self.assertIn("inventoryVersion", err)

    def test_an_unusable_registry_names_the_problem(self) -> None:
        write_json(self.tmp / "registry2.json", registry([], version=2))
        code, _, err = self.run_tool(str(self.inventory_path), str(self.tmp / "registry2.json"))
        self.assertEqual(code, 2)
        self.assertIn("is not a usable registry", err)
        self.assertIn("registryVersion", err)

    def test_a_protocol_mismatch_is_refused(self) -> None:
        write_json(self.tmp / "registry2.json", registry([], protocol=29))
        code, _, err = self.run_tool(str(self.inventory_path), str(self.tmp / "registry2.json"))
        self.assertEqual(code, 2)
        self.assertIn("protocol 28", err)
        self.assertIn("protocol 29", err)
        self.assertIn("every fixture as missing or extra", err)

    def test_an_unknown_format_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_tool(
                str(self.inventory_path), str(self.registry_path), "--format", "yaml"
            )
        self.assertEqual(caught.exception.code, 2)

    def test_a_missing_argument_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_tool(str(self.inventory_path))
        self.assertEqual(caught.exception.code, 2)

    def test_the_script_entry_point_exits_with_the_tool_status(self) -> None:
        original = sys.argv
        sys.argv = [str(COMPARE_PATH), str(self.inventory_path), str(self.registry_path)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(str(COMPARE_PATH), run_name="__main__")
        finally:
            sys.argv = original
        self.assertEqual(caught.exception.code, 0)

    def test_the_help_text_states_the_exit_codes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COMPARE_PATH), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Exit codes", result.stdout)
        self.assertIn("standard input", result.stdout)


class EmptyBaselineTests(unittest.TestCase):
    """The committed Protocol 29 registry is compared with engine inventories."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="inventory-empty-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = compare.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def empty_inventory(self, protocol: int = 29) -> Path:
        return write_json(
            self.tmp / "inventory.json", inventory([], protocol=protocol)
        )

    def test_empty_inventory_reports_fixture_in_committed_registry(self) -> None:
        code, out, _ = self.run_tool(
            str(self.empty_inventory()), str(PROTOCOL29_REGISTRY)
        )
        self.assertEqual(code, 1)
        self.assertIn("missing from the engine inventory (1)", out)
        self.assertIn("p29-rpc-network-mismatch", out)

    def test_an_engine_fixture_absent_from_the_registry_is_extra(self) -> None:
        path = write_json(
            self.tmp / "inventory.json",
            inventory(
                [engine_fixture("p29-rpc-health", surface="rpc", category="health")],
                protocol=29,
            ),
        )
        code, out, _ = self.run_tool(str(path), str(PROTOCOL29_REGISTRY))
        self.assertEqual(code, 1)
        self.assertIn("extra in the engine inventory (1)", out)
        self.assertIn("p29-rpc-health", out)

    def test_an_empty_inventory_against_a_populated_registry_reports_missing(self) -> None:
        path = write_json(self.tmp / "registry-v1.json", registry([registry_fixture("p28-a")]))
        code, out, _ = self.run_tool(str(self.empty_inventory(protocol=28)), str(path))
        self.assertEqual(code, 1)
        self.assertIn("missing from the engine inventory (1)", out)
        self.assertIn("p28-a", out)


if __name__ == "__main__":
    unittest.main()
