# Resolves #23: Add reviewer guidance for source_reference verification

## Description

This PR adds a short subsection to `CONTRIBUTING.md`'s "Adding a fixture" section to provide explicit guidance to reviewers on how to verify a `source_reference`.

Previously, `CONTRIBUTING.md` required a `source_reference` and an explanation of how the expected value was derived, but lacked concrete instructions for reviewers on how to enforce the "no-fabrication" policy. Since `validate.py` can only perform structural checks (e.g., verifying the field is a non-empty string), ensuring the validity of a fixture's expected values ultimately falls on the reviewers.

This update clarifies that reviewers must:
1. Actually open the cited documentation (CAP text, XDR definition, etc.) and confirm it explicitly documents the exact value asserted (rather than merely verifying the link resolves).
2. Re-run any stated commands or crate calls locally and diff the output to ensure the expected values match the fixture if the expectation was derived from execution.

## Changes

* **`CONTRIBUTING.md`**: Added a new `### Reviewing a source reference` subsection under `## Adding a fixture` section to document the required reviewer validation process.

## Testing

* Read-through review (Documentation-only change, no automated tests apply).
