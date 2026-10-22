# Fixture Pack Release Procedure

This document describes the end-to-end procedure for packaging, verifying,
attesting, and publishing deterministic fixture pack releases for
`ProtocolCanary-Fixtures`.

Consumers, including GitHub Actions and integration workflows across the
Stellar ecosystem, rely on release archives being byte-reproducible,
cryptographically attested, and consistently tagged.

---

## 1. Overview and Automation Boundary

The release procedure is split between maintainer pre-release checks and automated
CI execution:

- **Manual steps (maintainer):**
  1. Complete pre-release quality and consistency checks.
  2. Select the release version (Semantic Versioning `MAJOR.MINOR.PATCH`).
  3. Update `CHANGELOG.md` with the release version and UTC date.
  4. Create and push an immutable git tag (`vX.Y.Z` or `protocol-NN`).
- **Automated steps (`.github/workflows/release-pack.yml`):**
  1. Builds the release archive twice in independent passes/directories.
  2. Asserts bit-for-bit identical archive hashes (SHA-256).
  3. Extracts and verifies archive integrity against the pack schema and digest.
  4. Generates the release manifest (`.manifest.json`) and SHA-256 checksums.
  5. Cryptographically attests the archive and manifest using GitHub's build
     provenance attestation (`actions/attest-build-provenance`).
  6. Publishes the release assets to GitHub Releases.

---

## 2. Pre-Release Checks

Before creating a release tag, run all validation and test suites against a clean
working tree on the `main` branch:

### Step 2.1: Structural fixture validation
Verify schema conformance, unique IDs, source references, and payload references:

```bash
python3 tools/validate/validate.py
```

Expected output:
```
OK: 31 fixture file(s) valid across 3 root(s)
```

### Step 2.2: Fixtures count badge freshness
Confirm the README badge matches the fixture inventory:

```bash
python3 tools/badge/badge.py --check
```

Expected output:
```
OK: README.md fixtures badge is current (31 fixture file(s))
```

### Step 2.3: Repository test suite
Run all unit tests across the repository:

```bash
python3 -m unittest discover tests -v
```

Expected output:
```
OK
```

### Step 2.4: Registry freshness
Verify that committed registries match what `tools/registry/generate.py` generates.
For non-empty packs (such as `protocol-28`):

```bash
python3 tools/registry/generate.py protocol-28 --stdout
```

For intentionally empty baselines (such as `protocol-29`), supply `--allow-empty`
and the matching `--protocol`:

```bash
python3 tools/registry/generate.py protocol-29 --allow-empty --protocol 29 --stdout
```

### Step 2.5: CHANGELOG and version selection
1. Choose an exact version string following `MAJOR.MINOR.PATCH` (e.g. `0.1.0`).
2. Update the `## [Unreleased]` section in [`CHANGELOG.md`](../CHANGELOG.md) by
   creating a new heading for the version with the current UTC date in
   `YYYY-MM-DD` format (e.g. `## [0.1.0] - 2026-10-21`).
3. Commit the changelog change and ensure the branch is merged into `main`.

---

## 3. Local Build and Verification

Maintainers may run the packaging and verification tools locally to inspect the
resulting artifacts before tagging:

### Step 3.1: Build the deterministic pack archive
Run `tools/pack/pack.py`:

```bash
python3 tools/pack/pack.py protocol-28 --version 0.1.0 --output-dir dist
```

Expected output:
```
OK: wrote dist/protocolcanary-fixtures-0.1.0.tar.gz
sha256   d3275cd8f3242debc7edbab0cd30e9cbc564a0f335e0ca354741fcf62cc32207
bytes    20661
entries  40
digest   sha256:0a7e5a5743b34cb334d2c8d32d4617c7ab6bec7cceb531b229483ebad437f52a
```

### Step 3.2: Verify the archive contents
Run `tools/pack/verify_archive.py`:

```bash
python3 tools/pack/verify_archive.py dist/protocolcanary-fixtures-0.1.0.tar.gz
```

Expected output:
```
OK: protocolcanary-fixtures-0.1.0.tar.gz: 31 fixture(s), 31 file(s) valid; registry and pack digest match
```

### Step 3.3: Generate the release manifest
Run `tools/release/manifest.py` with the 40-character commit SHA:

