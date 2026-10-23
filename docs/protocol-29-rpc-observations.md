# Protocol 29 RPC observations

This is a dated log of what two public Stellar RPC endpoints returned. It is
**not** a verification record, it does not verify any fixture, and no fixture in
this repository depends on it. It exists so that the next person who adds
Protocol 29 coverage starts from what was actually seen rather than from
assumptions. Protocol 29 coverage policy is the CF-04 contract,
`docs/contracts/cf-04-verification-evidence.md` in `Protocol-Canary` (decision
D-09, Option C). It is named rather than linked here because it is added to
`Protocol-Canary` by a pull request that may not have merged when this is read;
link it once it has.

## What upstream says

[Software versions](https://developers.stellar.org/docs/networks/software-versions)
(read 2026-10-09): Protocol 29 is "a security-focused release that fixes
vulnerabilities in Stellar Core. It introduces no new CAPs." Testnet
2026-09-29, Mainnet 2026-10-01. There is no CAP to cite for a Protocol 29
fixture, and none is invented here.

## The capture

Taken on 2026-10-09 between 08:38 and 08:39 UTC, one request per method per
endpoint, with:

```bash
curl -s -X POST <endpoint> -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"<method>"}'
```

| Endpoint | Operator |
|---|---|
| `https://soroban-testnet.stellar.org` | the Testnet default used by `Protocol-Canary` |
| `https://mainnet.sorobanrpc.com` | a public Mainnet endpoint; its operator has not been verified by this project |

All ten requests returned HTTP 200 with a JSON-RPC `result`. Large XDR fields
are shown by length only; nothing was edited otherwise.

### `getNetwork`

| | Testnet | Mainnet |
|---|---|---|
| `passphrase` | `Test SDF Network ; September 2015` | `Public Global Stellar Network ; September 2015` |
| `protocolVersion` | `29` | `29` |
| `friendbotUrl` | `https://friendbot.stellar.org/` | absent |

### `getLatestLedger`

| | Testnet | Mainnet |
|---|---|---|
| `protocolVersion` | `29` | `29` |
| `sequence` | `5102304` | `64849866` |
| `id` | `9ba015c8543fb9a929a58065be2d19c1e3eb152e19df8e27340b8db33d01b4f4` | `1438bdf1928fe4677df00150854da12d4f8084f20615e7324f3277e8862ac407` |
| `closeTime` | `"1791535107"` | `"1791535112"` |
| `headerXdr` length | 572 characters | 572 characters |
| `metadataXdr` length | 210,432 characters | 1,284,944 characters |

### `getVersionInfo`

Identical on both endpoints:

| Field | Value |
|---|---|
| `version` | `29.0.0-b2b701685c79aee17fe4eb22dbd08a5dfd11594d` |
| `commitHash` | `b2b701685c79aee17fe4eb22dbd08a5dfd11594d` |
| `buildTimestamp` | `2026-09-22T14:52:44` |
| `captiveCoreVersion` | `stellar-core 29.0.0 (4eb83337380a29ad0907f4e32196ce97b8dc7649)` |
| `protocolVersion` | `29` |

### `getHealth` and `getFeeStats`

Both answered with the documented shapes. `getHealth` reported `status`
`healthy` and `ledgerRetentionWindow` `120960` on both endpoints.
`getFeeStats` returned `sorobanInclusionFee`, `inclusionFee` and `latestLedger`;
each fee object had `max`, `min`, `mode`, `p10` to `p99`, `transactionCount`
(strings) and `ledgerCount` (a number). Fee values are not recorded here because
they change every ledger.

## What this shows

- The three methods a fixture could assert on for network identity
  (`getNetwork`, `getLatestLedger`, `getVersionInfo`) exist on both networks and
  agreed on protocol `29` at that moment.
- `getVersionInfo` reports the node software version (Stellar RPC and core
  `29.0.0`, built 2026-09-22), which is information `getNetwork` does not carry.
- A `getLatestLedger` response is large on Mainnet (about 1.3 million
  characters, almost all `metadataXdr`).

## What this does not show

- That any fixture is verified. A fixture needs an authoritative source and a
  verification record with the captured request and response saved as evidence.
- That either endpoint is canonical, or that the values will stay the same.
  One request, once.
- Anything about Protocol 29 behavior beyond the reported number and software
  version. No transaction was submitted, simulated or signed.
- Soroban host behavior. The upstream page lists host `29.0.0` for Protocol 29,
  but no Protocol 29 simulation was run.

## What has not been done, on purpose

No Protocol 29 fixture exists. Adding one needs, together: an authoritative
source, a saved read-only capture made for that fixture, and a verification
record with the fields in the CF-04 contract. `protocol-27/` stays empty for the
same reason.
