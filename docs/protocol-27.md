# Protocol 27

Protocol 27 ("Zipper") is implemented by Stellar Core 27.x, Stellar RPC
27.x, Soroban host 27.x, and the corresponding `stellar-xdr` and
`soroban-sdk` releases. Its Protocol-version-specific changes are two
Soroban authorization CAPs:

```text
Protocol 27
    |
    ├── CAP-0071-01  (authentication delegation for custom accounts)
    └── CAP-0071-02  (address-bound SOROBAN_CREDENTIALS_ADDRESS_V2)
```

Both are described in the
[Stellar Zipper, Protocol 27 Upgrade Guide](https://stellar.org/blog/foundation-news/stellar-zipper-protocol-27-upgrade-guide).

## CAP-0071-01: authentication delegation for custom accounts

**What changed.**
[CAP-0071-01](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0071-01.md)
makes delegation of authentication from a custom (smart-contract) account to
another address a first-class protocol feature. It adds two host functions —
`delegate_account_auth` and `get_delegated_signers_for_current_auth_check` —
and a new credential type,
`SOROBAN_CREDENTIALS_ADDRESS_WITH_DELEGATES`, whose signature payload uses the
new `ENVELOPE_TYPE_SOROBAN_AUTHORIZATION_WITH_ADDRESS` envelope that explicitly
binds the payload to the top-level account address.

**What this pack tests.** Nothing, yet. This is a deliberate, documented gap,
not an oversight.

**Why there is no fixture.**
CAP-0071-01 is authorization semantics, not a new top-level XDR type. Testing
it for real requires either:

- a well-formed `SorobanCredentials` / `SorobanAuthorizationEntry` encoding
  whose bytes were derived from an authoritative source (the official
  `stellar-xdr` / `stellar-base` crate or the official CLI) and observed
  through the RPC surface or a live simulation, **or**
- a Soroban simulation that exercises `__check_auth` delegation end-to-end.

As of this pack's release that work has not been done in this repository. This
repository does not add a fixture that merely asserts a credential type name or
a host-function existence from the CAP text — that would be the kind of
unverified claim the no-fabrication rule in `CONTRIBUTING.md` exists to
prevent.

This gap closes once someone does that verification against an authoritative
source and wires it through a supported surface.

**Source.**
[CAP-0071-01](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0071-01.md)
and the
[Stellar Zipper, Protocol 27 Upgrade Guide](https://stellar.org/blog/foundation-news/stellar-zipper-protocol-27-upgrade-guide).

## CAP-0071-02: address-bound Soroban credentials (V2)

**What changed.**
[CAP-0071-02](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0071-02.md)
adds `SOROBAN_CREDENTIALS_ADDRESS_V2`, a credential type that uses the same
`ENVELOPE_TYPE_SOROBAN_AUTHORIZATION_WITH_ADDRESS` payload introduced in
CAP-0071-01. Unlike the existing `SOROBAN_CREDENTIALS_ADDRESS`, the V2 payload
explicitly includes the signer's address, closing a narrow cross-account replay
window that required both shared private keys across accounts and an invocation
payload that does not otherwise bind the signer address.

**What this pack tests.** Nothing, yet. Same reason as CAP-0071-01: this is
authorization-semantics behavior, and no fixture in this repository has yet
been verified against an authoritative source for Protocol 27.

**Why there is no fixture.** The existing `SOROBAN_CREDENTIALS_ADDRESS` type
remains valid until Protocol 28; the V2 type is an alternative, not a new wire
union arm at the XDR level. Asserting its correctness requires a concrete,
authoritatively-derived credential encoding and a surface that can observe it —
exactly what this pack does not yet have.

**Source.**
[CAP-0071-02](https://github.com/stellar/stellar-protocol/blob/master/core/cap-0071-02.md)
and the
[Stellar Zipper, Protocol 27 Upgrade Guide](https://stellar.org/blog/foundation-news/stellar-zipper-protocol-27-upgrade-guide).

## What this pack does not cover, generally

- **Any live-network assertion.** Every fixture in this repository that makes a
  live-network claim records exactly when and against which endpoint it was
  verified in its header comment. This pack has none yet, so it makes none.
- **Any XDR round-trip for these CAPs.** CAP-0071-01/02 do not add new
  top-level XDR types the way CAP-0083 and CAP-0085 do; they change the shape
  of existing Soroban credential/authorization payloads. That is a subtler
  observation problem, and this repository has not verified it yet for Protocol
  27.

## Relationship to `protocol-28/`

`protocol-28/` is the canonical, verified pack in this repository. Protocol 28
was verified first because its changes include two new top-level XDR types that
are directly observable through the XDR surface `Protocol-Canary`'s `canary-xdr`
crate already supports, plus a live RPC identity check and a Soroban simulation
smoke test that were straightforward to verify live against testnet.

Protocol 27's changes are more authorization-semantics-heavy and less amenable
to a pure XDR round-trip assertion without additional upstream verification work.
When that work is done against an authoritative source, this document will be
replaced with a populated pack and a corresponding fixture inventory.
