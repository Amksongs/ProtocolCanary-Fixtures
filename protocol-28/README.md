# Protocol 28 compatibility pack

This pack contains **93 fixtures**.

Implemented in Stellar Core 28.0.0, Stellar RPC 28.0.0 (integration-tested
against Soroban host 28.0.1), and the official `stellar-xdr` 28.0.0 crate.
Includes CAP-0083, CAP-0085, and CAP-0086.

This pack's fixtures are written against **fixture format
`schema_version` 1** ([`schemas/fixture-v1.schema.json`](../schemas/fixture-v1.schema.json)).
See [`../docs/protocol-28.md`](../docs/protocol-28.md#fixture-format-version)
for details, and [`../CONTRIBUTING.md`](../CONTRIBUTING.md#fixture-schema)
for why future packs should record their target version too.

This directory holds no `manifest.toml` — see the repository root
[`README.md`](../README.md#repository-relationship) for why: the
`Protocol-Canary` loader parses every `*.toml` file it finds as a fixture,
so a separate enumeration file in this format would either be ignored or,
worse, misparsed as a broken fixture. The fixture files below *are* the
enumeration.

| Fixture | Surface | CAP | What it proves |
|---|---|---|---|
| [`xdr/cap-0083/p28-xdr-cap83-empty-tx-set.toml`](xdr/cap-0083/p28-xdr-cap83-empty-tx-set.toml) | xdr | CAP-0083 | A `StellarValue` using `STELLAR_VALUE_EMPTY_TX_SET` round-trips byte-for-byte. |
| [`xdr/cap-0083/p28-xdr-cap83-empty-tx-set-malformed.toml`](xdr/cap-0083/p28-xdr-cap83-empty-tx-set-malformed.toml) | xdr | CAP-0083 | A truncated `StellarValue` using `STELLAR_VALUE_EMPTY_TX_SET` is correctly rejected, not silently accepted. |
| [`xdr/cap-0085/p28-xdr-cap85-external-ref-roundtrip.toml`](xdr/cap-0085/p28-xdr-cap85-external-ref-roundtrip.toml) | xdr | CAP-0085 | A `ContractExecutable` using `CONTRACT_EXECUTABLE_EXTERNAL_REF` round-trips byte-for-byte. |
| [`xdr/cap-0085/p28-xdr-cap85-external-ref-malformed.toml`](xdr/cap-0085/p28-xdr-cap85-external-ref-malformed.toml) | xdr | CAP-0085 | A truncated `ContractExecutable::ExternalRef` encoding is correctly rejected, not silently accepted. |
| [`xdr/contract-executable/p28-xdr-contract-executable-wasm-roundtrip.toml`](xdr/contract-executable/p28-xdr-contract-executable-wasm-roundtrip.toml) | xdr | — | A `ContractExecutable` using the `CONTRACT_EXECUTABLE_WASM` case round-trips byte-for-byte. |
| [`xdr/contract-executable/p28-xdr-contract-executable-wasm-decode-success.toml`](xdr/contract-executable/p28-xdr-contract-executable-wasm-decode-success.toml) | xdr | — | A well-formed `ContractExecutable` using the `CONTRACT_EXECUTABLE_WASM` case decodes successfully. |
| [`xdr/contract-executable/p28-xdr-contract-executable-wasm-decode-failure.toml`](xdr/contract-executable/p28-xdr-contract-executable-wasm-decode-failure.toml) | xdr | — | A truncated `ContractExecutable::Wasm` encoding is correctly rejected, not silently accepted. |
| [`xdr/contract-executable/p28-xdr-contract-executable-stellar-asset-roundtrip.toml`](xdr/contract-executable/p28-xdr-contract-executable-stellar-asset-roundtrip.toml) | xdr | — | A `ContractExecutable` using the `CONTRACT_EXECUTABLE_STELLAR_ASSET` case round-trips byte-for-byte. |
| [`xdr/contract-executable/p28-xdr-contract-executable-stellar-asset-decode-success.toml`](xdr/contract-executable/p28-xdr-contract-executable-stellar-asset-decode-success.toml) | xdr | — | A well-formed `ContractExecutable` using the `CONTRACT_EXECUTABLE_STELLAR_ASSET` case decodes successfully. |
| [`xdr/contract-executable/p28-xdr-contract-executable-stellar-asset-decode-failure.toml`](xdr/contract-executable/p28-xdr-contract-executable-stellar-asset-decode-failure.toml) | xdr | — | A truncated `ContractExecutable::StellarAsset` encoding is correctly rejected, not silently accepted. |
| [`xdr/stellar-value/p28-xdr-stellar-value-basic-roundtrip.toml`](xdr/stellar-value/p28-xdr-stellar-value-basic-roundtrip.toml) | xdr | — | A `StellarValue` using the `STELLAR_VALUE_BASIC` ext arm round-trips byte-for-byte. |
| [`xdr/stellar-value/p28-xdr-stellar-value-basic-decode-success.toml`](xdr/stellar-value/p28-xdr-stellar-value-basic-decode-success.toml) | xdr | — | A well-formed `StellarValue` using the `STELLAR_VALUE_BASIC` ext arm decodes successfully. |
| [`xdr/stellar-value/p28-xdr-stellar-value-basic-decode-failure.toml`](xdr/stellar-value/p28-xdr-stellar-value-basic-decode-failure.toml) | xdr | — | A truncated `STELLAR_VALUE_BASIC` `StellarValue` encoding is correctly rejected, not silently accepted. |
| [`xdr/stellar-value/p28-xdr-stellar-value-signed-roundtrip.toml`](xdr/stellar-value/p28-xdr-stellar-value-signed-roundtrip.toml) | xdr | — | A `StellarValue` using the `STELLAR_VALUE_SIGNED` ext arm round-trips byte-for-byte. |
| [`xdr/stellar-value/p28-xdr-stellar-value-signed-decode-success.toml`](xdr/stellar-value/p28-xdr-stellar-value-signed-decode-success.toml) | xdr | — | A well-formed `StellarValue` using the `STELLAR_VALUE_SIGNED` ext arm decodes successfully. |
| [`xdr/stellar-value/p28-xdr-stellar-value-signed-decode-failure.toml`](xdr/stellar-value/p28-xdr-stellar-value-signed-decode-failure.toml) | xdr | — | A truncated `STELLAR_VALUE_SIGNED` `StellarValue` encoding is correctly rejected, not silently accepted. |
| [`xdr/boundaries/p28-xdr-stellar-value-boundary-truncated.toml`](xdr/boundaries/p28-xdr-stellar-value-boundary-truncated.toml) | xdr | — | A `StellarValue` truncated to 44 of 48 bytes, cutting off its ext discriminant, is correctly rejected, not silently accepted. |
| [`xdr/boundaries/p28-xdr-stellar-value-boundary-trailing-bytes.toml`](xdr/boundaries/p28-xdr-stellar-value-boundary-trailing-bytes.toml) | xdr | — | A complete `StellarValue` followed by four trailing bytes is correctly rejected, not silently accepted. |
| [`xdr/boundaries/p28-xdr-stellar-value-boundary-unknown-ext-discriminant.toml`](xdr/boundaries/p28-xdr-stellar-value-boundary-unknown-ext-discriminant.toml) | xdr | — | A `StellarValue` whose ext union uses the undefined discriminant 3 is correctly rejected, not silently accepted. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-v0-roundtrip.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-v0-roundtrip.toml) | xdr | — | A `TransactionEnvelope` using the `ENVELOPE_TYPE_TX_V0` arm round-trips byte-for-byte. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-v0-decode-failure.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-v0-decode-failure.toml) | xdr | — | A `TransactionEnvelope` whose signature is truncated mid-signature is correctly rejected, not silently accepted. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-v1-roundtrip.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-v1-roundtrip.toml) | xdr | — | A `TransactionEnvelope` using the `ENVELOPE_TYPE_TX` arm round-trips byte-for-byte. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-v1-decode-failure.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-v1-decode-failure.toml) | xdr | — | A `TransactionEnvelope` with an unknown envelope-type discriminant is correctly rejected, not silently accepted. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-soroban-invoke-roundtrip.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-soroban-invoke-roundtrip.toml) | xdr | — | A `TransactionEnvelope` whose single operation is `INVOKE_HOST_FUNCTION` round-trips byte-for-byte. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-soroban-invoke-decode-failure.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-soroban-invoke-decode-failure.toml) | xdr | — | A Soroban `TransactionEnvelope` truncated inside its contract id is correctly rejected, not silently accepted. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-fee-bump-roundtrip.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-fee-bump-roundtrip.toml) | xdr | — | A `TransactionEnvelope` using the `ENVELOPE_TYPE_TX_FEE_BUMP` arm round-trips byte-for-byte. |
| [`xdr/transaction-envelope/p28-xdr-transaction-envelope-fee-bump-decode-failure.toml`](xdr/transaction-envelope/p28-xdr-transaction-envelope-fee-bump-decode-failure.toml) | xdr | — | A fee-bump `TransactionEnvelope` whose inner transaction is truncated is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-account-truncated.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-account-truncated.toml) | xdr | — | A truncated `ACCOUNT` `LedgerEntry` is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-account.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-account.toml) | xdr | — | An `ACCOUNT` `LedgerEntry` round-trips byte-for-byte. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-contract-code-truncated.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-contract-code-truncated.toml) | xdr | — | A truncated `CONTRACT_CODE` code blob is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-contract-code.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-contract-code.toml) | xdr | — | A `CONTRACT_CODE` `LedgerEntry` round-trips byte-for-byte. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-contract-data-key-truncated.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-contract-data-key-truncated.toml) | xdr | — | A `CONTRACT_DATA` entry cut after its key is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-contract-data.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-contract-data.toml) | xdr | — | A `CONTRACT_DATA` `LedgerEntry` round-trips byte-for-byte. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-trustline-truncated.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-trustline-truncated.toml) | xdr | — | A truncated `TRUSTLINE` `LedgerEntry` is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-trustline-unknown-asset-type.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-trustline-unknown-asset-type.toml) | xdr | — | A `TRUSTLINE` with an undefined `TrustLineAsset` type is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-trustline.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-trustline.toml) | xdr | — | A `TRUSTLINE` `LedgerEntry` round-trips byte-for-byte. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-ttl-missing-live-until.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-ttl-missing-live-until.toml) | xdr | — | A `TTL` entry missing `liveUntilLedgerSeq` is correctly rejected, not silently accepted. |
| [`xdr/ledger-entry/p28-xdr-ledger-entry-ttl.toml`](xdr/ledger-entry/p28-xdr-ledger-entry-ttl.toml) | xdr | — | A `TTL` `LedgerEntry` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-address-account.toml`](xdr/scval-composite/p28-xdr-scval-address-account.toml) | xdr | — | An account `ScVal::Address` with a synthetic key round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-address-contract.toml`](xdr/scval-composite/p28-xdr-scval-address-contract.toml) | xdr | — | A contract `ScVal::Address` with a synthetic id round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-address-unknown-discriminant.toml`](xdr/scval-composite/p28-xdr-scval-address-unknown-discriminant.toml) | xdr | — | A `ScVal::Address` with an undefined SCAddressType discriminant is correctly rejected, not silently accepted. |
| [`xdr/scval-composite/p28-xdr-scval-map-empty.toml`](xdr/scval-composite/p28-xdr-scval-map-empty.toml) | xdr | — | A present-but-empty `ScVal::Map` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-map-multi.toml`](xdr/scval-composite/p28-xdr-scval-map-multi.toml) | xdr | — | A three-entry `ScVal::Map` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-map-nested.toml`](xdr/scval-composite/p28-xdr-scval-map-nested.toml) | xdr | — | A `ScVal::Map` with a `ScVal::Vec` value round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-map-one.toml`](xdr/scval-composite/p28-xdr-scval-map-one.toml) | xdr | — | A one-entry `ScVal::Map` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-map-truncated-after-key.toml`](xdr/scval-composite/p28-xdr-scval-map-truncated-after-key.toml) | xdr | — | A `ScVal::Map` truncated after its key is correctly rejected, not silently accepted. |
| [`xdr/scval-composite/p28-xdr-scval-map-unsorted-keys.toml`](xdr/scval-composite/p28-xdr-scval-map-unsorted-keys.toml) | xdr | — | A `ScVal::Map` with non-ascending keys round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-vec-count-exceeds-data.toml`](xdr/scval-composite/p28-xdr-scval-vec-count-exceeds-data.toml) | xdr | — | A `ScVal::Vec` whose element count exceeds its data is correctly rejected, not silently accepted. |
| [`xdr/scval-composite/p28-xdr-scval-vec-empty.toml`](xdr/scval-composite/p28-xdr-scval-vec-empty.toml) | xdr | — | A present-but-empty `ScVal::Vec` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-vec-multi.toml`](xdr/scval-composite/p28-xdr-scval-vec-multi.toml) | xdr | — | A three-element `ScVal::Vec` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-vec-null.toml`](xdr/scval-composite/p28-xdr-scval-vec-null.toml) | xdr | — | An absent (null) `ScVal::Vec` round-trips byte-for-byte. |
| [`xdr/scval-composite/p28-xdr-scval-vec-one.toml`](xdr/scval-composite/p28-xdr-scval-vec-one.toml) | xdr | — | A one-element `ScVal::Vec` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-bool-false.toml`](xdr/scval/p28-xdr-scval-bool-false.toml) | xdr | — | `ScVal::Bool(false)` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-bool-true.toml`](xdr/scval/p28-xdr-scval-bool-true.toml) | xdr | — | `ScVal::Bool(true)` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-bytes-empty.toml`](xdr/scval/p28-xdr-scval-bytes-empty.toml) | xdr | — | An empty `ScVal::Bytes` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-bytes-small.toml`](xdr/scval/p28-xdr-scval-bytes-small.toml) | xdr | — | A five-byte `ScVal::Bytes` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-bytes-truncated.toml`](xdr/scval/p28-xdr-scval-bytes-truncated.toml) | xdr | — | A truncated `ScVal::Bytes` payload is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-duration.toml`](xdr/scval/p28-xdr-scval-duration.toml) | xdr | — | `ScVal::Duration(Duration(86_400))` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i128-max.toml`](xdr/scval/p28-xdr-scval-i128-max.toml) | xdr | — | `ScVal::I128` maximum round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i128-min.toml`](xdr/scval/p28-xdr-scval-i128-min.toml) | xdr | — | `ScVal::I128` minimum round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i128-truncated.toml`](xdr/scval/p28-xdr-scval-i128-truncated.toml) | xdr | — | A truncated `ScVal::I128` payload is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-i128-zero.toml`](xdr/scval/p28-xdr-scval-i128-zero.toml) | xdr | — | `ScVal::I128` zero round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i256-max.toml`](xdr/scval/p28-xdr-scval-i256-max.toml) | xdr | — | `ScVal::I256` maximum round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i256-min.toml`](xdr/scval/p28-xdr-scval-i256-min.toml) | xdr | — | `ScVal::I256` minimum round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i256-zero.toml`](xdr/scval/p28-xdr-scval-i256-zero.toml) | xdr | — | `ScVal::I256` zero round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i32-min.toml`](xdr/scval/p28-xdr-scval-i32-min.toml) | xdr | — | `ScVal::I32(i32::MIN)` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-i64-min.toml`](xdr/scval/p28-xdr-scval-i64-min.toml) | xdr | — | `ScVal::I64(i64::MIN)` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-string-empty.toml`](xdr/scval/p28-xdr-scval-string-empty.toml) | xdr | — | An empty `ScVal::String` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-string-small.toml`](xdr/scval/p28-xdr-scval-string-small.toml) | xdr | — | A six-byte `ScVal::String` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-string-truncated.toml`](xdr/scval/p28-xdr-scval-string-truncated.toml) | xdr | — | A truncated `ScVal::String` payload is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-symbol-32-boundary.toml`](xdr/scval/p28-xdr-scval-symbol-32-boundary.toml) | xdr | — | A 32-byte `ScVal::Symbol`, the SCSYMBOL_LIMIT, round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-symbol-33-invalid.toml`](xdr/scval/p28-xdr-scval-symbol-33-invalid.toml) | xdr | — | A 33-byte symbol, one past SCSYMBOL_LIMIT, is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-symbol-empty.toml`](xdr/scval/p28-xdr-scval-symbol-empty.toml) | xdr | — | An empty `ScVal::Symbol` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-symbol-small.toml`](xdr/scval/p28-xdr-scval-symbol-small.toml) | xdr | — | An eight-byte `ScVal::Symbol` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-timepoint.toml`](xdr/scval/p28-xdr-scval-timepoint.toml) | xdr | — | `ScVal::Timepoint(TimePoint(1_700_000_000))` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u128-high-bit.toml`](xdr/scval/p28-xdr-scval-u128-high-bit.toml) | xdr | — | `ScVal::U128` with the high bit set round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u128-max.toml`](xdr/scval/p28-xdr-scval-u128-max.toml) | xdr | — | `ScVal::U128` maximum round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u128-zero.toml`](xdr/scval/p28-xdr-scval-u128-zero.toml) | xdr | — | `ScVal::U128` zero round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u256-max.toml`](xdr/scval/p28-xdr-scval-u256-max.toml) | xdr | — | `ScVal::U256` maximum round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u256-truncated.toml`](xdr/scval/p28-xdr-scval-u256-truncated.toml) | xdr | — | A truncated `ScVal::U256` payload is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-u256-zero.toml`](xdr/scval/p28-xdr-scval-u256-zero.toml) | xdr | — | `ScVal::U256` zero round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u32-max.toml`](xdr/scval/p28-xdr-scval-u32-max.toml) | xdr | — | `ScVal::U32(u32::MAX)` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u32-truncated.toml`](xdr/scval/p28-xdr-scval-u32-truncated.toml) | xdr | — | A truncated `ScVal::U32` payload is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-u64-max.toml`](xdr/scval/p28-xdr-scval-u64-max.toml) | xdr | — | `ScVal::U64(u64::MAX)` round-trips byte-for-byte. |
| [`xdr/scval/p28-xdr-scval-u64-truncated.toml`](xdr/scval/p28-xdr-scval-u64-truncated.toml) | xdr | — | A truncated `ScVal::U64` payload is correctly rejected, not silently accepted. |
| [`xdr/scval/p28-xdr-scval-void.toml`](xdr/scval/p28-xdr-scval-void.toml) | xdr | — | `ScVal::Void` round-trips byte-for-byte. |
| [`rpc/p28-rpc-network.toml`](rpc/p28-rpc-network.toml) | rpc | — | A configured RPC endpoint's `getNetwork` reports protocol 28 with a `passphrase` field. |
| [`rpc/p28-rpc-latest-ledger.toml`](rpc/p28-rpc-latest-ledger.toml) | rpc | — | The same endpoint's `getLatestLedger` reports protocol 28, a numeric `sequence`, a string ledger `id`, and no `getNetwork`-only fields. |
| [`soroban/p28-soroban-native-asset-name.toml`](soroban/p28-soroban-native-asset-name.toml) | soroban | — | The full construct → `simulateTransaction` → result pipeline works against real Protocol 28 infrastructure. |
| [`soroban/p28-soroban-sim-error-unknown-function.toml`](soroban/p28-soroban-sim-error-unknown-function.toml) | soroban | — | Invoking a function the Stellar Asset Contract does not export fails with `Error(Value, InvalidInput)` in `result.error`. |
| [`soroban/p28-soroban-sim-error-missing-contract.toml`](soroban/p28-soroban-sim-error-missing-contract.toml) | soroban | — | A well-formed contract id with no stored instance fails with `Error(Storage, MissingValue)` rather than being treated as an empty contract. |
| [`soroban/p28-soroban-sim-error-arg-count.toml`](soroban/p28-soroban-sim-error-arg-count.toml) | soroban | — | Calling SEP-41 `transfer()` with zero arguments instead of three fails with `Error(Context, UnexpectedSize)`. |
| [`soroban/p28-soroban-sim-error-arg-type.toml`](soroban/p28-soroban-sim-error-arg-type.toml) | soroban | — | Calling SEP-41 `transfer()` with symbols in both address positions fails with `Error(Value, UnexpectedType)`. |

