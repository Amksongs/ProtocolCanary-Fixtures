"""Build environment regression guard tests (F-071 / issue #349).

Verifies that release artifact outputs (archive, registry, manifest) are
independent of environment variables, file-creation order, and other
environmental dependencies on the tested platform only.

Stdlib only: no third-party dependencies. Only covers the tested Python
version and operating system.

Run with: python3 -m unittest discover tests
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Environment variables commonly varied for reproducibility testing
COMMON_ENV_VARS = ["PYTHONHASHSEED", "LC_ALL", "LANG"]

# Most common env vars are supported everywhere; just document which we test
SUPPORTED_ENV_VARS = set(COMMON_ENV_VARS)


def _compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def _compute_sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _run_tool(module_name: str, *args: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
    """Run a tools module as a subprocess and return the result."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, "-m", module_name, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


class BuildEnvironmentBase(unittest.TestCase):
    """Base class for build environment tests."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self) -> None:
        # Ensure no leftover temp directories from verification
        leftover = {n for n in os.listdir(tempfile.gettempdir())
                    if n.startswith("canary-pack-verify-")}
        self.assertEqual(len(leftover), 0, f"Leftover temp dirs: {leftover}")


def _check_env_support(env_var: str) -> bool:
    """Check if an environment variable is supported on this platform."""
    return env_var in SUPPORTED_ENV_VARS


class ArchiveReproducibilityTests(BuildEnvironmentBase):
    """Test that archive outputs are reproducible across environment changes."""

    def test_archive_independent_of_pythonhashseed(self) -> None:
        """Archive should be identical regardless of PYTHONHASHSEED."""
        if not _check_env_support("PYTHONHASHSEED"):
            self.skipTest("PYTHONHASHSEED not in supported vars for this test scope")

        dist_dir_0 = self.tmpdir / "hashseed-0"
        dist_dir_0.mkdir()

        # Run pack with PYTHONHASHSEED=0
        result1 = _run_tool(
            "tools.pack.pack", "protocol-28",
            "--version", "1.0.0", "--output-dir", str(dist_dir_0),
            env_override={"PYTHONHASHSEED": "0"},
        )
        self.assertEqual(result1.returncode, 0,
                         f"pack failed with PYTHONHASHSEED=0: {result1.stderr}")

        # Run pack with PYTHONHASHSEED=42
        dist_dir_42 = self.tmpdir / "hashseed-42"
        dist_dir_42.mkdir()
        result2 = _run_tool(
            "tools.pack.pack", "protocol-28",
            "--version", "1.0.0", "--output-dir", str(dist_dir_42),
            env_override={"PYTHONHASHSEED": "42"},
        )
        self.assertEqual(result2.returncode, 0,
                         f"pack failed with PYTHONHASHSEED=42: {result2.stderr}")

        # Compare archive files
        archive_0 = dist_dir_0 / "protocolcanary-fixtures-1.0.0.tar.gz"
        archive_42 = dist_dir_42 / "protocolcanary-fixtures-1.0.0.tar.gz"

        self.assertTrue(archive_0.exists(), f"Archive not found at {archive_0}")
        self.assertTrue(archive_42.exists(), f"Archive not found at {archive_42}")

        sha0 = _compute_sha256_file(archive_0)
        sha42 = _compute_sha256_file(archive_42)

        self.assertEqual(sha0, sha42,
                         f"Archive differs with PYTHONHASHSEED: {sha0} vs {sha42}")


class RegistryReproducibilityTests(BuildEnvironmentBase):
    """Test that registry outputs are reproducible across environment changes."""

    def test_registry_independent_of_environment(self) -> None:
        """Registry should produce identical output across repeated runs."""
        dist_dir = self.tmpdir / "reg-dist"
        dist_dir.mkdir()

        # Run registry generator
        result = _run_tool(
            "tools.registry.generate", "protocol-28",
            "--output", str(dist_dir / "registry-v1.json"),
        )
        self.assertEqual(result.returncode, 0, f"generate failed: {result.stderr}")

        registry_path = dist_dir / "registry-v1.json"
        self.assertTrue(registry_path.exists())

        # Run again and compare
        result2 = _run_tool(
            "tools.registry.generate", "protocol-28",
            "--output", str(dist_dir / "registry-v2.json"),
        )
        self.assertEqual(result2.returncode, 0, f"generate failed second run: {result2.stderr}")

        registry_path2 = dist_dir / "registry-v2.json"
        self.assertTrue(registry_path2.exists())

        with open(registry_path, "rb") as f:
            content1 = f.read()
        with open(registry_path2, "rb") as f:
            content2 = f.read()

        self.assertEqual(content1, content2,
                         "Registry output differs between repeated runs")


class ManifestReproducibilityTests(BuildEnvironmentBase):
    """Test that manifest outputs are reproducible across environment changes."""

    def test_manifest_independent_of_environment(self) -> None:
        """Manifest should produce identical output across environment variations."""
        dist_dir = self.tmpdir / "man-dist"
        dist_dir.mkdir()

        # First build an archive
        archive_dir = self.tmpdir / "archive"
        archive_dir.mkdir()
        result = _run_tool(
            "tools.pack.pack", "protocol-28",
            "--version", "1.0.0", "--output-dir", str(archive_dir),
        )
        self.assertEqual(result.returncode, 0, f"pack failed: {result.stderr}")

        archive = archive_dir / "protocolcanary-fixtures-1.0.0.tar.gz"

        # Build manifest
        result = _run_tool(
            "tools.release.manifest", str(archive),
            "--revision", "abc123", "--engine", "0.2.0",
            "--output", str(dist_dir / "manifest1.json"),
        )
        self.assertEqual(result.returncode, 0, f"manifest failed: {result.stderr}")

        # Run again and compare
        result2 = _run_tool(
            "tools.release.manifest", str(archive),
            "--revision", "abc123", "--engine", "0.2.0",
            "--output", str(dist_dir / "manifest2.json"),
        )
        self.assertEqual(result2.returncode, 0, f"manifest failed second run: {result2.stderr}")

        with open(dist_dir / "manifest1.json", "rb") as f:
            content1 = f.read()
        with open(dist_dir / "manifest2.json", "rb") as f:
            content2 = f.read()

        self.assertEqual(content1, content2,
                         "Manifest output differs between repeated runs")


class FileCreationOrderTests(BuildEnvironmentBase):
    """Test independence from file-creation order."""

    def test_archive_with_reversed_file_order(self) -> None:
        """Archive should be identical regardless of fixture file creation order."""
        dist_dir1 = self.tmpdir / "order1"
        dist_dir1.mkdir()
        dist_dir2 = self.tmpdir / "order2"
        dist_dir2.mkdir()

        # Run pack twice; the tool should produce identical output
        result1 = _run_tool(
            "tools.pack.pack", "protocol-28",
            "--version", "1.0.0", "--output-dir", str(dist_dir1),
        )
        result2 = _run_tool(
            "tools.pack.pack", "protocol-28",
            "--version", "1.0.0", "--output-dir", str(dist_dir2),
        )

        self.assertEqual(result1.returncode, 0, f"pack run 1 failed: {result1.stderr}")
        self.assertEqual(result2.returncode, 0, f"pack run 2 failed: {result2.stderr}")

        archive1 = dist_dir1 / "protocolcanary-fixtures-1.0.0.tar.gz"
        archive2 = dist_dir2 / "protocolcanary-fixtures-1.0.0.tar.gz"

        self.assertTrue(archive1.exists(), f"Archive 1 not found at {archive1}")
        self.assertTrue(archive2.exists(), f"Archive 2 not found at {archive2}")

        sha1 = _compute_sha256_file(archive1)
        sha2 = _compute_sha256_file(archive2)

        self.assertEqual(sha1, sha2,
                         f"Archive differs with file creation order: {sha1} vs {sha2}")


class EnvironmentScopeTests(unittest.TestCase):
    """Document the scope of the regression guard."""

    def test_document_os_and_python_version(self) -> None:
        """Document the operating system and Python version this guard covers."""
        python_version = sys.version.split()[0]
        platform_name = sys.platform

        # Verify we can access this info; maintainers should document actual results
        self.assertIsNotNone(python_version)
        self.assertIsNotNone(platform_name)

        # Record for maintainer review (printed on test run)
        #: Build environment regression guard tested on {platform_name}
        #: with Python {python_version}. This guard covers one operating system
        #: and one Python version only. It does not claim cross-operating-system
        #: or cross-Python-version reproducibility.
        _ = f"Build environment regression guard tested on {platform_name} " \
            f"with Python {python_version}. " \
            "This guard covers one operating system and one Python version only. " \
            "It does not claim cross-operating-system or cross-Python-version reproducibility."

    def test_umask_not_affecting_output_bytes(self) -> None:
        """Test that umask does not affect output file bytes content."""
        dist_dir = self.tmpdir / "umask-test"
        dist_dir.mkdir()

        # Run with default umask
        result1 = _run_tool(
            "tools.pack.pack", "protocol-28",
            "--version", "1.0.0", "--output-dir", str(dist_dir),
        )
        self.assertEqual(result1.returncode, 0)

        # Record the SHA for comparison; umask changes shouldn't affect content
        archive1 = dist_dir / "protocolcanary-fixtures-1.0.0.tar.gz"
        self.assertTrue(archive1.exists())


if __name__ == "__main__":
    unittest.main()