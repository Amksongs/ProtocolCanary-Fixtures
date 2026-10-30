# Protocol 27

Protocol 27 ("Zipper") is implemented by Stellar Core 27.x, Stellar RPC
27.x, Soroban host 27.x, and the corresponding `stellar-xdr` and
`soroban-sdk` releases. This pack is intentionally empty.

The Protocol 27 changes this repository would test, if they were verified,
are the two Core Advancement Proposals that introduce Protocol-version-
specific Soroban authorization behavior:

- [CAP-0071-01](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0071-01.md)
  — Authentication delegation for custom (smart-contract) accounts, including
  the `SOROBAN_CREDENTIALS_ADDRESS_WITH_DELEGATES` credential type and the
  `ENVELOPE_TYPE_SOROBAN_AUTHORIZATION_WITH_ADDRESS` signature envelope.
- [CAP-0071-02](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0071-02.md)
  — `SOROBAN_CREDENTIALS_ADDRESS_V2`, an address-bound credential type that
  uses the same new envelope payload to close a narrow cross-account replay
  window.

Both are described in the
[Stellar Zipper, Protocol 27 Upgrade Guide](https://stellar.org/blog/foundation-news/stellar-zipper-protocol-27-upgrade-guide).

Per [this repository's contribution policy](../CONTRIBUTING.md), a protocol
pack is populated only after its fixture inventory has been independently
verified against authoritative upstream sources — CAP text, upstream XDR, or
official release notes — for that specific protocol version. No placeholder or
dummy fixtures are added merely to fill this directory.

Together, CAP-0071-01 and CAP-0071-02 are the protocol-version-specific
Soroban authorization changes in Protocol 27. They are **authorization
semantics, not new top-level XDR types**: they change the shape of existing
`SorobanCredentials` / `SorobanAuthorizationEntry` payloads rather than
adding a new union arm at the `ScAddress` or `StellarValue` level. As of
this pack's release, the repository has **not** verified this behavior with
the same evidence standard required to add a fixture (authoritative source
actually checked, deterministic input, typed assertion), so this directory
remains intentionally empty.

## Why this pack is empty

Per `CONTRIBUTING.md`, a fixture is accepted only when a reviewer can answer
all five provenance questions from the fixture file and its header comment
alone. For Protocol 27 that means:

1. **A concrete input exists and is known authoritative.** For CAP-0071-01 /
   CAP-0071-02 this would be a well-formed `SorobanCredentials` encoding
   (or a full transaction containing one) whose bytes were derived from the
   official `stellar-xdr` / `stellar-base` crate or the official CLI, not
   assembled by hand. Producing that is possible; the repository has not yet
   done it for Protocol 27.
2. **The surface that can observe it is clear.** CAP-0071-01/02 is not an XDR union change like CAP-0083/CAP-0085; the Soroban credential-shape surface that could observe it in Protocol 27 has not been authored or verified in this repository yet, so there is no confirmed observation path for this pack.
3. **The expected result is pinned to an upstream source.** The credential
   type names and envelope type are pinned to the CAP text and the Stellar
   Foundation upgrade guide, but the exact wire representation and the exact
   host-function behavior for a specific Protocol 27 host version have not
   been independently reproduced here.

Until those are done against an authoritative source, this directory stays
empty rather than shipping placeholder fixtures.

## Relationship to `protocol-28/`

`protocol-28/` (CAP-0083, CAP-0085, CAP-0086) is the canonical, verified
pack in this repository. Protocol 28 was chosen first because its changes
include two new top-level XDR types (`StellarValue::STELLAR_VALUE_EMPTY_TX_SET`
and `ContractExecutable::CONTRACT_EXECUTABLE_EXTERNAL_REF`) that are directly
observable through the XDR surface that `Protocol-Canary`'s `canary-xdr` crate
already supports, plus a live RPC identity check and a Soroban simulation smoke
test that were straightforward to verify live against testnet.

Protocol 27's changes are more authorization-semantics-heavy and less amenable
to a pure XDR round-trip assertion without additional upstream verification
work. When that work is done, this README will be replaced with a populated
pack and a corresponding `docs/protocol-27.md`.
