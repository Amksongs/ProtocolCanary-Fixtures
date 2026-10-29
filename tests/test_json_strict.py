"""Regression coverage for hostile JSON accepted by the command line tools."""
from __future__ import annotations

import unittest

from tools.common.json_strict import JSONInputError, load_json


class StrictJSONTests(unittest.TestCase):
    def test_valid_json_is_loaded(self) -> None:
        self.assertEqual(load_json('{"a": [1, true]}'), {"a": [1, True]})

    def test_duplicate_keys_are_refused_at_any_object_depth(self) -> None:
        for text in ('{"packDigest":"first","packDigest":"second"}',
                     '{"nested":{"key":1,"key":2}}'):
            with self.subTest(text=text), self.assertRaisesRegex(JSONInputError, "duplicate.*key"):
                load_json(text, "manifest")

    def test_deep_nesting_is_a_one_line_input_error(self) -> None:
        with self.assertRaisesRegex(JSONInputError, "nesting is too deep"):
            load_json("[" * 100_000 + "]" * 100_000, "record")

    def test_oversized_integer_is_a_one_line_input_error(self) -> None:
        with self.assertRaises(JSONInputError) as caught:
            load_json("{" + '"protocol":' + "9" * 5_000 + "}", "registry")
        self.assertIn("registry", str(caught.exception))

    def test_malformed_json_keeps_location_and_parser_message(self) -> None:
        with self.assertRaisesRegex(JSONInputError, r"line 1, column 2.*Expecting property name"):
            load_json("{x}", "registry")
