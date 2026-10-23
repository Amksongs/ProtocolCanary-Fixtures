# Contracts

This document describes the public contract surfaces of this repository:
the formats, schemas, and reports that other tools may rely on.

## Validator JSON report

**Schema:** `schemas/validator-report-v1.schema.json`
**Version field:** `version` (integer, currently always `1`)
**Command:** `python3 tools/validate/validate.py --format json [root ...]`

The validator can emit a structured JSON report instead of human-readable
text. The report is a single JSON object written to stdout. Consumers
should validate received reports against the published schema before
relying on any field.

### Report shape

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | Yes | Schema version. Currently always `1`. Bump when the shape changes in a non-backwards-compatible way. |
| `status` | string | Yes | `"ok"` if there are no errors, `"failed"` otherwise. |
| `roots` | array | Yes | The root directories that were validated. |
| `total_fixture_files` | integer | Yes | Total number of `.toml` fixture files found across all roots. |
| `errors` | array | Yes | Validation errors. Empty when `status` is `"ok"`. Each entry has `path` (string) and `message` (string). |
| `warnings` | array | Yes | Validation warnings. May be present even when `status` is `"ok"`. Each entry is a string. |

The schema allows additional properties on every object, so a future
version of the validator can add fields without breaking consumers that
ignore unknown fields.

### Roots entry

Each entry in the `roots` array has:

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Path to the root directory that was validated. |
| `valid` | boolean | Whether the path was a directory that could be scanned. |
| `fixture_count` | integer | Number of `.toml` files found under this root. |

### Error entry

Each entry in the `errors` array has:

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Path to the file or directory that produced the error. |
| `message` | string | Human-readable error message. |

### Versioning

The `version` field is the public contract version. Consumers should check
it and reject reports with an unknown version. The schema file is named with
the version (`validator-report-v1.schema.json`) so that future versions can
coexist.

When the report shape changes in a breaking way:
1. Bump the `version` field in `build_json_report`.
2. Create a new schema file (e.g. `validator-report-v2.schema.json`).
3. Document the change in `CHANGELOG.md`.

### Example

```bash
$ python3 tools/validate/validate.py --format json protocol-28
{
  "version": 1,
  "status": "ok",
  "roots": [
    {
      "path": "protocol-28",
      "valid": true,
      "fixture_count": 6
    }
  ],
  "total_fixture_files": 6,
  "errors": [],
  "warnings": []
}
```

## Fixture schema

**Schema:** `schemas/fixture-v1.schema.json`

Describes the TOML fixture format that `tools/validate/validate.py` checks.
See the fixture contract documentation in the `StellarCanary/Protocol-Canary`
repository's `docs/fixture-contract.md` for the authoritative definition.
