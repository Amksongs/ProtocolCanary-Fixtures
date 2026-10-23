"""Tests for the RPC absent-entity vectors (F-039, issue #296).

Run with: python3 -m unittest discover tests

Two vectors under ``tests/fixtures/rpc/absent/``:

* ``get-ledger-entries-nonexistent.toml``: a key with no ledger entry is
  omitted from ``entries``, which is then an empty array;
* ``get-transaction-not-found.toml``: an unknown 64-hex transaction hash
  answers ``status = "NOT_FOUND"``.

Both were captured from the live Testnet endpoint on 2026-10-23 (UTC); the
recorded answers below are those captures, trimmed to the fields a fixture can
name. The assertions are evaluated with ``tools/evidence/capture_live.py``'s
``evaluate_asserts``, the repository's own implementation of the assertion
vocabulary, so a vector is shown to pass against the real answer and to fail
against wrong ones.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpc_vector_support as support  # noqa: E402

validate = support.validate
evaluate = support.capture_live.evaluate_asserts

ENTRIES = "absent/get-ledger-entries-nonexistent.toml"
NOT_FOUND = "absent/get-transaction-not-found.toml"
ZERO_HASH = "0" * 64

# Live answers, 2026-10-23 UTC (trimmed to the fields below).
LIVE_NO_ENTRIES = {"entries": [], "latestLedger": 5349346}
LIVE_NOT_FOUND = {
    "latestLedger": 5349346,
    "latestLedgerCloseTime": "1792770317",
    "oldestLedger": 5228387,
    "oldestLedgerCloseTime": "1792165522",
    "status": "NOT_FOUND",
    "txHash": ZERO_HASH,
    "applicationOrder": 0,
    "feeBump": False,
    "events": {},
    "ledger": 0,
    "createdAt": "0",
}


class AbsentVectorTests(unittest.TestCase):
    def test_both_vectors_validate_cleanly(self) -> None:
        for name in (ENTRIES, NOT_FOUND):
            with self.subTest(vector=name):
                self.assertEqual(support.run_validation({"a.toml": support.read_text(name)}).errors, [])

    def test_both_vectors_validate_through_the_command_line(self) -> None:
        exit_code, stdout, _ = support.run_main([str(support.RPC_VECTORS / "absent")])
        self.assertEqual(exit_code, 0)
        self.assertIn("OK: 2 fixture file(s) valid", stdout)

    def test_the_vectors_target_the_methods_the_issue_names(self) -> None:
        self.assertEqual(support.load_toml(ENTRIES)["method"], "get-ledger-entries")
        self.assertEqual(support.load_toml(NOT_FOUND)["method"], "get-transaction")
        for name in (ENTRIES, NOT_FOUND):
            data = support.load_toml(name)
            self.assertEqual((data["surface"], data["protocol"], data["category"]), ("rpc", 28, "absent-entity"))

    def test_assertions_use_only_the_vocabulary_ca_01_allows(self) -> None:
        for name in (ENTRIES, NOT_FOUND):
            for assertion in support.load_toml(name)["assert"]:
                self.assertIn(assertion["kind"], validate.RPC_ASSERT_KINDS)
                self.assertIn(assertion["kind"], {"field-equals", "field-type"})


class NonexistentEntryTests(unittest.TestCase):
    def test_the_key_is_an_account_key_nobody_can_hold(self) -> None:
        keys = support.load_toml(ENTRIES)["request"]["keys"]
        self.assertEqual(len(keys), 1)
        raw = base64.b64decode(keys[0], validate=True)
        digest = hashlib.sha256(b"protocolcanary-fixtures absent ledger key #296").digest()
        # LedgerKey: type ACCOUNT (0), PublicKey type ed25519 (0), 32 key bytes.
        self.assertEqual(raw, (0).to_bytes(4, "big") + (0).to_bytes(4, "big") + digest)
        self.assertEqual(len(raw), 40)

    def test_the_assertions_hold_for_the_live_answer(self) -> None:
        self.assertEqual(evaluate(support.load_toml(ENTRIES)["assert"], LIVE_NO_ENTRIES), [])

    def test_a_found_entry_fails_the_empty_entries_assertion(self) -> None:
        found = dict(LIVE_NO_ENTRIES, entries=[{"key": "AAAA", "xdr": "AAAA", "lastModifiedLedgerSeq": 1}])
        problems = evaluate(support.load_toml(ENTRIES)["assert"], found)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("field-equals", problems[0])
        self.assertIn("'entries'", problems[0])

    def test_an_omitted_or_null_entries_field_does_not_pass_for_the_wrong_reason(self) -> None:
        asserts = support.load_toml(ENTRIES)["assert"]
        for answer in ({"latestLedger": 1}, {"entries": None, "latestLedger": 1}):
            with self.subTest(answer=answer):
                self.assertTrue(evaluate(asserts, answer))

    def test_a_missing_latest_ledger_fails(self) -> None:
        problems = evaluate(support.load_toml(ENTRIES)["assert"], {"entries": []})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("latestLedger", problems[0])


class TransactionNotFoundTests(unittest.TestCase):
    def test_the_hash_is_64_lowercase_hex_and_is_echoed_by_the_assertion(self) -> None:
        data = support.load_toml(NOT_FOUND)
        self.assertEqual(data["request"], {"hash": ZERO_HASH})
        self.assertRegex(data["request"]["hash"], r"^[0-9a-f]{64}$")
        equals = {a["field"]: a["value"] for a in data["assert"] if a["kind"] == "field-equals"}
        self.assertEqual(equals, {"status": "NOT_FOUND", "txHash": ZERO_HASH})

    def test_the_assertions_hold_for_the_live_answer(self) -> None:
        self.assertEqual(evaluate(support.load_toml(NOT_FOUND)["assert"], LIVE_NOT_FOUND), [])

    def test_a_found_transaction_fails(self) -> None:
        for status in ("SUCCESS", "FAILED"):
            with self.subTest(status=status):
                problems = evaluate(support.load_toml(NOT_FOUND)["assert"], dict(LIVE_NOT_FOUND, status=status))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("'status'", problems[0])
                self.assertIn(status, problems[0])

    def test_a_different_hash_in_the_answer_fails(self) -> None:
        problems = evaluate(support.load_toml(NOT_FOUND)["assert"], dict(LIVE_NOT_FOUND, txHash="1" * 64))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("'txHash'", problems[0])

    def test_status_is_compared_exactly_not_case_insensitively(self) -> None:
        problems = evaluate(support.load_toml(NOT_FOUND)["assert"], dict(LIVE_NOT_FOUND, status="not_found"))
        self.assertEqual(len(problems), 1, problems)

    def test_fields_the_live_answer_still_carries_are_not_asserted_absent(self) -> None:
        # CA-01 lists several fields as "present only for SUCCESS or FAILED",
        # but the live NOT_FOUND answer carries them with zero or empty values,
        # so a field-absent on any of them would fail against the real endpoint.
        absent = [a["field"] for a in support.load_toml(NOT_FOUND)["assert"] if a["kind"] == "field-absent"]
        self.assertEqual(absent, [])
        for field in ("ledger", "applicationOrder", "feeBump", "events", "createdAt"):
            self.assertIn(field, LIVE_NOT_FOUND)


class InvalidHashAndKeyTests(unittest.TestCase):
    """The loader rejects malformed requests, so they are invalid fixtures."""

    def tx(self, hash_literal: str):
        text = support.replace_once(support.read_text(NOT_FOUND), f'hash = "{ZERO_HASH}"', f"hash = {hash_literal}")
        return support.run_validation({"a.toml": text})

    def keys(self, keys_literal: str):
        base = support.read_text(ENTRIES)
        start = base.index("keys = [")
        end = base.index("\n", start)
        return support.run_validation({"a.toml": base[:start] + f"keys = {keys_literal}" + base[end:]})

    def test_a_hash_that_is_not_64_lowercase_hex_is_rejected(self) -> None:
        for literal in (
            f'"{"A" * 64}"',  # uppercase hex
            f'"{"0" * 63}"',  # one short
            f'"{"0" * 65}"',  # one long
            f'"{"g" * 64}"',  # not hex
            f'"0x{"0" * 62}"',  # prefixed
            f'" {"0" * 63}"',  # leading space
            '""',
        ):
            with self.subTest(hash=literal):
                report = self.tx(literal)
                self.assertTrue(any("must be 64 lowercase hex characters" in e for e in report.errors), report.errors)

    def test_a_hash_that_is_not_a_string_is_rejected(self) -> None:
        for literal in ("7", "true", "[1]", "{ h = 1 }"):
            with self.subTest(hash=literal):
                self.assertTrue(any("hash: must be a string" in e for e in self.tx(literal).errors))

    def test_a_missing_request_or_hash_is_rejected(self) -> None:
        base = support.read_text(NOT_FOUND)
        without_request = base[: base.index("[request]")] + base[base.index("[[assert]]"):]
        report = support.run_validation({"a.toml": without_request})
        self.assertTrue(any("requires a [request] table with 'hash'" in e for e in report.errors), report.errors)

    def test_an_unknown_request_key_is_rejected_rather_than_forwarded(self) -> None:
        text = support.replace_once(support.read_text(NOT_FOUND), f'hash = "{ZERO_HASH}"', f'hash = "{ZERO_HASH}"\ntxHash = "{ZERO_HASH}"')
        report = support.run_validation({"a.toml": text})
        self.assertTrue(any("unknown [request] key(s) ['txHash']" in e for e in report.errors), report.errors)

    def test_keys_must_be_a_non_empty_array_of_base64_strings(self) -> None:
        cases = {
            '[]': "keys: must not be empty",
            '"AAAA"': "keys: must be an array of strings",
            '[7]': "keys: entry 0 must be a string",
            '["not base64!"]': "entry 0 is not a base64 string",
            '[""]': "entry 0 is not a base64 string",
        }
        for literal, expected in cases.items():
            with self.subTest(keys=literal):
                report = self.keys(literal)
                self.assertTrue(any(expected in e for e in report.errors), report.errors)

    def test_more_than_50_keys_exceed_the_d06_bound(self) -> None:
        key = support.load_toml(ENTRIES)["request"]["keys"][0]
        self.assertEqual(self.keys("[" + ", ".join(f'"{key}"' for _ in range(50)) + "]").errors, [])
        report = self.keys("[" + ", ".join(f'"{key}"' for _ in range(51)) + "]")
        self.assertTrue(any("has 51 entries; the engine allows at most 50" in e for e in report.errors), report.errors)

    def test_xdr_format_json_is_rejected(self) -> None:
        key_line = 'keys = ["AAAAAAAAAADk9ktTswqgsgEiA3ZlQ5Rpr6sFhq0wAf8MsPWF3M2K9g=="]'
        text = support.replace_once(support.read_text(ENTRIES), key_line, f'{key_line}\nxdrFormat = "json"')
        report = support.run_validation({"a.toml": text})
        self.assertTrue(any("only 'base64' is supported" in e for e in report.errors), report.errors)

    def test_a_vector_with_no_assertion_is_invalid(self) -> None:
        base = support.read_text(NOT_FOUND)
        report = support.run_validation({"a.toml": base[: base.index("[[assert]]")]})
        self.assertTrue(any("at least one [[assert]]" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()
