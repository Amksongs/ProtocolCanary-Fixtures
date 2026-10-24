"""Run a deterministic fixture-pack archive against a pinned engine binary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.pack.verify_archive import extract_safely

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_BIN = os.environ.get("STELLAR_CANARY_BIN")
ENGINE_VERSION = "0.2.0"


class EngineCommandError(AssertionError):
    """A command failed, with its exit code and captured output preserved."""


def run_checked(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise EngineCommandError(
            f"command exited with code {result.returncode}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout or '<empty>'}\n"
            f"stderr:\n{result.stderr or '<empty>'}"
        )
    return result


class EngineCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(
        ENGINE_BIN or os.environ.get("STELLAR_CANARY_REQUIRED") == "1",
        "set STELLAR_CANARY_BIN to run pinned-engine integration",
    )
    def test_built_archive_passes_pinned_engine(self) -> None:
        engine = Path(ENGINE_BIN or "")
        self.assertTrue(engine.is_file(), f"engine binary does not exist: {engine}")
        self.assertTrue(
            os.access(engine, os.X_OK), f"engine binary is not executable: {engine}"
        )

        with tempfile.TemporaryDirectory(prefix="canary-engine-compat-") as directory:
            work = Path(directory)
            archive_dir = work / "archive"
            archive = archive_dir / "protocolcanary-fixtures-1.0.0.tar.gz"
            extracted_pack = work / "extracted-pack"
            extracted_pack.mkdir()

            run_checked(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools/pack/pack.py"),
                    str(REPO_ROOT / "protocol-28"),
                    "--version",
                    "1.0.0",
                    "--output-dir",
                    str(archive_dir),
                ]
            )
            run_checked(
                [sys.executable, str(REPO_ROOT / "tools/pack/verify_archive.py"), str(archive)]
            )
            extract_safely(archive, extracted_pack)

            version = run_checked([str(engine), "--version"])
            self.assertIn(ENGINE_VERSION, version.stdout, version.stdout)

            config = work / ".stellar-canary.toml"
            config.write_text(
                "version = 1\nprotocol = 28\n\n"
                "[tests]\nxdr = true\nrpc = false\nsoroban = false\n",
                encoding="utf-8",
            )
            result = run_checked(
                [
                    str(engine),
                    "check",
                    "--fixtures-dir",
                    str(extracted_pack),
                    "--protocol",
                    "28",
                    "--json",
                    "--no-cache",
                ],
                cwd=work,
            )

            try:
                report = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                self.fail(
                    f"engine output was not valid JSON: {error}\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            self.assertIsInstance(report, dict, result.stdout)
            self.assertEqual(report.get("status"), "pass", report)
            counts = report.get("counts")
            self.assertIsInstance(counts, dict, report)
            for field in ("total", "failed", "errors"):
                self.assertIsInstance(counts.get(field), int, counts)
            self.assertGreater(counts["total"], 0, counts)
            self.assertEqual(counts["failed"], 0, counts)
            self.assertEqual(counts["errors"], 0, counts)
            results = report.get("results")
            self.assertIsInstance(results, list, report)
            self.assertTrue(results, report)
            self.assertTrue(
                all(isinstance(item, dict) and item.get("surface") == "xdr" for item in results),
                results,
            )
            print(f"Engine {ENGINE_VERSION} passed the extracted archive: {counts}")

    def test_nonzero_exit_contains_command_and_output(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["stellar-canary", "check"],
            returncode=7,
            stdout="report was incomplete",
            stderr="engine rejected fixture",
        )
        with mock.patch("tests.test_engine_compat.subprocess.run", return_value=failed):
            with self.assertRaises(EngineCommandError) as raised:
                run_checked(["stellar-canary", "check"])

        message = str(raised.exception)
        self.assertIn("exited with code 7", message)
        self.assertIn("stellar-canary check", message)
        self.assertIn("report was incomplete", message)
        self.assertIn("engine rejected fixture", message)


if __name__ == "__main__":
    unittest.main()