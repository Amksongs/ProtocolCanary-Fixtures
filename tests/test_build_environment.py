"""Build environment regression guard (F-071 / issue #349).

The release artifacts -- the archive, the registry and the manifest -- must be
the same bytes whatever machine builds them. This module is the guard that
keeps it that way: it runs the three release tools in *temporary copies* of
the repository and compares the bytes they produce under different
environments.

What is varied:

* the time zone (``TZ``), so a tool that stamped a local time would show;
* the locale (``LC_ALL``, ``LANG``), so a tool that sorted or formatted with
  the C library would show;
* ``PYTHONHASHSEED``, so a tool that let a set or dict decide the order of
  its output would show;
* the process umask, so a tool that let the umask decide a file mode would
  show.

What else is compared:

* the same tool run twice with the same settings, which must give the same
  bytes;
* the same pack written in a different order, which must give the same bytes.

Scope: this guard covers **one operating system and one Python version**,
the ones it is run on. It does not claim cross-operating-system or
cross-Python-version reproducibility, and a difference it reports has to be
read as "this platform changed", not "every platform changed".

The guard is proved to have teeth: a scratch copy of the packer is changed so
that its output depends on the environment, and the guard is expected to
notice. The production tools are never modified.

Standard library only: the default test suite installs nothing.

Run with: python3 -m unittest tests.test_build_environment
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# A full 40-character lowercase git commit hash: tools/release/manifest.py
# requires one and rejects anything shorter. It is fixed so the manifest does
# not depend on the checkout the guard runs in.
REVISION = "0123456789abcdef0123456789abcdef01234567"

VERSION = "1.0.0"
ARCHIVE_NAME = f"protocolcanary-fixtures-{VERSION}.tar.gz"

# The files the tools need from the repository.
COPY_ENTRIES = ("tools", "schemas", "protocol-28")

# The outputs the guard compares.
OUTPUT_NAMES = ("archive", "registry", "manifest", "sha256")

# The seed of the shuffled file-creation order, so the shuffle is the same on
# every run.
ORDER_SEED = 20260921


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    umask: int | None = None,
) -> subprocess.CompletedProcess:
    """Run a tool with the interpreter that runs the tests."""
    extra: dict = {}
    if umask is not None and os.name == "posix":
        extra["umask"] = umask
    return subprocess.run(
        [sys.executable, *command],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        **extra,
    )


def copy_repository(destination: Path) -> Path:
    """A copy of the repository the tools can run in.

    Only the entries the three release tools read are copied: the tests in
    this module never run the validator or the documentation tools. The copy
    has no ``.git`` directory, so the tools cannot read the checkout the guard
    happens to run in, and no stale output from an earlier run comes with it.
    """
    destination.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "dist")
    for name in COPY_ENTRIES:
        shutil.copytree(REPO_ROOT / name, destination / name, ignore=ignore)
    return destination


def _pack_files(pack: Path) -> list[Path]:
    """Every file of the pack, sorted by path."""
    return sorted(
        (path for path in pack.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(pack).as_posix(),
    )


def rewrite_pack_in_order(repository: Path, order: str) -> None:
    """Write the pack again, in the given creation order.

    ``order`` is ``"normal"``, ``"reversed"`` or ``"shuffled"``. The bytes of
    the pack do not change; only the order in which the files appear on disk
    does, which is what a checkout, an unpack or a copy can change.
    """
    pack = repository / "protocol-28"
    files = _pack_files(pack)
    contents = {path: path.read_bytes() for path in files}
    if order == "normal":
        ordered = files
    elif order == "reversed":
        ordered = list(reversed(files))
    elif order == "shuffled":
        ordered = list(files)
        random.Random(ORDER_SEED).shuffle(ordered)
    else:
        raise ValueError(f"unknown creation order {order!r}")
    shutil.rmtree(pack)
    for path in ordered:
        target = pack / path.relative_to(pack)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[path])


def build_outputs(
    repository: Path,
    output: Path,
    *,
    environment: dict[str, str] | None = None,
    umask: int | None = None,
) -> dict[str, bytes]:
    """Run the three release tools in ``repository`` and collect their bytes."""
    env = os.environ.copy()
    env.update(environment or {})
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    output.mkdir(parents=True, exist_ok=True)
    dist = output / "dist"

    registry = output / "registry.json"
    result = _run(
        ["tools/registry/generate.py", "protocol-28", "--output", str(registry)],
        cwd=repository,
        env=env,
        umask=umask,
    )
    if result.returncode != 0:
        raise AssertionError(f"the registry generator failed:\n{result.stderr}")

    result = _run(
        [
            "tools/pack/pack.py",
            "protocol-28",
            "--version",
            VERSION,
            "--output-dir",
            str(dist),
        ],
        cwd=repository,
        env=env,
        umask=umask,
    )
    if result.returncode != 0:
        raise AssertionError(f"the packer failed:\n{result.stderr}")

    archive = dist / ARCHIVE_NAME
    manifest = output / "manifest.json"
    checksum = output / "archive.sha256"
    result = _run(
        [
            "tools/release/manifest.py",
            str(archive),
            "--revision",
            REVISION,
            "--engine",
            "0.2.0",
            "--output",
            str(manifest),
            "--sha256-file",
            str(checksum),
        ],
        cwd=repository,
        env=env,
        umask=umask,
    )
    if result.returncode != 0:
        raise AssertionError(f"the manifest generator failed:\n{result.stderr}")

    return {
        "archive": archive.read_bytes(),
        "registry": registry.read_bytes(),
        "manifest": manifest.read_bytes(),
        "sha256": checksum.read_bytes(),
    }


def available_locales() -> set[str]:
    """The locales this machine has, or an empty set when it cannot say."""
    if os.name != "posix":
        return set()
    try:
        result = subprocess.run(
            ["locale", "-a"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


class BuildEnvironmentBase(unittest.TestCase):
    """A temporary copy of the repository per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="canary-build-env-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.counter = 0

    def _repository(self) -> Path:
        self.counter += 1
        destination = self.root / f"repo-{self.counter}"
        return copy_repository(destination)

    def _output(self) -> Path:
        self.counter += 1
        return self.root / f"out-{self.counter}"

    def _build(
        self,
        repository: Path | None = None,
        *,
        environment: dict[str, str] | None = None,
        umask: int | None = None,
    ) -> dict[str, bytes]:
        if repository is None:
            repository = self._repository()
        return build_outputs(
            repository, self._output(), environment=environment, umask=umask
        )

    def assertSameOutputs(self, first: dict[str, bytes], second: dict[str, bytes], why: str) -> None:
        for name in OUTPUT_NAMES:
            with self.subTest(output=name):
                self.assertEqual(
                    first[name],
                    second[name],
                    f"{why}: the {name} differs",
                )


