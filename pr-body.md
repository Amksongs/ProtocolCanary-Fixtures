## What changed?

1. Scope corrected: this PR documents the intentionally-empty Protocol 27 pack
   and adds the tests that assert the documented gap. It no longer claims to
   implement Issues #282, #299, or #303. Those issues remain open until a
   separate, focused PR satisfies them.

2. RPC fixture contract corrected to the engine's actual supported surface
   (`main`): `schemas/fixture-v1.schema.json`, `tools/validate/validate.py`,
   and `tests/test_validate.py` no longer mention the unsupported assertion
   kinds `field-one-of` and `field-range` the earlier branch introduced, and
   no longer name assertion kinds the engine does not recognize.

3. `protocol-27/README.md` no longer claims the pack is "best tested through
   RPC `getLatestLedger` credential-shape observations." It now states plainly
   that the surface that can observe CAP-0071-01/02 has not been authored and
   verified here yet.

4. `CHANGELOG.md` now records the Protocol 27 addition under
   `## [Unreleased] > ### Added` with the required PR link, and duplicate
   historical entries have been purged.

## Why?

The PR now reflects only what is actually shipped: a documented Protocol 27
gap, the test that asserts it, a CHANGELOG entry, and a cleanup that aligns the
schema/validation/test surfaces with the engine's real supported contract on
`main`. It no longer over-closes the three linked issues or claims verification
that has not been authored.

## Tests performed

- [x] `python3 tools/validate/validate.py`
- [x] `python3 -m unittest tests.test_pack_protocol_27`
- [x] `python3 tools/badge/badge.py --check`

## Related issue

Closes #299
Fixes https://github.com/StellarCanary/ProtocolCanary-Fixtures/issues/299
