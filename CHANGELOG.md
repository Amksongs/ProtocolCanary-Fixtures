# Changelog

All notable changes to this project are documented in this file.

Every entry below links to the pull request that introduced it — or, for
changes that were pushed directly to `main` without a pull request, to the
introducing commit — so each line can be traced back to its review
discussion and diff. New entries must include that link; see
[CONTRIBUTING.md](CONTRIBUTING.md#updating-changelogmd).

## [Unreleased]

### Added

- `tools/inventory/compare.py`: a standard-library tool that compares the
  inventory `stellar-canary fixtures --format json` prints (CA-02,
  `inventoryVersion` 1) with a pack's `registry-v1.json`, asserting that the
  engine's loader discovered exactly the fixtures the registry lists, each
  with the same `surface` and `category`. It reports fixtures the engine did
  not discover, fixtures the registry does not list, and one entry per
  mismatched attribute; it exits `0` only when the inventories match, `1` when
  they differ, and `2` for an input it cannot compare (a missing or unreadable
  file, a document that is not UTF-8 or JSON, an unknown `inventoryVersion`,
  `fixtureFormat` or `registryVersion`, `directoryFound: false`, a
  `counts.total` that contradicts the fixture list, a duplicate fixture id, a
  registry that does not conform to `schemas/registry-v1.schema.json`, or an
  inventory and a registry for different protocols). The documented empty
  baseline (`protocol-29/registry-v1.json`, `fixtures: []`) is compared as a
  real empty inventory rather than refused, so a fixture the engine discovers
  but the registry does not list is reported as the difference it is.
  `--format json` prints one deterministic document for CI. Documented in
  `docs/tools.md`; the tests cover a match, every difference kind, both output
  formats, standard input, and each unusable-input path. Closes
  [issue #279](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/279).
  ([PR #467](https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/467))

- `tests/fixtures/rpc/`: one fixture per RPC method F-017 added
  (`get-health`, `get-version-info`, `get-fee-stats`), so the accepted
  vocabulary is exercised by a fixture and not only by a constant. The
  validator and schema already accepted the three names; what was missing was
  a fixture for each method and a test for the schema leg (the schema's
  `allOf`/`if`/`then` blocks are outside `jsonschema_lite`'s supported subset,
  so the RPC method enum is checked directly). `tests/test_validate.py` now
  validates the three files structurally, asserts each `method` is in the
  schema enum, and asserts the misspellings `get_health`, `getHealthy` and
  `get_fee_stats` are rejected with a diagnostic that lists the allowed
  names. Each fixture documents the answer shape captured live from
  `https://soroban-testnet.stellar.org` on 2026-10-22 and asserts only what
  `canary-rpc`'s typed models expose, by type where a value moves with the
  network. They live under `tests/fixtures/` rather than in a pack because
  every RPC fixture of a pack must be capturable by
  `tools/evidence/capture_live.py`, whose allowlist is exactly the three
  read-only methods CF-04 section 8 names. Closes
  [issue #280](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/280).
  ([PR #467](https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/467))

- Thirty-four `protocol-28/xdr/scval/` fixtures covering the scalar `ScVal`
  variants, which the pack previously had no evidence for: the primitives
  (`void`, `bool` true and false, `u32`, `i32`, `u64`, `i64`, `timepoint`,
  `duration`), the wide integers (`u128`, `i128`, `u256`, `i256` at their
  minimum, maximum and zero, plus a `u128` with the high bit set), and
  `bytes`, `string` and `symbol` at empty, small and — for `symbol` — the
  `SCSYMBOL_LIMIT` boundary of 32 bytes. Seven decode-failure fixtures complete
  the set: six truncations and a 33-byte symbol. Every payload was produced by
  the official `stellar-xdr` 28.0.1 crate (features `base64`, `alloc` —
  `rustc 1.99.1`, generated 2026-10-22 UTC) through a recorded construction
  expression, never hand-assembled, and the same program asserted that
  `from_xdr_base64` round-trips each valid value and rejects each invalid one
  (`failed to fill whole buffer` for the truncations, `xdr value max length
  exceeded` for the 33-byte symbol). The `u128` high-bit fixture is valid
  input and its header distinguishes it by ScValType discriminant from the
  bit-identical `i128` minimum; `u8` and `i8` are not ScVal variants and no
  fixture invents one. Every header cites `Stellar-contract.x` (plus
  `Stellar-types.x` where a typedef is involved) at `stellar/stellar-xdr`
  v28.0 (commit `9c9c145`) with file and line ranges, labels its bytes as
  synthetic structural values, and claims no network observation. All 34 pass
  `tools/validate/validate.py` and agree with `tests/scval_xdr.py` (decode and
  re-encode bit-for-bit; the seven invalid payloads rejected), and all 34 pass
  the engine offline (`stellar-canary 0.2.0`, `Protocol-Canary` commit
  `bc13306`): 27 round-trips byte-for-byte, 7 correctly rejected. The
  `protocol-28` pack's CF-04 structural records were regenerated, so
  `protocol-28/evidence/records/` holds one record per fixture. Closes
  [issue #360](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/360).
  ([PR #439])

- Fourteen `protocol-28/xdr/scval-composite/` fixtures covering the composite
  and address `ScVal` variants: `Vec` absent, present-but-empty, one element and
  three heterogeneous elements; `Map` empty, one entry, three entries, one
  level of map-in-vec nesting, and an encoding with non-ascending keys; and
  `Address` in both the account and contract arms. Three decode-failure
  fixtures complete the set: a vec whose count exceeds its data, a map cut
  after its key, and an address with an undefined `SCAddressType`. The vec and
  map fixtures pin the optional-pointer distinction (`SCVec *`/`SCMap *`), so
  an absent container and a present-but-empty one are shown to be different
  encodings. The non-ascending map records an observation: the pinned crate's
  `from_xdr_base64` accepted it and re-encoded it unchanged, and the engine
  passed it offline, so neither enforces ascending entry order on decode at
  these versions. Every payload was produced by the official `stellar-xdr`
  28.0.1 crate (features `base64`, `alloc` — `rustc 1.99.1`, generated
  2026-10-22 UTC) through a recorded construction expression, never
  hand-assembled; the three invalid payloads are documented mutations of
  crate-produced values that the same crate rejects (`failed to fill whole
  buffer` twice, `xdr value invalid` once). Address bytes are labelled
  synthetic structural values — 0x11-filled is not a real account key and
  0x22-filled is not a real contract id — and no fixture targets a depth limit
  (open #303). Every header cites `Stellar-contract.x` and `Stellar-types.x`
  at `stellar/stellar-xdr` v28.0 (commit `9c9c145`) with file and line ranges.
  All 14 pass `tools/validate/validate.py` and agree with `tests/scval_xdr.py`
  (11 roundtrips byte-for-byte, 3 rejected), and all 14 pass the engine offline
  (`stellar-canary 0.2.0`, `Protocol-Canary` commit `bc13306`). The pack's
  CF-04 structural records were regenerated, so `protocol-28/evidence/records/`
  holds one record per fixture. Closes
  [issue #361](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/361).
  ([PR #440])

- `docs/releasing.md`: comprehensive release guide detailing pre-release checks,
  build and verification commands with real outputs, tag naming and immutability rules,
  automated vs manual steps, post-release verification, and rollback procedures
  (issue #339). Linked from `README.md` and `CONTRIBUTING.md`. Closes
  [issue #339](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/339).
- `tools/validate/validate.py` and `schemas/fixture-v1.schema.json`: accept
  the lookup and paged RPC methods (`get-ledger-entries`, `get-transaction`,
  `get-ledgers`, `get-transactions`, `get-events`) alongside `get-network`
  and `get-latest-ledger`, and enforce `[request]` table validation according
  to CA-01-K. Closes
  [issue #326](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/326).

- Eleven `protocol-28/xdr/ledger-entry/` fixtures covering the ledger-entry arms
  that matter to the protocol: `ACCOUNT`, `TRUSTLINE`, `CONTRACT_DATA`,
  `CONTRACT_CODE` and `TTL`, each with a roundtrip and at least one
  decode-failure fixture (six in total: four end-of-structure truncations, a
  contract-code blob cut inside its length prefix, and a trustline whose
  `TrustLineAsset` discriminant is changed from `ASSET_TYPE_CREDIT_ALPHANUM4`
  to the undefined value 9). Every payload was produced by the official
  `stellar-xdr` 28.0.1 crate (features `base64`, `alloc` — `rustc 1.99.1`,
  generated 2026-10-22 UTC) through a recorded construction expression, never
  hand-assembled; the same program asserted that `from_xdr_base64` round-trips
  each valid entry and rejects each invalid one (`failed to fill whole buffer`
  for the five truncations, `xdr value invalid` for the undefined asset type).
  Every id, hash, key and balance is a synthetic structural value: the account
  ids, issuer, contract id, code hash and TTL key hash are fixed placeholders,
  the contract-code bytes are the four-byte WebAssembly magic used only to
  exercise the opaque path and are not a WASM module, `example.test` is a
  documentation domain, and no secret key appears anywhere. Each header cites
  `Stellar-ledger-entries.x` at `stellar/stellar-xdr` v28.0 (commit
  `9c9c145`) with file and line ranges, including the extension unions. The
  independent standard-library codec in `tests/xdr_codec.py` was extended with
  the five arms and checks all eleven fixtures (5 roundtrips byte-for-byte, 6
  rejected). All eleven pass `tools/validate/validate.py` and the engine
  offline (`stellar-canary 0.2.0`, `Protocol-Canary` commit `bc13306`): 5
  round-trips byte-for-byte, 6 correctly rejected. The pack's CF-04 structural
  records were regenerated, so `protocol-28/evidence/records/` holds one record
  per fixture (42). Closes
  [issue #363](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/363).
  ([PR #444])

- `tools/pack/archive_digests.py` and `.github/workflows/archive-baseline.yml`:
  a cross-platform baseline for the pack archive (issue #365). Every cell of
  the platform and Python-version matrix builds the `protocol-28` archive with a
  fixed version string and uploads the SHA-256 of the compressed `.tar.gz` and
  of the uncompressed tar stream, together with the Python and zlib versions
  that produced them; a final job compares the cells, fails when the
  uncompressed digests differ (naming the first differing byte and the tar
  member) and reports a compressed-digest difference as an observation only.
  The first measured run found that the Windows checkout rewrote the fixture
  files to CRLF, so the archive was not the same on every platform; `.gitattributes`
  now checks the hashed files out with `eol=lf` and the second run agrees in
  all nine cells. `docs/archive-reproducibility.md` records both runs and
  states that no cross-platform byte equality is claimed for the compressed
  archive. Closes
  [issue #365](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/365).
  ([PR #423])
- `tools/evidence/capture_live.py` and `.github/workflows/live-evidence.yml`: the
  scheduled read-only verification job (CF-04-E) that keeps the live RPC
  evidence fresh (issue #368). The script calls only the read-only methods
  CF-04 section 8 names (`getNetwork`, `getLatestLedger`, `getVersionInfo`)
  on an approved endpoint, with no credentials, and refuses any other method
  or endpoint before a request is made; a write call cannot be configured.
  Each call that really happened is saved as a capture in the same envelope
  the hand-taken corpus uses, and each RPC fixture gets a CF-04 verification
  record with `method: "live-read-only"`, the SHA-256 of the fixture file,
  `checkedAt` equal to the capture's `capturedAt`, and `observedProtocol`
  copied from the real `getNetwork` answer. A call that fails, times out or
  answers with something that is not a JSON-RPC result leaves no capture and
  no record, and the run fails. The workflow runs on a weekly cron and
  uploads the captures and the records as an artifact; the exact schedule,
  endpoints, storage and record location stay maintainer decisions, each in
  one place. `docs/live-verification.md` describes the schedule, the
  endpoints, the outputs and the failure behaviour. Closes
  [issue #368](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/368).
- `tools/evidence/record_structural.py`: writes CF-04 verification records for
  the structural check of a pack. The tool runs the check, then writes one
  record per fixture with the SHA-256 of the file as it is on disk, the
  instant the check ran and `method: "structural"`; it writes nothing when a
  fixture does not validate, never derives an instant from a date-only header
  comment and never records a live observation. The 23 records of the
  `protocol-28` pack are in `protocol-28/evidence/records/`,
  `docs/verification-records.md` states what they say and what they do not,
  and the validate workflow now checks them. Closes
  [issue #366](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/366).
  ([PR #424])
- Eight `protocol-28/xdr/transaction-envelope/` fixtures covering every arm of the
  `TransactionEnvelope` union, which the pack previously had no evidence for:
  `p28-xdr-transaction-envelope-v0-roundtrip` and
  `p28-xdr-transaction-envelope-v0-decode-failure` (the `ENVELOPE_TYPE_TX_V0` arm),
  `p28-xdr-transaction-envelope-v1-roundtrip` and
  `p28-xdr-transaction-envelope-v1-decode-failure` (the `ENVELOPE_TYPE_TX` arm),
  `p28-xdr-transaction-envelope-soroban-invoke-roundtrip` and
  `p28-xdr-transaction-envelope-soroban-invoke-decode-failure` (a v1 envelope whose single
  operation is `INVOKE_HOST_FUNCTION`) and
  `p28-xdr-transaction-envelope-fee-bump-roundtrip` and
  `p28-xdr-transaction-envelope-fee-bump-decode-failure` (the `ENVELOPE_TYPE_TX_FEE_BUMP`
  arm). Every payload was produced by the official `stellar-xdr` 28.0.1 crate
  (features `base64`, `alloc` — `rustc 1.99.1`, generated 2026-10-22 UTC) via a recorded
  construction expression, never hand-assembled; the four decode-failure payloads are
  documented mutations of those crate-produced values (three truncations — 150 of 212, 100 of
  244 and 130 of 328 bytes — and one envelope-type discriminant changed to an undefined
  value) that the same crate's `from_xdr_base64` rejects with `failed to fill whole buffer`
  or `xdr value invalid`. The source accounts, payment destinations, contract id, signature
  hints and signatures are labelled synthetic structural values in the headers, no secret
  key is used anywhere, no fixture claims a network observation or a submitted transaction,
  and each header cites `Stellar-transaction.x` (plus the ledger-entries, types and contract
  files) at `stellar/stellar-xdr` v28.0 (commit `9c9c145`) with file and line ranges. All
  eight pass the engine offline (`stellar-canary 0.2.0`, `Protocol-Canary` commit
  `bc13306`): the four roundtrips byte-for-byte, the four decode-failures because the
  engine rejects the value. Eight CF-04 structural verification records were added for
  the new fixtures with `tools/evidence/record_structural.py`, and the pack's records
  were regenerated, so `protocol-28/evidence/records/` holds one record per fixture
  (31). Closes
  [issue #362](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/362).
  ([PR #434])

- `tools/registry/diff.py`: Compares two fixture registries and reports which fixtures were
  added, removed or changed — the same id with a different file hash — so a pack release can
  be described from the registry data instead of by hand from `git log`. The output is three
  sorted lists keyed by fixture id — added, removed and changed — with the old and new file hash
  for a changed fixture, plus a separate list of fixtures that only moved, and the pack digest of
  each registry, in `text`, `json` or `markdown` (a CHANGELOG block) format.
  Both inputs are validated against `schemas/registry-v1.schema.json` before they are compared,
  and the rules a schema cannot express — a duplicate fixture id, an empty fixtures list — are
  checked too. Comparing registries of different protocols is refused unless
  `--allow-protocol-mismatch` is given. The exit code is 0 even when the registries differ, and
  2 for unusable input. `make registry-diff OLD=... NEW=...` runs it; `tests/test_registry_diff.py`
  covers the comparison, the validation rules, the command line and two registries generated from
  this repository's own pack at two different states. Closes
  [issue #338](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/338).

- `tools/common/pack_limits.py`: Shared pack extraction limits approved under decision
  D-06 (CF-02 section 7, CF-06 section 6: 2,000 files, 16 MiB total uncompressed, 1 MiB per file,
  path depth 8) shared between `validate.py`, `generate.py`, and `pack.py`. `tools/validate/validate.py`
  enforces all four limits with bounded reads (`read(limit + 1)`) and `stat()` bounds for pack
  members (CF-02 section 2), reporting violations with pack-relative paths and limits.
  `tools/registry/generate.py`'s depth check is aligned to count all path segments including the
  file name, matching the engine and `pack.py`. Closes
  [issue #369](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/369).
- `tools/scaffold/new_fixture.py`: Fixture scaffolding CLI tool that generates template fixtures
  with five required header sections and explicit `TODO` placeholders for missing evidence/results,
  intentionally failing `tools/validate/validate.py` until filled in. Closes
  [issue #353](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/353).
- `docs/tools.md`: Comprehensive documentation of the command-line behaviors, options, observed
  exit codes, and output streams for all repository tools (`pack.py`, `verify_archive.py`, `generate.py`,
  `manifest.py`, `badge.py`, `validate.py`, `schema_sync.py`), including an observations section for
  existing CLI inconsistencies tested in `tests/test_cli_contracts.py`. Closes
  [issue #351](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/351).
- `tests/xdr_codec.py`: Independent pure-Python RFC 4506 XDR codec for `StellarValue` (including
  basic, signed, and CAP-0083 empty-tx-set) and `ContractExecutable` (including wasm, stellar-asset,
  and CAP-0085 external-ref), citing `stellar/stellar-xdr` v28.0 (commit `9c9c145953e80990d6ff1ae3a6a973a0ce6d0694`).
  `tests/test_pack_xdr_independent.py` cross-checks all pack fixtures, ensuring roundtrip bit-identity
  and verifying structural decode failures. Closes
  [issue #348](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/348).

- `tools/validate/validate.py` validates Soroban `source_account` and
  `contract_id` with a standard-library-only strkey decoder (RFC 4648 unpadded base32,
  CRC16-XModem checksum, G.../C... version byte) and requires `function` to
  fit at most 32 UTF-8 bytes, matching the engine's transaction builder. Closes
  [issue #343](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/343).
- `tools/validate/validate.py` rejects hostile fixture input that crashes the
  validator with a traceback (issue #341): invalid UTF-8 bytes, extreme TOML nesting,
  and oversized integer literals are now reported as ordinary errors naming the file,
  exit 1, and no traceback; also every parsed integer outside the signed 64-bit range
  (-2^63..2^63-1) is rejected with the key path and magnitude (not the full digits).
- `tools/validate/validate.py` and `schemas/fixture-v1.schema.json` accept
  the `field-number-range` RPC assertion kind with `min` and/or `max` bounds
  (integers or finite floats, with `min <= max`), matching `canary-rpc`
  (read at Protocol-Canary commit `4418690`). `schema_sync.py` verifies the
  schema and validator remain in sync. Closes
  [issue #344](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/344).

- `tools/validate/check_changelog.py` and pull-request CI workflow job enforcing
  a CHANGELOG entry under `## [Unreleased]` for changes modifying fixtures
  (`protocol-*/`), schemas (`schemas/`), or tools (`tools/`) (rule [F-055]),
  with support for bypassing via the `no-changelog` PR label. Closes
  [issue #329](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/329).
- `tools/validate/validate.py` and `schemas/fixture-v1.schema.json` accept
  the `TransactionEnvelope` and `LedgerEntry` XDR type names, matching the
  five variants of `canary-xdr`'s `XdrTypeName` (read at Protocol-Canary
  commit `9b3fefcacde3de03b3cb34bfea4d47124ebc4d82`). `schema_sync.py` compares
  the validator's type set with the schema enum, and tests cover every XDR
  assertion kind for both new types plus a misspelled, lower-case and empty
  type name. Closes
  [issue #324](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/324).
  ([PR #381])
- `tools/validate/validate.py` validates each Soroban `[[args]]` entry
  instead of only checking that `args` is an array: the closed `kind`/`value`
  key set, all 18 supported kinds, the value type and range per kind (the
  full u128/i128/u256/i256 bounds included), hex or canonical padded base64
  for `bytes`, the 32-character `[A-Za-z0-9_]` symbol shape, a G.../C...
  strkey shape for `address` (secret seeds rejected, checksums left to the
  engine), and the eight-level `vec`/`map` nesting limit. The same structure
  is mirrored in `schemas/fixture-v1.schema.json` and checked by
  `schema_sync.py`; tests cover one valid and one invalid case per kind, the
  wide-integer bounds, over-deep nesting, and the issue's four negative
  cases. Closes
  [issue #325](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/325).
  ([PR #381])
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
  - `p28-rpc-latest-ledger` — Protocol 28 `getLatestLedger` identity check
    (a numeric `sequence`, `protocolVersion` 28, a string ledger `id`, and
    no `getNetwork`-only fields), verified live against
    `soroban-testnet.stellar.org` with `stellar-canary` 0.1.1.
    ([PR #236])
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
- `tools/validate/schema_sync.py`, a standard-library-only check that fails
  when `schemas/fixture-v1.schema.json`'s enums or required-field lists drift
  from `tools/validate/validate.py`'s constants, with coverage in
  `tests/test_validate.py`. `schemas/fixture-v1.schema.json` now also lists
  `source_reference` as required, matching the validator. ([PR #231])
- `tests/test_documentation_vocabulary.py`, which parses README.md's
  assertion-vocabulary table and CONTRIBUTING.md's per-surface field table and
  asserts they name exactly the RPC methods, assertion kinds and surfaces
  `tools/validate/validate.py` accepts — the documentation leg
  `schema_sync.py` does not cover, and the drift that issue #162 was about.
  ([PR #236])
- `tests/scval_xdr.py`, `tests/vectors/scval_parity/scval_parity.json` and
  `tests/test_scval_parity.py`: a standard-library-only XDR codec for the
  `ScVal` union, 36 golden vectors, and 29 tests asserting **bit-for-bit**
  roundtrip identity (not merely value equality). The vectors were derived
  field by field from `Stellar-contract.x` at `stellar/stellar-xdr` tag
  `v28.0` (commit `9c9c145`) independently of the codec, so the suite
  compares two derivations rather than checking a codec against its own
  output. Coverage spans integers (`u32`/`i32`/`u64`/`i64` and all four
  128/256-bit hi/lo forms), bytes, addresses (both `SCAddress` arms),
  vectors, maps and the remaining primitive variants; the five `ScVal`
  variants this repository has no use for are rejected on decode rather
  than silently skipped. Where the XDR text leaves strictness open the
  codec follows `stellar-xdr`'s generated `ReadXdr` implementations,
  because parity means agreeing with the reference implementation. Closes
  [issue #304](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/304).
  ([PR #308])
- Four `protocol-28/soroban/` fixtures asserting the failure side of the
  construct → `simulateTransaction` → result pipeline:
  `p28-soroban-sim-error-unknown-function` (`Error(Value, InvalidInput)`),
  `p28-soroban-sim-error-missing-contract` (`Error(Storage, MissingValue)`),
  `p28-soroban-sim-error-arg-count` (`Error(Context, UnexpectedSize)`) and
  `p28-soroban-sim-error-arg-type` (`Error(Value, UnexpectedType)`). Each
  `(type, code)` pair is a real `SCErrorType`/`SCErrorCode` member of
  `Stellar-contract.x` at `v28.0`, observed live against
  `soroban-testnet.stellar.org` on 2026-10-15 (UTC); only that stable form
  is pinned, never the host's diagnostic-event wording. The observations
  were bootstrapped by a `name()`/`decimals()` positive control that
  reproduced the values `p28-soroban-native-asset-name` records from
  2026-09-02, and the method is written up in `docs/protocol-28.md`.
  ([PR #308])
- `tests/test_sim_error_fixtures.py` (21 tests): derives the rendered
  host-error spellings from the `SCErrorType`/`SCErrorCode` enum names and
  checks every fixture's `message_contains` against them, so an invented
  error name cannot be committed; verifies the suite spans distinct codes
  and at least three host subsystems; pins the determinism rules (reserved
  or provably absent contracts only, the unfunded all-zero source account,
  no live-varying state); and covers the validator's `[expect]` rejections.
  ([PR #308])
- `tests/vectors/cf-02/` and `tests/test_cf02_vectors.py`: the shared
  conformance vectors for CF-02 (fixture registry and pack digest), which is
  CF-02-A — three packs (`minimal`, `standard`, `complex`) at three directory
  depths, each with its pack files' verified path/byte length/SHA-256 and
  resulting `packDigest` in `expected.json` plus the golden canonical registry
  manifest, and 57 tests that re-derive every hash and digest from the files on
  disk, check `tools/registry/generate.py` and `schemas/registry-v1.schema.json`
  against them, and cover the negative half of the contract (an altered space
  or CRLF, a reordered key, a reordered manifest array and a renamed file must
  each change what the contract accepts) together with the byte-versus-
  component path ordering that separates the two plausible implementations.
  The recorded values were computed with `sha256sum`/`wc -c`/`printf`, not with
  the generator, so the vectors define the contract instead of restating it.
  Closes
  [issue #286](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/286).
  ([PR #313])
- `tests/vectors/conformance/` and `tests/test_conformance_vectors.py`: the
  cross-language fixture parser conformance corpus (F-021) — 24 vectors, 12
  accepted and 12 rejected, covering the XDR, RPC and Soroban surfaces and
  indexed by `vectors.json`. Every rejected vector names an error code and a
  diagnostic fragment, and the harness requires the fragment to be both a
  prefix of that code's documented message and present in the validator's
  actual report, so a vector cannot claim an error class it does not produce;
  the rejected half covers missing required and conditional fields, wrong field
  types, an unknown key inside soroban's closed `[expect]` table, an
  unsupported RPC method, malformed TOML and a non-base64 payload, while the
  accepted half covers every assertion kind plus a 1 KiB inline payload and the
  validator's lower boundaries (`protocol = 1`, `sequence_number = 0`, empty
  `args`). The vectors assert fixture-format behavior only — the XDR bodies are
  deliberately placeholder values and nothing is executed or checked against a
  network — and the harness pins the corpus outside every `protocol-*/` scan
  root, so the fixture-count badge cannot move. Closes
  [issue #283](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/283).
  ([PR #315])

- `tools/validate/validate.py` validates verification evidence records
  (CF-04 section 3, `verificationVersion` 1): `validate_evidence(record)`
  and `--evidence PATH`, which takes a record file or a directory of
  `*.json` records. Missing or unknown fields, a hash that is not 64
  lowercase hex characters, a `checkedAt` that is not a UTC instant, a
  `live-*` record without `network` (name, passphrase and
  `observedProtocol`), `endpointHost` or `evidenceRef`, and a record that
  names a fixture that does not exist or whose hash is not the current
  file's, are errors. Nothing is scanned unless `--evidence` is given.
  ([PR #309])
- `tools/pack/pack.py` and `make pack VERSION=...`: the deterministic
  `protocolcanary-fixtures-VERSION.tar.gz` for a pack (CF-06 section 2):
  entries sorted in UTF-8 byte order, uid and gid 0 with empty names,
  mtime 0, mode 0644 for files and 0755 for directories, a gzip header
  with no name or time, the pack membership plus `registry.json`, and the
  D-06 limits (2,000 entries, 16 MiB, 1 MiB per file, depth 8). Building
  twice gives the same bytes. ([PR #309])
- `tools/release/manifest.py` and `schemas/release-manifest-v1.schema.json`:
  the release manifest for an archive (CF-06 section 3), with the archive
  hash, byte size, entry count, uncompressed size and `packDigest`
  recomputed from the archived files. Compatible engines are exact
  versions recorded as unverified. ([PR #309])
- `tools/pack/verify_archive.py`: extracts an archive under the CF-06
  section 6 safe-extraction rules into a temporary directory, checks the
  registry and pack digest, runs the validator over the contents and
  removes the directory on every path. Exit code 0 valid, 1 invalid, 2
  unreadable. ([PR #309])
- `tools/registry/generate.py`, the generator for a pack's `registry-v1.json`
  (CF-02-B): every fixture and referenced payload hashed with SHA-256 over
  the raw bytes, fixtures sorted by `id` and payloads by `path`, and the
  `packDigest`, validated against `schemas/registry-v1.schema.json` before it
  is written. An invalid pack (symbolic link, escaping payload, names that
  differ only by case) fails without writing anything. `make registry`
  writes `PACK/registry-v1.json`; the generated file is not committed yet
  (CF-02-E). Adds `tools/validate/jsonschema_lite.py`, a standard-library
  JSON Schema validator that rejects any keyword it does not implement.
  ([PR #306])
- `upstream-matrix.json` and `schemas/upstream-matrix.json`: a machine-readable
  map from Protocol 28 and 29 to the semver range of the Stellar Core,
  `soroban-rpc` and `rs-soroban-env` releases that belong to each. ([PR #306])
- `docs/upstream-matrix.md`, linked from the README: the Stellar Core, Stellar
  RPC, Stellar Horizon and Soroban host environment release and commit for
  Protocol 28 and 29 on Testnet and Mainnet, and the network passphrases,
  with `tests/test_upstream_matrix_docs.py` keeping the page and the matrix
  in agreement. ([PR #306])
- `tests/fixtures/capabilities.json`: the canonical `required_capabilities`
  vocabulary (the 5 approved capability strings, CF-07 section 9), pinned by
  `tests/test_validate.py` against `CAPABILITIES` in
  `tools/validate/validate.py` and the schema's enum, with a positive test
  for every approved capability and negative tests for unapproved strings
  (e.g. `fake-cap`). Engine-side parity is tracked in
  [Protocol-Canary#512](https://github.com/StellarCanary/Protocol-Canary/issues/512).
  <!-- TODO: switch to the PR link once this PR is opened. -->
  ([#288])
- `protocol-29/` baseline pack scaffold: `registry-v1.json` declaring
  `registryVersion: 1`, `protocol: 29` (integer) and the empty
  `fixtures: []` array, with `rpc/`, `xdr/` and `soroban/` subdirectories,
  and `tests/test_protocol29_baseline.py` asserting the manifest against
  `schemas/registry-v1.schema.json`, the canonical CF-02 section 3/5
  encoding and `packDigest`, and that the validator accepts the new
  directory without diagnostics. The empty baseline is a directory
  scaffold only, never reportable as compatibility coverage;
  `protocol-28/` is untouched.
  ([PR #318])

- Six `protocol-28/xdr/stellar-value/` fixtures covering the two
  previously untested `StellarValue.ext` arms,
  `STELLAR_VALUE_BASIC` and `STELLAR_VALUE_SIGNED`, so a decoder that
  handles only the CAP-0083 `STELLAR_VALUE_EMPTY_TX_SET` arm can no
  longer pass this pack: `p28-xdr-stellar-value-basic-roundtrip`,
  `p28-xdr-stellar-value-basic-decode-success` and
  `p28-xdr-stellar-value-basic-decode-failure`, plus
  `p28-xdr-stellar-value-signed-roundtrip`,
  `p28-xdr-stellar-value-signed-decode-success` and
  `p28-xdr-stellar-value-signed-decode-failure`. Every payload was
  produced by the official `stellar-xdr` 28.0.1 crate (features
  `base64`, `alloc` — `rustc 1.99.1`, generated 2026-10-19 UTC) via a
  recorded construction expression, never hand-assembled; the two
  decode-failure payloads are documented truncations of those
  crate-produced values that the same crate's `from_xdr_base64`
  rejects. The signed variant's node-id and signature bytes are
  labelled synthetic structural values in the headers; no key material
  that could be real is used, and nothing claims a network
  observation. Each header cites `Stellar-ledger.x`/`Stellar-types.x`
  at `stellar/stellar-xdr` v28.0 (commit `9c9c145`) with file and line
  ranges. Closes
  [issue #358](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/358).
  <!-- TODO: switch to the PR link once this PR is opened. -->
  ([#358])

- `protocol-29/evidence/testnet/`: read-only live Testnet evidence corpus
  (F-034, CF-04-H) — raw JSON-RPC captures of `getNetwork`,
  `getLatestLedger` and `getVersionInfo` taken 2026-10-18 UTC from
  `soroban-testnet.stellar.org` (all three report `protocolVersion` 29),
  stored as data only per CF-04 section 7, plus
  `tests/test_protocol29_evidence.py` enforcing the closed capture shape,
  RFC 3339 UTC instants, the endpoint allowlist, the read-only method
  guard and a no-credentials scan. The corpus establishes the evidence
  references required before any Protocol 29 fixture is authored.
  ([PR #319])

- Six `protocol-28/xdr/contract-executable/` fixtures covering the two
  previously untested `ContractExecutable` union variants,
  `CONTRACT_EXECUTABLE_WASM` and `CONTRACT_EXECUTABLE_STELLAR_ASSET`,
  so a decoder that handles only CAP-0085's
  `CONTRACT_EXECUTABLE_EXTERNAL_REF` case can no longer pass this pack:
  `p28-xdr-contract-executable-wasm-roundtrip`,
  `p28-xdr-contract-executable-wasm-decode-success`,
  `p28-xdr-contract-executable-wasm-decode-failure`,
  `p28-xdr-contract-executable-stellar-asset-roundtrip`,
  `p28-xdr-contract-executable-stellar-asset-decode-success` and
  `p28-xdr-contract-executable-stellar-asset-decode-failure`. Every
  payload was produced by the official `stellar-xdr` 28.0.1 crate
  (features `base64`, `alloc` — `rustc 1.99.1`, generated 2026-10-20
  UTC) via a recorded one-line construction expression, never
  hand-assembled; the two decode-failure payloads are documented
  truncations of those crate-produced values (24 of 36 bytes and 3 of 4
  bytes) that the same crate's `from_xdr_base64` rejects with
  `failed to fill whole buffer`. The Wasm hash and the bare-discriminant
  asset value are labelled synthetic structural values in the headers,
  no fixture claims a network observation, and each header cites
  `Stellar-contract.x` at `stellar/stellar-xdr` v28.0 (commit
  `9c9c145`) with file and line ranges. Closes
  [issue #357](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/357).
  <!-- TODO: switch to the PR link once this PR is opened. -->
  ([#357])

- `tools/coverage/report.py`: a standard-library-only fixture-coverage
  report. It imports `tools/validate/validate.py`'s own capability
  constants and loader (never duplicates them) and prints, per surface,
  RPC method, XDR type and XDR kind, RPC assertion kind and Soroban
  expectation kind, plus a per-`cap-<4-digit>` section, how many fixtures
  use it — an explicit `0` marked `no fixture` where none does — with
  fixtures the validator rejects counted separately as `invalid`.
  `--format json` emits the same data as one sorted JSON document;
  output is deterministic (sorted keys, no timestamps, no absolute
  paths), the tool only ever reads, and it exits non-zero with a clear
  message for a missing pack directory. `tests/test_coverage_report.py`
  covers synthetic packs built in temporary directories, the real
  `protocol-28` pack against an independent glob-and-parse, and that a
  capability constant added to the validator appears in the report
  automatically. Closes
  [issue #354](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/354).
  <!-- TODO: switch to the PR link once this PR is opened. -->
  ([#354])

- `tools/validate/portable_names.py`: one shared Windows-portable path rule
  for fixture packs, called by `tools/validate/validate.py`,
  `tools/registry/generate.py` and `tools/pack/verify_archive.py` so the three
  tools cannot disagree. It rejects reserved device names (`CON`, `PRN`,
  `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`) in any letter case and with any
  extension, segments ending in a dot or a space, and the characters
  `<`, `>`, `:`, `"`, `|`, `?` and `*`. A pack containing `con.toml`,
  `aux.v2.toml`, `NUL` or `bad./fixture.toml` now fails at validation,
  registry-generation and archive-verification time instead of failing later
  on a Windows checkout. Closes
  [issue #323](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/323).
  ([PR #380])
- Fixture-text scanning in `tools/validate/validate.py`: fixture TOML files,
  and verification evidence JSON files read through `--evidence`, now reject
  bidirectional override and isolate characters, zero-width and other `Cf`
  format characters, a byte order mark outside the first character, and `Cc`
  control characters other than tab, line feed and carriage return. The
  diagnostic names the file, 1-based line, 1-based column and code point in
  `U+XXXX` form; the validator reports and never rewrites the file. Tab, LF,
  CR, accented letters and CJK text remain valid. Closes
  [issue #322](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/322).
  ([PR #380])


### Changed

- Hardened contributor and release tooling across four paths: fixture scaffolds
  now use exclusive creation with failure cleanup; live RPC capture enforces a
  total response deadline; unsupported schema regexes produce location-aware
  `SchemaError`s; and registry, evidence, archive and release readers reject
  duplicate keys, excessive JSON nesting and oversized integers through their
  existing error paths. Added focused regression coverage without changing
  fixture data or adding dependencies. Closes issues #457, #456, #455 and #454.
  ([PR #459](https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/459))

- `tools/validate/validate.py` now rejects `expected_base64` on an XDR fixture whose
  `kind` is not `encode-equals`. The field states the expected encoding, and only an
  `encode-equals` fixture has one: `canary-xdr`'s loader accepts "kind", "type" and
  "value_base64" for every other kind and rejects the whole fixture when it finds
  another key, so a fixture that carried the field with, say, `kind = "roundtrip"` passed
  this validator and was refused by the engine. The validator now reports `field
  'expected_base64' is only allowed for kind 'encode-equals', not 'roundtrip'` at the
  line of the key, once per file, and a fixture whose `kind` is missing, not a string or
  not a supported kind reports only the kind error. The `encode-equals` behaviour is
  unchanged: the field is required there, must not be empty and must be valid base64.
  `schemas/fixture-v1.schema.json` is unchanged, because this is a loader-side rule the
  schema cannot express — like the other rules the validator enforces — and
  `tools/validate/schema_sync.py` reports no drift. Closes
  [issue #398](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/398).
  ([PR #433])
- `tools/validate/validate.py` now rejects a verification record whose `checkedAt` is in
  the future. The instant was checked for being a real RFC 3339 UTC value, but never
  compared with the clock, so a record dated 2099 was accepted and — because the
  freshness states of CF-04 section 4 are derived from `checkedAt` — would look
  "verified" for 73 years, and a record dated tomorrow could never go stale on
  schedule. `validate_evidence()` and `validate_evidence_file()` take an optional
  timezone-aware `now`; when it is not given, the current time is read once per run and
  the same instant is used for every record, so one run cannot judge two records
  against two clocks. A record may be up to five minutes ahead of the validator's
  clock, the documented tolerance for skew between the verifier's machine and the
  validator's. A malformed `checkedAt` still produces only the existing format
  message, and `capturedAt` in the Protocol 29 captures is unchanged. Closes
  [issue #397](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/397).
  ([PR #432])
- `tools/coverage/report.py --validator PATH` now reports a validator copy it cannot
  use as one error line naming the path and the reason, and exits 1, instead of
  dying with an internal `AssertionError` traceback. A file that is not Python, a
  file with a syntax error, a module that raises while it is executed, and a module
  that lacks the attributes and capability constants the report reads are all
  rejected this way; a valid copy and the default behaviour are unchanged, and the
  text and `--format json` reports of a normal run are byte-identical to before.
  Closes
  [issue #393](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/393).
  ([PR #431])

- `tools/pack/verify_archive.py --manifest` now checks the facts the manifest states about
  the archive, and not only its archive hash and pack digest. The file name, the size, the
  entry count, the uncompressed bytes, the version in the file name, the pack name, the
  manifest version, and the protocols and the registry version of the archived
  `registry.json` are compared with the archive itself; every difference is reported, with
  the field, the value the manifest states and the value the archive gives, and the tool
  exits 1. The entries and the uncompressed bytes are counted by the code that writes the
  manifest, so the two tools cannot disagree about them. `revision` and
  `compatibleEngines` are not compared: they cannot be derived from the archive. Closes
  [issue #416](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/416).

- `tools/validate/validate.py` and `schemas/fixture-v1.schema.json` now
  reject a soroban `[expect]` table containing a key other than `kind` or
  `message_contains`, a non-string `message_contains`, and an empty one.
  This closes a real divergence rather than adding a new rule:
  `canary-soroban` calls `unknown_body_keys(expect, ["kind",
  "message_contains"])` and reads the needle with
  `.and_then(toml::Value::as_str)`, so an unknown key is a loader error and
  a non-string is **silently dropped** — degrading the fixture to "the
  simulation failed" while it still looks like it pins a message. An empty
  needle matches every message for the same reason. The field remains
  genuinely optional, matching the loader's `Option<String>`;
  `test_message_contains_is_optional` pins that so it is not "fixed" into a
  divergence later. ([PR #308])
- `source_reference` must now be a CAP identifier (`CAP-0083`) or an absolute
  `https://` URL, and a `github.com` or `raw.githubusercontent.com` link must
  name a full commit SHA or a release tag, not a branch. Free text, relative
  links, `http://` and URLs with credentials are rejected, with a message
  that says what to change. The same pattern is in
  `schemas/fixture-v1.schema.json`, and `schema_sync.py` fails when the two
  differ. The four CAP-0083 and CAP-0085 fixtures that cited
  `.../blob/master/...` now cite commit `9cd7030`, whose files are identical;
  no fixture ID or expected value changed. ([PR #306])
- The structural validator now rejects an empty-string `description`,
  matching `schemas/fixture-v1.schema.json`'s `minLength: 1` and the
  existing `id`/`category` checks; a regression test covers the case.
  ([PR #232])
- Documented that `protocol` is intentionally unbounded above: a code
  comment in `tools/validate/validate.py` and a new "Protocol version
  range" subsection in `CONTRIBUTING.md` state that a stray or typo'd value
  is expected to be caught by pack-level tests rather than by structural
  validation. ([PR #232])
- `schemas/fixture-v1.schema.json`'s RPC `assert.value` property gained a
  description explaining that its type is intentionally unconstrained but
  must match the JSON type the targeted RPC field actually returns.
  ([PR #232])
- README.md's Validation section now distinguishes the structural
  conformance CI re-checks on every run from the point-in-time live-network
  verification recorded in fixture header comments and `docs/protocol-28.md`.
  ([PR #232])
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
- `.github/PULL_REQUEST_TEMPLATE.md`'s "New or changed fixture(s)?" section
  now links directly to `CONTRIBUTING.md`'s "Adding a fixture" checklist
  alongside the README's Provenance reference, so PR authors are pointed at
  the fuller step-by-step walkthrough (source, determinism, ID stability)
  that the template's review questions map to. ([PR #219])
- README.md's fixture-format section states which RPC methods the `rpc`
  surface currently supports (`get-network` and `get-latest-ledger`) and
  links `CONTRIBUTING.md` for adding a new one. ([PR #231])
- `CONTRIBUTING.md`'s fixture-schema section documents that `--protocol`
  filtering skips, rather than fails, fixtures whose `protocol` does not
  match, cross-referencing `schemas/fixture-v1.schema.json`, and describes
  the schema/validator sync enforcement added above. ([PR #231])
- `docs/protocol-28.md` records why an RPC fixture can only assert fields
  `canary-rpc` exposes to assertions: each response is serialized into its
  typed model (`NetworkInfo`, `LatestLedger`) before asserts run, so
  `getLatestLedger`'s raw `closeTime`/`headerXdr`/`metadataXdr` are not
  observable, and a `field-absent` assertion is meaningful only for a field
  the other method would report. ([PR #236])
- `.github/PULL_REQUEST_TEMPLATE.md`'s "Tests performed" checklist now
  includes `python3 tools/badge/badge.py --check`, the CI step that fails a
  fixture PR whose badge was not regenerated. ([PR #236])
- `tests/test_validate.py`'s invalid-RPC-method test now asserts the
  rejection message quotes the rejected method and enumerates the accepted
  ones, for both `get-balance` and `getTransactions`, instead of only
  checking that some error mentioned `method`. ([PR #236])
- `schemas/fixture-v1.schema.json`'s `category` description now states that
  `tools/validate/validate.py` rejects the vague values `misc`, `other`,
  `test` and `general` as errors, in any letter case, instead of only
  advising against them; a new test pins the mixed-case rejection.
  ([PR #252])
- `tools/validate/validate.py` and `schemas/fixture-v1.schema.json` now
  reject unknown keys in a fixture (F-031): an undeclared top-level field
  (a typo such as `descriptoin`), a key that belongs to another surface,
  and a misspelled key inside an `[[assert]]` table are errors, with the
  diagnostic naming the offending key. The schema sets
  `additionalProperties: false` on every object and declares the union of
  the common fields and all surface keys at the top level so the closure
  does not reject valid fixtures. The test that pinned the previous
  permissive behavior and `CONTRIBUTING.md`'s "Unknown top-level fields"
  section were updated to match.
  ([PR #316])

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
- **Soroban simulation `auth` and resource-estimation assertions are not
  covered.** [Issue #300](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/300)
  (F-043) asks for fixtures asserting on the `auth` array a
  `simulateTransaction` response carries, and
  [issue #301](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/301)
  (F-044) for fixtures asserting on `minResourceFee`/`transactionData`.
  Neither is expressible in the fixture contract this repository mirrors:
  read against `StellarCanary/Protocol-Canary` at `2a88756`,
  `SimulationResponse` has no `auth` field at all, `SorobanAssertion` has
  exactly two variants (`SimulationSuccess`, `SimulationError`) and rejects
  any other `expect.kind` or any extra `[expect]` key, and
  `min_resource_fee`/`transaction_data` are deserialized but read by no
  production code. Extending this repository's schema anyway would invert
  CONTRIBUTING.md's ownership rule — the schema mirrors the loader, never
  leads — and would break every consumer, because `canary-runner`'s
  scheduler calls `SorobanFixture::from_loaded` with `?`, so one unparseable
  fixture aborts the whole run as exit 4 rather than being skipped.
  `required_capabilities` cannot gate it either: `Capability` is a closed
  five-member enum with no member meaning auth or resource estimation. The
  gap closes once upstream
  [#517](https://github.com/StellarCanary/Protocol-Canary/issues/517)
  (E-119, open) and an equivalent resource-estimation assertion land and
  are released. See `docs/protocol-28.md`, "Soroban simulation auth and
  resource estimation". ([PR #308])
- **Contract panics and contract-defined error codes are not covered by the
  simulation-error suite.** `SCErrorType`'s tenth member, `SCE_CONTRACT`,
  carries a user-defined `uint32` rather than an `SCErrorCode`, and a WASM
  trap produces `Error(WasmVm, …)` from code this repository does not ship;
  reaching either needs a deployed contract, which "What never belongs in a
  fixture" rules out. `test_no_fixture_claims_a_contract_defined_error`
  guards the gap so it cannot be closed by fabrication. ([PR #308])
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
     without a pull request; PR #97, PR #143, PR #176, PR #219, PR #231,
     PR #232, PR #236, PR #252, PR #306, PR #308, PR #309, PR #313, PR #315,
     PR #380 and PR #381 are the [Unreleased] entries that originated from
     pull requests. -->

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
[PR #219]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/219
[PR #231]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/231
[PR #232]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/232
[PR #236]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/236
[PR #252]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/252
[PR #306]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/306
[PR #308]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/308
[PR #309]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/309
[PR #313]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/313
[PR #315]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/315
[PR #316]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/316
[PR #318]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/318
[PR #319]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/319
[#358]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/358
[#357]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/357
[#354]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/354
[PR #380]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/380
[PR #381]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/381
[PR #423]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/423
[PR #424]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/424
[PR #433]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/433
[PR #432]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/432
[PR #431]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/431
[PR #444]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/444
[PR #440]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/440
[PR #439]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/439
[PR #469]: https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/469