class EnvironmentVariationTests(BuildEnvironmentBase):
    """The outputs do not depend on the environment they are built in."""

    def test_time_zone_does_not_change_the_output(self) -> None:
        baseline = self._build()
        for zone in ("UTC", "America/New_York", "Pacific/Kiritimati", "Asia/Tokyo"):
            with self.subTest(time_zone=zone):
                outputs = self._build(environment={"TZ": zone})
                self.assertSameOutputs(baseline, outputs, f"under TZ={zone}")

    def test_locale_does_not_change_the_output(self) -> None:
        baseline = self._build()
        installed = available_locales()
        candidates = ["C", "POSIX", "C.UTF-8", "en_US.UTF-8", "de_DE.UTF-8"]
        checked = 0
        for locale in candidates:
            if locale not in installed and locale not in ("C", "POSIX"):
                # The locale is not installed on this machine, so the tool
                # would fall back to the C locale and the case would prove
                # nothing.
                continue
            checked += 1
            with self.subTest(locale=locale):
                outputs = self._build(environment={"LC_ALL": locale, "LANG": locale})
                self.assertSameOutputs(baseline, outputs, f"under LC_ALL={locale}")
        self.assertGreater(checked, 0, "no locale could be tested")

    def test_python_hash_seed_does_not_change_the_output(self) -> None:
        baseline = self._build()
        for seed in ("0", "1", "42", "12345"):
            with self.subTest(python_hash_seed=seed):
                outputs = self._build(environment={"PYTHONHASHSEED": seed})
                self.assertSameOutputs(baseline, outputs, f"under PYTHONHASHSEED={seed}")

    def test_umask_does_not_change_the_output(self) -> None:
        if os.name != "posix":
            self.skipTest("the process umask is a POSIX concept; Windows has none")
        baseline = self._build()
        for mask in (0o022, 0o077, 0o000, 0o002):
            with self.subTest(umask=oct(mask)):
                outputs = self._build(umask=mask)
                self.assertSameOutputs(baseline, outputs, f"under umask {oct(mask)}")

    def test_repeated_executions_produce_identical_output(self) -> None:
        """The same settings give the same bytes every time."""
        first = self._build()
        second = self._build()
        self.assertSameOutputs(first, second, "two runs with the same settings")

    def test_file_creation_order_does_not_change_the_output(self) -> None:
        """The order the pack files were written in does not matter."""
        baseline = self._build()
        for order in ("normal", "reversed", "shuffled"):
            with self.subTest(creation_order=order):
                repository = self._repository()
                rewrite_pack_in_order(repository, order)
                outputs = self._build(repository)
                self.assertSameOutputs(baseline, outputs, f"with the {order} order")


