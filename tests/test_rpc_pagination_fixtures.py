"""Tests for the RPC pagination boundary vectors (F-038, issue #295).

Run with: python3 -m unittest discover tests

``getLedgers`` and ``getTransactions`` accept a ``pagination.limit`` of up to
200 upstream, but the engine's approved bound (decision D-06, CA-01 section 3
rule 4) is 1..=50. The fixture loader rejects anything above it when the
fixture is loaded, so an out-of-spec page size never reaches an endpoint.

The valid boundaries are four vectors under ``tests/fixtures/rpc/pagination/``
(limit 1 and limit 50 for each method). The invalid ones are built here by
mutating those vectors, because an invalid fixture cannot live in a tree the
validator scans. The engine reports an invalid fixture with exit code 4; this
repository's validator reports it as an error and exits 1, which is what these
tests assert.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpc_vector_support as support  # noqa: E402

validate = support.validate

METHODS = ("get-ledgers", "get-transactions")
LIMITS = (1, 50)
UPSTREAM_MAX_LIMIT = 200  # Stellar RPC's published ceiling, measured live on 2026-10-23.
D06_MAX_LIMIT = 50


def vector_name(method: str, limit: int) -> str:
    return f"pagination/{method}-limit-{limit}.toml"


class PaginationBoundaryVectorTests(unittest.TestCase):
    def test_the_four_boundary_vectors_validate_cleanly(self) -> None:
        for method in METHODS:
            for limit in LIMITS:
                with self.subTest(method=method, limit=limit):
                    report = support.run_validation({"a.toml": support.read_text(vector_name(method, limit))})
                    self.assertEqual(report.errors, [])

    def test_the_directory_validates_and_the_cli_exits_zero(self) -> None:
        directory = support.RPC_VECTORS / "pagination"
        self.assertEqual(validate.validate_directory(directory).errors, [])
        exit_code, stdout, _stderr = support.run_main([str(directory)])
        self.assertEqual(exit_code, 0)
        self.assertIn("OK: 4 fixture file(s) valid", stdout)

    def test_each_vector_pins_its_method_and_limit(self) -> None:
        for method in METHODS:
            for limit in LIMITS:
                with self.subTest(method=method, limit=limit):
                    data = support.load_toml(vector_name(method, limit))
                    self.assertEqual(data["method"], method)
                    self.assertEqual(data["request"]["pagination"], {"limit": limit})
                    self.assertEqual(data["surface"], "rpc")
                    self.assertEqual(data["id"], f"test-rpc-{method}-limit-{limit}")

    def test_the_vectors_cover_both_ends_of_the_approved_range(self) -> None:
        limits = {
            (data["method"], data["request"]["pagination"]["limit"])
            for data in (support.load_toml(vector_name(m, n)) for m in METHODS for n in LIMITS)
        }
        self.assertEqual(limits, {(m, n) for m in METHODS for n in (1, D06_MAX_LIMIT)})

    def test_the_assertions_describe_a_page_and_its_cursor(self) -> None:
        for method, listing in (("get-ledgers", "ledgers"), ("get-transactions", "transactions")):
            data = support.load_toml(vector_name(method, 50))
            asserted = {(a["kind"], a["field"], a.get("expected_type")) for a in data["assert"]}
            with self.subTest(method=method):
                self.assertEqual(
                    asserted,
                    {
                        ("field-type", listing, "array"),
                        ("field-type", "latestLedger", "number"),
                        ("field-type", "oldestLedger", "number"),
                        ("field-type", "cursor", "string"),
                    },
                )
                for assertion in data["assert"]:
                    self.assertIn(assertion["kind"], validate.RPC_ASSERT_KINDS)


class OutOfBoundLimitTests(unittest.TestCase):
    """Every limit above 50 is an invalid fixture, for both methods."""

    def mutated(self, method: str, literal: str):
        text = support.set_limit(support.read_text(vector_name(method, 50)), literal)
        return support.run_validation({"a.toml": text})

    def test_limit_51_and_200_are_rejected_as_invalid_fixtures(self) -> None:
        for method in METHODS:
            for limit in (D06_MAX_LIMIT + 1, UPSTREAM_MAX_LIMIT):
                with self.subTest(method=method, limit=limit):
                    report = self.mutated(method, str(limit))
                    self.assertFalse(report.ok)
                    self.assertTrue(
                        any(f"limit {limit} is outside 1..=50" in error for error in report.errors),
                        report.errors,
                    )

    def test_the_ceiling_is_exactly_50(self) -> None:
        for method in METHODS:
            with self.subTest(method=method):
                self.assertEqual(self.mutated(method, "50").errors, [])
                self.assertTrue(self.mutated(method, "51").errors)

    def test_the_floor_is_exactly_1(self) -> None:
        for method in METHODS:
            with self.subTest(method=method):
                self.assertEqual(self.mutated(method, "1").errors, [])
                report = self.mutated(method, "0")
                self.assertTrue(any("limit 0 is outside 1..=50" in e for e in report.errors), report.errors)

    def test_negative_and_very_large_limits_are_rejected(self) -> None:
        for literal, shown in (("-1", "-1"), ("-50", "-50"), ("4294967295", "4294967295"), ("9007199254740993", "9007199254740993")):
            with self.subTest(limit=literal):
                report = self.mutated("get-ledgers", literal)
                self.assertTrue(any(f"limit {shown} is outside 1..=50" in e for e in report.errors), report.errors)

    def test_the_upstream_limit_is_not_the_engine_limit(self) -> None:
        # The reconciliation the issue asks for, stated as numbers: upstream
        # allows 200, D-06 approves 50, and the validator follows D-06.
        self.assertGreater(UPSTREAM_MAX_LIMIT, D06_MAX_LIMIT)
        self.assertEqual(validate._RPC_MAX_LIMIT, D06_MAX_LIMIT)
        self.assertTrue(self.mutated("get-ledgers", str(UPSTREAM_MAX_LIMIT)).errors)

    def test_an_out_of_bound_limit_fails_the_command_line_run(self) -> None:
        # CI runs `python3 tools/validate/validate.py`; any error is exit 1.
        text = support.set_limit(support.read_text(vector_name("get-transactions", 50)), "51")
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "a.toml").write_text(text, encoding="utf-8")
            exit_code, _stdout, stderr = support.run_main([scratch])
            self.assertEqual(exit_code, 1)
            self.assertIn("limit 51 is outside 1..=50", stderr)
            self.assertIn("FAILED: 1 error(s)", stderr)
            json_code, json_out, _ = support.run_main([scratch, "--format", "json"])
            document = json.loads(json_out)
            self.assertEqual(json_code, 1)
            self.assertFalse(document["valid"])
            self.assertEqual(document["summary"]["errors"], 1)
            self.assertIn("limit 51 is outside 1..=50", document["errors"][0]["message"])


class NonIntegerLimitTests(unittest.TestCase):
    """A limit that is not an integer cannot be a page size."""

    def mutated(self, literal: str, method: str = "get-ledgers"):
        text = support.set_limit(support.read_text(vector_name(method, 50)), literal)
        return support.run_validation({"a.toml": text})

    def test_floats_strings_booleans_and_containers_are_rejected(self) -> None:
        for literal in ("50.0", "50.5", '"50"', "true", "false", "[50]", "{ n = 50 }"):
            for method in METHODS:
                with self.subTest(limit=literal, method=method):
                    report = self.mutated(literal, method)
                    self.assertTrue(
                        any("pagination: limit must be an integer" in e for e in report.errors),
                        report.errors,
                    )

    def test_an_unknown_pagination_key_is_rejected(self) -> None:
        text = support.replace_once(support.read_text(vector_name("get-ledgers", 1)), "limit = 1\n", "limit = 1\npageSize = 1\n")
        report = support.run_validation({"a.toml": text})
        self.assertTrue(any("unknown key 'pageSize'" in e for e in report.errors), report.errors)

    def test_an_empty_cursor_is_rejected_and_a_real_one_is_accepted_with_the_ceiling(self) -> None:
        base = support.read_text(vector_name("get-transactions", 50))
        ok = support.replace_once(base, "limit = 50\n", 'limit = 50\ncursor = "22974218153062401"\n')
        self.assertEqual(support.run_validation({"a.toml": ok}).errors, [])
        bad = support.replace_once(base, "limit = 50\n", 'limit = 50\ncursor = ""\n')
        self.assertTrue(any("cursor must be a non-empty string" in e for e in support.run_validation({"a.toml": bad}).errors))

    def test_a_start_ledger_outside_the_32_bit_range_is_rejected(self) -> None:
        for literal in ("-1", "4294967296"):
            with self.subTest(startLedger=literal):
                base = support.read_text(vector_name("get-ledgers", 50))
                text = support.replace_once(base, "startLedger = 5340000", f"startLedger = {literal}")
                report = support.run_validation({"a.toml": text})
                self.assertTrue(any("is not a ledger sequence" in e for e in report.errors), report.errors)


class SchemaAndLoaderTests(unittest.TestCase):
    def test_the_paged_methods_are_in_the_schema_vocabulary(self) -> None:
        schema_sync = support.load_tool("canary_schema_sync_rpc_vectors", "tools/validate/schema_sync.py")
        block = schema_sync.surface_block(schema_sync.load_schema(), "rpc")
        assert block is not None
        for method in METHODS:
            self.assertIn(method, block["properties"]["method"]["enum"])
            self.assertIn(method, validate.RPC_METHODS)

    def test_both_methods_take_the_same_three_parameters(self) -> None:
        for method in METHODS:
            self.assertEqual(
                set(validate._RPC_METHOD_PARAMS[method]),
                {"startLedger", "pagination", "xdrFormat"},
            )


if __name__ == "__main__":
    unittest.main()
