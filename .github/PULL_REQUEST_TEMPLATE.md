## What changed?

## Why?

## Tests performed

- [ ] `python3 tools/validate/validate.py`
- [ ] `python3 -m unittest discover tests`
- [ ] `python3 tools/badge/badge.py --check` (or `make badge`) — required whenever a fixture was added or removed
- [ ] Verified against a real `Protocol-Canary` build (state the version)

## Related issue

Closes #

## New or changed fixture(s)?

If yes, link the CAP/source this fixture is derived from and confirm the
value was produced by a real implementation (not hand-assembled bytes) —
see the README's "Provenance" section and follow the full
["Adding a fixture" checklist](https://github.com/StellarCanary/ProtocolCanary-Fixtures/blob/main/CONTRIBUTING.md#adding-a-fixture)
in CONTRIBUTING.md, which maps directly to these review questions:
source, determinism, and ID stability.

## Breaking change?

- [ ] Yes — a fixture ID changed or was removed (breaks pinned consumers)
- [ ] No
