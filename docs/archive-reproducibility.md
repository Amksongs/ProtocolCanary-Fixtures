# Archive reproducibility

This document records the cross-platform baseline for the fixture-pack archive
(issue #365, CF-06 section 2). It states what was measured, what was equal,
what differed and why, which invariant the repository now enforces, and which
one it deliberately does not.

**No cross-platform byte equality is claimed for the compressed archive.** The
measurement below is the evidence for that statement; it is not a promise that
the compressed bytes never change.

---

## 1. What is measured

`tools/pack/pack.py` writes a gzip stream, so the archive has two digests, and
they answer different questions:

| Digest | What it covers | What it depends on |
|---|---|---|
| **compressed** (`compressedSha256`) | the `.tar.gz` file a consumer pins | this repository's tar metadata **and** the zlib implementation in the Python build that produced it |
| **uncompressed** (`uncompressedSha256`) | the tar stream inside the gzip wrapper | this repository's own code only: sorted entries, fixed metadata, `mtime` 0 |

The uncompressed digest is the one the repository can justify, because the
tar stream is produced by this repository's code. The compressed digest is
reported as an observation, because the compressed bytes are at the mercy of
the compression library in each Python build (and of the gzip header the
library writes).

Both digests, plus the environment that produced them (`sys.version`,
`zlib.ZLIB_VERSION`, `zlib.ZLIB_RUNTIME_VERSION`, platform), are written by
`tools/pack/archive_digests.py build` as one JSON document per cell.

## 2. What is enforced, and what is not

| Rule | Behaviour |
|---|---|
| The **uncompressed** tar-stream digest differs between two cells | the comparison job **fails** and prints the table and the first differing byte offset and tar member |
| The **compressed** digest differs between two cells | reported as an observation in the job summary; the job still **passes** |
| A cell produced no digest (the build or the artifact upload failed) | reported as a **cell failure**, not as a digest difference; the job fails |
| The number of cells does not match the declared matrix | reported as an inconsistency; the job fails |

Enforcing the uncompressed digest is safe because a difference there is a
defect in this repository's determinism or a platform-dependent path in its
code. Enforcing the compressed digest is not, because the compressed bytes are
not fully under this repository's control. Pinning the compression
implementation (for example shipping a fixed zlib, or writing the gzip stream
by hand) is a maintainer decision that needs this baseline first and is out of
scope for #365.

## 3. The measurement

The baseline was measured with `.github/workflows/archive-baseline.yml`, which
builds the archive for `protocol-28` with a fixed version string (`0.0.0`) in
every cell of the platform and Python-version matrix, uploads the two digests
and the tar stream as one artifact per cell, and compares the cells in a final
job.

Matrix: `ubuntu-latest`, `macos-latest`, `windows-latest` × Python 3.11, 3.12,
3.13.

Run: <https://github.com/ayomustap/ProtocolCanary-Fixtures/actions/runs/39700153480>
(fork `ayomustap/ProtocolCanary-Fixtures`, branch `main`, 2026-10-22).

### 3.1 First run: the uncompressed digest was not equal

The first run (2026-10-22, run
[39699647116](https://github.com/ayomustap/ProtocolCanary-Fixtures/actions/runs/39699647116))
failed exactly as designed: the three Windows cells produced a different
tar stream from the six Linux and macOS cells.

| cell | platform | Python | zlib (runtime) | compressed sha256 | uncompressed sha256 |
|---|---|---|---|---|---|
| macos-latest-py3.11 | Darwin | 3.11.9 | 1.2.12 | `c99ca009ed6a…` | `8ccdaefaefc9…` |
| macos-latest-py3.12 | Darwin | 3.12.10 | 1.2.12 | `c99ca009ed6a…` | `8ccdaefaefc9…` |
| macos-latest-py3.13 | Darwin | 3.13.16 | 1.2.12 | `c99ca009ed6a…` | `8ccdaefaefc9…` |
| ubuntu-latest-py3.11 | Linux | 3.11.17 | 1.3 | `c99ca009ed6a…` | `8ccdaefaefc9…` |
| ubuntu-latest-py3.12 | Linux | 3.12.15 | 1.3 | `c99ca009ed6a…` | `8ccdaefaefc9…` |
| ubuntu-latest-py3.13 | Linux | 3.13.16 | 1.3 | `c99ca009ed6a…` | `8ccdaefaefc9…` |
| windows-latest-py3.11 | Windows | 3.11.9 | 1.3.1 | `86f1274f551b…` | `4a62fc735ea1…` |
| windows-latest-py3.12 | Windows | 3.12.10 | 1.3.1 | `86f1274f551b…` | `4a62fc735ea1…` |
| windows-latest-py3.13 | Windows | 3.13.16 | 1.3.1 | `86f1274f551b…` | `4a62fc735ea1…` |

The comparison job printed the first differing byte and the tar member it
belongs to:

```
the uncompressed tar-stream digest differs between cells:
windows-latest-py3.11 vs macos-latest-py3.11: first difference at byte 680:
registry.json (data at byte 680, 12988 byte(s) of data)
```

### 3.2 The cause of the difference: the checkout, not the packer

The difference was **not** in `tools/pack/pack.py`. Comparing the tar members
of the Windows and macOS streams of that run:

| member | Windows | macOS |
|---|---|---|
| `rpc/p28-rpc-network.toml` | 1476 bytes, 43 CRLF line endings | 1433 bytes, 43 LF line endings |
| `soroban/p28-soroban-sim-error-arg-count.toml` | 3021 bytes, 55 CRLF | 2966 bytes, 55 LF |
| … | every fixture file: LF rewritten to CRLF | unchanged |
| `registry.json` | same length, different bytes | — |

Every fixture file on Windows was exactly its macOS counterpart with LF
rewritten to CRLF (the Windows copy is longer by one byte per line), and
`registry.json` differed because it carries the SHA-256 of each fixture file.

The cause is in this repository's checkout, not in the archive builder: the
Windows runners have `core.autocrlf=true`, and `.gitattributes` did not say
what should happen to the pack files. Without an explicit rule, git rewrites
LF as CRLF in the working tree, so the *fixture bytes* — and every digest
computed from them — changed on Windows before the packer ever ran.

The fix is in `.gitattributes`: the pack files and the conformance vectors are
now checked out with `eol=lf` on every platform, so the bytes the packer reads
are the bytes in the repository.

### 3.3 Second run: after the fix, every cell agrees

Run [39700153480](https://github.com/ayomustap/ProtocolCanary-Fixtures/actions/runs/39700153480)
(2026-10-22, after the `.gitattributes` fix) produced **one** uncompressed
digest and **one** compressed digest across all nine cells:

| cell | platform | Python | zlib (runtime / linked) | compressed sha256 | uncompressed sha256 |
|---|---|---|---|---|---|
| macos-latest-py3.11 | Darwin | 3.11.9 | 1.2.12 / 1.2.11 | `c99ca009ed6ad3c167dae981632f647f47894d7a385d49dfea760f600de30f24` | `8ccdaefaefc96a7a7f4c5a4365d1ccd6b1e027eb1e97094ec904fbbf13664c68` |
| macos-latest-py3.12 | Darwin | 3.12.10 | 1.2.12 / 1.2.11 | same | same |
| macos-latest-py3.13 | Darwin | 3.13.16 | 1.2.12 / 1.2.12 | same | same |
| ubuntu-latest-py3.11 | Linux | 3.11.17 | 1.3 / 1.3 | same | same |
| ubuntu-latest-py3.12 | Linux | 3.12.15 | 1.3 / 1.3 | same | same |
| ubuntu-latest-py3.13 | Linux | 3.13.16 | 1.3 / 1.3 | same | same |
| windows-latest-py3.11 | Windows | 3.11.9 | 1.3.1 / 1.3.1 | same | same |
| windows-latest-py3.12 | Windows | 3.12.10 | 1.3.1 / 1.3.1 | same | same |
| windows-latest-py3.13 | Windows | 3.13.16 | 1.3.1 / 1.3.1 | same | same |

Archive size in every cell: 15,364 compressed bytes, 102,400 uncompressed
bytes, 24 members (23 fixture and registry files plus the directory entries).

The comparison job **passed**: the uncompressed digest was identical in all
nine cells, and the compressed digest was reported as an observation.

## 4. Sources of legitimate variation

| What can vary | Why | Effect on the digests |
|---|---|---|
| zlib version (1.2.11, 1.2.12, 1.3, 1.3.1 in this matrix) | each Python build links its own zlib, and the deflate implementation may change between versions | the **compressed** digest can change; the uncompressed digest cannot |
| Python patch version (3.11.9, 3.12.10, 3.13.16, …) | the matrix tracks minor versions, and patch releases change the interpreter | none observed; the packer is standard-library code that does not depend on the patch level |
| gzip header bytes (OS byte, mtime) | written by the `gzip` module of each build | the OS byte was `255` ("unknown") in every cell of the baseline run, and `mtime` is 0 by construction |

In this run the compressed digest happened to be equal in all nine cells, even
though the cells link three different zlib versions. That is an observation
about this pack and this input, **not** a guarantee: it is exactly the kind of
coincidence the compressed digest must not be relied on for, which is why it
is not enforced.

## 5. Reproducing the measurement

```bash
# One cell: build the archive and print both digests and the environment.
python3 tools/pack/archive_digests.py build --pack protocol-28 --version 0.0.0

# Compare several cells (the artifacts of a workflow run).
python3 tools/pack/archive_digests.py compare --results artifacts \
    --expected-matrix '{"os": ["ubuntu-latest", "macos-latest", "windows-latest"],
                        "python": ["3.11", "3.12", "3.13"]}'
```

The whole matrix runs in CI: `.github/workflows/archive-baseline.yml`
(`workflow_dispatch`, plus `pull_request` and `push` on the paths that can
change the digests). It uses `permissions: contents: read` and pinned action
commits, and needs no secrets.

## 6. Negative testing

| Scenario | Expected | Result |
|---|---|---|
| A forced difference in the uncompressed stream | the comparison fails with a readable table | covered by `tests/test_archive_digests.py` (`test_compare_fails_when_the_uncompressed_digest_differs`), and observed for real in run 39699647116 above |
| A forced difference in compression only (different gzip level, same tar stream) | the comparison does not fail | covered by `tests/test_archive_digests.py` (`test_compare_reports_a_compressed_difference_without_failing`) |
| A cell that fails to build | reported as a cell failure, not as a digest difference | covered by `tests/test_archive_digests.py` (`test_compare_reports_a_missing_cell_as_a_cell_failure`) |

## 7. Open decisions for the maintainers

These are deliberately **not** decided here:

1. whether the compressed digest should become stable (pinning the
   compression implementation, or writing the gzip stream by hand);
2. whether the compressed digest should be published per platform, or only the
   uncompressed one;
3. whether the matrix should track Python patch versions.

Until a decision is recorded, the repository enforces exactly one thing: the
uncompressed tar stream is the same on every platform and Python version in the
matrix.