```bash
python3 tools/release/manifest.py dist/protocolcanary-fixtures-0.1.0.tar.gz \
  --revision $(git rev-parse HEAD) \
  --output dist/protocolcanary-fixtures-0.1.0.manifest.json \
  --sha256-file dist/protocolcanary-fixtures-0.1.0.sha256
```

Expected output:
```
OK: wrote dist/protocolcanary-fixtures-0.1.0.manifest.json
```

### Step 3.4: Verify archive against manifest and checksum
Verify that the archive matches the generated manifest:

```bash
python3 tools/pack/verify_archive.py dist/protocolcanary-fixtures-0.1.0.tar.gz \
  --manifest dist/protocolcanary-fixtures-0.1.0.manifest.json
```

Expected output:
```
OK: protocolcanary-fixtures-0.1.0.tar.gz: 31 fixture(s), 31 file(s) valid; registry and pack digest match
```

Verify the checksum file:

```bash
(cd dist && sha256sum -c protocolcanary-fixtures-0.1.0.sha256)
```

Expected output:
```
protocolcanary-fixtures-0.1.0.tar.gz: OK
```

---

## 4. Tag Naming Rules and Immutability

### Tag naming convention
Releases are triggered by pushing a git tag matching one of two patterns:
- Version tags: `v<MAJOR>.<MINOR>.<PATCH>` (e.g. `v0.1.0`)
- Protocol tags: `protocol-<NN>` (e.g. `protocol-28`)

### Immutability guarantee
**Published tags are never moved and never deleted.**

Downstream consumers, reproducibility proofs, and attestation certificates bind
strictly to specific git tags and commit hashes. Once a tag is pushed to
`upstream`:
- It must not be deleted.
- It must not be pointed to a different commit.
- Any change or fix requires a new, incremented release version.

---

## 5. Publishing the Release

Once pre-release checks pass and the commit is on `main`, create and push the tag:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push upstream v0.1.0
```

The `.github/workflows/release-pack.yml` workflow triggers automatically on tag
push:
1. It builds the pack twice in independent directories (`/tmp/build1` and `/tmp/build2`)
   and asserts bit-for-bit identical output (`cmp`).
2. It generates `protocolcanary-fixtures-<version>.manifest.json` and
   `protocolcanary-fixtures-<version>.sha256`.
3. It generates build provenance attestations for both the archive and manifest.
4. It publishes the release assets to GitHub Releases.

---

## 6. Post-Release Verification

After the release workflow completes, verify the published assets directly from GitHub:

### Step 6.1: Check SHA-256 checksums
Download `protocolcanary-fixtures-<version>.tar.gz` and
`protocolcanary-fixtures-<version>.sha256`, then verify:

```bash
sha256sum -c protocolcanary-fixtures-0.1.0.sha256
```

### Step 6.2: Verify archive and manifest integrity
Verify that the archive contents conform to the manifest:

```bash
python3 tools/pack/verify_archive.py protocolcanary-fixtures-0.1.0.tar.gz \
  --manifest protocolcanary-fixtures-0.1.0.manifest.json
```

### Step 6.3: Verify build provenance attestation
Using the GitHub CLI (`gh`), verify that the archive was built by this repository's
release workflow:

```bash
gh attestation verify protocolcanary-fixtures-0.1.0.tar.gz \
  --repo StellarCanary/ProtocolCanary-Fixtures \
  --signer-workflow StellarCanary/ProtocolCanary-Fixtures/.github/workflows/release-pack.yml
```

And verify the manifest attestation:

```bash
gh attestation verify protocolcanary-fixtures-0.1.0.manifest.json \
  --repo StellarCanary/ProtocolCanary-Fixtures \
  --signer-workflow StellarCanary/ProtocolCanary-Fixtures/.github/workflows/release-pack.yml
```

---

## 7. Rollback and Superseding Bad Releases

If a defect is discovered in a published release archive or manifest:

1. **Do not move or delete the tag.** Moving tags breaks consumer caches and
   violates provenance guarantees.
2. **Author the fix.** Prepare a pull request addressing the defect.
3. **Bump the patch version.** Update `CHANGELOG.md` with an incremented patch
   version (e.g. `0.1.1`), explicitly stating that it supersedes `0.1.0` and
   describing the issue resolved.
4. **Publish the superseding release.** Merge to `main` and tag the new patch
   version (e.g. `v0.1.1`).
5. **Update release notes.** Edit the GitHub release notes of the superseded
   release to point users to the new version.
