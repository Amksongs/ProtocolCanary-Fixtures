---
name: Schema/validator drift
about: schemas/fixture-v1.schema.json and tools/validate/validate.py disagree on fixture-v1 behavior
title: ""
labels: bug
---

## Summary

Where do `schemas/fixture-v1.schema.json` and `tools/validate/validate.py` disagree? Describe the field or rule in question.

## Which one is wrong?

- [ ] `schemas/fixture-v1.schema.json`
- [ ] `tools/validate/validate.py`
- [ ] Both — neither matches Protocol-Canary's actual behavior

## What does Protocol-Canary actually do?

State (or quote) the real behavior this fixture format is supposed to mirror. [`docs/fixture-contract.md`](https://github.com/StellarCanary/Protocol-Canary/blob/main/docs/fixture-contract.md) in `Protocol-Canary` is authoritative — link the relevant section if you can.

## How the drift shows up

e.g. the schema permits a value the validator rejects, or the validator accepts something the schema doesn't declare. Include the field name and both behaviors.

## Fixture(s) that exposed this (if any)

Path(s) under `protocol-*/`, e.g. `protocol-28/xdr/cap-0083/p28-xdr-cap83-empty-tx-set.toml`.

## Related issues

e.g. #9
Use this template when `schemas/fixture-v1.schema.json` (documentation for
editors and CI linting) and `tools/validate/validate.py` (the structural
validator) accept or reject the same fixture differently, or when either of
them disagrees with `Protocol-Canary`'s actual loader. For an individual
fixture's value being wrong, use the **Bug report** template instead.

## Summary

What the two say differently, in one or two sentences.

## Where the disagreement is

Quote the specific bit of each side, e.g. the schema's `required` list and
the corresponding `_require(...)` call in `validate.py`.

- `schemas/fixture-v1.schema.json`:
- `tools/validate/validate.py`:
- Fixture that exposes it (if any), e.g. `protocol-28/soroban/....toml`:

## Which side is correct, and why

State which of the two you believe is wrong and what the real behavior is.
The tie-breaker is `Protocol-Canary`'s implementation, not this repository's
two mirrors of it — quote the code, error text, or test in
[`Protocol-Canary`](https://github.com/StellarCanary/Protocol-Canary) that
settles it (e.g. the `canary-fixtures` loader's parse path):

- Verdict (schema is wrong / validator is wrong / both are wrong):
- Evidence from `Protocol-Canary`:

## Against the authoritative contract

Per
[`docs/fixture-contract.md`](https://github.com/StellarCanary/Protocol-Canary/blob/main/docs/fixture-contract.md),
what does the contract require for this field? Quote the section.

## Direction of the fix

Which file should change, and should the other follow? If a real behavior
change is involved, note that `Protocol-Canary` must be updated first —
this repository mirrors it and never defines the contract itself.

## Environment

- Python version:
- `Protocol-Canary` version or commit checked against (required):
