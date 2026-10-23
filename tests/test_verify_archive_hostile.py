"""The hostile-archive corpus for tools/pack/verify_archive.py (F-070 / issue #346).

Every case is built locally, from the real ``protocol-28`` pack, with the
standard library only: nothing is downloaded, and the same input always gives
the same archive bytes. The corpus is run against the ``verify_archive.py``
command line tool, so the exit code, the message and the files left on disk
are the ones a consumer would see.

For every case the test records:

* the CF-06 clause the case exercises;
* the classification of the observed behaviour -- ``rejected`` when the
  verifier refuses the archive, ``accepted`` when it accepts the archive and
  the contract permits it, and ``policy-decision`` when it accepts the
  archive but the contract does not settle the question;
* the exit code the verifier returns.

The cases classified ``policy-decision`` are listed with the follow-up a
maintainer has to make. Accepting an archive is not, on its own, evidence of
an exploitable problem: it is a question about what the contract says, and
the corpus exists to put that question in front of a maintainer.

The tools are not changed by this corpus. ``tools/pack/verify_archive.py`` and
``tools/pack/pack.py`` are the code under test, and the corpus only builds
inputs for them.

Run with: python3 -m unittest tests.test_verify_archive_hostile
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hostile_archives as corpus  # noqa: E402

VERIFY = REPO_ROOT / "tools" / "pack" / "verify_archive.py"

# The whole corpus has to finish well inside the CI job. The limit is a
# guard against a case that turns into a decompression or extraction bomb.
TIME_LIMIT_SECONDS = 120


def _verify_directories() -> set[str]:
    """The extraction directories the verifier is supposed to clean up."""
    return {
        name
        for name in os.listdir(tempfile.gettempdir())
        if name.startswith("canary-pack-verify-")
    }


def _repository_snapshot() -> dict[str, int]:
    """The size of every file in the repository, so a write would show."""
    snapshot: dict[str, int] = {}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(".git/") or "__pycache__" in relative:
            continue
        try:
            snapshot[relative] = path.stat().st_size
        except OSError:
            continue
    return snapshot


class HostileArchiveCorpusTests(unittest.TestCase):
    """Run every case of the corpus against the verifier."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="canary-hostile-corpus-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.before_directories = _verify_directories()
        self.before_repository = _repository_snapshot()

    def tearDown(self) -> None:
        # The verifier must not leave an extraction directory behind.
        self.assertEqual(
            _verify_directories(),
            self.before_directories,
            "the verifier left an extraction directory behind",
        )

    def _build(self, case) -> Path:
        """Build one case in a directory of its own."""
        directory = self.work / case.name
        directory.mkdir(exist_ok=True)
        return case.build(directory)

    def _run(self, archive: Path) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        # Keep the repository tree free of __pycache__ directories, so the
        # "nothing was written outside the destination" check stays exact.
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(VERIFY), str(archive)],
            cwd=str(self.work),
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_corpus_cases(self) -> None:
        """Each case gives the expected exit code, without a traceback."""
        started = time.monotonic()
        for case in corpus.CASES:
            with self.subTest(case=case.name):
                archive = self._build(case)
                self.assertTrue(archive.is_file(), f"{case.name} produced no archive")
                result = self._run(archive)
                self.assertNotIn(
                    "Traceback (most recent call last)",
                    result.stderr,
                    f"{case.name} made the verifier crash:\n{result.stderr}",
                )
                self.assertIn(
                    result.returncode,
                    (0, 1, 2),
                    f"{case.name} returned an unexpected exit code",
                )
                self.assertEqual(
                    result.returncode,
                    case.exit_code,
                    f"{case.name}: expected exit code {case.exit_code}, got "
                    f"{result.returncode}\n{result.stdout}{result.stderr}",
                )
        elapsed = time.monotonic() - started
        self.assertLess(
            elapsed,
            TIME_LIMIT_SECONDS,
            f"the corpus took {elapsed:.1f}s, over the {TIME_LIMIT_SECONDS}s limit",
        )

    def test_nothing_is_written_outside_the_destination(self) -> None:
        """The verifier writes only inside its own temporary directory."""
        for case in corpus.CASES:
            with self.subTest(case=case.name):
                archive = self._build(case)
                self._run(archive)
                directory = archive.parent
                leftovers = sorted(
                    path.name for path in directory.iterdir() if path.name != archive.name
                )
                self.assertEqual(
                    leftovers,
                    [],
                    f"{case.name} left files in the working directory: {leftovers}",
                )
        self.assertEqual(
            _repository_snapshot(),
            self.before_repository,
            "the verifier wrote to the repository tree",
        )

    def test_rejected_cases_say_why(self) -> None:
        """A refused archive names the problem instead of failing silently."""
        for case in corpus.CASES:
            if case.classification != corpus.REJECTED:
                continue
            with self.subTest(case=case.name):
                archive = self._build(case)
                result = self._run(archive)
                self.assertEqual(result.returncode, case.exit_code)
                self.assertTrue(
                    result.stderr.strip(),
                    f"{case.name} was refused without a message",
                )
                self.assertIn(
                    "error:",
                    result.stderr,
                    f"{case.name} did not report an error:\n{result.stderr}",
                )

    def test_accepted_cases_report_success(self) -> None:
        """An accepted archive says so, and names what it checked."""
        for case in corpus.CASES:
            if case.classification != corpus.ACCEPTED:
                continue
            with self.subTest(case=case.name):
                archive = self._build(case)
                result = self._run(archive)
                self.assertEqual(result.returncode, case.exit_code)
                self.assertIn(
                    "OK:",
                    result.stdout,
                    f"{case.name} was accepted without a success message:\n"
                    f"{result.stdout}{result.stderr}",
                )


