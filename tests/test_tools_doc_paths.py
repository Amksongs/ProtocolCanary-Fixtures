"""docs/tools.md names only repository paths that exist (issue #451, F-132).

The document is the reference for the command-line tools. Every
repository-relative path written in backticks with one of the pack or tool
prefixes has to resolve to a file or directory, so a renamed schema cannot
leave a stale name behind.

Run with: python3 -m unittest tests.test_tools_doc_paths
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DOC = REPO_ROOT / "docs" / "tools.md"

# A backtick-quoted token that starts with a repository directory. `protocol-NN`
# is only a placeholder when it is written with letters, so `protocol-28/` is
# checked like any other prefix.
_PATH_PATTERN = re.compile(r"`((?:tools|tests|schemas|docs|protocol-\d+|\.github)/[^`\s]*)`")
_PLACEHOLDER_CHARS = ("<", ">", "*")


def documented_paths(text: str) -> list[tuple[int, str]]:
    """Return ``(line number, path)`` for every checkable path in ``text``."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _PATH_PATTERN.finditer(line):
            path = match.group(1)
            if any(char in path for char in _PLACEHOLDER_CHARS):
                continue
            found.append((number, path))
    return found


class ToolsDocPathTests(unittest.TestCase):
    def test_every_documented_repository_path_exists(self) -> None:
        paths = documented_paths(TOOLS_DOC.read_text(encoding="utf-8"))
        self.assertGreater(len(paths), 0, "the scan found no paths; the pattern is broken")
        missing = [
            f"docs/tools.md:{number}: `{path}`"
            for number, path in paths
            if not (REPO_ROOT / path).exists()
        ]
        self.assertEqual(missing, [], "paths named in docs/tools.md that do not exist")


class DocumentedPathsHelperTests(unittest.TestCase):
    def test_reports_the_line_of_every_path(self) -> None:
        text = "intro\nsee `tools/a.py` and `schemas/b.json`\n\n`tests/c.py`\n"
        self.assertEqual(
            documented_paths(text),
            [(2, "tools/a.py"), (2, "schemas/b.json"), (4, "tests/c.py")],
        )

    def test_skips_placeholders_and_globs(self) -> None:
        text = "`tools/<name>.py` `schemas/*.json` `docs/x>y` `tools/ok.py`"
        self.assertEqual(documented_paths(text), [(1, "tools/ok.py")])

    def test_ignores_tokens_outside_the_known_prefixes(self) -> None:
        text = "`README.md` `protocol-NN/` `src/x.py` `--flag` `toolsx/y`"
        self.assertEqual(documented_paths(text), [])

    def test_a_missing_path_is_named_with_its_line(self) -> None:
        text = "a\n`schemas/manifest-v1.schema.json`\n"
        self.assertEqual(
            [(n, p) for n, p in documented_paths(text) if not (REPO_ROOT / p).exists()],
            [(2, "schemas/manifest-v1.schema.json")],
        )


if __name__ == "__main__":
    unittest.main()
