"""Subprocess tests for the command-line contracts of the repository's tools.

``tools/validate/schema_sync.py`` used to parse its arguments by hand and
treat ``--help`` as an unknown argument (exit 2). These tests pin the
argparse-based contract exactly as a shell sees it: usage and exit status.
badge.py's sibling contract lives in ``tests/test_badge.py``.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SYNC_PATH = REPO_ROOT / "tools" / "validate" / "schema_sync.py"


class SchemaSyncArgumentTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCHEMA_SYNC_PATH), *args],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

    def test_no_arguments_keep_the_successful_behaviour(self) -> None:
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "OK: schemas/fixture-v1.schema.json matches tools/validate/validate.py",
            result.stdout,
        )
        self.assertEqual(result.stderr, "")

    def test_help_exits_0_with_usage_on_stdout(self) -> None:
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = self.run_cli(flag)
                self.assertEqual(result.returncode, 0)
                self.assertIn("usage:", result.stdout)
                self.assertIn("schema_sync.py", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_unknown_argument_exits_2_with_usage_on_stderr(self) -> None:
        for arg in ("--nope", "--chek", "extra"):
            with self.subTest(arg=arg):
                result = self.run_cli(arg)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
