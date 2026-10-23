"""Tests for tools/evidence/freshness.py (F-007, issue #271)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.evidence import freshness


class TestVerificationFreshness(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_checked_at_valid(self) -> None:
        valid_ts = "2026-10-22T08:00:00Z"
        dt = freshness.parse_checked_at(valid_ts, now=self.now)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 10)
        self.assertEqual(dt.day, 22)
        self.assertEqual(dt.hour, 8)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_checked_at_with_fractions(self) -> None:
        valid_ts = "2026-10-22T08:00:00.123456Z"
        dt = freshness.parse_checked_at(valid_ts, now=self.now)
        self.assertEqual(dt.microsecond, 123456)

    def test_parse_checked_at_rejects_future_timestamp(self) -> None:
        """Negative test: future timestamps report a format error."""
        future_ts = "2026-10-23T12:00:00Z"
        with self.assertRaises(freshness.FreshnessFormatError) as ctx:
            freshness.parse_checked_at(future_ts, now=self.now)
        self.assertIn("future timestamp", str(ctx.exception))

    def test_parse_checked_at_rejects_unparseable_date_strings(self) -> None:
        """Negative test: unparseable date strings report a format error."""
        invalid_cases = (
            "not-a-date",
            "2026-10-22",
            "2026-13-01T00:00:00Z",
            "2026-10-22T25:00:00Z",
            "2026-10-22T00:00:00",  # missing Z
            "2026-10-22T00:00:00+00:00",  # not ending in Z
            12345,
            None,
        )
        for val in invalid_cases:
            with self.subTest(value=val):
                with self.assertRaises(freshness.FreshnessFormatError) as ctx:
                    freshness.parse_checked_at(val, now=self.now)
                self.assertIn("unparseable date string", str(ctx.exception))

    def test_freshness_classification(self) -> None:
        # <30d: fresh
        self.assertEqual(freshness.classify_freshness(0), "fresh")
        self.assertEqual(freshness.classify_freshness(15), "fresh")
        self.assertEqual(freshness.classify_freshness(29), "fresh")

        # 30-90d: aging
        self.assertEqual(freshness.classify_freshness(30), "aging")
        self.assertEqual(freshness.classify_freshness(60), "aging")
        self.assertEqual(freshness.classify_freshness(90), "aging")

        # >90d: stale
        self.assertEqual(freshness.classify_freshness(91), "stale")
        self.assertEqual(freshness.classify_freshness(180), "stale")

    def test_calculate_record_freshness(self) -> None:
        path = Path("fake_record.json")

        # Record from 10 days ago
        data_fresh = {"fixtureId": "fixture-fresh", "checkedAt": "2026-10-12T12:00:00Z"}
        res_fresh = freshness.calculate_record_freshness(path, data_fresh, now=self.now)
        self.assertEqual(res_fresh.age_days, 10)
        self.assertEqual(res_fresh.status, "fresh")

        # Record from 40 days ago
        data_aging = {"fixtureId": "fixture-aging", "checkedAt": "2026-09-12T12:00:00Z"}
        res_aging = freshness.calculate_record_freshness(path, data_aging, now=self.now)
        self.assertEqual(res_aging.age_days, 40)
        self.assertEqual(res_aging.status, "aging")

        # Record from 100 days ago
        data_stale = {"fixtureId": "fixture-stale", "checkedAt": "2026-07-14T12:00:00Z"}
        res_stale = freshness.calculate_record_freshness(path, data_stale, now=self.now)
        self.assertEqual(res_stale.age_days, 100)
        self.assertEqual(res_stale.status, "stale")

    def test_strict_flag_exits_1_on_stale_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            stale_record = tmppath / "stale.json"
            stale_record.write_text(
                json.dumps({
                    "verificationVersion": 1,
                    "fixtureId": "test-stale",
                    "checkedAt": "2025-01-01T00:00:00Z",  # Over 90 days ago
                }),
                encoding="utf-8",
            )

            # Without --strict: returns 0
            code = freshness.main([str(tmppath)])
            self.assertEqual(code, 0)

            # With --strict: returns 1
            code_strict = freshness.main([str(tmppath), "--strict"])
            self.assertEqual(code_strict, 1)

    def test_strict_flag_exits_0_when_all_records_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            fresh_record = tmppath / "fresh.json"
            fresh_record.write_text(
                json.dumps({
                    "verificationVersion": 1,
                    "fixtureId": "test-fresh",
                    "checkedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }),
                encoding="utf-8",
            )
            code = freshness.main([str(tmppath), "--strict"])
            self.assertEqual(code, 0)

    def test_format_error_handling_in_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            future_record = tmppath / "future.json"
            future_record.write_text(
                json.dumps({
                    "verificationVersion": 1,
                    "fixtureId": "test-future",
                    "checkedAt": "2099-01-01T00:00:00Z",
                }),
                encoding="utf-8",
            )
            results, errors = freshness.scan_freshness([tmppath], now=self.now)
            self.assertEqual(len(results), 0)
            self.assertEqual(len(errors), 1)
            self.assertIn("future timestamp", errors[0][1])

            # main exits 1 when errors exist
            exit_code = freshness.main([str(tmppath)])
            self.assertEqual(exit_code, 1)

    def test_additional_coverage_paths(self) -> None:
        # parse_checked_at with now=None
        now_dt = datetime.now(timezone.utc)
        parsed = freshness.parse_checked_at(now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertIsNotNone(parsed)

        # calculate_record_freshness with now=None
        rec = freshness.calculate_record_freshness(
            Path("rec.json"),
            {"fixtureId": "f1", "checkedAt": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")},
        )
        self.assertEqual(rec.status, "fresh")

        # calculate_record_freshness missing checkedAt
        with self.assertRaises(freshness.FreshnessFormatError):
            freshness.calculate_record_freshness(Path("rec.json"), {"fixtureId": "f1"})

        # format_table with empty results
        self.assertEqual(freshness.format_table([]), "No evidence records evaluated.")

        # find_record_files with direct file path
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "direct.json"
            f.write_text("{}", encoding="utf-8")
            self.assertEqual(freshness.find_record_files([f]), [f])

            # scan_freshness with invalid JSON
            bad_json = Path(tmpdir) / "bad.json"
            bad_json.write_text("{bad", encoding="utf-8")

            # scan_freshness with verificationVersion but missing checkedAt
            no_checked = Path(tmpdir) / "no_checked.json"
            no_checked.write_text(json.dumps({"verificationVersion": 1}), encoding="utf-8")

            _, errors = freshness.scan_freshness([f, bad_json, no_checked])
            self.assertTrue(any("JSON parse error" in e[1] for e in errors))
            self.assertTrue(any("missing 'checkedAt' field" in e[1] for e in errors))

    def test_default_main_execution(self) -> None:
        # main() with default paths
        code = freshness.main([])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
