"""Tests for schemas/run-record-v1.schema.json (issue #367).

The schema and the reader in ``tools/release/run_records.py`` have to agree:
the schema says what a record looks like, the reader says what the manifest
tool will accept. A record that satisfies one and not the other would make
the manifest fail on a file that looks fine on disk, or -- worse -- let a
record through that the schema forbids.

Stdlib only, like the rest of the suite: the CI ``validate`` job runs
``unittest discover`` on a bare interpreter.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
import pack_support as support  # noqa: E402

_schema_spec = support.load_tool(
    "canary_jsonschema_lite", "tools/validate/jsonschema_lite.py"
)
run_records = support.load_tool("canary_run_records", "tools/release/run_records.py")

SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "run-record-v1.schema.json").read_text(encoding="utf-8")
)

DIGEST = "sha256:" + "ab" * 32

RECORD = {
    "runRecordVersion": 1,
    "engineVersion": "0.2.0",
    "packDigest": DIGEST,
    "checkedAt": "2026-10-20T12:00:00Z",
    "verifier": {"name": "protocol-canary-ci", "version": "0.2.0"},
    "outcome": "passed",
    "evidenceRef": None,
}


def schema_problems(document: dict) -> list[str]:
    return _schema_spec.validate(document, SCHEMA)


class RunRecordSchemaTests(unittest.TestCase):
    def test_a_valid_record_conforms_to_the_schema(self) -> None:
        self.assertEqual(schema_problems(copy.deepcopy(RECORD)), [])

    def test_the_schema_and_the_reader_agree_on_a_valid_record(self) -> None:
        self.assertEqual(run_records.validate_run_record(copy.deepcopy(RECORD)), [])

    def test_a_record_without_the_optional_evidence_reference_conforms(self) -> None:
        record = copy.deepcopy(RECORD)
        del record["evidenceRef"]
        self.assertEqual(schema_problems(record), [])
        self.assertEqual(run_records.validate_run_record(record), [])

    def test_an_unknown_field_is_refused_by_both(self) -> None:
        record = copy.deepcopy(RECORD)
        record["surprise"] = True
        self.assertTrue(schema_problems(record))
        self.assertTrue(run_records.validate_run_record(record))

    def test_a_missing_required_field_is_refused_by_both(self) -> None:
        for field in (
            "runRecordVersion",
            "engineVersion",
            "packDigest",
            "checkedAt",
            "verifier",
            "outcome",
        ):
            with self.subTest(field=field):
                record = copy.deepcopy(RECORD)
                del record[field]
                self.assertTrue(schema_problems(record))
                self.assertTrue(run_records.validate_run_record(record))

    def test_a_range_is_refused_by_both(self) -> None:
        record = copy.deepcopy(RECORD)
        record["engineVersion"] = "0.2.x"
        self.assertTrue(schema_problems(record))
        problems = run_records.validate_run_record(record)
        self.assertTrue(problems)
        self.assertTrue(any("exact" in problem for problem in problems), problems)

    def test_a_digest_without_the_sha256_prefix_is_refused_by_both(self) -> None:
        record = copy.deepcopy(RECORD)
        record["packDigest"] = "ab" * 32
        self.assertTrue(schema_problems(record))
        self.assertTrue(run_records.validate_run_record(record))

    def test_an_unknown_outcome_is_refused_by_both(self) -> None:
        record = copy.deepcopy(RECORD)
        record["outcome"] = "maybe"
        self.assertTrue(schema_problems(record))
        self.assertTrue(run_records.validate_run_record(record))

    def test_a_verifier_without_a_version_is_refused_by_both(self) -> None:
        record = copy.deepcopy(RECORD)
        record["verifier"] = {"name": "protocol-canary-ci"}
        self.assertTrue(schema_problems(record))
        self.assertTrue(run_records.validate_run_record(record))

    def test_the_reader_refuses_a_date_only_timestamp(self) -> None:
        # A date is not an instant: the record says when the run happened,
        # and a day is not enough to say that.
        record = copy.deepcopy(RECORD)
        record["checkedAt"] = "2026-10-22"
        problems = run_records.validate_run_record(record)
        self.assertTrue(problems)
        self.assertTrue(any("RFC 3339" in problem for problem in problems), problems)

    def test_the_reader_refuses_a_timestamp_that_is_not_utc(self) -> None:
        record = copy.deepcopy(RECORD)
        record["checkedAt"] = "2026-10-22T01:00:00+02:00"
        problems = run_records.validate_run_record(record)
        self.assertTrue(problems)
        self.assertTrue(any("RFC 3339" in problem for problem in problems), problems)

    def test_the_schema_declares_the_fields_the_reader_requires(self) -> None:
        # The two lists are written in different places; a field added to one
        # and not the other would let a record through one door only.
        self.assertEqual(
            set(SCHEMA["required"]), set(run_records.REQUIRED_FIELDS)
        )
        self.assertEqual(
            set(SCHEMA["properties"]),
            set(run_records.REQUIRED_FIELDS) | set(run_records.OPTIONAL_FIELDS),
        )

    def test_the_schema_closes_the_record(self) -> None:
        self.assertFalse(SCHEMA["additionalProperties"])


class RunRecordReaderTests(unittest.TestCase):
    """The reader's own rules, beyond what the schema can express.

    A timestamp that looks like an instant but is not a real one, a record
    that is not an object, an ``evidenceRef`` that points outside the
    repository: the reader refuses each of them with a message that names
    the problem.
    """

    def test_a_record_that_is_not_an_object_is_refused(self) -> None:
        for bad in ([], "a record", 3, None):
            with self.subTest(bad=bad):
                problems = run_records.validate_run_record(bad)
                self.assertEqual(problems, ["a run record must be a JSON object"])

    def test_a_timestamp_that_is_not_a_real_date_is_refused(self) -> None:
        # The shape is right, the date is not: 2026-13-45 does not exist.
        problems = run_records.validate_run_record(dict(RECORD, checkedAt="2026-13-45T00:00:00Z"))
        self.assertTrue(problems)
        self.assertTrue(any("not a real date" in problem for problem in problems), problems)

    def test_a_wrong_run_record_version_is_refused(self) -> None:
        for bad in (0, 2, "1", True, None):
            with self.subTest(version=bad):
                problems = run_records.validate_run_record(
                    dict(RECORD, runRecordVersion=bad)
                )
                self.assertTrue(problems)
                self.assertTrue(
                    any("runRecordVersion" in problem for problem in problems), problems
                )

    def test_a_verifier_that_is_not_an_object_is_refused(self) -> None:
        problems = run_records.validate_run_record(dict(RECORD, verifier="me"))
        self.assertTrue(problems)
        self.assertTrue(any("verifier" in problem for problem in problems), problems)

    def test_a_verifier_with_an_unknown_field_is_refused(self) -> None:
        problems = run_records.validate_run_record(
            dict(RECORD, verifier={"name": "ci", "version": "1", "host": "example"})
        )
        self.assertTrue(problems)
        self.assertTrue(any("host" in problem for problem in problems), problems)

    def test_an_empty_verifier_field_is_refused(self) -> None:
        problems = run_records.validate_run_record(
            dict(RECORD, verifier={"name": "ci", "version": "  "})
        )
        self.assertTrue(problems)
        self.assertTrue(any("verifier.version" in problem for problem in problems), problems)

    def test_an_evidence_reference_outside_the_repository_is_refused(self) -> None:
        for bad in ("/etc/passwd", "..\\secrets.json", "../../etc/passwd", "a//b.json"):
            with self.subTest(evidenceRef=bad):
                problems = run_records.validate_run_record(dict(RECORD, evidenceRef=bad))
                self.assertTrue(problems)
                self.assertTrue(
                    any("relative path" in problem for problem in problems), problems
                )

    def test_an_empty_evidence_reference_is_refused(self) -> None:
        problems = run_records.validate_run_record(dict(RECORD, evidenceRef=""))
        self.assertTrue(problems)
        self.assertTrue(any("evidenceRef" in problem for problem in problems), problems)

    def test_an_unreadable_record_is_reported_as_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.json"
            path.write_bytes(b"\xff\xfe not utf-8")
            with self.assertRaisesRegex(run_records.RunRecordError, "cannot read"):
                run_records.load_run_record(path)

    def test_a_directory_named_like_a_record_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not-a-record.json").mkdir()
            (root / "real.json").write_text(
                json.dumps(RECORD), encoding="utf-8"
            )
            records = run_records.load_run_records(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["engineVersion"], "0.2.0")

    def test_a_clock_skew_inside_the_tolerance_is_accepted(self) -> None:
        # The record is written by another machine, so its clock can be a
        # little behind; a small lead is tolerated rather than refused.
        now = datetime(2026, 10, 20, 12, 5, 0, tzinfo=timezone.utc)
        record = dict(RECORD, checkedAt="2026-10-20T12:08:00Z")
        self.assertEqual(run_records.validate_run_record(record, now=now), [])


if __name__ == "__main__":
    unittest.main()
