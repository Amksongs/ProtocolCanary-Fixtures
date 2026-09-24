# Protocol 28

Implemented in Stellar Core 28.0.0, Stellar RPC 28.0.0 (whose integration
environment uses Soroban host 28.0.1), and the official `stellar-xdr`
28.0.0 crate. Includes, among other changes, three CAPs this pack targets:

```text
Protocol 28
    |
    ├── CAP-0083  (validators can vote to drop a transaction set)
    ├── CAP-0085  (externally managed contract executables / fleet upgrades)
    └── CAP-0086  (sparse-map host functions for storage migration)
```

## CAP-0083: STELLAR_VALUE_EMPTY_TX_SET

**What changed.** [CAP-0083](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0083.md)
gives validators a way to vote to drop a transaction set from the ledger
being closed, by adding a new `StellarValueType` case,
`STELLAR_VALUE_EMPTY_TX_SET`, to the `StellarValue` union's `ext`. A
`StellarValue` using this case carries the zero hash in its top-level
`txSetHash`, with the real hash of the dropped transaction set moved into
the nested `proposedValue.txSetHash`.

**What this pack tests.**

- `xdr/cap-0083/p28-xdr-cap83-empty-tx-set.toml`: a real, well-formed
  `StellarValue` using this ext case round-trips byte-for-byte through the
  project's configured `stellar-xdr` dependency.
- `xdr/cap-0083/p28-xdr-cap83-empty-tx-set-malformed.toml`: a truncated
  encoding of the same shape — the nested `proposedValue.txSetHash` cut
  short after 12 of its 32 bytes, with the rest of the `proposedValue` arm
  (including the `lcValueSignature`) missing entirely — is correctly
  rejected, not silently accepted.

**Surface.** XDR only. This is validator-internal consensus behavior, not
something a Soroban transaction or RPC call can meaningfully reproduce —
see the top-level project's rule against inventing a user-level scenario
to stand in for protocol-level behavior.

**What Canary does not test here.** Anything about *when* or *why* a real
validator network chooses to emit this value — only that the wire
representation, once it exists, decodes/encodes correctly.

**Source.** [CAP-0083](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0083.md).

## CAP-0085: externally managed contract executables

**What changed.** [CAP-0085](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0085.md)
lets many contract instances ("a fleet") share and atomically upgrade a
single Wasm implementation (the "beacon proxy" pattern), by adding a new
`ContractExecutableType` case, `CONTRACT_EXECUTABLE_EXTERNAL_REF`, to the
`ContractExecutable` union. That case carries a `ContractExecutableExternalRef`
struct naming an owner contract `SCAddress` and a string `tag` identifying
which persistent storage entry on that owner (keyed by an
`ExecutableTagObject`) holds the Wasm hash to execute.

**What this pack tests.**

- `xdr/cap-0085/p28-xdr-cap85-external-ref-roundtrip.toml`: a real,
  well-formed `ContractExecutable::ExternalRef` value round-trips
  byte-for-byte.
- `xdr/cap-0085/p28-xdr-cap85-external-ref-malformed.toml`: a truncated
  encoding of the same shape is correctly rejected, not silently accepted.