> **Column legend** — *Fixture*: the fixture file, linked to its path inside
> this pack (the fixture ID is the file's name without the `.toml`
> extension). *Surface*: the Protocol-Canary checker the fixture targets —
> `xdr` (decode/encode, via `canary-xdr`), `rpc` (a read-only JSON-RPC
> call, via `canary-rpc`), or `soroban` (a simulated contract invocation,
> via `canary-soroban`) — and matches the fixture's own `surface` field.
> *CAP*: the Stellar Core Advancement Proposal number the fixture is
> specific to, or `—` when it asserts general Protocol 28 behavior rather
> than one CAP. *What it proves*: the single concrete assertion it makes.

See [`../docs/protocol-28.md`](../docs/protocol-28.md) for what this pack
checks, what it deliberately does not (including why CAP-0086 has no
fixture yet, and why there are no simulation-`auth` fixtures), and source
provenance for every assertion above.

The fixture count above is the whole pack. Three further resource-estimation
fixtures are written but **staged** outside it, under
[`../tests/vectors/resource_estimation/`](../tests/vectors/resource_estimation/),
because `canary-soroban` has no assertion kind for a resource estimate yet and a
fixture the loader cannot parse aborts a run rather than being skipped. They are
not counted here, not validated by `tools/validate/validate.py`, and not
consumable — see [the staged resource-estimation
corpus](../docs/protocol-28.md#the-staged-resource-estimation-corpus) for what
they assert and what would promote them.
