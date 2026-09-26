# Changelog

All notable changes to this project are documented in this file.

Every entry below links to the pull request that introduced it — or, for
changes that were pushed directly to `main` without a pull request, to the
introducing commit — so each line can be traced back to its review
discussion and diff. New entries must include that link; see
[CONTRIBUTING.md](CONTRIBUTING.md#updating-changelogmd).

## [Unreleased]

### Added

- Repository scaffold: `schemas/`, `tools/validate/`, `tests/`, `docs/`,
  CI validation workflow.
  ([757e1e7], [5142110], [764111c], [806549c], [c8d8e75])
- `schemas/fixture-v1.schema.json` documenting the fixture format
  implemented by `StellarCanary/Protocol-Canary`'s `canary-fixtures` crate.
  ([5142110])
- `tools/validate/validate.py`: structural validator (schema conformance,
  unique IDs, protocol/surface enums, source references, referenced-file
  existence). No live-network or execution behavior. ([764111c])
- Protocol 28 compatibility pack (`protocol-28/`): ([c5b882c])
  - `p28-xdr-cap83-empty-tx-set` — CAP-0083 `StellarValue`
    (`STELLAR_VALUE_EMPTY_TX_SET`) round-trip, built with the official
    `stellar-xdr` 28.0.0 crate. ([2b3d07b])
  - `p28-xdr-cap83-empty-tx-set-malformed` — a truncated encoding of the
    same CAP-0083 `StellarValue` shape is correctly rejected, mirroring the
    CAP-0085 malformed-input fixture. ([PR #97])
  - `p28-xdr-cap85-external-ref-roundtrip` and
    `p28-xdr-cap85-external-ref-malformed` — CAP-0085
    `ContractExecutable` (`CONTRACT_EXECUTABLE_EXTERNAL_REF`) round-trip
    and malformed-input rejection. ([3f097d1])
  - `p28-rpc-network` — Protocol 28 `getNetwork` identity check, verified
    live against `soroban-testnet.stellar.org`. ([0f54e20])
  - `p28-soroban-native-asset-name` — a Soroban simulation smoke fixture
    (SEP-41 `name()` on the reserved native-asset contract), verified live
    against `soroban-testnet.stellar.org`. ([ea8b63b])
- `docs/protocol-28.md` documenting exactly what this pack checks, what it
  does not, and why. ([806549c])
- A fixture-count badge in README.md's badge row, plus `tools/badge/badge.py`,
  a stdlib-only generator/checker that counts fixtures using the same
  discovery rule as the validator and rewrites only the marked region of
  README.md. `make badge` regenerates it; CI runs `--check`, so the number
  cannot silently drift from the fixture tree. ([ab88ca4])

### Changed

- The structural validator now treats a missing `source_reference` as an
  error rather than a warning, so a fixture with no authoritative provenance
  reference fails `tools/validate/validate.py` (and therefore CI) instead of
  passing with a printed advisory. `CONTRIBUTING.md`, `SECURITY.md`,
  `README.md` and `schemas/fixture-v1.schema.json` were updated to describe
  the rule as enforced. ([PR #143])
- Documented the reciprocal RPC type-list maintenance relationship, linked
  the malformed-input review guidance into the fixture walkthrough, and
  recorded the current CAP-0085 CLI status and tracked deployment gap.
  ([PR #176])
- `schemas/fixture-v1.schema.json` gained a top-level `examples` array
  containing one minimal, schema-valid XDR fixture mirroring
  `protocol-28/xdr/cap-0085/p28-xdr-cap85-external-ref-roundtrip.toml`,
  so schema-aware editors (e.g. Even Better TOML/Taplo) can offer a
  worked completion example.
- `protocol-27/README.md` now links its "contribution policy" reference
  directly to `CONTRIBUTING.md`, where the pack-population verification
  policy is spelled out.

### Known gaps

- **CAP-0086 is not covered.** CAP-0086 (sparse-map host functions) has no
  corresponding top-level XDR type — testing it for real requires a
  deployed Soroban contract that calls
  `sparse_map_new_from_linear_memory`/`sparse_map_unpack_to_linear_memory`.
  As of this release, the latest published `soroban-sdk` (27.0.6) does not
  expose these host functions, so no such contract can be built and
  verified without hand-crafting the host-function ABI — which this
  project's no-guessing rule forbids. See `docs/protocol-28.md` for
  details and what would need to be true upstream before this gap can be
  closed. ([757e1e7])
- **CAP-0085 Soroban-level (not just XDR-level) behavior is not covered.**
  The XDR fixtures above prove the wire representation round-trips; they
  do not exercise an actual deployed externally-managed-executable
  contract fleet end-to-end, which would require deploying and verifying a
  real Protocol 28 contract using this brand-new executable type. The Rust
  `stellar` CLI **27.1.0** installed while authoring this pack had no
  supported external-reference deployment flow. The current **28.0.0**
  release can resolve and invoke existing external references, but its
  `stellar contract deploy` command still has no direct
  `--executable-owner`/`--executable-tag` construction option; the draft
  [`stellar-cli` PR #2659](https://github.com/stellar/stellar-cli/pull/2659)
  is the upstream candidate to unblock that gap. The exact commands,
  re-check date, and distinction between reference resolution and direct
  deployment are recorded in [`docs/protocol-28.md`](docs/protocol-28.md) and
  tracked by [issue #8](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/8).
  ([757e1e7])
- `protocol-27/` is intentionally empty; see `protocol-27/README.md`.
  ([757e1e7])

### Upstream dependency change

- `StellarCanary/Protocol-Canary`'s `canary-xdr` crate gained
  `ContractExecutable` decode/encode support (previously only
  `StellarValue` was supported), so that the CAP-0085 fixtures above are
  actually runnable rather than merely well-formed TOML. See that
  repository's own changelog for the corresponding entry. ([757e1e7])

<!-- Link definitions: the pull request or commit that introduced each
     entry above. Commits listed here were pushed directly to `main`
     without a pull request; PR #97, PR #143, and PR #176 are the
     [Unreleased] entries that originated from pull requests. -->

[757e1e7]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/757e1e777489bb5c20e7500b245370de227c66b3
[5142110]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/51421106999811666502b2e7da7ae3b9e351fd9c
[764111c]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/764111cb2fecc02a0a300feeecf46c9e38c379a0
[c5b882c]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/c5b882c347a1913bf4c035ce51b7950232a964b6
[2b3d07b]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/2b3d07b32923b0274170f106575915ad85fc2251
[3f097d1]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/3f097d176b1bcf80c3c8fe255015d2b7ee0a12ff
[0f54e20]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/0f54e20410747e669d8797c825b698cdc0d19d5d
[ea8b63b]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/ea8b63b5eb46118b8475568c2332f9d43f571ee2
[c8d8e75]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/c8d8e75b741b35873e8b5074fac6f8321bc94197
[806549c]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/806549c1ab8f21dbfd44d5091eb899b776ea5767
[ab88ca4]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/ab88ca4ee03e4e189c003402fe68aa8430411d00
[PR #97]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/97
[PR #143]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/143
[PR #176]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/176