**Surface.** XDR only, and only as of this pack: testing this required
adding `ContractExecutable` support to Protocol-Canary's `canary-xdr`
crate, which previously supported only `StellarValue` (see that
repository's changelog). Both fixtures were verified directly against the
official `stellar-xdr` 28.0.0 crate before being committed.

**What Canary does not test here — and why.** These fixtures prove the
*wire representation* round-trips. They do not exercise a real, deployed
externally-managed-executable contract fleet end-to-end (deploy an owner
contract, write an `ExecutableTagObject` entry, deploy an instance whose
executable references it, invoke a function through that reference, and
confirm the resolved Wasm actually runs). Building that verifiably, rather
than guessing at it, requires deploying real Protocol 28 contracts using a
brand-new executable type — which needs either upstream `stellar` CLI
support for constructing an external-ref deployment (not yet available: the
CLI installed while authoring this pack was 27.1.0) or hand-crafting the
raw `InvokeHostFunction`/ledger-entry operations directly against the XDR,
which risks guessing behavior this project's rules forbid. This is tracked
as a known gap in `CHANGELOG.md`, not silently skipped.

**Source.** [CAP-0085](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0085.md).

## CAP-0086: sparse-map host functions

**What changed.** [CAP-0086](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0086.md)
adds two Soroban host environment functions —
`sparse_map_new_from_linear_memory` and `sparse_map_unpack_to_linear_memory`
— to support migrating map-based Soroban user-defined types without the
strict all-keys-present/no-extra-keys validation the existing map host
functions enforce. Unlike CAP-0083/CAP-0085, this CAP adds no new
top-level XDR type: it is host-environment behavior, only observable by
invoking a deployed contract that actually calls these functions.

**What this pack tests.** Nothing, yet. This is a deliberate, documented
gap, not an oversight.

**Why there is no fixture.** Testing this for real requires a deployed
Soroban contract whose exported function calls
`sparse_map_new_from_linear_memory`/`sparse_map_unpack_to_linear_memory`
and a `soroban` fixture that invokes it and checks
`simulation-success`/`simulation-error`. As of this pack's release, the
latest published `soroban-sdk` (27.0.6, per docs.rs) does not expose these
host functions at any stable, documented API surface. Building a contract
that calls them anyway would mean hand-crafting host-function-import ABI
details this project could not independently verify against an
authoritative source — exactly the kind of guess the top-level
no-fabrication rule exists to prevent (see `CONTRIBUTING.md`). This gap
closes once either `soroban-sdk` exposes these functions, or someone can
point to a verified, deployed contract using them.

**Source.** [CAP-0086](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0086.md).

## Protocol 28 RPC identity

**What this pack tests.** `rpc/p28-rpc-network.toml` calls the real
Stellar RPC `getNetwork` method and asserts the configured endpoint
reports `protocolVersion = 28` with a string `passphrase` field present.
Verified live against `https://soroban-testnet.stellar.org` on
2026-09-02 (the exact observed response is recorded in the fixture's
header comment).

**Surface.** RPC.

**What Canary does not test here.** Anything about a specific downstream
application's own RPC usage beyond this one endpoint-identity check, and
anything about mainnet — this fixture was verified against testnet only.

## Soroban simulation smoke test

**What this pack tests.** `soroban/p28-soroban-native-asset-name.toml`
builds and simulates a real, unsigned `InvokeHostFunction` transaction
calling the standard SEP-41 `name()` function on the network's reserved
native-asset Stellar Asset Contract — proving the full construction →
`simulateTransaction` → result pipeline works against real Protocol 28
infrastructure. Verified live against `https://soroban-testnet.stellar.org`
on 2026-09-02.

**Surface.** Soroban.

**What Canary does not test here.** CAP-0085/CAP-0086 host-function
semantics specifically (see above) — this fixture is a general Protocol 28
Soroban-pipeline smoke test, not a CAP-specific one.

## What this pack does not check, generally

- **Anything about a specific downstream application** beyond whether the
  fixtures above pass against that application's configured dependencies
  and RPC endpoint.
- **Mainnet.** Every live-network fixture in this pack was verified
  against testnet only.
- **No fixture in this pack asks `Protocol-Canary` to submit a real
  transaction.** Every check above is decode/encode, a read-only RPC call,
  or simulation.

## Consuming this pack

For a concise index of the fixtures in this pack, see [`protocol-28/README.md`](../protocol-28/README.md).

```bash
stellar-canary check --fixtures-dir <checkout-of-this-repo>/protocol-28 --json
# or, scanning every protocol pack in the repository at once:
stellar-canary check --fixtures-dir <checkout-of-this-repo> --protocol 28 --json
```

Both were run and passed 5/5 against a local `Protocol-Canary` build on
2026-09-02, confirming this pack is consumable exactly as documented in
`Protocol-Canary`'s `docs/fixture-contract.md`.

## Adding more Protocol 28 fixtures

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md#adding-a-fixture). Every new
fixture must cite a real upstream source in its `source_reference` field
and explain, in its own header comment, how its expected values were
derived or observed — the same way every fixture in this pack does.
