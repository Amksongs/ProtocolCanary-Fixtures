"""Tests for tools/registry/diff.py (F-064).

The tool compares two ``registry-v1.json`` files so that the changelog of a
pack release can be written from the registry data instead of from ``git
log``. The tests cover the comparison itself (hand-built registries), the
rules that make a registry unusable (duplicate id, empty fixtures list,
unsupported version, unreadable file), the command line (formats, exit
codes, the protocol guard) and a comparison of two registries generated from
this repository's own pack at two different states.

Run with: python3 -m unittest tests/test_registry_diff.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
DIFF_PATH = REPO_ROOT / "tools" / "registry" / "diff.py"
GENERATE_PATH = REPO_ROOT / "tools" / "registry" / "generate.py"
PACK_DIR = REPO_ROOT / "protocol-28"

_spec = importlib.util.spec_from_file_location("registry_diff", DIFF_PATH)
diff = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["registry_diff"] = diff
_spec.loader.exec_module(diff)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64


def fixture(identifier: str, path: str, sha256: str, surface: str = "xdr") -> dict:
    """A minimal registry fixture entry."""
    return {
        "id": identifier,
        "path": path,
        "sha256": sha256,
        "surface": surface,
        "category": "cap-0083",
        "description": f"fixture {identifier}",
        "payloads": [],
    }


def registry(
    fixtures: list[dict],
    protocol: int = 28,
    digest: str = DIGEST_A,
    version: int = 1,
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
    """Added, removed and changed fixtures are reported correctly."""

    def setUp(self) -> None:
        self.old = registry(
            [
                fixture("p28-b", "xdr/b.toml", SHA_B),
                fixture("p28-a", "xdr/a.toml", SHA_A),
                fixture("p28-c", "xdr/c.toml", SHA_C),
            ],
            digest=DIGEST_A,
        )
        self.new = registry(
            [
                fixture("p28-a", "xdr/a.toml", SHA_A),
                fixture("p28-c", "xdr/c2.toml", SHA_D),
                fixture("p28-d", "xdr/d.toml", SHA_B),
            ],
            digest=DIGEST_B,
        )
        self.diff = diff.diff_registries(self.old, self.new)

    def test_a_new_fixture_is_added(self) -> None:
        self.assertEqual([entry["id"] for entry in self.diff["added"]], ["p28-d"])
        self.assertEqual(self.diff["added"][0]["path"], "xdr/d.toml")

    def test_a_missing_fixture_is_removed(self) -> None:
        self.assertEqual([entry["id"] for entry in self.diff["removed"]], ["p28-b"])
        self.assertEqual(self.diff["removed"][0]["path"], "xdr/b.toml")

    def test_a_fixture_with_a_different_hash_is_changed(self) -> None:
        self.assertEqual([entry["id"] for entry in self.diff["changed"]], ["p28-c"])
        changed = self.diff["changed"][0]
        self.assertEqual(changed["old_sha256"], SHA_C)
        self.assertEqual(changed["new_sha256"], SHA_D)
        self.assertEqual(changed["old_path"], "xdr/c.toml")
        self.assertEqual(changed["new_path"], "xdr/c2.toml")

    def test_a_fixture_that_only_moved_is_reported_as_moved(self) -> None:
        old = registry([fixture("p28-a", "xdr/a.toml", SHA_A)])
        new = registry([fixture("p28-a", "xdr/moved/a.toml", SHA_A)])
        result = diff.diff_registries(old, new)
        self.assertEqual(result["changed"], [])
        self.assertEqual([entry["id"] for entry in result["moved"]], ["p28-a"])
        self.assertEqual(result["moved"][0]["old_path"], "xdr/a.toml")
        self.assertEqual(result["moved"][0]["new_path"], "xdr/moved/a.toml")

    def test_an_unchanged_fixture_is_not_listed(self) -> None:
        listed = [entry["id"] for entry in self.diff["added"] + self.diff["removed"] + self.diff["changed"]]
        self.assertNotIn("p28-a", listed)
        self.assertEqual(self.diff["unchanged"], 1)

    def test_the_output_is_sorted_by_id(self) -> None:
        old = registry([fixture(f"p28-{letter}", f"xdr/{letter}.toml", SHA_A) for letter in "cba"])
        new = registry([fixture(f"p28-{letter}", f"xdr/{letter}.toml", SHA_A) for letter in "cba"])
        result = diff.diff_registries(old, new)
        self.assertEqual(result["unchanged"], 3)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["moved"], [])

    def test_a_fixture_that_only_changed_content_is_changed(self) -> None:
        old = registry([fixture("p28-a", "xdr/a.toml", SHA_A)])
        new = registry([fixture("p28-a", "xdr/a.toml", SHA_B)])
        result = diff.diff_registries(old, new)
        self.assertEqual([entry["id"] for entry in result["changed"]], ["p28-a"])
        self.assertEqual(result["changed"][0]["old_sha256"], SHA_A)
        self.assertEqual(result["changed"][0]["new_sha256"], SHA_B)

    def test_two_identical_registries_differ_in_nothing(self) -> None:
        result = diff.diff_registries(self.old, self.old)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["moved"], [])
        self.assertEqual(result["unchanged"], 3)


class RegistryValidationTests(unittest.TestCase):
    """A registry that cannot be compared is refused with a reason."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registry-diff-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def load(self, document: object, name: str = "registry.json") -> dict:
        return diff.load_registry(write_json(self.tmp / name, document))

    def test_a_valid_registry_is_loaded(self) -> None:
        document = registry([fixture("p28-a", "xdr/a.toml", SHA_A)])
        self.assertEqual(self.load(document)["fixtures"][0]["id"], "p28-a")

    def test_a_missing_file_is_refused(self) -> None:
        with self.assertRaises(diff.DiffError) as caught:
            diff.load_registry(self.tmp / "absent.json")
        self.assertIn("no such file", str(caught.exception))

    def test_a_file_that_is_not_json_is_refused(self) -> None:
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(diff.DiffError) as caught:
            diff.load_registry(path)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_a_document_that_is_not_an_object_is_refused(self) -> None:
        with self.assertRaises(diff.DiffError) as caught:
            self.load([1, 2, 3])
        self.assertIn("JSON object", str(caught.exception))

    def test_a_duplicate_fixture_id_is_refused(self) -> None:
        document = registry(
            [fixture("p28-a", "xdr/a.toml", SHA_A), fixture("p28-a", "xdr/b.toml", SHA_B)]
        )
        with self.assertRaises(diff.DiffError) as caught:
            self.load(document)
        self.assertIn("appears twice", str(caught.exception))

    def test_an_unsupported_registry_version_is_refused(self) -> None:
        document = registry([fixture("p28-a", "xdr/a.toml", SHA_A)], version=2)
        with self.assertRaises(diff.DiffError) as caught:
            self.load(document)
        self.assertIn("registry-v1.schema.json", str(caught.exception))

    def test_an_empty_fixtures_list_is_refused(self) -> None:
        with self.assertRaises(diff.DiffError) as caught:
            self.load(registry([]))
        self.assertIn("fixtures list is empty", str(caught.exception))

    def test_a_registry_that_breaks_the_schema_is_refused(self) -> None:
        document = registry([fixture("p28-a", "xdr/a.toml", SHA_A)])
        del document["packDigest"]
        with self.assertRaises(diff.DiffError) as caught:
            self.load(document)
        self.assertIn("registry-v1.schema.json", str(caught.exception))


