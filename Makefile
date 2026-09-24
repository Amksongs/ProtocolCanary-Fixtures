# Convenience shortcuts for the checks CI runs (.github/workflows/validate.yml).
#
# Targets:
#   make validate  - structural fixture validation (tools/validate/validate.py)
#   make test      - repository test suite (unittest discover tests)
#   make check     - both of the above, in CI's order; stops at the first failure
#
# Run from the repository root (make defaults to this file's directory).
# Requires Python 3.11+ (the validator uses the stdlib `tomllib` module).

.PHONY: validate test check

validate:
	python3 tools/validate/validate.py

test:
	python3 -m unittest discover tests -v

check: validate test
