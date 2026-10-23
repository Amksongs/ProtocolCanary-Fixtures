"""Protocol 29 endpoint versus Protocol 28 target mismatch fixture."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "protocol-29" / "rpc" / "p29-rpc-network-mismatch.toml"


class ProtocolMismatchFixtureTests(unittest.TestCase):
    def test_fixture_validates_and_describes_the_mismatch(self) -> None:
        run = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "validate" / "validate.py"), "protocol-29", "--format", "json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
        report = json.loads(run.stdout)
        self.assertTrue(report["valid"], report["errors"])
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertIn("Protocol 28 target", text)
        self.assertIn('protocol = 29', text)
        self.assertIn('field = "protocolVersion"', text)

    def test_invalid_schema_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            invalid = root / "invalid.toml"
            invalid.write_text(
                FIXTURE.read_text(encoding="utf-8") + '\nunexpected_field = true\n',
                encoding="utf-8",
            )
            run = subprocess.run(
                [sys.executable, str(REPO_ROOT / "tools" / "validate" / "validate.py"), str(root)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(run.returncode, 1)
        self.assertIn("unexpected_field", run.stderr)


if __name__ == "__main__":
    unittest.main()