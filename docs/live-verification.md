# Scheduled live verification

The hand-taken captures in
[`protocol-29/evidence/testnet/`](../protocol-29/evidence/testnet/) go stale.
This page describes the job that keeps the live evidence fresh: the
workflow, the script it runs, what a run produces, and what it does when the
endpoint misbehaves.

The job is the CF-04-E unit ("scheduled read-only verification job that
saves captures"). It is issue [#368](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/368).

## What it does

On the schedule, the job:

1. calls the approved read-only JSON-RPC methods on the approved endpoint --
   nothing else, and with no credentials;
2. saves each request and its answer as a *capture*, in the same envelope the
   hand-taken corpus uses (`capturedAt`, `endpointHost`, `request`,
   `response`);
3. writes one CF-04 *verification record* per RPC fixture of the pack, with
   `method: "live-read-only"`, the SHA-256 of the fixture file, `checkedAt`
   equal to the capture time of the capture the record points at,
   `observedProtocol` copied from the real `getNetwork` answer, and
   `evidenceRef` naming that capture;
4. checks the records with
   [`tools/validate/validate.py`](../tools/validate/validate.py) -- the same
   rules the CI uses -- and uploads the captures and the records as a build
   artifact.

The script is [`tools/evidence/capture_live.py`](../tools/evidence/capture_live.py);
the workflow is
[`.github/workflows/live-evidence.yml`](../.github/workflows/live-evidence.yml).

## The schedule

| | |
|---|---|
| Cron | `17 7 * * 1` -- weekly, Monday 07:17 UTC |
| Where | the `schedule:` block of `.github/workflows/live-evidence.yml` |
| Triggers | the schedule, and `workflow_dispatch` for a manual run |

The minute is off the hour on purpose: the other scheduled jobs in this
repository run at 05:17 and 06:00 UTC, and the top of the hour is when the
GitHub Actions scheduler is busiest. Weekly is well inside decision D-05's
30-day freshness window.

**The exact schedule is a maintainer decision** (issue #368 lists it as
still open). It is one line in the workflow, and nothing else depends on it.

## The endpoints and the methods

The approved endpoint is the public Testnet Soroban RPC endpoint:

| | |
|---|---|
| Host | `soroban-testnet.stellar.org` |
| URL | `https://soroban-testnet.stellar.org` |
| Network name in a record | `testnet` |

The list lives in the script, in `APPROVED_ENDPOINTS`. A host that is not on
it is refused: the tool never calls an endpoint that was not approved there.

The methods it may call are the three read-only ones CF-04 section 8 names,
and no others:

| Method | Why |
|---|---|
| `getNetwork` | the passphrase and the observed protocol of the endpoint |
| `getLatestLedger` | what `p28-rpc-latest-ledger` asserts against |
| `getVersionInfo` | the third capture of the hand-taken corpus |

A method that is not on that list is refused *before* a request is made, so a
write call (`submitTransaction` and friends) cannot be configured, by
accident or on purpose.

No credentials are used. The request carries a `User-Agent` -- the public
endpoint's edge refuses Python's default agent -- and nothing else: no
token, no cookie, no authorization header.

**The exact endpoints are a maintainer decision** (issue #368 lists them as
still open). They are one mapping in the script, and the workflow calls the
first entry.

## What a run writes

```
protocol-28/evidence/live/
├── captures/
│   ├── get-latest-ledger.json
│   ├── get-network.json
│   └── get-version-info.json
└── records/
    ├── p28-rpc-latest-ledger.live-read-only.json
    └── p28-rpc-network.live-read-only.json
```

The output directory is `--output-dir`; the default is
`PACK/evidence/live`, next to the corpus the hand-taken captures live in.
The location of the *records* follows the location issue #366 proposes for
the structural records; see [the issue
#366](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/366).

A capture is the closed envelope the corpus uses:

```json
{
  "capturedAt": "2026-10-22T01:22:21Z",
  "endpointHost": "soroban-testnet.stellar.org",
  "request": {"jsonrpc": "2.0", "id": 1, "method": "getNetwork"},
  "response": {"jsonrpc": "2.0", "id": 1, "result": {"passphrase": "..."}}
}
```

A record is a CF-04 verification record (`method: "live-read-only"`), and
passes `python3 tools/validate/validate.py protocol-28 --evidence
protocol-28/evidence/live/records`:

```json
{
  "verificationVersion": 1,
  "fixtureId": "p28-rpc-network",
  "fixtureSha256": "cd53626db9d7a130e678f90d7d32545c23c95895cc0eb3de71e44cd82fc9596d",
  "method": "live-read-only",
  "checkedAt": "2026-10-22T01:22:21Z",
  "verifier": {"name": "protocolcanary-fixtures-capture-live", "version": "ff61db2..."},
  "outcome": "mismatched",
  "network": {
    "name": "testnet",
    "passphrase": "Test SDF Network ; September 2015",
    "observedProtocol": 29
  },
  "endpointHost": "soroban-testnet.stellar.org",
  "evidenceRef": "protocol-28/evidence/live/captures/get-network.json"
}
```

`checkedAt` is the `capturedAt` of the capture the record points at, and
`observedProtocol` is the `protocolVersion` the endpoint actually reported --
copied, never assumed.

`outcome` is `matched` only when the fixture's own assertions hold against
the live answer **and** the endpoint reports the protocol the fixture
targets. The Protocol 28 RPC fixtures target protocol 28, and the public
Testnet endpoint has been on protocol 29 since 2026-10-09, so the records
this job writes today are `mismatched` -- which is the honest answer, and
the same one the fixtures' own header comments predict.

## Failure behaviour

A capture that did not happen leaves nothing behind:

| What went wrong | What the run does |
|---|---|
| the endpoint answers HTTP 4xx or 5xx | no capture, no record for that method, the run fails |
| the endpoint does not answer in time | no capture, no record for that method, the run fails |
| the answer is not JSON | no capture, no record for that method, the run fails |
| the answer is a JSON-RPC error | no capture, no record for that method, the run fails |
| the answer carries no `result` | no capture, no record for that method, the run fails |
| the `getNetwork` call failed | no record at all: the passphrase and the observed protocol are unknown, so nothing is written |

A capture that succeeded but does not satisfy the fixture is **not** a
failure of the job: the record is written with `outcome: "mismatched"` and
the reasons are printed. A mismatched record is evidence in its own right
(CF-04 section 4) -- it explains why a fixture is not trusted.

The workflow fails the job when the script exits non-zero, so a broken
endpoint is visible in the run list and not only in the artifact.

## Running it by hand

```bash
python3 tools/evidence/capture_live.py protocol-28 --capture-method getVersionInfo
```

The script writes into `protocol-28/evidence/live/` by default. Use
`--output-dir DIR` for another place, `--dry-run` to make the calls and
print what would be written without writing it, and `--help` for the full
list of options. The command-line contract is in
[`docs/tools.md`](tools.md).

## A dry run against the local mock

The mock endpoint in [`tests/mock_rpc.py`](../tests/mock_rpc.py) answers the
same three read-only methods on the loopback interface, so the tool can be
exercised without a network:

```bash
python3 tests/mock_rpc.py --port 8099 &
python3 tools/evidence/capture_live.py protocol-28 \
    --local-endpoint http://127.0.0.1:8099 --output-dir /tmp/live-evidence
```

`--local-endpoint` is refused unless the address is a loopback one, so the
escape hatch can never be pointed at a remote host. The mock can also
misbehave on purpose (`--fail-method`, `--hang-method`,
`--malformed-method`, `--rpc-error-method`, `--no-result-method`,
`--wrong-id-method`), which is how the tests cover the failure paths.

## The decisions a maintainer still has to make

Issue #368 lists four of them. This page and the two files above implement
the mechanism; each decision is in one place:

| Decision | Where it is now | What changing it means |
|---|---|---|
| the schedule | the `cron:` line in the workflow | one line |
| the endpoints | `APPROVED_ENDPOINTS` in the script | one mapping, plus the workflow's `--endpoint` |
| how the results are stored | the upload step in the workflow | an artifact needs no write permission; a pull request or a bot commit needs `pull-requests: write` or `contents: write`, and is a security decision |
| where the records live | the `--output-dir` default in the script | one constant |

## What the job never does

- it never makes a write call and never sends a transaction;
- it never uses a credential;
- it never records a live result that was not actually captured;
- it never derives a timestamp from anything but the moment of the call;
- it never marks a fixture verified from a structural check -- the record
  says what the live endpoint answered, and nothing else;
- it never writes to the repository: the workflow has `permissions: contents:
  read` and uploads the results as an artifact.
