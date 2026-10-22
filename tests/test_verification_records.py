"""Tests for the Protocol 28 structural verification records (F-092, #366).

CF-04 section 3 defines a verification record: a fixture, the hash of the
bytes that were checked, the method, the instant of the check, the verifier
and the outcome. This repository's records live in
``protocol-28/evidence/records/`` and are produced by
``tools/evidence/record_structural.py``, which executes the structural check
and writes what it found.

The rules this file pins down are the ones issue #366 states:

* a record carries an instant, never a date taken from a header comment;
* a record's ``fixtureSha256`` is the hash of the fixture file that is there
  now;
* a live claim needs a saved capture, so no record here claims one;
* every record was made by a check that actually ran.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "protocol-28"
RECORDS_DIR = PACK / "evidence" / "records"

VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate_for_records", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_for_records"] = validate
_spec.loader.exec_module(validate)

RECORD_PATH = REPO_ROOT / "tools" / "evidence" / "record_structural.py"
_record_spec = importlib.util.spec_from_file_location("record_structural", RECORD_PATH)
record_structural = importlib.util.module_from_spec(_record_spec)
assert _record_spec.loader is not None
sys.modules["record_structural"] = record_structural
_record_spec.loader.exec_module(record_structural)


def fixture_files(pack: Path) -> list[Path]:
    """Every fixture file of a pack, in the order the validator finds them."""
    return validate.find_fixture_files(pack)


def fixture_ids(pack: Path) -> dict[str, Path]:
    """``{fixture id: path}`` for every fixture of a pack."""
    ids: dict[str, Path] = {}
    scratch = validate.Report()
    for path in fixture_files(pack):
        loaded = validate.load_fixture(path, scratch, root=pack)
        fixture_id = validate.known_fixture_id(loaded) if loaded is not None else None
        if fixture_id:
            ids[fixture_id] = path
    return ids


class CommittedRecordTests(unittest.TestCase):
    """The records that are committed, checked against the CF-04 rules."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = sorted(RECORDS_DIR.glob("*.json"))
        cls.records = {
            path.name: json.loads(path.read_text(encoding="utf-8")) for path in cls.paths
        }
        cls.fixtures = fixture_ids(PACK)

    def test_every_fixture_has_exactly_one_record(self) -> None:
        self.assertTrue(self.paths, f"no record found in {RECORDS_DIR}")
        recorded = {record["fixtureId"] for record in self.records.values()}
        self.assertEqual(
            recorded,
            set(self.fixtures),
            "the records and the pack's fixtures do not describe the same set",
        )
        self.assertEqual(
            len(self.paths), len(self.fixtures), "a fixture has more than one record"
        )

    def test_every_record_is_accepted_by_the_validator(self) -> None:
        for name, record in self.records.items():
            with self.subTest(record=name):
                self.assertEqual(validate.validate_evidence(record), [])

    def test_every_record_names_a_fixture_with_the_current_hash(self) -> None:
        hashes = validate.fixture_hashes([PACK])
        for name, record in self.records.items():
            with self.subTest(record=name):
                self.assertIn(record["fixtureId"], hashes)
                self.assertEqual(record["fixtureSha256"], hashes[record["fixtureId"]])
                path = self.fixtures[record["fixtureId"]]
                self.assertEqual(
                    record["fixtureSha256"],
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )

    def test_the_records_claim_only_a_structural_check(self) -> None:
        # A structural record says the file is well formed. It says nothing
        # about Stellar behavior, so it may not carry a network, an endpoint or
        # a capture (CF-04 section 2).
        for name, record in self.records.items():
            with self.subTest(record=name):
                self.assertEqual(record["method"], "structural")
                self.assertEqual(record["outcome"], "matched")
                self.assertIsNone(record.get("evidenceRef"))
                self.assertIsNone(record.get("network"))
                self.assertIsNone(record.get("endpointHost"))

    def test_every_record_carries_an_instant_not_a_date(self) -> None:
        # A header comment names a day ("Verified live on 2026-09-02"); an
        # instant is not that. No record may hold a date, and none may hold a
        # midnight or noon guess, which is what a date-only header would have
        # been turned into.
        for name, record in self.records.items():
            with self.subTest(record=name):
                checked_at = record["checkedAt"]
                self.assertRegex(
                    checked_at,
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    "checkedAt is not an RFC 3339 UTC instant",
                )
                moment = datetime.strptime(checked_at, "%Y-%m-%dT%H:%M:%SZ")
                self.assertNotEqual(
                    (moment.hour, moment.minute, moment.second),
                    (0, 0, 0),
                    "checkedAt is midnight; that is a guessed instant",
                )
                self.assertNotEqual(
                    (moment.hour, moment.minute, moment.second),
                    (12, 0, 0),
                    "checkedAt is noon; that is a guessed instant",
                )

    def test_no_record_is_in_the_future(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for name, record in self.records.items():
            with self.subTest(record=name):
                checked_at = datetime.strptime(record["checkedAt"], "%Y-%m-%dT%H:%M:%SZ")
                self.assertLessEqual(checked_at, now)

    def test_the_verifier_is_named(self) -> None:
        for name, record in self.records.items():
            with self.subTest(record=name):
                verifier = record["verifier"]
                self.assertTrue(verifier["name"])
                self.assertTrue(verifier["version"])


class RejectedRecordTests(unittest.TestCase):
    """The records the validator has to refuse (issue #366's negative tests)."""

    def setUp(self) -> None:
        self.record = {
            "verificationVersion": 1,
            "fixtureId": "p28-rpc-network",
            "fixtureSha256": "0" * 64,
            "method": "structural",
            "checkedAt": "2026-10-22T00:00:00Z",
            "verifier": {"name": "protocolcanary-fixtures-validate", "version": "x"},
            "outcome": "matched",
            "evidenceRef": None,
        }

    def test_a_date_only_checked_at_is_rejected(self) -> None:
        # A header comment names a day. The record needs the instant of a
        # check that ran, so a day on its own is not a checkedAt.
        for value in ("2026-09-02", "2026-09-02 12:00:00", "2026-09-02T12:00:00+00:00"):
            with self.subTest(checkedAt=value):
                record = copy.deepcopy(self.record)
                record["checkedAt"] = value
                problems = validate.validate_evidence(record)
                self.assertTrue(problems, f"checkedAt {value!r} was accepted")
                self.assertTrue(any("checkedAt" in p for p in problems), problems)

    def test_a_hash_that_does_not_match_the_fixture_is_rejected(self) -> None:
        record = copy.deepcopy(self.record)
        record["fixtureSha256"] = "f" * 64
        hashes = validate.fixture_hashes([PACK])
        report = validate.Report()
        validate.check_evidence_against_fixtures(Path("record.json"), record, hashes, report)
        self.assertTrue(report.errors, "a mismatching fixtureSha256 was accepted")

    def test_a_live_record_without_a_capture_is_rejected(self) -> None:
        record = copy.deepcopy(self.record)
        record["method"] = "live-read-only"
        record["network"] = {
            "name": "testnet",
            "passphrase": "Test SDF Network ; September 2015",
            "observedProtocol": 28,
        }
        record["endpointHost"] = "soroban-testnet.stellar.org"
        problems = validate.validate_evidence(record)
        self.assertTrue(problems, "a live record without a capture was accepted")
        self.assertTrue(any("evidenceRef" in p for p in problems), problems)

    def test_a_live_record_without_a_network_is_rejected(self) -> None:
        record = copy.deepcopy(self.record)
        record["method"] = "live-read-only"
        record["endpointHost"] = "soroban-testnet.stellar.org"
        record["evidenceRef"] = "protocol-28/evidence/records/example.json"
        problems = validate.validate_evidence(record)
        self.assertTrue(problems, "a live record without a network was accepted")
        self.assertTrue(any("network" in p for p in problems), problems)

    def test_a_record_for_an_unknown_fixture_is_rejected(self) -> None:
        record = copy.deepcopy(self.record)
        record["fixtureId"] = "p28-does-not-exist"
        hashes = validate.fixture_hashes([PACK])
        report = validate.Report()
        validate.check_evidence_against_fixtures(Path("record.json"), record, hashes, report)
        self.assertTrue(report.errors, "a record for an unknown fixture was accepted")


class RecordToolTests(unittest.TestCase):
    """The tool that writes the records."""

    def _copy_pack(self, directory: Path) -> Path:
        pack = directory / "protocol-28"
        shutil.copytree(PACK, pack)
        shutil.rmtree(pack / "evidence", ignore_errors=True)
        return pack

    def test_the_tool_writes_one_record_per_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            output = Path(tmp) / "records"
            written, checked_at = record_structural.run(pack, output_dir=output)
            self.assertEqual(len(written), len(fixture_files(pack)))
            self.assertTrue(checked_at.endswith("Z"))
            for path in written:
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validate.validate_evidence(record), [])
                self.assertEqual(record["method"], "structural")
                self.assertEqual(record["checkedAt"], checked_at)

    def test_the_tool_refuses_to_record_a_pack_that_does_not_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            broken = pack / "rpc" / "p28-rpc-network.toml"
            broken.write_text("not = [valid\n", encoding="utf-8")
            output = Path(tmp) / "records"
            with self.assertRaises(record_structural.RecordError):
                record_structural.run(pack, output_dir=output)
            self.assertFalse(output.exists(), "a record was written for a broken pack")

    def test_the_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            output = Path(tmp) / "records"
            written, _ = record_structural.run(pack, output_dir=output, dry_run=True)
            self.assertEqual(written, [])
            self.assertFalse(output.exists())

    def test_the_record_hashes_the_file_that_is_there_now(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            output = Path(tmp) / "records"
            written, _ = record_structural.run(pack, output_dir=output)
            for path in written:
                record = json.loads(path.read_text(encoding="utf-8"))
                fixture = fixture_files(pack)
                ids = {p.name: p for p in fixture}
                source = ids[record["fixtureId"] + ".toml"]
                self.assertEqual(
                    record["fixtureSha256"],
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                )


class RecordToolCommandTests(unittest.TestCase):
    """The command line of the tool: what it prints and what it returns."""

    def _copy_pack(self, directory: Path) -> Path:
        pack = directory / "protocol-28"
        shutil.copytree(PACK, pack)
        shutil.rmtree(pack / "evidence", ignore_errors=True)
        return pack

    def test_main_writes_the_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            output = Path(tmp) / "records"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = record_structural.main(
                    [str(pack), "--output-dir", str(output), "--verifier-version", "test"]
                )
            self.assertEqual(code, 0)
            self.assertIn("OK", stdout.getvalue())
            self.assertTrue(sorted(output.glob("*.json")))
            record = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["verifier"]["version"], "test")

    def test_main_reports_a_pack_that_does_not_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            (pack / "rpc" / "p28-rpc-network.toml").write_text("not = [valid\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = record_structural.main([str(pack)])
            self.assertEqual(code, 1)
            self.assertIn("does not validate", stderr.getvalue())

    def test_main_reports_a_missing_pack(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = record_structural.main(["no-such-pack"])
        self.assertEqual(code, 1)
        self.assertIn("pack not found", stderr.getvalue())

    def test_main_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._copy_pack(Path(tmp))
            output = Path(tmp) / "records"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = record_structural.main(
                    [str(pack), "--output-dir", str(output), "--dry-run"]
                )
            self.assertEqual(code, 0)
            self.assertFalse(output.exists())

    def test_help_exits_zero(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                record_structural.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("record_structural.py", stdout.getvalue())

    def test_a_missing_file_is_reported(self) -> None:
        with self.assertRaises(record_structural.RecordError):
            record_structural.sha256_of(Path("no-such-file.toml"))

    def test_a_record_that_cannot_be_written_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "not-a-directory"
            blocked.write_text("", encoding="utf-8")
            with self.assertRaises(record_structural.RecordError):
                record_structural.write_records(
                    {"p28-rpc-network": {"verificationVersion": 1}}, blocked
                )

    def test_the_revision_is_a_commit_or_unknown(self) -> None:
        revision = record_structural.git_revision(REPO_ROOT)
        self.assertTrue(revision == "unknown" or len(revision) == 40)
        self.assertEqual(record_structural.git_revision(Path("/no/such/dir")), "unknown")


if __name__ == "__main__":
    unittest.main()
