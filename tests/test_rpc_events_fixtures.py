"""Tests for the RPC event-filter vector (F-040, issue #297).

Run with: python3 -m unittest discover tests

``tests/fixtures/rpc/events/get-events-multitopic.toml`` declares a
``getEvents`` request with two filters (the approved D-06 ceiling; upstream
allows five) and topic patterns made of exact base64 ``ScVal`` segments and the
``*`` wildcard. These tests prove that the request obeys the D-06 bounds, that
every segment really is the ScVal its header says it is, that the assertions
hold for a recorded live answer and fail for wrong ones, and that a request
past the bounds is an invalid fixture.

The recorded answer is a trimmed capture from
https://soroban-testnet.stellar.org on 2026-10-23 (UTC).
"""
from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpc_vector_support as support  # noqa: E402
import scval_xdr  # noqa: E402

validate = support.validate
evaluate = support.capture_live.evaluate_asserts

VECTOR = "events/get-events-multitopic.toml"
D06_MAX_FILTERS = 2
UPSTREAM_MAX_FILTERS = 5
CONTRACT_ID = "CADR3ZIARTBJDBDMNBXCKEVMSAETCPCJK3NPOHUQBOMF5LWPODMQU5RQ"

LIVE_EVENT = {
    "type": "contract",
    "ledger": 5349248,
    "ledgerClosedAt": "2026-10-23T15:37:07Z",
    "contractId": CONTRACT_ID,
    "id": "0022974845218234368-0000000000",
    "operationIndex": 0,
    "transactionIndex": 10,
    "txHash": "f104ac201f1f87838aad796b6edbb063514bf98cfc2a97a6a836dac94b14a2ca",
    "topic": ["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"],
    "value": "AAAAEQAAAAEAAAAE",
}
LIVE_ANSWER = {
    "events": [LIVE_EVENT],
    "cursor": "0022974845218234368-0000000000",
    "latestLedger": 5349347,
    "oldestLedger": 5228388,
    "latestLedgerCloseTime": "1792770322",
    "oldestLedgerCloseTime": "1792165527",
}
# The event fields CA-01 documents for a getEvents answer, with their JSON types.
EVENT_FIELDS = {
    "type": str,
    "ledger": int,
    "ledgerClosedAt": str,
    "contractId": str,
    "id": str,
    "operationIndex": int,
    "transactionIndex": int,
    "txHash": str,
    "topic": list,
    "value": str,
}
EVENT_TYPES = {"contract", "system", "diagnostic"}


def event_problems(event: object) -> list[str]:
    """What is wrong with one event of a getEvents answer, against the documented shape."""
    if not isinstance(event, dict):
        return ["the event is not an object"]
    problems = [f"missing field {name!r}" for name in EVENT_FIELDS if name not in event]
    for name, expected in EVENT_FIELDS.items():
        if name in event and (isinstance(event[name], bool) or not isinstance(event[name], expected)):
            problems.append(f"field {name!r} is {type(event[name]).__name__}, expected {expected.__name__}")
    if event.get("type") not in EVENT_TYPES:
        problems.append(f"type {event.get('type')!r} is not one of {sorted(EVENT_TYPES)}")
    topic = event.get("topic")
    if isinstance(topic, list) and not all(isinstance(segment, str) for segment in topic):
        problems.append("topic must be an array of base64 strings")
    return problems


def strkey_is_valid(text: str, version_byte: int) -> bool:
    """Whether ``text`` is a well-formed Stellar strkey with the given version byte."""
    try:
        raw = base64.b32decode(text + "=" * (-len(text) % 8), casefold=False)
    except ValueError:
        return False
    if len(raw) != 35 or raw[0] != version_byte:
        return False
    crc = 0
    for byte in raw[:-2]:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return raw[-2:] == crc.to_bytes(2, "little")


class EventVectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = support.load_toml(VECTOR)
        self.filters = self.data["request"]["filters"]

    def test_the_vector_validates_cleanly(self) -> None:
        self.assertEqual(support.run_validation({"a.toml": support.read_text(VECTOR)}).errors, [])
        exit_code, stdout, _ = support.run_main([str(support.RPC_VECTORS / "events")])
        self.assertEqual(exit_code, 0)
        self.assertIn("OK: 1 fixture file(s) valid", stdout)

    def test_it_is_a_get_events_request_with_two_filters(self) -> None:
        self.assertEqual(self.data["method"], "get-events")
        self.assertEqual(len(self.filters), 2)

    def test_the_filter_count_is_within_the_d06_bound_and_below_the_upstream_one(self) -> None:
        self.assertEqual(validate._RPC_MAX_FILTERS, D06_MAX_FILTERS)
        self.assertLessEqual(len(self.filters), D06_MAX_FILTERS)
        self.assertLess(D06_MAX_FILTERS, UPSTREAM_MAX_FILTERS)

    def test_each_filter_uses_only_declared_keys_and_types(self) -> None:
        for flt in self.filters:
            self.assertLessEqual(set(flt), {"type", "contractIds", "topics"})
            self.assertIn(flt["type"], validate._RPC_EVENT_FILTER_TYPES)
            self.assertLessEqual(len(flt.get("contractIds", [])), 5)
            self.assertLessEqual(len(flt["topics"]), 5)
            for pattern in flt["topics"]:
                self.assertLessEqual(len(pattern), 5)
                self.assertTrue(all(isinstance(segment, str) for segment in pattern))

    def test_the_contract_id_is_a_well_formed_contract_strkey(self) -> None:
        contract_ids = self.filters[0]["contractIds"]
        self.assertEqual(contract_ids, [CONTRACT_ID])
        self.assertTrue(strkey_is_valid(CONTRACT_ID, 2 << 3), "a contract strkey has version byte 0x10")
        self.assertFalse(strkey_is_valid(CONTRACT_ID[:-1] + ("A" if CONTRACT_ID[-1] != "A" else "B"), 2 << 3))

    def test_every_exact_segment_is_the_scval_the_header_names(self) -> None:
        first, second = self.filters
        self.assertEqual(scval_xdr.decode_base64(first["topics"][0][0]), ("symbol", "new_block_event"))
        self.assertEqual(scval_xdr.decode_base64(second["topics"][0][0]), ("symbol", "transfer"))

    def test_the_other_segments_are_wildcards(self) -> None:
        self.assertEqual(self.filters[0]["topics"], [["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]])
        self.assertEqual(self.filters[1]["topics"][0][1:], ["*", "*"])

    def test_every_non_wildcard_segment_decodes_as_a_canonical_scval(self) -> None:
        for flt in self.filters:
            for pattern in flt["topics"]:
                for segment in pattern:
                    if segment == "*":
                        continue
                    with self.subTest(segment=segment):
                        kind, value = scval_xdr.decode_base64(segment)
                        # Canonical: re-encoding gives the same base64 back.
                        self.assertEqual(base64.b64encode(scval_xdr.encode((kind, value))).decode(), segment)

    def test_the_assertions_hold_for_the_recorded_live_answer(self) -> None:
        self.assertEqual(evaluate(self.data["assert"], LIVE_ANSWER), [])

    def test_an_answer_with_no_events_still_satisfies_the_envelope_assertions(self) -> None:
        self.assertEqual(evaluate(self.data["assert"], dict(LIVE_ANSWER, events=[])), [])

    def test_a_malformed_answer_fails(self) -> None:
        asserts = self.data["assert"]
        for label, answer in (
            ("events missing", {k: v for k, v in LIVE_ANSWER.items() if k != "events"}),
            ("events not an array", dict(LIVE_ANSWER, events={})),
            ("events null", dict(LIVE_ANSWER, events=None)),
            ("latestLedger as text", dict(LIVE_ANSWER, latestLedger="5349347")),
            ("cursor as number", dict(LIVE_ANSWER, cursor=7)),
        ):
            with self.subTest(case=label):
                self.assertTrue(evaluate(asserts, answer))

    def test_the_recorded_event_has_the_documented_structure(self) -> None:
        self.assertEqual(event_problems(LIVE_EVENT), [])
        self.assertEqual(set(LIVE_EVENT), set(EVENT_FIELDS))

    def test_a_wrongly_shaped_event_is_reported(self) -> None:
        self.assertTrue(event_problems("nope"))
        self.assertTrue(event_problems({k: v for k, v in LIVE_EVENT.items() if k != "topic"}))
        self.assertTrue(event_problems(dict(LIVE_EVENT, ledger="5349248")))
        self.assertTrue(event_problems(dict(LIVE_EVENT, ledger=True)))
        self.assertTrue(event_problems(dict(LIVE_EVENT, type="other")))
        self.assertTrue(event_problems(dict(LIVE_EVENT, topic=[1])))


class FilterBoundTests(unittest.TestCase):
    """A request past the D-06 bounds is an invalid fixture."""

    def with_filters(self, count: int):
        base = support.read_text(VECTOR)
        marker = "[[request.filters]]"
        head = base[: base.index(marker)]
        tail = base[base.index("[[assert]]"):]
        tables = "".join(f'{marker}\ntype = "contract"\ntopics = [["*"]]\n\n' for _ in range(count))
        return support.run_validation({"a.toml": head + tables + tail})

    def test_two_filters_are_accepted(self) -> None:
        self.assertEqual(self.with_filters(2).errors, [])

    def test_one_filter_is_accepted(self) -> None:
        self.assertEqual(self.with_filters(1).errors, [])

    def test_three_or_more_filters_are_rejected(self) -> None:
        for count in (3, 4, 5):
            with self.subTest(filters=count):
                report = self.with_filters(count)
                self.assertFalse(report.ok)
                self.assertTrue(
                    any(f"has {count} filters; the engine allows at most 2" in e for e in report.errors),
                    report.errors,
                )

    def test_three_filters_fail_the_command_line_run(self) -> None:
        base = support.read_text(VECTOR)
        marker = "[[request.filters]]"
        text = base[: base.index(marker)] + (marker + '\ntype = "contract"\n\n') * 3 + base[base.index("[[assert]]"):]
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "a.toml").write_text(text, encoding="utf-8")
            exit_code, _stdout, stderr = support.run_main([scratch])
        self.assertEqual(exit_code, 1)
        self.assertIn("has 3 filters; the engine allows at most 2", stderr)

    def mutate(self, old: str, new: str):
        return support.run_validation({"a.toml": support.replace_once(support.read_text(VECTOR), old, new)})

    def test_a_filter_with_the_wrong_shape_is_rejected(self) -> None:
        cases = (
            ('type = "contract"\ncontractIds', 'type = "other"\ncontractIds', "type must be 'contract', 'system' or 'diagnostic'"),
            ('topics = [["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]]', 'topics = "AAAA"', "topics must be an array of arrays"),
            ('topics = [["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]]', 'topics = [["AAAA", 7]]', "a topics entry must contain only strings"),
            ('topics = [["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]]', 'topics = ["AAAA"]', "a topics entry must be an array of strings"),
            ('topics = [["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]]', 'topics = [["a","b","c","d","e","f"]]', "a topics entry has more than 5 entries"),
            ('topics = [["AAAADwAAAA9uZXdfYmxvY2tfZXZlbnQA"]]', 'topics = [["*"],["*"],["*"],["*"],["*"],["*"]]', "topics has more than 5 entries"),
            (f'contractIds = ["{CONTRACT_ID}"]', f'contractIds = ["{CONTRACT_ID}", "{CONTRACT_ID}", "{CONTRACT_ID}", "{CONTRACT_ID}", "{CONTRACT_ID}", "{CONTRACT_ID}"]', "contractIds has more than 5 entries"),
            (f'contractIds = ["{CONTRACT_ID}"]', "contractIds = [7]", "contractIds must contain only strings"),
            (f'contractIds = ["{CONTRACT_ID}"]', f'contractIds = ["{CONTRACT_ID}"]\nunknownKey = 1', "unknown key 'unknownKey'"),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected):
                report = self.mutate(old, new)
                self.assertTrue(any(expected in e for e in report.errors), report.errors)

    def test_filters_that_are_not_a_list_of_tables_are_rejected(self) -> None:
        base = support.read_text(VECTOR)
        head = base[: base.index("[[request.filters]]")]
        tail = base[base.index("[[assert]]"):]
        # `filters` must be set in [request] itself, before [request.pagination].
        head = support.replace_once(head, "startLedger = 5347400\n", 'startLedger = 5347400\nfilters = "contract"\n')
        report = support.run_validation({"a.toml": head + tail})
        self.assertTrue(any("filters: must be an array of tables" in e for e in report.errors), report.errors)

    def test_the_request_keys_are_the_documented_getevents_parameters(self) -> None:
        self.assertEqual(
            set(validate._RPC_METHOD_PARAMS["get-events"]),
            {"startLedger", "endLedger", "filters", "pagination", "xdrFormat"},
        )
        report = self.mutate("startLedger = 5347400", "startLedger = 5347400\ncursor = \"x\"")
        self.assertTrue(any("unknown [request] key(s) ['cursor']" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()