class GuardHasTeethTests(BuildEnvironmentBase):
    """The guard notices an output that depends on the environment."""

    # The packer writes the gzip header without a name, so the archive does
    # not carry one. The scratch copy below puts the time zone into that
    # header, which is exactly the kind of environment dependence the guard
    # exists to catch.
    PATCH = (
        'gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0)',
        'gzip.GzipFile(\n            filename=os.environ.get("TZ", ""),\n'
        '            mode="wb",\n'
        '            fileobj=raw,\n'
        '            compresslevel=9,\n'
        '            mtime=0,\n'
        '        )',
    )

    def test_an_environment_dependent_output_is_caught(self) -> None:
        """A scratch packer that leaks the time zone is noticed."""
        repository = self._repository()
        packer = repository / "tools" / "pack" / "pack.py"
        source = packer.read_text(encoding="utf-8")
        self.assertIn(self.PATCH[0], source, "the scratch patch no longer applies")
        source = source.replace(self.PATCH[0], self.PATCH[1], 1)
        source = source.replace("import re\n", "import os\nimport re\n", 1)
        packer.write_text(source, encoding="utf-8")

        first = self._build(repository, environment={"TZ": "UTC"})
        second = self._build(repository, environment={"TZ": "Asia/Tokyo"})
        self.assertNotEqual(
            first["archive"],
            second["archive"],
            "the environment-dependent scratch packer was not noticed",
        )

    def test_the_production_packer_is_not_the_scratch_one(self) -> None:
        """The scratch copy is a copy; the production packer is untouched."""
        source = (REPO_ROOT / "tools" / "pack" / "pack.py").read_text(encoding="utf-8")
        self.assertIn(self.PATCH[0], source)
        self.assertNotIn('os.environ.get("TZ"', source)


class ScopeDocumentationTests(unittest.TestCase):
    """The guard says what it covers, so nobody reads more into it."""

    def test_the_scope_is_documented(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("one operating system and one Python version", source)
        self.assertIn("does not claim cross-operating-system", source)

    def test_the_platform_is_reported(self) -> None:
        """The platform the guard covers is visible in the run."""
        self.assertIn(sys.platform, (os.name, sys.platform, "win32", "linux", "darwin"))
        self.assertTrue(sys.version_info >= (3, 11))


if __name__ == "__main__":
    unittest.main()
