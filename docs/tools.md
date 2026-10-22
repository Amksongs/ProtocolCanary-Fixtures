# Tool Command-Line Contracts

This document records the exact command-line interface, options, exit codes, and output streams of the repository's maintenance, packaging, and validation tools.

CI jobs, release workflows, and contributor scripts rely on these contracts. Any changes to exit codes or stream destinations represent changes to these contracts.

---

## Table of Tools

1. [`tools/pack/pack.py`](#toolspackpackpy)
2. [`tools/pack/verify_archive.py`](#toolspackverify_archivepy)
3. [`tools/registry/generate.py`](#toolsregistrygeneratepy)
4. [`tools/registry/diff.py`](#toolsregistrydiffpy)
5. [`tools/release/manifest.py`](#toolsreleasemanifestpy)
6. [`tools/badge/badge.py`](#toolsbadgebadgepy)
7. [`tools/validate/validate.py`](#toolsvalidatevalidatepy)
8. [`tools/validate/schema_sync.py`](#toolsvalidateschema_syncpy)
9. [Observed Inconsistencies](#observed-inconsistencies)

---

## `tools/pack/pack.py`

Builds the deterministic release archive for one protocol pack (CF-06). Reads pack fixtures and generated registry; verifies limits and produces a reproducible `.tar.gz`.

### Synopsis

```bash
python3 tools/pack/pack.py PACK --version VERSION [--output-dir DIR]
```

### Options

- `-h`, `--help`: show this help message and exit
- `--version VERSION`: release version, MAJOR.MINOR.PATCH; names the archive
- `--output-dir DIR`: directory for the archive (default: dist)

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: deterministic archive created in output directory. |
| `1` | Pack error: pack path is not a directory, empty pack, invalid semver format, broken fixture, limit violation, or archive write failure. |
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

## `tools/registry/generate.py`

Generates the fixture registry (`registry-v1.json`) for one protocol pack per CF-02. Reads pack contents, validates against schema, and writes or prints the registry.

### Synopsis

```bash
python3 tools/registry/generate.py [--output PATH | --stdout] pack
```

### Options

- `-h`, `--help`: show this help message and exit
- `--output PATH`: write the registry here (default: PACK/registry-v1.json)
- `--stdout`: print the registry instead of writing a file

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: registry generated and successfully validated against `schemas/registry-v1.schema.json`. |
| `1` | Pack error: pack path is not a directory, contains invalid fixtures, or violates extraction limits. |
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
python3 tools/badge/badge.py [--check]
```

### Options

- `--check`: verify that the badge count in `README.md` is current without modifying the file; exits non-zero if stale.

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: badge updated or already current. When called without `--check`, exits 0 even if arbitrary arguments or nonexistent paths are passed. |
| `1` | Under `--check`: badge in `README.md` is stale. Also returned if `README.md` cannot be read or markers are missing. |

### Output Streams

- **stdout**: Success and status messages (`OK: README.md fixtures badge ...`).
- **stderr**: Error message when the badge is stale or file read fails.

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
python3 tools/validate/schema_sync.py
```

### Options

- None. The tool takes no arguments.

### Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success: schema matches validator constants. |
| `1` | Schema drift: one or more discrepancies found between schema and validator. |
| `2` | Any argument provided (including `--help` or arbitrary paths). |

### Output Streams

- **stdout**: `OK: schemas/fixture-v1.schema.json matches tools/validate/validate.py` on success.
- **stderr**: Drift errors and summary on failure; usage message if any argument is supplied.

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
   - `tools/badge/badge.py`: exits `0` (argument ignored).
