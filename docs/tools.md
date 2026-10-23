# Tool Command-Line Contracts

This document records the exact command-line interface, options, exit codes, and output streams of the repository's maintenance, packaging, and validation tools.

CI jobs, release workflows, and contributor scripts rely on these contracts. Any changes to exit codes or stream destinations represent changes to these contracts.

---

## Table of Tools

1. [`tools/pack/pack.py`](#toolspackpackpy)
2. [`tools/pack/verify_archive.py`](#toolspackverify_archivepy)
3. [`tools/pack/archive_digests.py`](#toolspackarchive_digestspy)
4. [`tools/evidence/record_structural.py`](#toolsevidencerecord_structuralpy)
5. [`tools/registry/generate.py`](#toolsregistrygeneratepy)
6. [`tools/registry/diff.py`](#toolsregistrydiffpy)
7. [`tools/inventory/compare.py`](#toolsinventorycomparepy)
8. [`tools/release/manifest.py`](#toolsreleasemanifestpy)
9. [`tools/badge/badge.py`](#toolsbadgebadgepy)
10. [`tools/validate/validate.py`](#toolsvalidatevalidatepy)
11. [`tools/validate/schema_sync.py`](#toolsvalidateschema_syncpy)
12. [`tools/evidence/capture_live.py`](#toolsevidencecapture_livepy)
13. [`tools/validate/validate_registry.py`](#toolsvalidatevalidate_registrypy)
14. [Observed Inconsistencies](#observed-inconsistencies)

---

## `tools/pack/pack.py`

Builds the deterministic release archive for one protocol pack (CF-06). Reads pack fixtures and generated registry; verifies limits and produces a reproducible `.tar.gz`.

### Synopsis

```bash
python3 tools/pack/pack.py PACK --version VERSION [--output-dir DIR] [--verified]
```

### Options

- `-h`, `--help`: show this help message and exit
- `--version VERSION`: release version, MAJOR.MINOR.PATCH; names the archive
- `--output-dir DIR`: directory for the archive (default: dist)
- `--verified`: require valid, passing CF-04 evidence for every fixture

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: deterministic archive created in output directory. |
| `1` | Pack error: pack path is not a directory, empty pack, invalid semver format, broken fixture, missing or invalid verification evidence with `--verified`, limit violation, or archive write failure. |
| `2` | Command-line syntax error: missing required arguments (`PACK` or `--version`), or unknown options. |

### Output Streams

- **stdout**: Information about created archive (archive name, SHA-256 digest, uncompressed byte size); help text when `--help` is invoked.
- **stderr**: Argument parsing errors and pack build failures.

---

## `tools/pack/verify_archive.py`

Extracts a fixture-pack archive safely and validates its contents according to CF-06.

### Synopsis

```bash
python3 tools/pack/verify_archive.py [--sha256 HEX] [--manifest PATH] archive
```

### Options

- `-h`, `--help`: show this help message and exit
- `--sha256 HEX`: expected SHA-256 of the archive (64 hexadecimal characters)
- `--manifest PATH`: a release manifest the archive must match. The archive hash and the pack digest are compared, and every fact the manifest states about the archive is checked against the archive: the file name, the size, the entry count, the uncompressed bytes, the version in the file name, the pack name, the manifest version, and the protocols and the registry version of the archived `registry.json`. Every difference is reported, with the field, the value the manifest states and the value the archive gives.

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: archive passes all extraction safety and validation checks, and matches expected SHA-256 / manifest if supplied. |
| `1` | Archive verification error: archive hash mismatch, `--sha256` disagreeing with the manifest, a fact of the manifest that the archive does not bear out, or archive contents violate pack limits/rules. |
| `2` | Unusable input: missing archive argument, unknown command-line option, a `--sha256` that is not 64 hexadecimal characters, a manifest that cannot be read or does not carry `archive.sha256` and `packDigest`, an archive file that does not exist, or a path that is not a regular file. |

### Output Streams

- **stdout**: Verification status message (`OK: <archive>: ... valid; registry and pack digest match`); help text when `--help` is invoked.
- **stderr**: Error diagnostics on failure.

---

## `tools/pack/archive_digests.py`

Measures the archive's two digests and compares them across cells (issue #365, `docs/archive-reproducibility.md`). Builds the archive with `tools/pack/pack.py` and only reads the bytes back; it never changes the archive format or the compression settings.
## `tools/evidence/record_structural.py`

Writes CF-04 verification records for the structural check of a pack (issue #366, `docs/verification-records.md`). Runs the structural validation, then writes one record per fixture with the SHA-256 of the fixture file, the instant the check ran and `method: "structural"`. It writes nothing when a fixture does not validate, never derives an instant from a header comment, and never records a live observation.

### Synopsis

```bash
python3 tools/pack/archive_digests.py build [--pack PACK] [--version VERSION]
    [--output PATH] [--stream PATH] [--cell NAME]
python3 tools/pack/archive_digests.py compare --results DIR
    [--expected-cell CELL] [--expected-matrix JSON] [--summary-file PATH]
python3 tools/evidence/record_structural.py PACK [--output-dir DIR]
    [--verifier-version VERSION] [--dry-run]
```

### Options

`build`:

- `-h`, `--help`: show this help message and exit
- `--pack PACK`: pack directory to build (default: `protocol-28`)
- `--version VERSION`: release version used to name the archive (default: `0.0.0`)
- `--output PATH`: also write the result document here (default: stdout only)
- `--stream PATH`: also write the uncompressed tar stream here (default: `stream.tar` next to `--output`)
- `--cell NAME`: the name of the cell this measurement was made in (default: the platform and Python version)

`compare`:

- `-h`, `--help`: show this help message and exit
- `--results DIR`: directory holding the result documents of the cells (required)
- `--expected-cell CELL`: a cell that must be present; may be given more than once
- `--expected-matrix JSON`: the matrix the cells come from, as JSON (`{"os": [...], "python": [...]}`); every cell it names must be present
- `--summary-file PATH`: also write the report here (for example `$GITHUB_STEP_SUMMARY`)
- `-h`, `--help`: show this help message and exit
- `PACK`: the pack directory to check (required)
- `--output-dir DIR`: where to write the records (default: `PACK/evidence/records`)
- `--verifier-version VERSION`: the version to record for the verifier (default: the commit the validator was read from)
- `--dry-run`: run the check and report what would be written, but write nothing

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: the digests were measured, or the cells agree on the uncompressed tar-stream digest. |
| `1` | The digests differ between cells, a cell produced no digest, the cell count does not match the declared matrix, a result document is unreadable, or the archive could not be built. |
| `2` | Command-line syntax error: missing `--results`, unknown options, or `--expected-matrix` that is not a JSON object. |

### Output Streams

- **stdout**: the result document (`build`) or the markdown table and report (`compare`); help text when `--help` is invoked.
- **stderr**: error diagnostics; the comparison failures are repeated there as `error: …`.
| `0` | Success: the pack validates and every record was written (or would be, with `--dry-run`). |
| `1` | The records cannot be written: the pack does not validate, holds no fixture, or a record would not satisfy the CF-04 rules. Nothing is written. |
| `2` | Command-line syntax error: missing `PACK` or unknown options. |

### Output Streams

- **stdout**: the number of records written and their paths; help text when `--help` is invoked.
- **stderr**: error diagnostics; the validator's own findings when the pack does not validate.

---

## `tools/registry/generate.py`

Generates the fixture registry (`registry-v1.json`) for one protocol pack per CF-02. Reads pack contents, validates against schema, and writes or prints the registry.

### Synopsis

```bash
python3 tools/registry/generate.py [--allow-empty] [--protocol N]
    [--output PATH | --stdout] pack
```

### Options

- `-h`, `--help`: show this help message and exit
- `--allow-empty`: allow generating an empty baseline registry (requires `--protocol N`)
- `--protocol N`: protocol number for the pack (required with `--allow-empty`)
- `--output PATH`: write the registry here (default: PACK/registry-v1.json)
- `--stdout`: print the registry instead of writing a file

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: registry generated and successfully validated against `schemas/registry-v1.schema.json`. |
| `1` | Pack error: pack path is not a directory, contains invalid fixtures, violates extraction limits, empty pack without `--allow-empty`, or `--allow-empty` without a valid `--protocol`. |
| `2` | Command-line syntax error: missing `pack` argument, unknown options, or mutually exclusive options (`--output` and `--stdout` together). |

### Output Streams

- **stdout**: Serialized registry JSON document when `--stdout` is specified; help text when `--help` is invoked.
- **stderr**: Error messages and validation diagnostics.

---

## `tools/registry/diff.py`

Compares two fixture registries (`registry-v1.json`) and reports which fixtures were added, removed or changed, so that the release notes of a new pack release can be written from the registry data instead of by hand. Reads the two registry files only; never executes anything and never reads a fixture.

### Synopsis

```bash
python3 tools/registry/diff.py [--format text|json|markdown] [--allow-protocol-mismatch] OLD NEW
```

### Options

- `-h`, `--help`: show this help message and exit
- `--format text|json|markdown`: output format (default: `text`)
- `--allow-protocol-mismatch`: compare registries of different protocols instead of refusing

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: the registries were compared. There may or may not be differences; a difference is not an error. |
| `2` | Unusable input: a missing, unreadable or non-JSON file, a registry that does not conform to `schemas/registry-v1.schema.json`, a duplicate fixture id, an empty fixtures list, a protocol mismatch without `--allow-protocol-mismatch`, or a command-line syntax error. |

### Output Streams

- **stdout**: The report in the requested format; help text when `--help` is invoked.
- **stderr**: Error messages.

---

## `tools/inventory/compare.py`

Compares the fixture inventory that `stellar-canary fixtures --format json` prints with a pack's `registry-v1.json`, and asserts that the engine's loader discovered exactly the fixtures the registry lists, each with the same `surface` and `category`. Reads the two JSON documents only; it never opens a fixture, scans a directory or executes anything. It is not part of `make check` because it needs an inventory captured from the engine.

### Synopsis

```bash
python3 tools/inventory/compare.py INVENTORY REGISTRY [--format text|json]
```

`INVENTORY` is the JSON document the engine printed, or `-` to read it from standard input; `REGISTRY` is a `registry-v1.json`.

### Options

- `-h`, `--help`: show this help message and exit
- `--format text|json`: output format (default: `text`)

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: the inventories match. The same fixture ids are present with the same surfaces and categories. |
| `1` | The inventories differ: a fixture is in the registry but the engine did not discover it, a fixture was discovered but the registry does not list it, or a fixture's surface or category differs. The missing, extra and mismatched entries are printed. |
| `2` | Unusable input: a missing or unreadable file, a document that is not valid UTF-8 or valid JSON, an unknown `inventoryVersion`/`fixtureFormat`/`registryVersion`, `directoryFound: false`, a `counts.total` that disagrees with the fixture list, a duplicate fixture id, a registry that does not conform to `schemas/registry-v1.schema.json`, an inventory and a registry for different protocols, or a command-line syntax error. |

### Output Streams

- **stdout**: The report in the requested format; help text when `--help` is invoked.
- **stderr**: Error messages.

---

## `tools/release/manifest.py`

Generates the CF-06 release manifest (`.manifest.json`) for a built fixture-pack archive.

### Synopsis

```bash
python3 tools/release/manifest.py --revision REVISION [--engine VERSION] [--runs DIR] [--output PATH] [--sha256-file PATH] archive
```

### Options

- `-h`, `--help`: show this help message and exit
- `--revision REVISION`: full 40-character git commit hash of the pack source
- `--engine VERSION`: an exact engine version to list as a compatible engine, recorded as unverified unless a run record says that exact engine version ran against this exact pack; may be given more than once
- `--runs DIR`: directory of pack-by-engine run records (issue #367); an engine is marked `verified` only when a record there names that exact engine version, this exact pack digest and a passed run. Without this option every engine stays unverified
- `--output PATH`: write the manifest here (default: next to the archive, .manifest.json)
- `--sha256-file PATH`: also write the sha256sum-format checksum line here

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: manifest generated and validated against `schemas/manifest-v1.schema.json`. |
| `1` | Manifest error: archive does not exist, revision is not a 40-character commit hash, invalid archive content, cannot write output file, or a run record in `--runs` is unreadable, malformed, describes another pack, or is dated in the future. |
| `2` | Command-line syntax error: missing required arguments (`archive` or `--revision`), or unrecognized options. |

### Output Streams

- **stdout**: Help text when `--help` is invoked; the path of the written manifest; one line per engine marked `verified`, naming the instant of the recorded run.
- **stderr**: Usage and error diagnostics on failure.

See [`docs/run-records.md`](run-records.md) for the run-record format and the rule the `verified` flag follows.

---

## `tools/badge/badge.py`

Generates or checks the dynamic fixture-count shield badge in `README.md`.

### Synopsis

```bash
python3 tools/badge/badge.py [-h] [--check]
```

### Options

- `-h`, `--help`: show this help message and exit without modifying `README.md`
- `--check`: verify that the badge count in `README.md` is current without modifying the file; exits non-zero if stale.

Any other argument is a command-line error: usage is printed to stderr and the tool exits 2 without touching `README.md` (issue #392).

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: badge updated or already current, or `--help` requested. |
| `1` | Under `--check`: badge in `README.md` is stale. Also returned if `README.md` cannot be read or markers are missing. |
| `2` | Command-line syntax error: unrecognized arguments (usage printed to stderr; `README.md` is not modified). |

### Output Streams

- **stdout**: Success and status messages (`OK: README.md fixtures badge ...`); help text on `--help`.
- **stderr**: Error message when the badge is stale or file read fails; usage on a command-line syntax error.

---

## `tools/validate/validate.py`

Structural validator for fixture packs and evidence records.

### Synopsis

```bash
python3 tools/validate/validate.py [--evidence PATH] [-q] [--format {text,json}] [root ...]
```

### Options

- `-h`, `--help`: show this help message and exit
- `--evidence PATH`: a verification record file, or a directory of *.json records (CF-04); may be given more than once. A record whose `checkedAt` is later than the current time is rejected, with a five-minute tolerance for clock skew between the verifier's machine and the validator's
- `-q`, `--quiet`: suppress warning output in the text format; errors and the final OK/FAILED summary are still printed (JSON output is unaffected)
- `--format {text,json}`: output format: 'text' (default) is the human-readable report; 'json' prints one structured JSON document on stdout and nothing on stderr

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | All fixtures valid; or `--help` requested. |
| `1` | One or more validation errors occurred, or a specified root directory does not exist. |
| `2` | Command-line syntax error: unrecognized arguments or invalid format option. |

### Output Streams

- **stdout**: In text format: warnings and summary line (`OK: ...` or `FAILED: ...`). In JSON format: single structured JSON document containing all errors and warnings. On `--help`: help text.
- **stderr**: In text format: error diagnostics. In JSON format: nothing is emitted to stderr. Syntax errors on argument parsing write usage to stderr.

---

## `tools/validate/schema_sync.py`

Verifies that `schemas/fixture-v1.schema.json` mirrors the constants in `tools/validate/validate.py`.

### Synopsis

```bash
python3 tools/validate/schema_sync.py [-h]
```

### Options

- `-h`, `--help`: show this help message and exit.

Without arguments the tool performs the sync check.

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: schema matches validator constants; or `--help` requested. |
| `1` | Schema drift: one or more discrepancies found between schema and validator. |
| `2` | Command-line syntax error: any argument other than `-h`/`--help` (usage printed to stderr). |

### Output Streams

- **stdout**: `OK: schemas/fixture-v1.schema.json matches tools/validate/validate.py` on success; help text on `--help`.
- **stderr**: Drift errors and summary on failure; usage on a command-line syntax error.

---

## `tools/evidence/capture_live.py`

Captures live read-only RPC evidence from the approved endpoint and writes one CF-04 verification record per RPC fixture of a pack. Only the read-only methods CF-04 section 8 names are called, no credentials are used, and a record is written only for a capture that actually happened. See [`docs/live-verification.md`](live-verification.md).

### Synopsis

```bash
python3 tools/evidence/capture_live.py PACK [--output-dir DIR] [--endpoint HOST]
    [--local-endpoint URL] [--capture-method METHOD] [--timeout SECONDS]
    [--verifier-version VERSION] [--dry-run]
```

### Options

- `-h`, `--help`: show this help message and exit
- `PACK`: the pack directory whose RPC fixtures are verified live
- `--output-dir DIR`: where to write the captures and the records (default: `PACK/evidence/live`)
- `--endpoint HOST`: the approved endpoint to call (default: the first approved endpoint)
- `--local-endpoint URL`: a loopback mock endpoint to call instead of an approved one, for the tests and for a dry run on a fork
- `--capture-method METHOD`: an extra read-only method to capture, on top of the ones the pack's fixtures need (repeatable)
- `--timeout SECONDS`: how long one call may take before it is a failure (default: 30)
- `--verifier-version VERSION`: the version to record for the verifier (default: the commit the script was read from)
- `--dry-run`: make the calls and print what would be written, but write nothing

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: every capture succeeded; the captures and the records were written (or printed, in a dry run). |
| `1` | Capture error: a call failed, timed out or answered with something that is not a JSON-RPC result; no record was written for it. The same code is used for a refused method, endpoint or local endpoint. |
| `2` | Command-line syntax error: missing the `PACK` argument, or an unknown option. |

### Output Streams

- **stdout**: the endpoint, the captures, the records and their outcomes; the documents that would be written in a dry run; help text when `--help` is invoked.
- **stderr**: the reason each failed capture failed, and the `FAILED:` summary.

---

## `tools/validate/validate_registry.py`

Cross-validates a protocol pack's fixtures against its committed `registry-v1.json`: every regular `*.toml` file on disk must be listed in the registry's `fixtures[]` array, every listed fixture and payload must exist as a regular file, and every recorded `sha256` must equal the hash of the bytes on disk (CF-02 section 6, rules 2 and 3; issue #273). The registry document itself is checked against `schemas/registry-v1.schema.json` first, so an unusable registry is input error, not a cross-validation result. Freshness (regenerating and comparing bytes) belongs to CI's `check-registry` step; this tool only compares what is committed against what is on disk. Reads files only; never executes anything.

### Synopsis

```bash
python3 tools/validate/validate_registry.py [PACK ...]
```

### Options

- `-h`, `--help`: show this help message and exit
- `PACK ...`: pack directories to check; when omitted, every `protocol-*` directory in the repository is checked

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Every checked pack matches its registry (including a pack with no fixtures and no registry). |
| `1` | Cross-validation problems: a fixture on disk is not listed in the registry, a listed fixture or payload is missing on disk, a sha256 differs, or a pack with fixtures has no `registry-v1.json`. |
| `2` | Unusable input: a pack path that is not a directory, a registry that cannot be read or is not a usable registry document (invalid JSON, schema violation, a path that escapes the pack), or a command-line error. |

### Output Streams

- **stdout**: one `OK:` line per pack that matches its registry; help text when `--help` is invoked.
- **stderr**: one `error:` line per problem, a final `FAILED: N problem(s)` summary, input errors, and usage on a command-line error.

---

## Observed Inconsistencies

The following behaviors are recorded as observations of current implementations, not normative decisions. Changing any of them is out of scope for documentation issue #351 and belongs in separate issues should maintainers choose to open them:

1. **`tools/badge/badge.py` argument handling**:
   `badge.py` does not use `argparse`. It checks only for the substring `"--check"` in `sys.argv`. Any other arguments, including `--help`, unknown flags, or nonexistent paths, are silently ignored and the script proceeds with exit code 0.
2. **`tools/validate/schema_sync.py --help`**:
   `schema_sync.py` does not parse `--help`. If any arguments are provided (`if argv:`), it immediately prints a one-line usage to stderr and exits with status 2.
3. **Nonexistent input path exit codes**:
   When passed a nonexistent path argument, the tools diverge in exit codes:
   - `tools/validate/validate.py`: exits `1` (treated as validation failure).
   - `tools/registry/generate.py`: exits `1` (treated as pack load failure).
   - `tools/pack/pack.py`: exits `2` (handled via argument error).
   - `tools/pack/verify_archive.py`: exits `2` (handled via archive error).
   - `tools/release/manifest.py`: exits `2` (handled via archive error).
   - `tools/validate/validate_registry.py`: exits `2` (handled as unusable input).
   - `tools/badge/badge.py`: exits `0` (argument ignored).
