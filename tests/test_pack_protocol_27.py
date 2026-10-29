"""Pack-level checks for the intentionally-empty Protocol 27 fixture pack.

Protocol 27 ("Zipper", CAP-0071-01 and CAP-0071-02) is not yet verified in
this repository. This test asserts the documented gap: the directory contains
no fixtures, no fixture claims CAP-0071-01/02 category/source, and the
documentation files describe the gap rather than fabricating coverage.
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

from tools.validate.validate import find_fixture_files

PACK = REPO_ROOT / "protocol-27"
README = PACK / "README.md"
DOCS = REPO_ROOT / "docs" / "protocol-27.md"


class Protocol27PackTests(unittest.TestCase):
    def test_protocol_27_pack_has_no_fixtures_yet(self) -> None:
        self.assertEqual(find_fixture_files(PACK), [])

    def test_protocol_27_readme_explains_the_gap(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("intentionally empty", text.lower())
        self.assertIn("CAP-0071-01", text)
        self.assertIn("CAP-0071-02", text)
        for ref in (
            "stellar/stellar-protocol/blob/master/core/cap-0071-01.md",
            "stellar/stellar-protocol/blob/master/core/cap-0071-02.md",
        ):
            self.assertIn(ref, text)
        self.assertIn(
            "stellar.org/blog/foundation-news/stellar-zipper-protocol-27-upgrade-guide",
            text,
        )

    def test_protocol_27_docs_describe_the_gap(self) -> None:
        text = DOCS.read_text(encoding="utf-8")
        self.assertIn("CAP-0071-01", text)
        self.assertIn("CAP-0071-02", text)
        self.assertTrue(
            "nothing, yet" in text.lower() or "no fixture" in text.lower(),
            "docs/protocol-27.md should explicitly state the pack has no fixture yet",
        )
        for cap in ("cap-0071-01.md", "cap-0071-02.md"):
            self.assertIn(cap, text)
        self.assertIn(
            "stellar.org/blog/foundation-news/stellar-zipper-protocol-27-upgrade-guide",
            text,
        )

    def test_no_fixture_claims_cap_0071_in_protocol_27(self) -> None:
        # Even if a fixture were accidentally added later, this asserts the
        # documented gap is not violated by claiming CAP-0071 coverage.
        files = find_fixture_files(PACK)
        self.assertEqual(files, [])
