"""Documentation must name exactly the vocabulary the validator accepts.

Issue #162 was a real three-way drift: README.md documented the `field-absent`
RPC assert kind while `schemas/fixture-v1.schema.json`'s enum and
`validate.py`'s `RPC_ASSERT_KINDS` both omitted it. The schema/validator leg is
now checked by `tools/validate/schema_sync.py` (run from
`tests/test_validate.py`'s `SchemaSyncTests`), but nothing compared the human
documentation -- README.md's assertion-vocabulary table and CONTRIBUTING.md's
per-surface field table -- against those same lists. These tests close that
last leg; with both checks in place the three artifacts are pinned together.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
README_PATH = REPO_ROOT / "README.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"

_spec = importlib.util.spec_from_file_location("validate_vocabulary", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_vocabulary"] = validate
_spec.loader.exec_module(validate)


def markdown_rows(path: Path, anchor: str, columns: int) -> list[list[str]]:
    """Rows of the markdown table following `anchor`, which must have `columns` cells.

    Parsing stops at the next heading so a table elsewhere in the same file,
    with a different shape, cannot be picked up by mistake.
    """
    text = path.read_text(encoding="utf-8")
    body = text[text.index(anchor) + len(anchor) :]
    next_heading = re.search(r"^#{1,4} ", body, re.MULTILINE)
    if next_heading:
        body = body[: next_heading.start()]
    rows = []
    for line in body.splitlines():
        if line.startswith("|") and not re.fullmatch(r"[|\s:-]+", line):
            # Split on unescaped pipes only: CONTRIBUTING.md separates
            # vocabulary values inside one cell with a literal `\|`.
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))]
            if len(cells) == columns:
                rows.append(cells)
    assert len(rows) > 1, f"no table with {columns} columns found after {anchor!r}"
    return rows[1:]  # drop the header row


def readme_vocabulary() -> dict[tuple[str, str], set[str]]:
    """README's assertion-vocabulary table, keyed by (surface, field)."""
    table: dict[tuple[str, str], set[str]] = {}
    for surface, field, value, _assertion in markdown_rows(
        README_PATH, "### Assertion vocabulary", 4
    ):
        key = (surface.strip("`"), field.strip("`"))
        table.setdefault(key, set()).add(value.strip("`"))
    return table


def contributing_rpc_methods() -> set[str]:
    """Method names from CONTRIBUTING.md's per-surface field table."""
    for surface, fields in markdown_rows(CONTRIBUTING_PATH, "Per-surface body", 2):
        if surface.strip("`") == "rpc":
            return set(re.findall(r'"([a-z0-9][a-z0-9-]*)"', fields))
    raise AssertionError("no `rpc` row in CONTRIBUTING.md's per-surface table")


class TestDocumentationMatchesVocabulary(unittest.TestCase):
    def test_readme_table_names_exactly_the_rpc_assert_kinds(self) -> None:
        documented = readme_vocabulary()[("rpc", "[[assert]].kind")]
        self.assertEqual(documented, validate.RPC_ASSERT_KINDS)

    def test_readme_table_names_exactly_the_xdr_kinds(self) -> None:
        self.assertEqual(readme_vocabulary()[("xdr", "kind")], validate.XDR_KINDS)

    def test_readme_table_names_exactly_the_soroban_expect_kinds(self) -> None:
        self.assertEqual(
            readme_vocabulary()[("soroban", "[expect].kind")],
            validate.SOROBAN_EXPECT_KINDS,
        )

    def test_contributing_names_exactly_the_rpc_methods(self) -> None:
        self.assertEqual(contributing_rpc_methods(), validate.RPC_METHODS)

    def test_readme_table_has_no_row_for_an_unsupported_surface(self) -> None:
        # A row for a surface the validator rejects would document something no
        # fixture can use, and would silently widen the table's keys.
        surfaces = {surface for surface, _field in readme_vocabulary()}
        self.assertEqual(surfaces, validate.SURFACES)


if __name__ == "__main__":
    unittest.main()
