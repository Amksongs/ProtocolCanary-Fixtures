"""Tests for tools/validate/validate_registry.py (F-004, issue #273).

The tool cross-validates a pack's ``*.toml`` corpus against its committed
``registry-v1.json`` (CF-02 section 6, rules 2 and 3): every fixture on disk
must be listed, every listed fixture and payload must exist as a regular
file, and every recorded sha256 must equal the hash of the bytes on disk.
The tests cover the three rejections the issue requires (orphaned fixture,
phantom entry, hash mismatch), the payload entries, unusable inputs (exit
2), the command line, and the repository's own protocol packs.

Run with: python3 -m unittest tests/test_validate_registry.py
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "validate" / "validate_registry.py"

_spec = importlib.util.spec_from_file_location("validate_registry", TOOL_PATH)
vr = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_registry"] = vr
_spec.loader.exec_module(vr)

# The tool never checks packDigest (freshness is CI's check-registry step),
# so a syntactically valid constant is enough for every registry built here.
PACK_DIGEST = "sha256:" + "a" * 64


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_entry(path: str, data: bytes, payloads: dict[str, bytes] | None = None) -> dict:
    """A schema-complete registry fixture entry for ``data`` at ``path``."""
    return {
        "id": Path(path).stem,
        "path": path,
        "sha256": sha256(data),
        "surface": "xdr",
        "category": "cap-0083",
        "description": f"test fixture {Path(path).stem}",
        "payloads": [
            {"path": payload_path, "sha256": sha256(payload_data)}
            for payload_path, payload_data in sorted((payloads or {}).items())
        ],
    }


def write_registry(pack: Path, fixtures: list[dict], protocol: int = 28) -> Path:
    """Write a minimal but schema-valid registry document for ``pack``."""
    document = {
        "registryVersion": 1,
        "protocol": protocol,
        "fixtures": fixtures,
        "packDigest": PACK_DIGEST,
    }
    registry = pack / "registry-v1.json"
    registry.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return registry


class ValidateRegistryTestCase(unittest.TestCase):
    """Shared temp-pack fixture and CLI runner."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="validate-registry-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pack = self.tmp / "protocol-28"
        (self.pack / "xdr").mkdir(parents=True)

    def write_file(self, rel: str, data: bytes) -> Path:
        path = self.pack / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vr.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def run_subprocess(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL_PATH), *args],
            capture_output=True,
            text=True,
        )


class MatchingPackTests(ValidateRegistryTestCase):
    """A pack that matches its registry passes with exit code 0."""

    def test_fixtures_and_hashes_that_match_pass(self) -> None:
        a = b'id = "p28-a"\nsurface = "xdr"\n'
        b = b'id = "p28-b"\nsurface = "xdr"\n'
        self.write_file("xdr/a.toml", a)
        self.write_file("xdr/nested/b.toml", b)
        write_registry(
            self.pack,
            [fixture_entry("xdr/a.toml", a), fixture_entry("xdr/nested/b.toml", b)],
        )
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertIn("OK: ", out)
        self.assertIn("2 fixture(s) and 0 payload hash(es) match registry-v1.json", out)

    def test_a_matching_payload_is_hashed_and_counted(self) -> None:
        fixture = b'id = "p28-payload"\n'
        payload = b"\x00\x01input bytes\n"
        self.write_file("xdr/p.toml", fixture)
        self.write_file("xdr/p-input.bin", payload)
        write_registry(
            self.pack,
            [fixture_entry("xdr/p.toml", fixture, {"xdr/p-input.bin": payload})],
        )
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 0, err)
        self.assertIn("1 fixture(s) and 1 payload hash(es) match", out)

    def test_a_pack_with_no_fixtures_and_no_registry_passes(self) -> None:
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 0, err)
        self.assertIn("no fixtures and no registry-v1.json to check", out)

    def test_an_empty_baseline_registry_matches_an_empty_pack(self) -> None:
        # protocol-29 ships as an empty baseline: empty fixtures array,
        # no *.toml files. The schema's minItems floor must not reject it.
        write_registry(self.pack, [], protocol=29)
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 0, err)
        self.assertIn("0 fixture(s) and 0 payload hash(es) match", out)

    def test_a_git_directory_is_not_part_of_the_pack(self) -> None:
        fixture = b'id = "p28-kept"\n'
        self.write_file("xdr/kept.toml", fixture)
        write_registry(self.pack, [fixture_entry("xdr/kept.toml", fixture)])
        git_dir = self.pack / ".git"
        git_dir.mkdir()
        (git_dir / "hidden.toml").write_bytes(b"id = 'never scanned'")
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 0, err)
        self.assertNotIn("hidden.toml", err)


