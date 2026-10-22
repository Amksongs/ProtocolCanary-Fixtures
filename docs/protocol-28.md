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

## Fixture format version

Every fixture in this pack is written against **fixture format
`schema_version` 1**, the format described by
[`schemas/fixture-v1.schema.json`](../schemas/fixture-v1.schema.json) (titled
"Protocol Canary fixture (schema_version 1)"). The `schema_version` is a
property of the pack as a whole, not a per-fixture TOML field — no fixture
in this repository sets a `schema_version` key, and the schema neither
requires nor defines one. Recording it here means that if the fixture format
is ever revised to `schema_version 2`, this pack's target version is on the
record and can be migrated deliberately rather than inferred. Future packs
should likewise state the version they target; see
[`../CONTRIBUTING.md`](../CONTRIBUTING.md#fixture-schema).

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

## StellarValue ext: the BASIC and SIGNED arms

Added 2026-10-19. CAP-0083 above covers only the arm CAP-0083 itself
added. The `StellarValue.ext` union has three arms in `Stellar-ledger.x`
at [`stellar/stellar-xdr` v28.0](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-ledger.x)
— `enum StellarValueType` (lines 14-19) with `STELLAR_VALUE_BASIC = 0`,
`STELLAR_VALUE_SIGNED = 1` and `STELLAR_VALUE_EMPTY_TX_SET = 2`; the
`ext` union (lines 41-56) carries no body for BASIC (line 43) and a
`LedgerCloseValueSignature` (lines 20-24) for SIGNED. The two
pre-CAP-0083 arms had no fixture, so a decoder that mishandled them
would pass this pack unnoticed.

**What this pack tests.** For each of the two arms, three fixtures under
[`protocol-28/xdr/stellar-value/`](../protocol-28/xdr/stellar-value/):
a roundtrip (decode + re-encode must reproduce the bytes), a
decode-success (a decoder that cannot decode the arm at all fails
here), and a decode-failure whose payload is a documented truncation of
the crate-produced value — for BASIC the first 40 of 48 bytes (the
`upgrades` vector and ext discriminant missing), for SIGNED the first
100 of 152 bytes (the 64-byte signature cut after 12 bytes).

**How the payloads were made.** Every `value_base64` is the output of a
program that builds the typed value with the official `stellar-xdr`
28.0.1 crate (features `base64` and `alloc` — the version pinned for
Protocol 28) and calls `to_xdr_base64(Limits::none())`; each fixture's
header records the one-line construction expression, the crate version,
the Rust version (`rustc 1.99.1 (58cf8f9c3 2026-10-13)`) and the
generation date (2026-10-19 UTC). The same crate round-trips both
values byte-for-byte and returns `Err("failed to fill whole buffer")`
for both truncations, which the headers also record. All bytes are
synthetic structural values — a filler hash, an arbitrary close time,
an empty upgrades vector, a filler node id and a filler 64-byte
signature that is a signature over nothing; no real or real-looking
key material is used, and nothing was observed on a network.

**Surface.** XDR only, like the CAP-0083 fixtures above — validator-
internal consensus values, not something a transaction or RPC call can
meaningfully reproduce.

**What Canary does not test here.** Anything about which validators
sign ledger-close values, when, or with what keys — only that the wire
representation of both arms decodes and encodes correctly.

**Source.** [`Stellar-ledger.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-ledger.x)
(`StellarValueType` lines 14-19, `LedgerCloseValueSignature` lines
20-24, `StellarValue` lines 26-57, `ext` union lines 41-56) and
[`Stellar-types.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-types.x)
(`PublicKey` union lines 53-57, `Signature` line 80, `NodeID` line 84)
at `stellar/stellar-xdr` tag `v28.0`, commit
`9c9c145953e80990d6ff1ae3a6a973a0ce6d0694`.

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
confirm the resolved Wasm actually runs). At authoring time, the installed
Rust `stellar` CLI was **27.1.0** and did not provide a supported way to
construct that deployment. A re-check on **2026-09-25 UTC** of the
[`stellar-cli` 28.0.0 release](https://github.com/stellar/stellar-cli/releases/tag/v28.0.0)
(published 2026-08-26) found that it adds Protocol 28 support and can
resolve, fetch, and invoke existing external references, but
`stellar contract deploy` still exposes only `--wasm` and `--wasm-hash` for
selecting the executable; it has no direct external-reference deployment
option. The v28.0.0
[CAP-0085 integration test](https://github.com/stellar/stellar-cli/blob/v28.0.0/cmd/crates/soroban-test/tests/it/integration/contract/external_ref.rs)
demonstrates the owner-side flow with commands equivalent to:

```text
stellar contract invoke --id <OWNER_ID> -- publish --tag fleet --wasm-hash <WASM_HASH>
stellar contract invoke --id <OWNER_ID> -- deploy_ref --tag fleet
```

(the test supplies the configured source account and network). This requires a
separately deployed owner contract and is not a general CLI construction path.
The open draft [`stellar-cli` PR #2659](https://github.com/stellar/stellar-cli/pull/2659)
proposes `--executable-owner` and `--executable-tag`; until that support is
released, adding a live fixture would require hand-crafting raw
`InvokeHostFunction`/ledger-entry operations directly against the XDR, which
risks guessing behavior this project's rules forbid. This gap is tracked by
[#8](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/8),
rather than silently skipped.

**Source.** [CAP-0085](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0085.md).

## ContractExecutable: the Wasm and StellarAsset arms

Added 2026-10-20. The CAP-0085 section above covers only the case
CAP-0085 added. The `ContractExecutable` union in `Stellar-contract.x`
at [`stellar/stellar-xdr` v28.0](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-contract.x)
has three cases — `enum ContractExecutableType` (lines 172-177) with
`CONTRACT_EXECUTABLE_WASM = 0`, `CONTRACT_EXECUTABLE_STELLAR_ASSET = 1`
and `CONTRACT_EXECUTABLE_EXTERNAL_REF = 2`; the `union ContractExecutable`
(lines 229-237) carries a `Hash wasm_hash` for WASM and nothing (`void`)
for STELLAR_ASSET. Both original arms predate Protocol 28: the same
two-case union is already present in
[`stellar/stellar-xdr` v20](https://github.com/stellar/stellar-xdr/blob/v20/Stellar-contract.x),
Protocol 20's XDR (checked 2026-10-20 UTC), the protocol
[CAP-0046](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0046.md)
Soroban introduced — CAP-0046's `CREATE_CONTRACT` carries a
`ContractExecutable`. Neither arm is a Protocol-28 CAP change, and until
this section's fixtures existed neither had one here, so a decoder that
mishandled them would pass this pack unnoticed.

**What this pack tests.** For each of the two arms, three fixtures under
[`protocol-28/xdr/contract-executable/`](../protocol-28/xdr/contract-executable/):
a roundtrip (decode + re-encode must reproduce the bytes), a
decode-success (a decoder that cannot decode the arm at all fails
here), and a decode-failure whose payload is a documented truncation of
the crate-produced value — for Wasm the first 24 of 36 bytes (the
32-byte `wasmHash` cut after 20 of its bytes), for StellarAsset the
first 3 of 4 bytes (the union discriminant incomplete). Neither
truncation is empty, and each fixture's base64 is literally the prefix
of the well-formed value it was cut from.

**How the payloads were made.** Every `value_base64` is the output of a
program that builds the typed value with the official `stellar-xdr`
28.0.1 crate (features `base64` and `alloc` — the version pinned for
Protocol 28) and calls `to_xdr_base64(Limits::none())`; each fixture's
header records the one-line construction expression
(`ContractExecutable::Wasm(Hash([0xab; 32]))` and
`ContractExecutable::StellarAsset`), the crate version, the Rust version
(`rustc 1.99.1 (58cf8f9c3 2026-10-13)`) and the generation date
(2026-10-20 UTC). The same crate round-trips both values byte-for-byte
and returns `Err("failed to fill whole buffer")` for both truncations,
which the headers also record. All bytes are synthetic structural
values — the 0xab-filled hash is not the hash of any real uploaded Wasm
and identifies no real contract, account or ledger entry, and the
StellarAsset value is a bare discriminant carrying no payload — and
nothing was observed on a network.

**Surface.** XDR only, like the fixtures above — a contract instance's
executable is ledger state a transaction or RPC call cannot meaningfully
reproduce; only the wire representation can be checked here.

**What Canary does not test here.** Anything about which Wasm a real
contract instance points at, or any asset-contract execution end-to-end —
only that the wire representation of both arms decodes and encodes
correctly.

**Source.** [`Stellar-contract.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-contract.x)
(`ContractExecutableType` lines 172-177, `ContractExecutable` union lines
229-237) at `stellar/stellar-xdr` tag `v28.0`, commit
`9c9c145953e80990d6ff1ae3a6a973a0ce6d0694`.

## TransactionEnvelope: every arm of the union

Added 2026-10-22. The `TransactionEnvelope` union in `Stellar-transaction.x`
at [`stellar/stellar-xdr` v28.0](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-transaction.x)
is the envelope every transaction reaches a network in, and it is the most
complex union the engine decodes — three arms, two of which nest a whole
envelope inside another. `enum EnvelopeType`
([`Stellar-ledger-entries.x` lines 656-669](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-ledger-entries.x))
gives the union's discriminant: `ENVELOPE_TYPE_TX_V0 = 0`, `ENVELOPE_TYPE_TX = 2`
and `ENVELOPE_TYPE_TX_FEE_BUMP = 5`; `union TransactionEnvelope`
(`Stellar-transaction.x` lines 1002-1010) carries a `TransactionV0Envelope`
(lines 924-930) for the first, a `TransactionV1Envelope` (lines 967-973) for
the second and a `FeeBumpTransactionEnvelope` (lines 993-999) for the third.
Until these fixtures existed the pack had no evidence for any arm, so a
decoder that mis-handled the bare `uint256` source account of the v0 arm, the
`MuxedAccount`/`Preconditions` pair of the v1 arm, or the nesting of the
fee-bump arm would pass this pack unnoticed.

**What this pack tests.** Eight fixtures under
[`protocol-28/xdr/transaction-envelope/`](../protocol-28/xdr/transaction-envelope/):
one roundtrip per arm (decode + re-encode must reproduce the bytes) and one
decode-failure per arm, whose payload is a documented mutation of the
crate-produced value:

| Fixture | Arm | Decode-failure mutation |
| --- | --- | --- |
| `p28-xdr-transaction-envelope-v0-roundtrip` | `ENVELOPE_TYPE_TX_V0` | — |
| `p28-xdr-transaction-envelope-v0-decode-failure` | `ENVELOPE_TYPE_TX_V0` | first 150 of 212 bytes — cut inside the 64-byte signature |
| `p28-xdr-transaction-envelope-v1-roundtrip` | `ENVELOPE_TYPE_TX` | — |
| `p28-xdr-transaction-envelope-v1-decode-failure` | `ENVELOPE_TYPE_TX` | the 4-byte discriminant changed from `ENVELOPE_TYPE_TX` (2) to 63, an undefined envelope type |
| `p28-xdr-transaction-envelope-soroban-invoke-roundtrip` | `ENVELOPE_TYPE_TX` with one `INVOKE_HOST_FUNCTION` operation | — |
| `p28-xdr-transaction-envelope-soroban-invoke-decode-failure` | `ENVELOPE_TYPE_TX` with one `INVOKE_HOST_FUNCTION` operation | first 100 of 244 bytes — cut inside the 32-byte contract id |
| `p28-xdr-transaction-envelope-fee-bump-roundtrip` | `ENVELOPE_TYPE_TX_FEE_BUMP` | — |
| `p28-xdr-transaction-envelope-fee-bump-decode-failure` | `ENVELOPE_TYPE_TX_FEE_BUMP` | first 130 of 328 bytes — cut inside the inner transaction's destination account |

**How the payloads were made.** Every `value_base64` is the output of a
program that builds the typed value with the official `stellar-xdr` 28.0.1
crate (features `base64` and `alloc` — the version pinned for Protocol 28) and
calls `to_xdr_base64(Limits::none())`; each fixture's header records the
construction expression, the crate version, the Rust version
(`rustc 1.99.1 (58cf8f9c3 2026-10-13)`) and the generation date
(2026-10-22 UTC). The same crate round-trips all four well-formed values
byte-for-byte, and its `from_xdr_base64` returns `Err("failed to fill whole
buffer")` for the three truncations and `Err("xdr value invalid")` for the
mutated discriminant — the headers record which of the two each fixture
provokes.

**Every byte is a synthetic structural value.** The source accounts, payment
destinations, contract id, signature hints and signatures are fixed bytes
repeated to fill a field (0x11, 0x22, 0x33 for the v0 envelope; 0x44, 0x55,
0x66 for the v1 one; 0x77, 0xab, 0x88 for the Soroban one; 0xcc, 0x99, 0xaa,
0xbb, 0xdd for the fee-bump one). None of them is a real account, contract or
network object, the signatures sign nothing, no secret key is used anywhere,
and nothing here was observed on a network or submitted to one. The fees,
sequence numbers, time bounds, amounts, resource limits and resource fee are
arbitrary fixed numbers; the Soroban footprint and authorization list are
empty, so the value invokes nothing.

**Surface.** XDR only, like the fixtures above — a transaction envelope is
wire representation, and what a fixture can check is that the bytes decode
and re-encode exactly, and that a malformed encoding is rejected.

**What Canary does not test here.** Anything about whether a real network
would accept the envelope: the signatures do not sign anything, no sequence
number is meaningful against a real account, and the Soroban value names a
contract that does not exist. Only that the wire representation of each arm
decodes, encodes and — when malformed — is refused.

**Source.** [`Stellar-transaction.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-transaction.x)
(`TransactionEnvelope` union lines 1002-1010, `TransactionV0` lines 902-922,
`TransactionV0Envelope` lines 924-930, `Transaction` lines 932-965,
`TransactionV1Envelope` lines 967-973, `FeeBumpTransaction` lines 975-991,
`FeeBumpTransactionEnvelope` lines 993-999, `Operation` lines 653-719,
`InvokeHostFunctionOp` lines 618-629, `HostFunction` union lines 521-531,
`InvokeContractArgs` lines 515-519, `SorobanTransactionData` lines 879-900,
`SorobanResources` lines 856-869, `LedgerFootprint` lines 849-854,
`Preconditions` union lines 839-847, `MuxedAccount` union lines 20-31,
`DecoratedSignature` lines 33-37, `PaymentOp` lines 92-97),
[`Stellar-ledger-entries.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-ledger-entries.x)
(`EnvelopeType` lines 656-669, `Asset` union lines 55-66),
[`Stellar-types.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-types.x)
(`CryptoKeyType` lines 29-38, `Signature` line 80, `SignatureHint` line 82)
and [`Stellar-contract.x`](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-contract.x)
(`SCAddress` union lines 206-222, `SCSymbol` line 12) at `stellar/stellar-xdr`
tag `v28.0`, commit `9c9c145953e80990d6ff1ae3a6a973a0ce6d0694`.

**Verified against the engine.** `stellar-canary 0.2.0`, built from
`Protocol-Canary` main at commit `bc1330660c36eb67a87747513c7d14ba04d39238`,
run as `stellar-canary check --fixtures-dir <repo>/protocol-28 --protocol 28
--offline --no-cache --json` from a project directory whose
`.stellar-canary.toml` enables `xdr = true`: all eight fixtures pass, the
four roundtrips as "TransactionEnvelope round-tripped byte-for-byte" and the
four decode-failures as "TransactionEnvelope was correctly rejected".

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

`rpc/p28-rpc-latest-ledger.toml` calls the other RPC method
`canary-rpc` supports, `getLatestLedger`, and asserts the same endpoint
identity from that response: `protocolVersion` equals 28, `sequence` is
present and numeric, and `id` (the ledger hash) is a string. It also
carries the pack's only `field-absent` assertion, checking that this
method's response does not report `friendbotUrl` — a `getNetwork` field.
Verified live against `https://soroban-testnet.stellar.org` on
2026-09-28 UTC with `stellar-canary 0.1.1`.

**Surface.** RPC.

**One caveat that shapes what an RPC fixture can assert.** `canary-rpc`
serializes each response into its own typed model (`NetworkInfo`,
`LatestLedger` in `crates/canary-rpc/src/models.rs`) *before* evaluating
assertions, so a fixture sees only the fields that model carries — not the
raw RPC response. `getLatestLedger` really also returns `closeTime`,
`headerXdr` and `metadataXdr`, none of which a fixture can observe. Both
fixtures above therefore assert only on modeled fields, and a `field-absent`
assertion is meaningful only for a field the *other* method would report.

**What Canary does not test here.** Anything about a specific downstream
application's own RPC usage beyond these two endpoint-identity checks, and
anything about mainnet — both fixtures were verified against testnet only.
Neither asserts a ledger `sequence`: it advances with every ledger, so
`p28-rpc-latest-ledger.toml` checks its type only.

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

## Soroban simulation error fixtures

Added 2026-10-15. The four `soroban/p28-soroban-sim-error-*.toml` fixtures
assert the *failure* side of the same pipeline the smoke test above asserts the
success side of: that `simulateTransaction` reports a broken invocation as a
typed host error in `result.error`, rather than as a transport-level JSON-RPC
error or as a silent success.

| Fixture | Condition | `result.error` observed |
| --- | --- | --- |
| `p28-soroban-sim-error-unknown-function` | SEP-41 function the SAC does not export | `HostError: Error(Value, InvalidInput)` |
| `p28-soroban-sim-error-missing-contract` | valid CONTRACT strkey with no stored instance | `HostError: Error(Storage, MissingValue)` |
| `p28-soroban-sim-error-arg-count` | `transfer()` with zero arguments instead of three | `HostError: Error(Context, UnexpectedSize)` |
| `p28-soroban-sim-error-arg-type` | `transfer()` with symbols in both address positions | `HostError: Error(Value, UnexpectedType)` |

Each `(type, code)` pair is a real `SCErrorType`/`SCErrorCode` member from
`Stellar-contract.x` at `stellar/stellar-xdr` `v28.0`, rendered the way
soroban-env-host renders it. `tests/test_sim_error_fixtures.py` derives those
spellings from the enum names and asserts every fixture's `message_contains`
against them, so an invented or typo'd error name cannot be committed. Only the
stable `Error(<type>, <code>)` form is asserted; the diagnostic-event wording
the host attaches ("symbol not found in slice of strs", "wrong number of args to
func", …) is host-internal and free to change, and is recorded in the fixture
headers for a reader but never pinned.

### How the observations were made

`stellar-canary` could not be used to collect these observations. Building
`Protocol-Canary` on the authoring machine fails at the link step — the toolchain
pin resolves, but neither an MSVC `link.exe` nor binutils `dlltool` is present, so
no Rust binary can be produced there. Rather than record unverified expectations,
the transaction envelopes were constructed directly from the XDR definitions and
posted to `simulateTransaction` with a short standard-library script, matching
`canary-soroban`'s `build_invoke_transaction_envelope` field for field:
`MuxedAccount::Ed25519`, `fee = 100`, the fixture's `sequence_number`,
`Preconditions::None`, `Memo::None`, one `Operation` with
`source_account = None` and body `InvokeHostFunction` →
`HostFunction::InvokeContract`, an empty `auth` vector, `TransactionExt::V0`,
envelope type `ENVELOPE_TYPE_TX`, no signatures.

That method is only as trustworthy as the envelope it builds, so a **positive
control was run first**: the same script invoking SEP-41 `name()` on the native
SAC returned `error: null` with `results[0].xdr` of `AAAADgAAAAZuYXRpdmUAAA==`,
which decodes to the `ScVal` symbol `native`, and `decimals()` returned
`AAAAAwAAAAc=`, which decodes to `ScVal` u32 `7`. Those are the same values
`p28-soroban-native-asset-name.toml` records as verified through the real CLI on
2026-09-02, so the harness reproduces a known-good result and the four error
observations below it are evidence rather than predictions.

The observations are dated 2026-10-15 UTC against
`https://soroban-testnet.stellar.org`. As described in [Live networks that
report a newer protocol](#live-networks-that-report-a-newer-protocol), that
endpoint reported protocol 29 at the time while this pack targets protocol 28;
`stellar-canary check --protocol 28` treats the mismatch as a warning and
proceeds, and the four host errors above are properties of the contract
interface rather than of the protocol version, but the caveat applies to these
fixtures exactly as it does to the existing ones.

### What this suite does not cover, and why

- **Contract panics and contract-defined error codes.** `SCErrorType` has a
  tenth member, `SCE_CONTRACT`, which carries a user-defined `uint32` instead of
  an `SCErrorCode`; a WASM trap produces `Error(WasmVm, …)` from code this
  repository does not ship. Reaching either needs a deployed contract, and
  "a request for `Protocol-Canary` to submit a real, state-changing transaction"
  is listed in [What this pack does not check, generally](#what-this-pack-does-not-check-generally)
  as something that never belongs in a fixture. The gap is deliberate and
  guarded: `test_no_fixture_claims_a_contract_defined_error` fails if a fixture
  ever asserts a `Contract` error without one being deployable. Issue #302 asks
  for panic and contract-error-code coverage; it is not delivered here.
- **Resource limits.** An `SCE_BUDGET` error needs a call that exhausts an
  instruction or memory footprint limit, which cannot be constructed against the
  reserved SAC and needs a deployed contract. See [Soroban simulation auth and
  resource estimation](#soroban-simulation-auth-and-resource-estimation) below:
  the resource-estimation *fields* a successful simulation returns do have
  fixtures, staged because the loader cannot yet assert on them, but a budget
  exhaustion is neither staged nor shippable.

## Soroban simulation auth and resource estimation

Added 2026-10-15; resource-estimation half updated 2026-10-16. Issues
[#300](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/300)
(F-043) and [#301](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/301)
(F-044) ask this pack for fixtures asserting on the `auth` array a
`simulateTransaction` response carries (`SorobanAuthorizationEntry`, root
invocation, address credentials) and on its resource-estimation fields
(`minResourceFee`, `transactionData`, CPU and memory instructions).

**What this pack tests.** For `auth`: nothing, and that is a deliberate,
documented gap rather than an oversight, exactly as with CAP-0086 above. For
resource estimation: nothing *consumable* — but the fixtures now exist in staged
form under
[`tests/vectors/resource_estimation/`](../tests/vectors/resource_estimation/),
with their proposed assertion vocabulary in
[`schemas/proposed/simulation-resource-estimate.expect.json`](../schemas/proposed/simulation-resource-estimate.expect.json)
and an offline suite in
[`tests/test_sim_resource_fixtures.py`](../tests/test_sim_resource_fixtures.py)
that validates them and re-decodes the observations they are based on. See [The
staged resource-estimation
corpus](#the-staged-resource-estimation-corpus) below.

**Why neither assertion can ship in `protocol-28/`.** Neither is expressible in
the fixture contract this repository is required to mirror. Read against
`StellarCanary/Protocol-Canary` at commit
`4d2cb9978127ecd1045b4cca022a4681875d0052` — re-read 2026-10-16 for issue #301,
not carried over from the earlier audit that pinned
`2a88756536e2a8fbb3bae475ca1ec0e0c69f2f9c`; nothing relevant had changed:

- `canary-rpc`'s `SimulationResponse` (`crates/canary-rpc/src/models.rs`) has
  exactly four fields — `latest_ledger`, `error`, `transaction_data`,
  `min_resource_fee` — and **no `auth` field**. The `auth` array RPC returns is
  dropped during deserialization, so there is nothing downstream for a fixture to
  assert on. This is precisely what upstream issue
  [#517](https://github.com/StellarCanary/Protocol-Canary/issues/517) (E-119,
  "Parse and Assert Simulation Auth Structures in canary-soroban") exists to fix,
  and it was still open at the time of writing — itself depending on
  [#427](https://github.com/StellarCanary/Protocol-Canary/issues/427),
  [#428](https://github.com/StellarCanary/Protocol-Canary/issues/428) and
  [#504](https://github.com/StellarCanary/Protocol-Canary/issues/504).
- `SorobanAssertion` (`crates/canary-soroban/src/runner.rs`) has exactly two
  variants, `SimulationSuccess` and `SimulationError { message_contains }`. Its
  `From` impl rejects any other `expect.kind` with
  `unsupported expectation kind`, and rejects any key inside `[expect]` other
  than `kind` and `message_contains` before the kind is even read.
  `Protocol-Canary`'s own `docs/fixture-contract.md` states the same two kinds.
- `min_resource_fee` and `transaction_data` *are* deserialized, but the only
  places either name occurs in that workspace are the `SimulationResponse` field
  declarations and `"transactionData"` inside test JSON literals — no production
  code reads them, so even the fields that survive parsing are not reachable from
  an assertion.

**Why this repository does not extend its own schema to cover them.** Issue #301
asks for `schemas/fixture-v1.schema.json` and `tools/validate/validate.py` to
learn a resource-estimation assertion kind. Doing that *in the shipped schema*
would invert the ownership rule in
[`../CONTRIBUTING.md`](../CONTRIBUTING.md#fixture-schema):
that schema "is a convenience JSON Schema mirroring that contract … if the two
ever disagree, `Protocol-Canary`'s implementation wins and this repository's
schema/validator must be corrected to match — never the other way around", and
an unsupported assertion is to be added here "only … once that support exists
and is released". The proposed vocabulary is therefore written down in
[`schemas/proposed/`](../schemas/proposed/), which `fixture-v1.schema.json` does
not reference and `tools/validate/schema_sync.py` does not read — a proposal a
reviewer can check, not a claim about what the loader accepts.

It would also break the pack for every consumer, not just omit a check. In
`canary-runner`'s scheduler, `SorobanFixture::from_loaded` is called with `?`, so
a fixture whose `[expect]` the loader cannot parse aborts the whole run as an
invalid-fixture error (exit 4 per `docs/fixture-contract.md`) rather than being
skipped. Declaring `required_capabilities` would not rescue it either: that filter
does run first, but `Capability` is a closed five-member enum
(`soroban-contract`, `rpc-client`, `stellar-sdk-dependency`, `wasm-artifact`,
`raw-ledger-access`) with no member meaning "auth assertions" or "resource
estimation", so borrowing one would misdescribe the fixture to get it skipped.

### The staged resource-estimation corpus

Issue #301's fixtures are written; they are simply not where the loader can see
them. [`tests/vectors/resource_estimation/`](../tests/vectors/resource_estimation/)
holds three complete files, each with the header comment
[`../CONTRIBUTING.md`](../CONTRIBUTING.md#adding-a-fixture) requires of a
shipped fixture:

| Staged fixture | Function | What it asserts |
|---|---|---|
| `p28-soroban-sim-resource-min-fee-positive` | `name()` | The estimate is present, positive, and within the XDR widths that carry it (`instructions` uint32, `resourceFee` int64). |
| `p28-soroban-sim-resource-fee-matches-transaction-data` | `decimals()` | `SorobanTransactionData.resourceFee` inside `transactionData` equals the same response's `minResourceFee`. |
| `p28-soroban-sim-resource-pure-read-footprint` | `symbol()` | A read-only accessor is estimated as read-only: one-entry `readOnly` footprint naming the invoked contract, empty `readWrite`, zero `diskReadBytes` and `writeBytes`. |

They live under `tests/vectors/` rather than `protocol-28/soroban/` because both
`tools/validate/validate.py` and `tools/badge/badge.py` discover packs by
globbing `protocol-*/` only, so nothing there is parsed as a fixture, counted in
README.md's badge, or handed to the loader. That is the same arrangement
[`tests/vectors/scval_parity/`](../tests/vectors/scval_parity/) already uses. The
directory's own [`README.md`](../tests/vectors/resource_estimation/README.md)
records the promotion criteria.

**Where the expectations come from.** Observed on **2026-10-16 UTC** against
`https://soroban-testnet.stellar.org` at ledger 5216960, using the same
unsigned all-zero-source `InvokeHostFunction` envelope that
[`p28-soroban-native-asset-name`](../protocol-28/soroban/p28-soroban-native-asset-name.toml)
ships. Each response's `minResourceFee` and `transactionData` are recorded
verbatim in the fixture's `[staged_observation]` table, and
[`../tests/test_sim_resource_fixtures.py`](../tests/test_sim_resource_fixtures.py)
decodes that `transactionData` offline against `stellar-xdr` v28.0 — asserting
the buffer is consumed to the byte, so a mis-aligned decode cannot pass — then
checks that the bounds the fixture declares actually hold for the observation it
cites. Observed: `name()` fee 6143 / 116253 instructions, `decimals()` 6126 /
109125, `symbol()` 6151 / 116390; all three with `diskReadBytes` 0,
`writeBytes` 0, an empty `readWrite` footprint, and a single `readOnly`
`CONTRACT_DATA` key whose contract hash is the strkey payload of
`CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC`.

**Two things that shaped the assertions.** Fees and instruction counts are
live-varying, so every assertion is a bound, an XDR field width, or a relation
between two fields of one response — never an equality against a recorded
number, which [`../CONTRIBUTING.md`](../CONTRIBUTING.md#what-never-belongs-in-a-fixture)
rules out. And `cost` is now `null` in testnet's `simulateTransaction` response:
the deprecated `cost.cpuInsns`/`cost.memBytes` pair issue #301 mentions is no
longer returned, so the instruction estimate has to be read from
`SorobanResources.instructions` inside `transactionData`, which is what the
staged fixtures do.

**What is deliberately not staged.** An `SCE_BUDGET` fixture. Exhausting an
instruction or memory footprint limit needs a call the reserved SAC cannot
provide, and the resource *limits* themselves are a host-configuration matter
rather than something a `simulateTransaction` response exposes. Staging a file
for it would be staging a guess, so there is none; see [What this suite does not
cover, and why](#what-this-suite-does-not-cover-and-why) above.

**What closes the gap.** For `auth`, upstream
[#517](https://github.com/StellarCanary/Protocol-Canary/issues/517) landing and
being released. For resource estimation, an equivalent extension of
`SorobanAssertion` (sequenced alongside or after #517, as #301 itself notes) plus
[#504](https://github.com/StellarCanary/Protocol-Canary/issues/504) (E-110,
still open). Once either exists in a released `Protocol-Canary`, the fixture,
schema and validator changes follow the ordinary
[Adding a fixture](../CONTRIBUTING.md#adding-a-fixture) steps — and for the
staged corpus that means the `git mv` into `protocol-28/soroban/`, merging the
proposed fragment into `schemas/fixture-v1.schema.json`, extending
`SOROBAN_EXPECT_KINDS`/`SOROBAN_EXPECT_FIELDS` in `tools/validate/validate.py`,
refreshing `EXPECTED_IDS_BY_SURFACE` in
[`../tests/test_pack_protocol_28.py`](../tests/test_pack_protocol_28.py),
dropping each `[staged_observation]` table, and running `make badge`. The
staging directory's [`README.md`](../tests/vectors/resource_estimation/README.md)
lists the same criteria next to the files they apply to.

**Source.** `StellarCanary/Protocol-Canary` at
`4d2cb9978127ecd1045b4cca022a4681875d0052`: `crates/canary-rpc/src/models.rs`,
`crates/canary-soroban/src/runner.rs`, `crates/canary-runner/src/scheduler.rs`,
`crates/canary-core/src/model.rs`, `docs/fixture-contract.md`. Field layouts and
widths from [`stellar-xdr` v28.0](https://github.com/stellar/stellar-xdr/blob/9c9c145953e80990d6ff1ae3a6a973a0ce6d0694/Stellar-transaction.x)
(`Stellar-transaction.x` for `SorobanTransactionData`, `SorobanResources` and
`LedgerFootprint`; `Stellar-ledger-entries.x` for `LedgerKey` and
`ContractDataDurability`; `Stellar-contract.x` for `SCVal` and `SCAddress`).

## What this pack does not check, generally

- **Anything about a specific downstream application** beyond whether the
  fixtures above pass against that application's configured dependencies
  and RPC endpoint.
- **Mainnet.** Every live-network fixture in this pack was verified
  against testnet only.
- **No fixture in this pack asks `Protocol-Canary` to submit a real
  transaction.** Every check above is decode/encode, a read-only RPC call,
  or simulation.

## Live networks that report a newer protocol

Added 2026-10-09. The text above is a historical record of what was true when it
was written and is left as it was.

`p28-rpc-network` and `p28-rpc-latest-ledger` assert `protocolVersion = 28`.
They are evidence about Protocol 28 and are never edited to expect a later
protocol. On 2026-10-09 the Testnet endpoint `soroban-testnet.stellar.org` and a
public Mainnet endpoint both reported protocol 29 (see
[`protocol-29-rpc-observations.md`](protocol-29-rpc-observations.md)), so those
two fixtures fail against them: `stellar-canary check --protocol 28` built from
`Protocol-Canary` `main` at `1ff7908` gave 5 passed and 2 failed against Testnet,
the two failures being exactly these fixtures, with the warning
`the RPC endpoint reports protocol 29, but this run targets protocol 28`. The XDR
fixtures and the Soroban simulation fixture passed.

An endpoint that reports protocol 29 cannot serve as a live environment that
matches this pack. That is a correct result, not a defect in the fixtures. To run
this pack against a network that reports protocol 28 you need an endpoint you
operate on that protocol. Setting `[tests] rpc = false` in `.stellar-canary.toml`
makes `check` skip the two RPC fixtures (reported as skipped, with the reason),
but the Soroban simulation fixture still calls the configured endpoint.

Protocol 29 coverage is developed separately and only from real evidence; see
[`protocol-29-rpc-observations.md`](protocol-29-rpc-observations.md).

## Ledger entries

Added 2026-10-22. Ledger entries are the data the network stores, and their
encodings change whenever a protocol adds a field — which is exactly why each
entry arm needs its own fixture: a decoder that drifts on one arm can keep
every other arm passing.

**What this pack tests.** Eleven fixtures under
[`protocol-28/xdr/ledger-entry/`](../protocol-28/xdr/ledger-entry/), one
roundtrip and at least one decode-failure per arm:

| Arm | Roundtrip | Decode failure |
|---|---|---|
| `ACCOUNT` (0) | `p28-xdr-ledger-entry-account` | `-account-truncated` |
| `TRUSTLINE` (1) | `p28-xdr-ledger-entry-trustline` | `-trustline-truncated`, `-trustline-unknown-asset-type` |
| `CONTRACT_DATA` (6) | `p28-xdr-ledger-entry-contract-data` | `-contract-data-key-truncated` |
| `CONTRACT_CODE` (7) | `p28-xdr-ledger-entry-contract-code` | `-contract-code-truncated` |
| `TTL` (9) | `p28-xdr-ledger-entry-ttl` | `-ttl-missing-live-until` |

The truncations remove bytes from the end of a crate-produced entry: the
entry-level ext discriminant for the account and trustline arms, the final
`liveUntilLedgerSeq` for TTL, two bytes of the code blob for contract code,
and everything after the key for contract data. `-trustline-unknown-asset-type`
changes one field instead: the `TrustLineAsset` discriminant is set from
`ASSET_TYPE_CREDIT_ALPHANUM4` (1) to 9, which `enum AssetType` does not define.

**Where the definitions come from.** Every header cites
`Stellar-ledger-entries.x` in `stellar/stellar-xdr` at tag `v28.0`, commit
`9c9c145953e80990d6ff1ae3a6a973a0ce6d0694`:

- `enum LedgerEntryType` lines 92-104 and `struct LedgerEntry` lines 548-586,
  including the data union (552-573) and the ext union (575-585);
- `struct AccountEntry` lines 190-217 with its inline ext union (206-216),
  `struct Signer` lines 106-110, `typedef string string32<32>` line 13 and
  `typedef opaque Thresholds[4]` line 12;
- `struct TrustLineEntry` lines 276-307, `union TrustLineAsset` lines 247-262,
  `enum AssetType` lines 24-30 and `struct AlphaNum4` lines 43-47;
- `struct ContractDataEntry` lines 490-497 and `enum ContractDataDurability`
  lines 485-488, with `union SCAddress` (Stellar-contract.x 206-222) and
  `union SCVal` (Stellar-contract.x 254-316) nested inside;
- `struct ContractCodeEntry` lines 513-528, including its inline ext union and
  the `opaque code<>` field;
- `struct TTLEntry` lines 530-534;
- `typedef PublicKey AccountID` (`Stellar-types.x` line 85) and
  `typedef opaque Hash[32]` (line 8).

The extension unions are cited explicitly because they are where a protocol
adds fields. Every fixture here uses the V0 arm; a decoder that mishandled the
ext discriminant would fail on the truncation fixtures, which remove exactly
those four bytes.

**How the payloads were produced.** Every `value_base64` is the output of a
Rust program that builds the typed value with the official `stellar-xdr`
28.0.1 crate (features `base64` and `alloc`) and calls
`to_xdr_base64(Limits::none())`; nothing is hand-assembled. Each header records
the construction expression, the crate version, `rustc 1.99.1 (58cf8f9c3
2026-10-13)` and the generation date (2026-10-22 UTC). The same program
asserted that `from_xdr_base64` round-trips every valid entry and rejects every
decode-failure value with the error the header quotes (`failed to fill whole
buffer` for the five truncations, `xdr value invalid` for the undefined asset
type).

Every id, hash, key and balance is a synthetic structural value. The
0x11/0x33-filled account ids are not accounts, the 0x44-filled issuer is not
an issuer, the 0x22-filled contract id is not a deployed contract, the
0x55-filled code hash is not the hash of any upload, and the four contract-code
bytes (`00 61 73 6d`) are the WebAssembly magic prefix used only to exercise
the opaque path — they are not a WASM module. `example.test` is a
documentation domain. No secret key is used anywhere, and no fixture claims a
network observation.

**Verification.** `tools/validate/validate.py` accepts all 11 fixtures. The
independent standard-library LedgerEntry codec in `tests/xdr_codec.py` (added
with these fixtures) decodes and re-encodes all five roundtrips byte-for-byte
and rejects all six decode-failures. With the engine: `stellar-canary` 0.2.0,
`Protocol-Canary` main at commit
`bc1330660c36eb67a87747513c7d14ba04d39238`, run offline with `--offline
--no-cache --json` from a project whose `.stellar-canary.toml` enables
`xdr = true`, reports all 11 as passing — 5 "LedgerEntry round-tripped
byte-for-byte" and 6 "LedgerEntry was correctly rejected".

## ScVal vectors, maps and addresses

Added 2026-10-22. Composite and address values are what real Soroban calls
pass: argument lists, storage keys, contract addresses. Their encodings —
the optional-pointer flag in front of `SCVec`/`SCMap`, the key/value entry
stride, the address arm — are where an XDR implementation most often differs
from the reference.

**What this pack tests.** Fourteen fixtures under
[`protocol-28/xdr/scval-composite/`](../protocol-28/xdr/scval-composite/):

| Group | Fixtures | What they cover |
|---|---|---|
| Vec | `p28-xdr-scval-vec-null`, `-vec-empty`, `-vec-one`, `-vec-multi` | absent versus present-but-empty, one element, and three heterogeneous elements |
| Map | `p28-xdr-scval-map-empty`, `-map-one`, `-map-multi`, `-map-nested`, `-map-unsorted-keys` | empty, one entry, three entries, one level of map-in-vec nesting, and an encoding whose keys are not in ascending order |
| Address | `p28-xdr-scval-address-account`, `-address-contract` | the account arm (a `PublicKey` union inside an `SCAddress` union) and the contract arm (a plain 32-byte id) |
| Decode failures | `p28-xdr-scval-vec-count-exceeds-data`, `-map-truncated-after-key`, `-address-unknown-discriminant` | a count larger than the data, an entry cut after its key, and an undefined `SCAddressType` |

**The absent-versus-empty distinction.** `SCVec *vec` and `SCMap *map` are XDR
optional pointers, so an absent container is a 4-byte flag of 0 and no
sequence, while a present-but-empty one is flag 1 followed by a count of 0.
The two encodings differ and both are exercised. A decoder that treated a
non-zero flag as "present" would also accept corrupt input; the ScVal codec in
`tests/scval_xdr.py` rejects any flag other than 0 or 1.

**Map entry order.** The XDR definition says nothing about the order of
entries in an `SCMap`; `ScMap::sorted_from_entries` in the crate sorts when a
program builds a map that way, but the decoder itself does not enforce an
order. The generator observed that `from_xdr_base64` accepts the
non-ascending `b`, `a` encoding and re-encodes it unchanged, and the same
fixture passes the engine offline, so neither the pinned crate nor
`stellar-canary` 0.2.0 enforces ascending order on decode. That observation
is pinned in `p28-xdr-scval-map-unsorted-keys`: an implementation that sorted
on decode would not round-trip those bytes.

**Depth and recursion.** `p28-xdr-scval-map-nested` nests a vec inside a map
value — one level — to prove nested containers encode. It does not target a
depth limit: depth and recursion limits are open issue #303 and no fixture in
this directory approaches one.

**Where the definitions come from.** Every header cites the pinned file
`Stellar-contract.x` in `stellar/stellar-xdr` at tag `v28.0`, commit
`9c9c145953e80990d6ff1ae3a6a973a0ce6d0694`:

- `union SCVal` lines 254-316 with the `SCV_VEC` (298-299), `SCV_MAP`
  (300-301) and `SCV_ADDRESS` (303-304) cases;
- `typedef SCVal SCVec<>;` line 242 and `typedef SCMapEntry SCMap<>;` line
  243, with `struct SCMapEntry` lines 318-322;
- `enum SCAddressType` lines 179-190 and `union SCAddress` lines 206-222;
- `typedef PublicKey AccountID;` (`Stellar-types.x` line 85), the `PublicKey`
  union (lines 53-57) and `typedef Hash ContractID;` (line 87).

**How the payloads were produced.** Every `value_base64` is the output of a
Rust program that builds the typed value with the official `stellar-xdr`
28.0.1 crate (features `base64` and `alloc` — the version Protocol-Canary's
`canary-xdr` pins for Protocol 28) and calls
`to_xdr_base64(Limits::none())`; nothing is hand-assembled. Each header
records the construction expression, the crate version, `rustc 1.99.1
(58cf8f9c3 2026-10-13)` and the generation date (2026-10-22 UTC), and the
program asserted that `from_xdr_base64` round-trips every valid value and
rejects every decode-failure value with the error the header quotes
(`failed to fill whole buffer` twice, `xdr value invalid` once).

The 32-byte address payloads are synthetic structural values: the
0x11-filled key is not a real account (and no secret key exists for it) and
the 0x22-filled id is not the hash of any deployed Wasm. No fixture claims a
network observation or a real contract, account or key.

**Verification.** `tools/validate/validate.py` accepts all 14 fixtures; the
`tests/scval_xdr.py` cross-check decodes and re-encodes all 11 roundtrips
byte-for-byte and rejects all 3 decode-failures, 14 of 14 agreeing. With the
engine: `stellar-canary 0.2.0`, `Protocol-Canary` main at commit
`bc1330660c36eb67a87747513c7d14ba04d39238`, run offline with
`--offline --no-cache --json` from a project whose `.stellar-canary.toml`
enables `xdr = true`, reports all 14 as passing — 11 "ScVal round-tripped
byte-for-byte" and 3 "ScVal was correctly rejected".

## Consuming this pack

For a concise index of the fixtures in this pack, see [`protocol-28/README.md`](../protocol-28/README.md).

```bash
stellar-canary check --fixtures-dir <path-to-this-repo>/protocol-28 --json
```

The `--fixtures-dir` argument must point at the `protocol-28/` pack directory,
not at the repository root. The repository root contains test vectors under
`tests/vectors/` (some deliberately invalid) that the loader would attempt to
parse as fixtures, causing the run to fail. See the top-level README.md
"Repository relationship" section for details.

This command was run on 2026-09-02 against a local `Protocol-Canary` build
(commit `1ff7908`, `stellar-canary 0.1.1`) with `--offline --no-cache` and
passed for every fixture in the pack as it stood then, confirming this pack
is consumable exactly as documented in `Protocol-Canary`'s
`docs/fixture-contract.md`. This record is deliberately not tied to a
hardcoded fixture count, so adding a fixture does not make it stale — but a
newly added fixture is only covered by this record once it has been
re-verified the same way.

## Adding more Protocol 28 fixtures

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md#adding-a-fixture). Every new
fixture must cite a real upstream source in its `source_reference` field
and explain, in its own header comment, how its expected values were
derived or observed — the same way every fixture in this pack does.
