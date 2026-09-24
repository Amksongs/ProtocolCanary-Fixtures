# ProtocolCanary-Fixtures

![ProtocolCanary-Fixtures](assets/ProtocolCanary-Fixtures-banner.svg)

[![Validate](https://github.com/StellarCanary/ProtocolCanary-Fixtures/actions/workflows/validate.yml/badge.svg)](https://github.com/StellarCanary/ProtocolCanary-Fixtures/actions/workflows/validate.yml) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Canonical compatibility fixtures for Stellar Protocol Canary.

[Documentation](https://stellarcanary.github.io/Protocol-Canary/) | [Protocol-Canary](https://github.com/StellarCanary/Protocol-Canary) | [Action](https://github.com/StellarCanary/ProtocolCanary-Action)

## Quick start

The validator requires **Python 3.11 or newer** — it imports `tomllib`,
which only became part of the standard library in Python 3.11. On an
older interpreter it fails immediately with
`ModuleNotFoundError: No module named 'tomllib'`. Nothing else needs to
be installed.

```bash
python3 tools/validate/validate.py    # structural fixture validation
python3 -m unittest discover tests    # repository test suite
```

See [Validation](#validation) below (and
[`CONTRIBUTING.md`](CONTRIBUTING.md#development-setup)) for details,
including the equivalent `make` targets.

## Purpose

This repository answers one question: **what exact Stellar protocol
behavior should Protocol Canary test?**

```text
Protocol specification / upstream implementation
                    |
                    v
            Canonical fixture
                    |
                    v
       ProtocolCanary-Fixtures   <- this repository
                    |
                    v
            Protocol-Canary
                    |
                    v
          Compatibility Result
```
[Protocol specification / upstream implementation](https://github.com/StellarCanary/Protocol-Canary)
[Canonical fixture / ProtocolCanary-Fixtures](https://github.com/StellarCanary/ProtocolCanary-Fixtures)
[Protocol-Canary](https://github.com/StellarCanary/Protocol-Canary)
[Compatibility Result](https://github.com/StellarCanary/Protocol-Canary)
`ProtocolCanary-Fixtures` defines **what** should be tested. The
[`StellarCanary/Protocol-Canary`](https://github.com/StellarCanary/Protocol-Canary)
CLI defines **how** the test is executed.
[`StellarCanary/ProtocolCanary-Action`](https://github.com/StellarCanary/ProtocolCanary-Action)
runs that CLI against this repository's fixtures in GitHub CI. This
repository contains no business logic, no server, no database, and no
executable fixture code — it is a versioned corpus of declarative test
data.

## Repository relationship

`Protocol-Canary` loads fixtures with `canary_fixtures::load_directory`,
exposed via:

```bash
stellar-canary check --fixtures-dir <path-to-a-checkout-of-this-repo> --json
```

The loader recursively walks the given directory and parses **every**
`*.toml` file as one fixture — see
[`docs/fixture-contract.md`](https://github.com/StellarCanary/Protocol-Canary/blob/main/docs/fixture-contract.md)
in `Protocol-Canary` for the authoritative, implementation-verified contract
this repository conforms to. Two consequences that shape this repository's
layout:

- **No `manifest.toml` files.** The loader treats every `.toml` file under
  the given directory as a fixture; a separate discovery/enumeration file
  would either be silently ignored (harmless) or, if named `*.toml`, would
  be mis-parsed as a malformed fixture and fail the whole run. Each
  protocol pack instead has a plain `README.md` (ignored by the loader,
  read by humans).
- **Directory names are cosmetic.** `xdr/`, `rpc/`, `soroban/`, `cap-0083/`
  etc. exist for human navigation only; a fixture's `surface`, `protocol`,
  and `category` fields — not its file path — are what the loader and the
  planner act on.

You can point `--fixtures-dir` at this repository's root, or at a single
`protocol-NN/` directory to scope one pack; the loader's protocol filtering
makes a mixed-protocol directory safe either way.

## Protocol packs

| Pack | Status | Notes |
|---|---|---|
| [`protocol-28/`](protocol-28/) | Active | CAP-0083, CAP-0085 (XDR); Protocol 28 RPC identity; a Soroban simulation smoke fixture. Fixture counts by surface: **4 xdr, 1 rpc, 1 soroban** (6 total). See [`docs/protocol-28.md`](docs/protocol-28.md). |
| [`protocol-27/`](protocol-27/) | Not yet populated | **0 fixtures.** See [`protocol-27/README.md`](protocol-27/README.md) — fixtures are added only after their upstream behavior is independently verified, never as placeholders. |

## Fixture format

Every fixture is one TOML file with common metadata plus a surface-specific
body:

```toml
id = "p28-xdr-cap83-empty-tx-set"     # required, unique across the tree
protocol = 28                          # required
surface = "xdr"                        # required: "xdr" | "rpc" | "soroban"
category = "cap-0083"                  # required, free-text
description = "..."                    # required
source_reference = "CAP-0083"          # optional, should be authoritative

# surface-specific fields follow — see docs/protocol-28.md and
# Protocol-Canary's docs/fixture-contract.md for the exact per-surface
# schema (xdr: type/kind/value_base64; rpc: method/[[assert]]; soroban:
# source_account/contract_id/function/[expect]).
```

### Assertion vocabulary

Each surface states its expected result through a small set of `kind`
values. These are the only values consumers accept — anything else fails
at fixture parse time, before any check runs. An XDR fixture carries a
single top-level `kind`; an RPC fixture carries one or more `[[assert]]`
tables, all of which must pass; a Soroban fixture carries one `[expect]`
table.

| Surface | Field | Value | Asserts that… |
|---|---|---|---|
| `xdr` | `kind` | `decode-success` | `value_base64` decodes successfully as the named `type`. |
| `xdr` | `kind` | `decode-failure` | `value_base64` is rejected when decoded as the named `type` — malformed input must fail, never silently decode. |
| `xdr` | `kind` | `roundtrip` | Decoding `value_base64` and re-encoding it reproduces the same bytes. |
| `xdr` | `kind` | `encode-equals` | Decoding `value_base64` and re-encoding it produces exactly `expected_base64` (used when testing canonicalization). |
| `rpc` | `[[assert]].kind` | `field-exists` | The method's response contains the named `field`. |
| `rpc` | `[[assert]].kind` | `field-absent` | The response does not contain the named `field`. |
| `rpc` | `[[assert]].kind` | `field-equals` | The named `field` equals `value` exactly. |
| `rpc` | `[[assert]].kind` | `field-type` | The named `field` has the JSON type named by `expected_type`. |
| `soroban` | `[expect].kind` | `simulation-success` | `simulateTransaction` succeeds with no error. |
| `soroban` | `[expect].kind` | `simulation-error` | `simulateTransaction` fails — optionally requiring `message_contains` to appear in the error message. |

The full per-surface field list (including the non-`kind` fields each
value requires, such as `value_base64` or `expected_type`) is in
[`CONTRIBUTING.md`](CONTRIBUTING.md#fixture-schema); the authoritative
schema is `Protocol-Canary`'s
[`docs/fixture-contract.md`](https://github.com/StellarCanary/Protocol-Canary/blob/main/docs/fixture-contract.md).

Fixtures are declarative data, never code: no fixture field is interpreted
as a shell command, script, or executable instruction of any kind.

## Provenance

Every protocol-specific fixture cites a `source_reference` — a CAP number,
an upstream XDR definition, or an official release/API reference — and
carries a header comment explaining what was verified, how, and (for
anything involving a live network call) when and against which endpoint.
No fixture asserts a value that isn't traceable to an authoritative
upstream source; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Validation

Requires **Python 3.11+** (the validator uses the stdlib `tomllib`
module, unavailable before 3.11); CI pins `3.11.16`.

```bash
python3 tools/validate/validate.py
```

Validates schema conformance, unique IDs, protocol/surface enums, source
references, and referenced-file existence for every fixture in the repo.
This is structural validation only — it never executes a compatibility
check itself. CI (`.github/workflows/validate.yml`) runs it, plus
`python3 -m unittest discover tests`, on every push and pull request.

The same two commands are also available as Makefile targets, so you can
run exactly what CI runs without typing the commands out:

| Command | What it does |
|---|---|
| `make validate` | Structural fixture validation only. |
| `make test` | Repository test suite only. |
| `make check` | Both of the above, in CI's order — the same two steps as `.github/workflows/validate.yml`, stopping at the first failure. |

`make check` is the quickest way to confirm a contribution passes CI
before you push; each target runs from the repository root and exits
non-zero on the first failure, just like CI's steps do.

The same two commands are also available as Makefile targets, so you can
run exactly what CI runs without typing the commands out:

| Command | What it does |
|---|---|
| `make validate` | Structural fixture validation only. |
| `make test` | Repository test suite only. |
| `make check` | Both of the above, in CI's order — the same two steps as `.github/workflows/validate.yml`, stopping at the first failure. |

`make check` is the quickest way to confirm a contribution passes CI
before you push; each target runs from the repository root and exits
non-zero on the first failure, just like CI's steps do.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to add a fixture.

## Security

See [`SECURITY.md`](SECURITY.md). In short: no secrets, no private keys, no
executable fixture code, no transaction submission — fixture files must be
treated as untrusted input by any consumer.

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Maintainers & Community

**Maintainer:** [@Hollujay](https://github.com/Hollujay) — reachable via
this repository's GitHub profile; no other official contact channel is
published for this project.

**Community:** There is no dedicated community channel yet. Contribution
and discussion happen through GitHub
[issues](https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues)
and pull requests on this repository.

**Contributors:**

[![Contributors](https://contrib.rocks/image?repo=StellarCanary/ProtocolCanary-Fixtures)](https://github.com/StellarCanary/ProtocolCanary-Fixtures/graphs/contributors)
