# Contributing

## Adding a fixture

A fixture is accepted only if a reviewer can answer all of the following
from the fixture file and its header comment alone, without running a
script:

1. What Stellar behavior does this test?
2. Why is that behavior important?
3. What protocol/CAP introduced it?
4. What is the expected result, and where does that expectation come from?
5. Is the test deterministic?

To add one:

**Short version** (the detailed walkthrough follows below):

- **Source it** — identify the upstream behavior from an authoritative source
  you have actually checked, and record it in `source_reference` plus a header
  comment explaining how the expected value was derived.
- **Write it** — stable, repository-unique `p<protocol>-<surface>-<slug>` ID;
  deterministic input; an explicit expected result using the surface's typed
  assertion vocabulary.
- **Check it** — run `make validate` (or `python3 tools/validate/validate.py` directly).
- **Document & test it** — update the relevant `docs/protocol-NN.md` table
  (and the pack's `README.md` for a new CAP or surface), then run
  `make test` (or `python3 -m unittest discover tests` directly).

1. **Identify the upstream behavior.** Read the CAP text, the upstream XDR
   definition, the upstream implementation, or the official release/API
   docs — in that order of preference. Never cite a source you have not
   actually checked describes the specific behavior you are asserting.
2. **Add source provenance.** Every fixture sets `source_reference` to an
   authoritative URL or CAP identifier (note: omitting it currently produces
   a warning, not a validator error), and its header comment (a `#`
   comment block above the TOML body) explains, in prose, how the expected
   value was derived or observed — e.g. "built with the official
   `stellar-xdr` 28.0.0 crate against the CAP-0083 `StellarValue` type",
   not "looks right". If the header comment records *when* an observation
   was made, use the date convention below.
3. **Define a stable ID.** Follow `p<protocol>-<surface>-<slug>` (e.g.
   `p28-xdr-cap85-external-ref-roundtrip`). IDs are lowercase, unique
   across the *entire* repository (the loader validates this across all
   `*.toml` files under a given `--fixtures-dir`, not just one file), and
   never renamed just because an implementation detail changed — if the
   semantic assertion itself changes, add a new fixture ID instead of
   silently repurposing an old one.
4. **Create deterministic input.** No fixture may depend on ledger state
   that changes between runs (a current ledger sequence, "the latest
   anything") unless the assertion is explicitly scoped as a live-network
   check and documented as such.
5. **Define an explicit expected result** using the assertion vocabulary
   the target surface actually supports (see "Fixture schema" below) — no
   generic string matching when a typed assertion exists.
6. **Validate the fixture**: `make validate` — or
   `python3 tools/validate/validate.py` directly. Only errors produce a
   non-zero exit code: the validator exits 1 if the report contains at
   least one error and 0 otherwise, and warnings alone never change the
   exit code. CI runs this exact command
   (`.github/workflows/validate.yml`), so that exit code is what CI
   treats as pass/fail — any error fails the workflow on your PR, while
   warnings never do (they are advisory: fix them when you can, but they
   will not fail CI).
7. **Add/update documentation**: the relevant `docs/protocol-NN.md` table
   and, if you added a new CAP or surface, the pack's `README.md`.
8. **Run the repository tests**: `make test` — or
   `python3 -m unittest discover tests` directly.

Before pushing, `make check` runs both of the above in one command, in
the same order CI (`.github/workflows/validate.yml`) runs them.

> **Note**: Do not add a `manifest.toml` or similar discovery/enumeration file. The loader recursively treats every `*.toml` file under `--fixtures-dir` as a fixture, so a manifest `.toml` file would be mis-parsed as a malformed fixture and fail the run (see [README.md](README.md#repository-relationship)).

No fixture should be merged solely because it makes some consumer's CI
green. If you cannot pin down the exact expected wire representation or
host-function behavior from an authoritative source, **stop** — do not
guess a byte sequence or invent an undocumented host function because it
"looks right". Open an issue describing the gap instead.

## Recording verification dates

When a fixture's header comment records when a live-network observation was
made (for example, the date an RPC endpoint or a simulation was last checked
to still return the documented result), write the date as **`YYYY-MM-DD` in
UTC** — e.g. `2026-09-02`. State the `UTC` designation the first time a date
appears in a header comment (or otherwise make clear it is UTC).

Rationale: these dates exist so a future reader can judge how stale an
observation may be. Recording them in local time would make a date recorded
near a day boundary ambiguous by up to a day, defeating that purpose.

## Fixture schema

This repository's fixture files must conform exactly to what
`StellarCanary/Protocol-Canary`'s `canary-fixtures`/`canary-xdr`/
`canary-rpc`/`canary-soroban` crates actually parse — that implementation,
documented in its `docs/fixture-contract.md`, is authoritative. This
repository does not define its own competing schema. `schemas/fixture-v1.schema.json`
here is a convenience JSON Schema mirroring that contract for editor/CI
linting; if the two ever disagree, `Protocol-Canary`'s implementation wins
and this repository's schema/validator must be corrected to match — never
the other way around.

The fixture format is versioned: `schemas/fixture-v1.schema.json` is titled
"Protocol Canary fixture (schema_version 1)". **Every protocol pack must
state, in its `docs/protocol-NN.md` or the pack's `README.md`, which fixture
format `schema_version` its fixtures were written against** — the
`protocol-28` pack, for instance, targets `schema_version 1`. The schema
version is a per-pack property recorded in prose, not a field repeated in
each fixture file. Recording it from the start is what lets a future format
revision (e.g. `schema_version 2`) be scoped per pack rather than
retrofitted by guesswork.

Common fields (every fixture):

```toml
id = "unique-string"
protocol = 28
surface = "xdr" # | "rpc" | "soroban"
category = "cap-0083"
description = "..."
source_reference = "CAP-0083"          # optional but expected for protocol-specific fixtures
required_capabilities = []              # optional, see fixture-contract.md
input_file = "..."                      # optional, path relative to this file (currently unused by any fixture)
expected_file = "..."                   # optional (currently unused by any fixture)
```

Per-surface body (everything else in the file):

| Surface | Fields |
|---|---|
| `xdr` | `type` (currently `"StellarValue"` or `"ContractExecutable"`), `kind` (`"decode-success"` \| `"decode-failure"` \| `"roundtrip"` \| `"encode-equals"`), `value_base64`, `expected_base64` (only for `encode-equals`) |
| `rpc` | `method` (`"get-network"` \| `"get-latest-ledger"`), one or more `[[assert]]` tables (`{kind, field, value?, expected_type?}`) |
| `soroban` | `source_account`, `contract_id`, `function`, `sequence_number`, optional `[[args]]`, `[expect]` (`{kind = "simulation-success"}` or `{kind = "simulation-error", message_contains?}`) |

### Unknown top-level fields

Neither `tools/validate/validate.py` nor `schemas/fixture-v1.schema.json` sets
`additionalProperties: false` at the top level, so an unrecognized top-level
field is **intentionally permitted today** and does not by itself produce a
validator error. This permissiveness is deliberate — the fixture contract is
owned by `Protocol-Canary`'s loader, and a hard failure on unknown fields here
would reject fixtures using fields that loader supports before this
repository's schema/validator has caught up.

The practical consequence is that a typo'd field name (e.g. `soure_reference`
instead of `source_reference`) is silently ignored while the intended field is
reported as missing — or, if the intended field is also present, nothing is
reported at all. If you get a confusing "missing field" error, check for a
misspelled duplicate first. Tightening this (rejecting unknown fields) would be
a deliberate change requiring a matching update to the test that documents the
current behavior in `tests/test_validate.py` — never an accidental side effect.

If you need an XDR `type` this repository does not yet support, that is a
`Protocol-Canary` limitation, not something to work around here — open an
issue/PR against `Protocol-Canary`'s `canary-xdr` crate first (see its own
`CONTRIBUTING.md`), and only add the fixture here once that support exists
and is released.

## What never belongs in a fixture

- Shell commands, scripts, or any embedded JavaScript/Python/Bash/Rust —
  fixtures are declarative data, never code. There is no `exec`,
  `shell_command`, `pre_run`, or `post_run` field, and none will ever be
  added.
- Private keys, seed phrases, or funded-account secrets.
- A request for `Protocol-Canary` to submit a real, state-changing
  transaction. Fixtures may require simulation, decoding/encoding, or a
  read-only RPC call — never submission.
- A claim about current live network state (a specific ledger sequence, a
  specific balance) unless the fixture is explicitly and narrowly scoped as
  a live-network check with its assumptions documented.
- A `manifest.toml` or any discovery/enumeration file. The loader recursively
  parses every `*.toml` file under `--fixtures-dir` as a fixture, so a manifest
  file would be mis-parsed as a malformed fixture and fail validation (see
  [README.md](README.md#repository-relationship)).

## Deprecating a fixture

Do not silently delete a fixture that is still referenced by a released
`Protocol-Canary` version's tests or documentation. Mark it deprecated in
its header comment with the reason, note it in `CHANGELOG.md`, and remove
it in a later, separate change once nothing depends on it.

Note that deprecation is communicated **only** via this header comment
convention. There is intentionally no `deprecated` field or equivalent
structured marker in the schema. This is by design: deprecation is meant
for humans reading the fixture or reviewing a PR, while automated consumers
parsing the file via the schema treat it like any other fixture until it is
fully removed.
## Updating CHANGELOG.md

Every user-visible change — a new fixture, a validator behavior change, new
tooling — gets an entry under `CHANGELOG.md`'s `## [Unreleased]` section in
the same pull request that makes the change.

Each entry must include a link to the pull request that introduced it, so a
reader can jump straight from the changelog line to the review discussion
and the diff:

```markdown
- `p28-xdr-example` — what the fixture checks.
  ([PR #123](https://github.com/StellarCanary/ProtocolCanary-Fixtures/pull/123))
```

If a change is pushed directly to `main` without a pull request, link the
introducing commit instead:

```markdown
- Something else. ([abc1234](https://github.com/StellarCanary/ProtocolCanary-Fixtures/commit/abc1234))
```

A changelog entry without one of these links is not ready for review.

## Development setup

No build system is required. `tools/validate/validate.py` uses only the
Python 3.11+ standard library (`tomllib`), so there is nothing to install.

For convenience, a `Makefile` wraps the two commands CI runs:

- `make validate` — structural fixture validation.
- `make test` — the repository test suite.
- `make check` — both, in CI's order, stopping at the first failure.

The underlying commands work identically if run directly, so `make` is
not a requirement for contributing — it only saves typing.
