# Convenience shortcuts for the checks CI runs (.github/workflows/validate.yml).
#
# Targets:
#   make validate     - structural fixture validation (tools/validate/validate.py)
#   make badge        - regenerate README.md's fixture-count badge (tools/badge/badge.py)
#   make badge-check  - fail if that badge is stale (what CI runs)
#   make test         - repository test suite (unittest discover tests)
#   make check-changelog - verify CHANGELOG entry for changed files (tools/validate/check_changelog.py)
#   make check-links  - check fixture source reference links (tools/validate/check_source_links.py)
#   make coverage     - test suite under branch coverage of tools/, failing below
#                       .coveragerc's fail_under (what CI's coverage job runs);
#                       needs the dev dependency `pip install coverage==7.16.2`
#   make registry     - write PACK/registry-v1.json (tools/registry/generate.py);
#                       PACK defaults to protocol-28. Not part of `make check`.
#   make records      - write PACK/evidence/records/*.json, the CF-04 structural
#                       verification records (tools/evidence/record_structural.py);
#                       PACK defaults to protocol-28. Run it after a fixture
#                       changes: a record holds the hash of the file it checked.
#   make registry-diff- compare two registries and report what changed
#                       (tools/registry/diff.py); OLD and NEW are the registry
#                       files, FORMAT is text (default), json or markdown.
#   make pack         - build dist/protocolcanary-fixtures-VERSION.tar.gz for PACK
#                       (tools/pack/pack.py); VERSION is required, e.g. VERSION=1.0.0
#   make check        - all of the above, in CI's order; stops at the first failure
#
# Run from the repository root (make defaults to this file's directory).
# Requires Python 3.11+ (the validator uses the stdlib `tomllib` module).

PACK ?= protocol-28
OLD ?=
NEW ?=
FORMAT ?= text

.PHONY: validate badge badge-check test check-changelog check-links coverage registry records registry-diff pack check

validate:
	python3 tools/validate/validate.py

check-changelog:
	python3 tools/validate/check_changelog.py

check-links:
	python3 tools/validate/check_source_links.py

badge:
	python3 tools/badge/badge.py

badge-check:
	python3 tools/badge/badge.py --check

test:
	python3 -m unittest discover tests -v

coverage:
	coverage run -m unittest discover tests
	coverage report -m

registry:
	python3 tools/registry/generate.py $(PACK)

records:
	python3 tools/evidence/record_structural.py $(PACK)

registry-diff:
	@test -n "$(OLD)" && test -n "$(NEW)" || { echo "usage: make registry-diff OLD=REGISTRY NEW=REGISTRY [FORMAT=text|json|markdown]" >&2; exit 2; }
	python3 tools/registry/diff.py "$(OLD)" "$(NEW)" --format "$(FORMAT)"

pack:
	@test -n "$(VERSION)" || { echo "usage: make pack VERSION=1.0.0 [PACK=protocol-28]" >&2; exit 2; }
	python3 tools/pack/pack.py $(PACK) --version $(VERSION) --output-dir dist

check: validate badge-check test
