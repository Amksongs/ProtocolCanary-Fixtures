# Pack-by-engine run records

CF-06 section 3 says `compatibleEngines[].verified` in the release manifest is
`true` only when that exact engine version and that exact pack were run
together and the run is recorded. A manifest must never claim a range, and
never claims a combination that was not run.

This page documents the record format, the rule the manifest tool follows, and
what the tool refuses to do.

> **Status.** The record *format* and the manifest *rule* are implemented here
> (`schemas/run-record-v1.schema.json`, `tools/release/run_records.py`,
> `tools/release/manifest.py --runs`). Where records live in the repository,
> and whether runs are recorded as part of a release, are maintainer decisions
> that this change does not make: the tool takes the record directory as an
> argument, so the location is not baked in. No record is committed here, and
> no engine has been run against a pack as part of this change.

## The record

A run record is a small JSON object, one file per run:

```json
{
  "runRecordVersion": 1,
  "engineVersion": "0.2.0",
  "packDigest": "sha256:<64 lowercase hex characters>",
  "checkedAt": "2026-10-22T01:00:00Z",
  "verifier": { "name": "protocol-canary-ci", "version": "0.2.0" },
  "outcome": "passed",
  "evidenceRef": null
}
```

| Field | Rule |
|---|---|
| `runRecordVersion` | Exactly `1`. |
| `engineVersion` | An exact `MAJOR.MINOR.PATCH`. A range (`0.2.x`) is refused: a range is never a verified combination. |
| `packDigest` | The CF-02 pack digest of the pack that was run, `sha256:` followed by 64 lowercase hex characters. It is the digest of the pack *files*, so a record cannot be about a different pack that happens to carry the same version number. |
| `checkedAt` | The instant the run happened, RFC 3339 UTC with a `Z`. A record dated more than five minutes in the future is refused: a run that has not happened yet cannot be recorded. |
| `verifier` | `name` and `version` of whatever performed the run. |
| `outcome` | `passed` or `failed`. Only `passed` verifies an engine. |
| `evidenceRef` | Optional relative path to a saved artifact of the run, or `null`. A path that escapes the repository is refused. |

The schema is [`schemas/run-record-v1.schema.json`](../schemas/run-record-v1.schema.json);
the reader and its rules are in
[`tools/release/run_records.py`](../tools/release/run_records.py).

## The manifest rule

`tools/release/manifest.py` reads records from the directory given with
`--runs` and sets the flag like this:

1. No `--runs`, or an empty directory: every engine stays `verified: false`,
   exactly as before. The manifest is byte-for-byte the one the tool wrote
   before run records existed.
2. A record names **that exact engine version**, **that exact pack digest**
   and a run that `passed`: the engine is `verified: true`.
3. A record names a different engine version: it says nothing about the
   engine that was asked for. The engine stays `verified: false`.
4. A record names the same engine but **another pack digest**: this is an
   inconsistency the caller has to resolve, not something to guess about. The
   tool refuses to write a manifest and says which pack the record describes.
   Writing `verified: false` there would hide the fact that the record
   offered for this engine talks about a different pack.
5. A record is unreadable, malformed, dated in the future, or names a range:
   the tool fails with a clear message and writes nothing. A broken record
   is never read as "no record", because that would silently downgrade a
   verified engine to unverified.

```bash
python3 tools/release/manifest.py \
    --revision "$(git rev-parse HEAD)" \
    --engine 0.2.0 \
    --runs path/to/run-records \
    protocolcanary-fixtures-1.0.0.tar.gz
```

## What the tool never does

- It never writes a record. A record is written by whoever actually ran the
  pair; the manifest tool only reads.
- It never sets `verified: true` because a structural test passed, because
  the engine version is listed, or from a range.
- It never marks an engine verified from a record for a different pack.

## Related

- CF-06 section 3: the release manifest and the `verified` flag
  ([contract](https://github.com/StellarCanary/Protocol-Canary/blob/main/docs/contracts/cf-06-fixture-releases.md)).
- [`docs/tools.md`](tools.md): the command-line contract of
  `tools/release/manifest.py`.
- Issue #367, which tracks this work.