class OrphanedFixtureTests(ValidateRegistryTestCase):
    """Acceptance: a fixture on disk that the registry does not list fails."""

    def make_matching_pack(self) -> bytes:
        fixture = b'id = "p28-only"\n'
        self.write_file("xdr/only.toml", fixture)
        write_registry(self.pack, [fixture_entry("xdr/only.toml", fixture)])
        return fixture

    def test_an_extra_fixture_on_disk_is_rejected_with_its_path(self) -> None:
        self.make_matching_pack()
        self.write_file("xdr/extra.toml", b'id = "p28-extra"\n')
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 1)
        self.assertIn("xdr/extra.toml", err)
        self.assertIn("fixture on disk is not listed", err)
        self.assertIn("FAILED: 1 problem(s)", err)
        # the matching fixture is not implicated
        self.assertNotIn("only.toml", err)

    def test_the_issue_negative_case_exits_nonzero_via_the_real_cli(self) -> None:
        # Issue #273's negative testing: a synthetic extra fixture file on
        # disk causes a non-zero exit code with the path of the untracked
        # fixture in the output.
        self.make_matching_pack()
        self.write_file("xdr/synthetic.toml", b'id = "p28-synthetic"\n')
        result = self.run_subprocess(str(self.pack))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("xdr/synthetic.toml", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_pack_with_fixtures_but_no_registry_lists_them_all(self) -> None:
        self.write_file("xdr/one.toml", b"id = 'one'")
        self.write_file("xdr/two.toml", b"id = 'two'")
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 1)
        self.assertIn("registry-v1.json: does not exist", err)
        self.assertIn("xdr/one.toml", err)
        self.assertIn("xdr/two.toml", err)
        self.assertIn("FAILED: 3 problem(s)", err)


class MissingEntryTests(ValidateRegistryTestCase):
    """Acceptance: a registry entry whose file is missing on disk fails."""

    def test_a_listed_fixture_missing_from_disk_is_rejected(self) -> None:
        data = b'id = "p28-gone"\n'
        self.write_file("xdr/gone.toml", data)
        write_registry(self.pack, [fixture_entry("xdr/gone.toml", data)])
        (self.pack / "xdr" / "gone.toml").unlink()
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 1)
        self.assertIn("xdr/gone.toml", err)
        self.assertIn("listed in", err)
        self.assertIn("is missing from the pack", err)
        self.assertIn("FAILED: 1 problem(s)", err)

    def test_a_listed_payload_missing_from_disk_is_rejected(self) -> None:
        fixture = b'id = "p28-p"\n'
        payload = b"bytes"
        self.write_file("xdr/p.toml", fixture)
        write_registry(
            self.pack,
            [fixture_entry("xdr/p.toml", fixture, {"xdr/input.bin": payload})],
        )
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 1)
        self.assertIn("xdr/input.bin", err)
        self.assertIn("payload listed under", err)
        self.assertIn("is missing from the pack", err)


class HashMismatchTests(ValidateRegistryTestCase):
    """Acceptance: a file whose bytes differ from the recorded sha256 fails."""

    def test_a_fixture_changed_after_registration_is_rejected(self) -> None:
        original = b'id = "p28-changed"\n'
        self.write_file("xdr/ch.toml", original)
        write_registry(self.pack, [fixture_entry("xdr/ch.toml", original)])
        changed = b'id = "p28-changed" # edited\n'
        (self.pack / "xdr" / "ch.toml").write_bytes(changed)
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 1)
        self.assertIn("xdr/ch.toml", err)
        self.assertIn("sha256 mismatch", err)
        self.assertIn(sha256(original), err)  # what the registry recorded
        self.assertIn(sha256(changed), err)  # what is on disk
        self.assertIn("FAILED: 1 problem(s)", err)

    def test_a_payload_changed_after_registration_is_rejected(self) -> None:
        fixture = b'id = "p28-p"\n'
        payload = b"expected"
        self.write_file("xdr/p.toml", fixture)
        write_registry(
            self.pack,
            [fixture_entry("xdr/p.toml", fixture, {"xdr/want.bin": payload})],
        )
        (self.pack / "xdr" / "want.bin").write_bytes(b"actual!")
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 1)
        self.assertIn("xdr/want.bin", err)
        self.assertIn("sha256 mismatch (payload of", err)
        self.assertIn(sha256(b"actual!"), err)


