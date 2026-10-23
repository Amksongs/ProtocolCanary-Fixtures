# Makefile for ProtocolCanary-Fixtures
#
# Run `make check` to run the full suite of repository checks:
#   - Ruff lint (ruff check)
#   - Ruff format check (ruff format --check)
#   - Python unit tests
#
# Ruff is pinned to version 0.17.2 in ruff.toml and the CI workflow.

.PHONY: check

check:
	ruff check .
	ruff format --check .
	python3 -m unittest discover tests
