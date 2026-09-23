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