"""Tests for tools/validate/portable_names.py (F-049, issue #450).

One shared rule decides whether a fixture-pack name can be created on
Windows, and the validator, the registry generator and the archive verifier
all call it. The names below are written out rather than derived from
``WINDOWS_RESERVED_NAMES``: a table that is built from the implementation
cannot notice a truncated table (``range(1, 10)`` narrowed to
``range(1, 9)`` would shrink both sides and stay green), so this module is
the single place that says what the rule is.

Run with: python3 -m unittest tests.test_portable_names
      or: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PORTABLE_NAMES_PATH = REPO_ROOT / "tools" / "validate" / "portable_names.py"

_spec = importlib.util.spec_from_file_location(
    "portable_names_under_test", PORTABLE_NAMES_PATH
)
portable_names = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["portable_names_under_test"] = portable_names
_spec.loader.exec_module(portable_names)

# The Windows device names, grouped so the expected size (4 + 9 + 9) is
# visible in the table itself rather than only in the assertion.
_CON_STEMS = ("CON", "PRN", "AUX", "NUL")
_COM_STEMS = (
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
)
_LPT_STEMS = (
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
)
_RESERVED_STEMS = _CON_STEMS + _COM_STEMS + _LPT_STEMS


def _reserved_spellings(stem: str) -> tuple[str, ...]:
    """Every spelling of one reserved device name that must be rejected.

    Upper, lower and mixed case, bare and with an extension, plus the
    trailing space or dot Windows strips before it resolves the stem
    (``con .toml`` and ``con..toml`` are still CON).
    """
    lower = stem.lower()
    mixed = stem[0] + stem[1:].lower()
    return (
        stem,
        lower,
        mixed,
        f"{lower}.toml",
        f"{mixed}.tar.gz",
        f"{lower} .toml",
        f"{lower}..toml",
    )


RESERVED_NAME_CASES = tuple(
    spelling
    for stem in _RESERVED_STEMS
    for spelling in _reserved_spellings(stem)
)

FORBIDDEN_CHARACTERS = ('<', '>', ':', '"', '|', '?', '*')


class PortableNameTestCase(unittest.TestCase):
    """Assertion helpers that also check the error payload."""

    def assert_segment_rejected(self, segment: str) -> portable_names.PortableNameError:
        with self.assertRaises(portable_names.PortableNameError) as caught:
            portable_names.check_segment(segment)
        error = caught.exception
        self.assertEqual(error.segment, segment)
        self.assertTrue(error.problem, "problem must say what is wrong")
        if segment:
            self.assertIn(repr(segment), str(error), "message must name the segment")
        return error

    def assert_path_rejected(
        self, path: str, offending_segment: str
    ) -> portable_names.PortableNameError:
        with self.assertRaises(portable_names.PortableNameError) as caught:
            portable_names.check_path(path)
        error = caught.exception
        self.assertEqual(error.segment, offending_segment)
        self.assertTrue(error.problem, "problem must say what is wrong")
        return error


class ReservedNameTests(PortableNameTestCase):
    def test_table_has_four_plus_nine_plus_nine_stems(self) -> None:
        self.assertEqual(len(_CON_STEMS), 4)
        self.assertEqual(len(_COM_STEMS), 9)
        self.assertEqual(len(_LPT_STEMS), 9)
        self.assertEqual(len(_RESERVED_STEMS), 4 + 9 + 9)
        self.assertEqual(len(set(_RESERVED_STEMS)), 4 + 9 + 9)

    def test_every_stem_has_every_spelling_in_the_table(self) -> None:
        # Asserted stem by stem, so a table that silently dropped COM9 --
        # the failure mode this module exists to prevent -- is named here
        # instead of shrinking with the implementation.
        for stem in _RESERVED_STEMS:
            with self.subTest(stem=stem):
                spellings = _reserved_spellings(stem)
                self.assertEqual(len(spellings), 7)
                for spelling in spellings:
                    self.assertIn(spelling, RESERVED_NAME_CASES)
        self.assertEqual(len(RESERVED_NAME_CASES), 22 * 7)
        self.assertEqual(len(set(RESERVED_NAME_CASES)), 22 * 7)

    def test_the_two_documented_spellings_are_present(self) -> None:
        for name in ("nul.toml", "Com9.tar.gz", "con .toml", "con..toml"):
            with self.subTest(name=name):
                self.assertIn(name, RESERVED_NAME_CASES)

    def test_the_module_table_matches_the_names_above(self) -> None:
        self.assertEqual(len(portable_names.WINDOWS_RESERVED_NAMES), 4 + 9 + 9)
        self.assertEqual(
            set(portable_names.WINDOWS_RESERVED_NAMES), set(_RESERVED_STEMS)
        )

    def test_every_reserved_name_is_rejected(self) -> None:
        for name in RESERVED_NAME_CASES:
            with self.subTest(name=name):
                self.assert_segment_rejected(name)

    def test_names_that_only_look_reserved_are_accepted(self) -> None:
        for name in (
            "COM0",
            "com0",
            "LPT0",
            "lpt0",
            "COM10",
            "com10",
            "LPT10",
            "CONSOLE",
            "console",
            "aux1",
            "AUX1",
            "CONS",
            "\u0421ON",  # Cyrillic ES, not an ASCII C
            "\u0421on.toml",
        ):
            with self.subTest(name=name):
                portable_names.check_segment(name)


class TrailingDotOrSpaceTests(PortableNameTestCase):
    def test_trailing_dot_or_space_is_rejected(self) -> None:
        for name in (
            "name.",
            "name ",
            ".",
            "..",
            "...",
            "a..",
            "a. ",
            "a .",
            "leading.",
            "with space ",
        ):
            with self.subTest(name=name):
                self.assert_segment_rejected(name)

    def test_inner_dots_and_a_leading_dot_are_accepted(self) -> None:
        for name in (
            ".hidden",
            ".hidden.toml",
            "a.b",
            "a.b.c",
            "a b",
            "a..b",
            "trailing_space_inside.toml",
        ):
            with self.subTest(name=name):
                portable_names.check_segment(name)


class ForbiddenCharacterTests(PortableNameTestCase):
    def test_each_forbidden_character_is_rejected_on_its_own(self) -> None:
        for character in FORBIDDEN_CHARACTERS:
            with self.subTest(character=character):
                error = self.assert_segment_rejected(character)
                self.assertIn(character, error.problem)

    def test_each_forbidden_character_is_rejected_inside_a_longer_name(self) -> None:
        for character in FORBIDDEN_CHARACTERS:
            for name in (
                f"a{character}b.toml",
                f"{character}leading",
                f"trailing{character}",
                f"a{character}{character}b",
            ):
                with self.subTest(character=character, name=name):
                    error = self.assert_segment_rejected(name)
                    self.assertIn(character, error.problem)

    def test_allowed_punctuation_and_non_ascii_letters_are_accepted(self) -> None:
        for name in (
            "-",
            "_",
            "+",
            "a-b_c+d.toml",
            "a-b_c+d",
            "\u00e9",
            "na\u00efve.toml",
            "\u65e5\u672c\u8a9e.toml",
            "\u0421ON.toml",  # Cyrillic look-alike, not reserved
        ):
            with self.subTest(name=name):
                portable_names.check_segment(name)


class EmptySegmentTests(PortableNameTestCase):
    def test_empty_segment_is_rejected(self) -> None:
        error = self.assert_segment_rejected("")
        self.assertIn("empty", error.problem)

    def test_empty_segment_in_a_path_is_rejected(self) -> None:
        for path in ("a//b", "/a", "a/", "", "/", "a//b//c"):
            with self.subTest(path=path):
                error = self.assert_path_rejected(path, "")
                self.assertIn("empty", error.problem)

    def test_a_path_without_empty_segments_is_accepted(self) -> None:
        for path in ("a/b/c.toml", "a", "a.toml", "xdr/cap-0083/a.toml"):
            with self.subTest(path=path):
                portable_names.check_path(path)

    def test_a_reserved_or_forbidden_segment_in_a_path_is_rejected(self) -> None:
        for path, offending in (
            ("a/CON/b", "CON"),
            ("xdr/con.toml", "con.toml"),
            ("a/b/c.", "c."),
            ("a/b:c/d", "b:c"),
        ):
            with self.subTest(path=path):
                self.assert_path_rejected(path, offending)


class ErrorPayloadTests(PortableNameTestCase):
    def test_error_carries_the_offending_segment_and_problem(self) -> None:
        error = self.assert_segment_rejected("con.toml")
        self.assertEqual(error.segment, "con.toml")
        self.assertTrue(error.problem)
        self.assertIn("con.toml", str(error))
        self.assertIn(error.problem, str(error))

    def test_error_message_names_the_offending_path_segment(self) -> None:
        error = self.assert_path_rejected("a/CON/b.toml", "CON")
        self.assertIn(repr("CON"), str(error))
        self.assertIn("device name", str(error))
        # The message names the bad segment, not merely the whole path.
        self.assertNotIn("a/CON/b.toml", str(error))

    def test_error_is_a_value_error(self) -> None:
        self.assertTrue(issubclass(portable_names.PortableNameError, ValueError))


if __name__ == "__main__":
    unittest.main()
