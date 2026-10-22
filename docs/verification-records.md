# Verification records

This document describes the verification records in this repository: where they
live, what they say, what they deliberately do not say, and how they are
produced (issue #366, CF-04 section 3).

A verification record is a small, dated, attributed statement:

> this fixture file, with these exact bytes, was checked by this verifier, at
> this instant, and the outcome was this.

It is not prose, and it is not a claim about Stellar behavior unless the record
says so.

---

## 1. Where the records live

```
protocol-28/evidence/records/<fixture-id>.json
```

One file per fixture, named after the fixture's id.

**This location is a proposal, not a settled decision.** Issue #366 records
that the location of the records and the way a date-only history is
represented are still maintainer decisions, and that a backfill of past
checks needs a decision of its own. This repository therefore:

* keeps the records of one pack inside that pack, next to the fixtures they
  describe (`protocol-28/evidence/records/`), which is where CF-04 section 3
  allows them ("in the registry (CF-02) or beside the fixture");
* keeps the captures of a network in their own directory
  (`protocol-29/evidence/testnet/`), so a capture and a record are never
  confused for one another;
* makes the location a single constant in
  `tools/evidence/record_structural.py` (`RECORDS_DIRNAME`), so a decision
  that says otherwise is a one-line change.

## 2. What the Protocol 28 records say

Thirty-one records, one for each fixture of the `protocol-28` pack. Every
one of them is a **structural** record:

```json
{
  "verificationVersion": 1,
  "fixtureId": "p28-rpc-network",
  "fixtureSha256": "cd53626db9d7a130e678f90d7d32545c23c95895cc0eb3de71e44cd82fc9596d",
  "method": "structural",
  "checkedAt": "2026-10-22T06:44:39Z",
  "verifier": {
    "name": "protocolcanary-fixtures-validate",
    "version": "eb90c66ca49451d6d672397bb0dd6e64de580db1"
  },
  "outcome": "matched",
  "evidenceRef": null
}
```

* `method: "structural"` — the check that was performed is the one CF-04
  section 2 calls structural: the fixture file conforms to the format and the
  validator accepts it.
* `fixtureSha256` — the SHA-256 of the fixture file as it was when the check
  ran. It is the hash of the bytes in the repository, so the record goes stale
  the moment the file changes (see section 5).
* `checkedAt` — the instant the check ran, in RFC 3339 UTC. It is the time
  of the run, not a date copied from anywhere.
* `verifier.version` — the commit the validator was read from, so the exact
  code that did the check can be looked at.
* `evidenceRef: null` — a structural check has no capture behind it. Saying
  so explicitly is better than leaving the reader to guess.

The check that produced them is the one the CI runs, and it was actually run:

```console
$ python3 tools/evidence/record_structural.py protocol-28
OK: wrote 31 record(s) at 2026-10-22T06:44:39Z
  protocol-28/evidence/records/p28-rpc-latest-ledger.json
  protocol-28/evidence/records/p28-rpc-network.json
  ...
```

The tool refuses to write anything when a fixture does not validate, so a
record always says that the check passed.

## 3. What the records do not say

They are honest about their own reach:

* **No live claim.** No record here has `method: "live-read-only"` or
  `"live-simulation"`. The Protocol 28 header comments describe live
  observations made in the past; those observations cannot be re-run (the
  public networks now report protocol 29) and no capture behind them is
  stored in this repository, so **no record was derived from them**. A live
  record without a saved capture is not evidence, and this repository does
  not pretend otherwise.
* **No invented instant.** A header comment such as `Verified live on
  2026-09-02` names a day, not an instant. No record carries that day, and
  no record carries midnight or noon on that day either: an instant that was
  guessed is worse than no instant at all.
* **No "verified" claim.** A structural record says the file is well formed.
  It says nothing about what a node would answer, and it is not a claim that
  the fixture is verified against a network. The freshness states of CF-04
  section 4 are derived elsewhere and are never stored in a record.
* **No claim about the engine.** The check was performed by this repository's
  validator, and the record names that validator. It does not name an engine
  version, because no engine ran.

## 4. How the records are checked

The validator accepts them, and the CI checks that it does:

```console
$ python3 tools/validate/validate.py --evidence protocol-28/evidence/records
OK: 31 fixture file(s) valid across 3 root(s); 31 evidence record(s) valid
```

`tests/test_verification_records.py` pins the rules above down: every fixture
has exactly one record, every record's hash is the hash of the file that is
there now, no record carries a network, an endpoint or a capture, no record
carries a date instead of an instant, and the validator rejects the records it
has to reject (a date-only `checkedAt`, a `fixtureSha256` that does not match
the fixture, a live record without a capture, a record for a fixture that does
not exist).

## 5. Regenerating the records

```console
$ make records                      # the protocol-28 pack
$ python3 tools/evidence/record_structural.py protocol-28
```

Run it after a fixture changes. The record holds the hash of the file, so a
changed fixture makes the old record describe an earlier version of the file:
the validator then reports it, which is the point. The record is not
refreshed silently; it is replaced by a new one that says when the check ran.

> **The hashes assume an LF checkout.** The records hash the fixture files as
> they are on disk. A checkout that rewrites LF as CRLF (git's
> `core.autocrlf`, which is on by default on the Windows runners) produces
> different bytes and therefore different hashes. `.gitattributes` pins the
> pack files to `eol=lf`; the measurement behind that is issue #365.

## 6. What is still a maintainer decision

Issue #366 lists three decisions that have not been recorded yet, and this
repository does not take them silently:

1. **where the records live** — this document proposes
   `protocol-28/evidence/records/` and makes the location one constant;
2. **how a date-only history is represented** — this repository represents it
   by *not* representing it: the dates stay in the header comments as prose,
   and no record is derived from them;
3. **whether a backfill of past checks is acceptable at all** — this
   repository backfills nothing. Every record here was produced by a check
   that ran, and the records exist only for the check that can be run again.