class UnusableInputTests(ValidateRegistryTestCase):
    """Exit code 2: inputs the checker cannot even start on."""

    def test_a_missing_pack_directory_exits_2(self) -> None:
        code, out, err = self.run_tool(str(self.tmp / "no-such-pack"))
        self.assertEqual(code, 2)
        self.assertIn("no such directory", err)

    def test_a_pack_path_that_is_a_file_exits_2(self) -> None:
        file_path = self.tmp / "not-a-dir"
        file_path.write_bytes(b"x")
        code, out, err = self.run_tool(str(file_path))
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)

    def test_a_registry_that_is_not_json_exits_2(self) -> None:
        (self.pack / "registry-v1.json").write_bytes(b"{not json at all")
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 2)
        self.assertIn("error:", err)
        self.assertIn("registry-v1.json", err)

    def test_a_registry_that_is_not_an_object_exits_2(self) -> None:
        (self.pack / "registry-v1.json").write_text("[]\n", encoding="utf-8")
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 2)
        self.assertIn("usable registry", err)

    def test_a_registry_missing_required_keys_exits_2(self) -> None:
        (self.pack / "registry-v1.json").write_text(
            json.dumps({"fixtures": []}) + "\n", encoding="utf-8"
        )
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 2)
        self.assertIn("usable registry", err)

    def test_a_registry_path_that_escapes_the_pack_exits_2(self) -> None:
        document = {
            "registryVersion": 1,
            "protocol": 28,
            "fixtures": [
                fixture_entry("xdr/ok.toml", b"unused"),
            ],
            "packDigest": PACK_DIGEST,
        }
        document["fixtures"][0]["path"] = "../outside.toml"
        (self.pack / "registry-v1.json").write_text(
            json.dumps(document) + "\n", encoding="utf-8"
        )
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 2)
        self.assertIn("'..' segment", err)

    def test_a_registry_path_that_is_a_directory_exits_2(self) -> None:
        (self.pack / "registry-v1.json").mkdir()
        code, out, err = self.run_tool(str(self.pack))
        self.assertEqual(code, 2)
        self.assertIn("is a directory", err)

    def test_an_unknown_option_exits_2(self) -> None:
        result = self.run_subprocess("--no-such-flag")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: validate_registry.py", result.stderr)


class CommandLineTests(ValidateRegistryTestCase):
    """The documented command-line contract."""

    def test_help_exits_zero_and_documents_the_exit_codes(self) -> None:
        result = self.run_subprocess("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: validate_registry.py", result.stdout)
        self.assertIn("Exit codes:", result.stdout)

    def test_one_bad_pack_does_not_hide_the_other_pack_result(self) -> None:
        good = self.tmp / "protocol-29"
        good.mkdir()
        write_registry(good, [], protocol=29)
        bad = self.tmp / "protocol-99"
        (bad / "xdr").mkdir(parents=True)
        (bad / "xdr" / "orphan.toml").write_bytes(b"id = 'orphan'")
        code, out, err = self.run_tool(str(good), str(bad))
        self.assertEqual(code, 1)
        self.assertIn("OK: ", out)
        self.assertIn("orphan.toml", err)


class RepositoryPacksTests(ValidateRegistryTestCase):
    """The repository's own packs, whatever state the checkout is in."""

    def test_default_run_checks_every_protocol_pack(self) -> None:
        code, out, err = self.run_tool()
        # protocol-28's committed registry lands with PR #469 (issue #269);
        # this issue does not depend on it, so assert whichever state the
        # checkout has: with the registry every pack matches, without it the
        # unlisted corpus is reported -- which is exactly what the tool is for.
        if (REPO_ROOT / "protocol-28" / "registry-v1.json").exists():
            self.assertEqual(code, 0, err)
            self.assertIn("OK: protocol-28", out)
        else:
            self.assertEqual(code, 1)
            self.assertIn("protocol-28/registry-v1.json: does not exist", err)
            self.assertIn("protocol-28/xdr/", err)
        # protocol-27 has neither fixtures nor a registry; protocol-29 ships
        # as an empty baseline with a committed registry (issue #290).
        self.assertIn("OK: protocol-27", out)
        self.assertIn("OK: protocol-29", out)

    def test_protocol29_matches_its_committed_baseline(self) -> None:
        code, out, err = self.run_tool(str(REPO_ROOT / "protocol-29"))
        self.assertEqual(code, 0, err)
        self.assertIn("OK: protocol-29", out)


if __name__ == "__main__":
    unittest.main()