class CommandLineTests(unittest.TestCase):
    """The command line reports the difference and fails on bad input."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registry-diff-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.old_path = write_json(
            self.tmp / "old.json",
            registry([fixture("p28-a", "xdr/a.toml", SHA_A)], digest=DIGEST_A),
        )
        self.new_path = write_json(
            self.tmp / "new.json",
            registry(
                [
                    fixture("p28-a", "xdr/a.toml", SHA_B),
                    fixture("p28-b", "xdr/b.toml", SHA_C),
                ],
                digest=DIGEST_B,
            ),
        )

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = diff.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_comparing_two_registries_exits_zero_even_when_they_differ(self) -> None:
        code, out, _ = self.run_tool(str(self.old_path), str(self.new_path))
        self.assertEqual(code, 0)
        self.assertIn("p28-b", out)

    def test_the_text_format_lists_the_changes(self) -> None:
        _, out, _ = self.run_tool(str(self.old_path), str(self.new_path))
        self.assertIn("added (1)", out)
        self.assertIn("removed (0)", out)
        self.assertIn("changed (1)", out)
        self.assertIn("moved (0)", out)
        self.assertIn("p28-b", out)
        self.assertIn(SHA_A, out)
        self.assertIn(SHA_B, out)

    def test_the_json_format_is_machine_readable(self) -> None:
        _, out, _ = self.run_tool(
            str(self.old_path), str(self.new_path), "--format", "json"
        )
        document = json.loads(out)
        self.assertEqual([entry["id"] for entry in document["added"]], ["p28-b"])
        self.assertEqual([entry["id"] for entry in document["changed"]], ["p28-a"])
        self.assertEqual(document["moved"], [])
        self.assertEqual(document["unchanged"], 0)
        self.assertEqual(document["old"]["packDigest"], DIGEST_A)
        self.assertEqual(document["new"]["packDigest"], DIGEST_B)

    def test_the_markdown_format_is_a_changelog_block(self) -> None:
        _, out, _ = self.run_tool(
            str(self.old_path), str(self.new_path), "--format", "markdown"
        )
        self.assertIn("### Added", out)
        self.assertIn("### Changed", out)
        self.assertIn("`p28-b`", out)
        self.assertNotIn("### Removed", out)

    def test_the_markdown_format_says_when_nothing_changed(self) -> None:
        _, out, _ = self.run_tool(
            str(self.old_path), str(self.old_path), "--format", "markdown"
        )
        self.assertIn("No fixture changed", out)

    def test_a_missing_file_exits_two(self) -> None:
        code, _, err = self.run_tool(str(self.tmp / "absent.json"), str(self.new_path))
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)

    def test_comparing_different_protocols_is_refused(self) -> None:
        other = write_json(
            self.tmp / "other.json",
            registry([fixture("p29-a", "xdr/a.toml", SHA_A)], protocol=29),
        )
        code, _, err = self.run_tool(str(self.old_path), str(other))
        self.assertEqual(code, 2)
        self.assertIn("protocol", err)
        self.assertIn("--allow-protocol-mismatch", err)

    def test_comparing_different_protocols_is_allowed_with_the_override(self) -> None:
        other = write_json(
            self.tmp / "other.json",
            registry([fixture("p29-a", "xdr/a.toml", SHA_A)], protocol=29),
        )
        code, out, _ = self.run_tool(
            str(self.old_path), str(other), "--allow-protocol-mismatch"
        )
        self.assertEqual(code, 0)
        self.assertIn("p29-a", out)

    def test_an_unknown_format_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_tool(str(self.old_path), str(self.new_path), "--format", "yaml")
        self.assertEqual(caught.exception.code, 2)

    def test_a_missing_argument_exits_two(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_tool(str(self.old_path))
        self.assertEqual(caught.exception.code, 2)

    def test_the_help_text_states_the_exit_codes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(DIFF_PATH), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Exit codes", result.stdout)
        self.assertIn("--allow-protocol-mismatch", result.stdout)


class RealRegistryTests(unittest.TestCase):
    """Two registries generated from this repository's own pack."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registry-diff-pack-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pack = self.tmp / "protocol-28"
        shutil.copytree(PACK_DIR, self.pack)
        self.old_path = self.tmp / "old-registry.json"
        self.new_path = self.tmp / "new-registry.json"

    def generate(self, output: Path) -> Path:
        result = subprocess.run(
            [sys.executable, str(GENERATE_PATH), str(self.pack), "--stdout"],
            capture_output=True,
            text=True,
            check=True,
        )
        output.write_text(result.stdout, encoding="utf-8")
        return output

    def test_two_registries_from_the_pack_at_different_states(self) -> None:
        old = self.generate(self.old_path)

        # Change one fixture, add one, remove one.
        changed = self.pack / "xdr" / "cap-0083" / "p28-xdr-cap83-empty-tx-set.toml"
        changed.write_text(
            changed.read_text(encoding="utf-8").replace(
                "round-trips byte-for-byte",
                "round-trips byte-for-byte (edited)",
            ),
            encoding="utf-8",
        )
        added = self.pack / "xdr" / "cap-0083" / "p28-xdr-cap83-empty-tx-set-copy.toml"
        added.write_text(
            changed.read_text(encoding="utf-8")
            .replace(
                'id = "p28-xdr-cap83-empty-tx-set"',
                'id = "p28-xdr-cap83-empty-tx-set-copy"',
            )
            .replace(
                "round-trips byte-for-byte (edited)",
                "round-trips byte-for-byte (copy)",
            ),
            encoding="utf-8",
        )
        (self.pack / "xdr" / "cap-0083" / "p28-xdr-cap83-empty-tx-set-malformed.toml").unlink()

        new = self.generate(self.new_path)

        result = diff.diff_registries(
            diff.load_registry(old), diff.load_registry(new)
        )
        self.assertEqual(
            [entry["id"] for entry in result["added"]],
            ["p28-xdr-cap83-empty-tx-set-copy"],
        )
        self.assertEqual(
            [entry["id"] for entry in result["removed"]],
            ["p28-xdr-cap83-empty-tx-set-malformed"],
        )
        self.assertEqual(
            [entry["id"] for entry in result["changed"]],
            ["p28-xdr-cap83-empty-tx-set"],
        )
        self.assertEqual(
            result["unchanged"], len(diff.load_registry(old)["fixtures"]) - 2
        )

    def test_the_two_registries_differ_in_their_pack_digest(self) -> None:
        old = self.generate(self.old_path)
        changed = self.pack / "xdr" / "cap-0083" / "p28-xdr-cap83-empty-tx-set.toml"
        changed.write_text(
            changed.read_text(encoding="utf-8") + "\n# a comment changes the hash\n",
            encoding="utf-8",
        )
        new = self.generate(self.new_path)
        self.assertNotEqual(
            diff.load_registry(old)["packDigest"], diff.load_registry(new)["packDigest"]
        )