class CorpusDocumentationTests(unittest.TestCase):
    """The corpus documents itself: clauses, classifications and coverage."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="canary-hostile-docs-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_every_case_is_classified(self) -> None:
        for case in corpus.CASES:
            with self.subTest(case=case.name):
                self.assertIn(case.classification, corpus.CLASSIFICATIONS)
                self.assertTrue(case.clauses, f"{case.name} names no CF-06 clause")
                self.assertTrue(case.description)
                self.assertTrue(
                    case.note or case.required_follow_up,
                    f"{case.name} has neither a note nor a follow-up",
                )

    def test_policy_decisions_name_their_follow_up(self) -> None:
        """A case that needs a maintainer decision says what the decision is."""
        self.assertTrue(
            corpus.POLICY_DECISION_CASES,
            "the corpus has no case that needs a maintainer decision",
        )
        for case in corpus.POLICY_DECISION_CASES:
            with self.subTest(case=case.name):
                self.assertTrue(
                    case.required_follow_up,
                    f"{case.name} needs a decision but does not say which",
                )

    def test_the_required_attack_shapes_are_covered(self) -> None:
        """Every shape the issue names is in the corpus."""
        names = " ".join(case.name for case in corpus.CASES)
        for shape in corpus.REQUIRED_SHAPES:
            with self.subTest(shape=shape):
                self.assertIn(shape, names, f"the corpus has no {shape} case")

    def test_the_corpus_is_deterministic(self) -> None:
        """Building a case twice gives the same bytes."""
        for case in corpus.CASES:
            with self.subTest(case=case.name):
                first_directory = self.root / "first" / case.name
                second_directory = self.root / "second" / case.name
                first_directory.mkdir(parents=True, exist_ok=True)
                second_directory.mkdir(parents=True, exist_ok=True)
                first = case.build(first_directory)
                second = case.build(second_directory)
                self.assertEqual(
                    first.read_bytes(),
                    second.read_bytes(),
                    f"{case.name} is not deterministic",
                )

    def test_the_corpus_does_not_change_the_tools(self) -> None:
        """The tools under test do not know about the corpus."""
        for relative in ("tools/pack/verify_archive.py", "tools/pack/pack.py"):
            with self.subTest(tool=relative):
                source = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("hostile", source)
                self.assertNotIn("unittest", source)

    def test_the_valid_case_is_the_real_pack(self) -> None:
        """The baseline case really is the protocol-28 archive."""
        members = corpus.protocol28_members()
        self.assertIn("registry.json", members)
        self.assertTrue(
            any(name.endswith(".toml") for name in members),
            "the pack has no fixtures",
        )
        with tempfile.TemporaryDirectory(prefix="canary-hostile-baseline-") as directory:
            archive = corpus._plain(Path(directory), "valid.tar.gz")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(archive)],
                cwd=directory,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fixture(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
