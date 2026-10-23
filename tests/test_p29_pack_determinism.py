"""Protocol 29 release archive reproducibility (CF-06)."""
from __future__ import annotations

import gzip
import hashlib
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_support as support  # noqa: E402

pack = support.pack


class Protocol29PackDeterminismTests(unittest.TestCase):
    def test_two_protocol29_builds_are_identical_and_within_limits(self) -> None:
        source = support.REPO_ROOT / "protocol-29"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = pack.build_archive(source, root / "first", "1.0.0")
            second = pack.build_archive(source, root / "second", "1.0.0")
            first_bytes = first.path.read_bytes()
            second_bytes = second.path.read_bytes()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.sha256, hashlib.sha256(first_bytes).hexdigest())

        members, _, _ = pack.collect_members(source)
        directories = pack.directories_of(members)
        pack.check_limits(members, directories)
        with tarfile.open(fileobj=io.BytesIO(first_bytes), mode="r:gz") as archive:
            entries = archive.getmembers()
        names = [entry.name for entry in entries]
        self.assertEqual(names, sorted(names, key=lambda name: name.encode("utf-8")))
        self.assertTrue(all(entry.mtime == 0 for entry in entries))
        self.assertEqual(first.entries, len(entries))
        self.assertLessEqual(first.uncompressed_bytes, pack.MAX_TOTAL_BYTES)

    def test_unsorted_entries_do_not_match_the_canonical_archive(self) -> None:
        source = support.REPO_ROOT / "protocol-29"
        members, _, _ = pack.collect_members(source)
        directories = set(pack.directories_of(members))
        names = sorted(set(members) | directories, key=lambda name: name.encode("utf-8"))
        raw = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as stream:
            with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8") as archive:
                for name in reversed(names):
                    if name in members:
                        data = members[name]
                        archive.addfile(
                            pack._tar_info(name, directory=False, size=len(data)), io.BytesIO(data)
                        )
                    else:
                        archive.addfile(pack._tar_info(name, directory=True))

        self.assertNotEqual(
            hashlib.sha256(raw.getvalue()).digest(),
            hashlib.sha256(pack.render_archive(members)).digest(),
        )


if __name__ == "__main__":
    unittest.main()