def text_sections(output: str) -> dict[str, list[str]]:
    """The entry lines under each ``name (count):`` heading of the text format."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.endswith(":") and " (" in line:
            current = line.split(" (", 1)[0]
            sections[current] = []
        elif current is not None and line.startswith("  "):
            sections[current].append(line.strip())
        elif not line.startswith("  "):
            current = None
    return sections


def markdown_sections(text: str) -> dict[str, list[str]]:
    """The entry lines under each ``### Name`` heading of the Markdown format."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            sections[current] = []
        elif current is not None and line.strip():
            sections[current].append(line.strip())
    return sections


class OutputFormatTests(unittest.TestCase):
    """F-130 (issue #449): every kind of change in every output format."""

    NON_ASCII_PATH = "xdr/caf\u00e9/added.toml"

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registry-diff-formats-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.old_path = write_json(
            self.tmp / "old.json",
            registry(
                [
                    fixture("p28-removed", "xdr/removed.toml", SHA_C),
                    fixture("p28-changed", "xdr/changed.toml", SHA_A),
                    fixture("p28-moved", "xdr/old/moved.toml", SHA_B),
                    fixture("p28-stable", "xdr/stable.toml", SHA_D),
                ],
                digest=DIGEST_A,
            ),
        )
        self.new_path = write_json(
            self.tmp / "new.json",
            registry(
                [
                    fixture("p28-added", self.NON_ASCII_PATH, SHA_C),
                    fixture("p28-changed", "xdr/changed.toml", SHA_B),
                    fixture("p28-moved", "xdr/new/moved.toml", SHA_B),
                    fixture("p28-stable", "xdr/stable.toml", SHA_D),
                ],
                digest=DIGEST_B,
            ),
        )

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = diff.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_the_text_format_lists_every_change_under_its_heading(self) -> None:
        code, out, err = self.run_tool(str(self.old_path), str(self.new_path))
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        for heading in ("added (1):", "removed (1):", "changed (1):", "moved (1):"):
            self.assertIn(heading, out)
        self.assertIn("unchanged (1)", out)

        sections = text_sections(out)
        self.assertEqual(
            {name: len(entries) for name, entries in sections.items()},
            {"added": 1, "removed": 1, "changed": 1, "moved": 1},
        )
        self.assertIn("p28-added", sections["added"][0])
        self.assertIn(self.NON_ASCII_PATH, sections["added"][0])
        self.assertIn("p28-removed", sections["removed"][0])
        self.assertIn("xdr/removed.toml", sections["removed"][0])
        changed = sections["changed"][0]
        self.assertIn("p28-changed", changed)
        self.assertIn("xdr/changed.toml", changed)
        self.assertIn(SHA_A, changed)
        self.assertIn(SHA_B, changed)
        moved = sections["moved"][0]
        self.assertIn("p28-moved", moved)
        self.assertIn("xdr/old/moved.toml", moved)
        self.assertIn("xdr/new/moved.toml", moved)

    def test_the_markdown_format_has_a_section_for_every_change(self) -> None:
        code, out, err = self.run_tool(
            str(self.old_path), str(self.new_path), "--format", "markdown"
        )
        self.assertEqual(code, 0, err)
        sections = markdown_sections(out)
        self.assertEqual(set(sections), {"Added", "Removed", "Changed", "Moved"})
        self.assertEqual(len(sections["Added"]), 1)
        self.assertEqual(len(sections["Removed"]), 1)
        self.assertEqual(len(sections["Changed"]), 1)
        self.assertEqual(len(sections["Moved"]), 1)

        self.assertIn("p28-added", sections["Added"][0])
        self.assertIn(self.NON_ASCII_PATH, sections["Added"][0])
        self.assertIn("p28-removed", sections["Removed"][0])
        self.assertIn("xdr/removed.toml", sections["Removed"][0])
        changed = sections["Changed"][0]
        self.assertIn("p28-changed", changed)
        self.assertIn(SHA_A, changed)
        self.assertIn(SHA_B, changed)
        moved = sections["Moved"][0]
        self.assertIn("p28-moved", moved)
        self.assertIn("xdr/old/moved.toml", moved)
        self.assertIn("xdr/new/moved.toml", moved)

    def test_identical_registries_report_every_count_as_zero(self) -> None:
        code, out, err = self.run_tool(str(self.old_path), str(self.old_path))
        self.assertEqual(code, 0, err)
        for heading in ("added (0):", "removed (0):", "changed (0):", "moved (0):"):
            self.assertIn(heading, out)
        self.assertIn("unchanged (4)", out)

    def test_identical_registries_render_the_no_change_markdown(self) -> None:
        code, out, err = self.run_tool(
            str(self.old_path), str(self.old_path), "--format", "markdown"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("No fixture changed between the two registries.", out)
        self.assertNotIn("###", out)

    def test_the_json_format_pins_keys_layout_and_encoding(self) -> None:
        code, out, err = self.run_tool(
            str(self.old_path), str(self.new_path), "--format", "json"
        )
        self.assertEqual(code, 0, err)
        document = json.loads(out)
        self.assertEqual(
            set(document),
            {"old", "new", "added", "removed", "changed", "moved", "unchanged"},
        )
        self.assertEqual(document["unchanged"], 1)
        self.assertEqual([entry["id"] for entry in document["moved"]], ["p28-moved"])

        # The layout is part of the contract: release tooling may diff or
        # store this document, so two-space indent, one trailing newline and
        # unescaped UTF-8 must not drift.
        self.assertTrue(out.endswith("\n"))
        self.assertFalse(out.endswith("\n\n"))
        self.assertIn('\n  "old": {', out)
        self.assertIn('\n  "added": [', out)
        self.assertIn("caf\u00e9", out)
        self.assertNotIn("\\u", out)


class UnusableInputTests(unittest.TestCase):
    """F-130: every unusable input is one message and exit code 2."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="registry-diff-input-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.valid_path = write_json(
            self.tmp / "valid.json",
            registry([fixture("p28-a", "xdr/a.toml", SHA_A)]),
        )

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = diff.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def assert_refused(self, code: int, out: str, err: str, *fragments: str) -> None:
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error: "), err)
        for fragment in fragments:
            self.assertIn(fragment, err)

    def test_a_directory_is_refused(self) -> None:
        directory = self.tmp / "a-directory"
        directory.mkdir()
        code, out, err = self.run_tool(str(directory), str(self.valid_path))
        self.assert_refused(
            code, out, err, str(directory), "is a directory, not a registry file"
        )

    def test_a_file_that_cannot_be_read_is_refused(self) -> None:
        with mock.patch.object(
            Path, "read_bytes", side_effect=PermissionError("permission denied")
        ):
            code, out, err = self.run_tool(str(self.valid_path), str(self.valid_path))
        self.assert_refused(code, out, err, str(self.valid_path), "could not be read")

    def test_a_file_that_is_not_utf8_is_refused(self) -> None:
        path = self.tmp / "not-utf8.json"
        path.write_bytes(b'\xff\xfe{"registryVersion": 1}')
        code, out, err = self.run_tool(str(path), str(self.valid_path))
        self.assert_refused(code, out, err, str(path), "is not valid UTF-8")

    def test_a_file_with_malformed_json_is_refused(self) -> None:
        path = self.tmp / "broken.json"
        path.write_text("{not json\n", encoding="utf-8")
        code, out, err = self.run_tool(str(path), str(self.valid_path))
        self.assert_refused(code, out, err, str(path), "not valid JSON")


if __name__ == "__main__":
    unittest.main()
