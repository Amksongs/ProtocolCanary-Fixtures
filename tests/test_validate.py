"""Tests for tools/validate/validate.py.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"

_spec = importlib.util.spec_from_file_location("validate", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate"] = validate
_spec.loader.exec_module(validate)


VALID_XDR = """
id = "p28-xdr-cap83-example"
protocol = 28
surface = "xdr"
category = "cap-0083"
description = "example"
source_reference = "CAP-0083"

type = "StellarValue"
kind = "decode-success"
value_base64 = "AAAAAA=="
"""

VALID_RPC = """
id = "p28-rpc-example"
protocol = 28
surface = "rpc"
category = "network"
description = "example"
source_reference = "https://developers.stellar.org/docs/data/apis/rpc/api-reference/methods/getNetwork"

method = "get-network"

[[assert]]
kind = "field-equals"
field = "protocolVersion"
value = 28
"""

VALID_SOROBAN = """
id = "p28-soroban-example"
protocol = 28
surface = "soroban"
category = "smoke"
description = "example"
source_reference = "https://developers.stellar.org/docs/tokens/stellar-asset-contract"

source_account = "GAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWHF"
contract_id = "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC"
function = "name"
sequence_number = 1

[expect]
kind = "simulation-success"
"""


def write(dir_path: Path, name: str, contents: str) -> Path:
    path = dir_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


class ValidatorTests(unittest.TestCase):
    def run_validation(self, files: dict[str, str]) -> "validate.Report":
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, contents in files.items():
                write(root, name, contents)
            return validate.validate_directory(root)

    def test_accepts_a_valid_xdr_fixture(self) -> None:
        report = self.run_validation({"a.toml": VALID_XDR})
        self.assertEqual(report.errors, [])

    def test_accepts_a_valid_rpc_fixture(self) -> None:
        report = self.run_validation({"a.toml": VALID_RPC})
        self.assertEqual(report.errors, [])

    def test_accepts_a_valid_soroban_fixture(self) -> None:
        report = self.run_validation({"a.toml": VALID_SOROBAN})
        self.assertEqual(report.errors, [])

    def test_rejects_duplicate_ids(self) -> None:
        other = VALID_XDR.replace(
            'category = "cap-0083"', 'category = "cap-0083-2"'
        )
        report = self.run_validation({"a.toml": VALID_XDR, "b.toml": other})
        self.assertTrue(any("duplicate fixture id" in e for e in report.errors))

    def test_rejects_duplicate_ids_across_nested_directories(self) -> None:
        # The repository stores fixtures in nested per-surface/per-CAP
        # directories (e.g. protocol-28/xdr/cap-0083/a.toml vs.
        # protocol-28/soroban/b.toml), so duplicate detection must recurse
        # through the whole subtree rather than only compare files that sit
        # directly in the root. This guards against a regression that keeps
        # flat-directory detection working while breaking the recursive case.
        other = VALID_XDR.replace(
            'category = "cap-0083"', 'category = "cap-0083-2"'
        )
        report = self.run_validation(
            {
                "xdr/cap-0083/a.toml": VALID_XDR,
                "soroban/b.toml": other,
            }
        )
        duplicates = [e for e in report.errors if "duplicate fixture id" in e]
        self.assertTrue(duplicates, report.errors)
        # The error should point at one of the nested files, confirming the
        # nested fixture was actually discovered by the recursive walk.
        self.assertTrue(
            any("soroban/b.toml" in e or "xdr/cap-0083/a.toml" in e for e in duplicates)
        )

    def test_rejects_invalid_surface(self) -> None:
        bad = VALID_XDR.replace('surface = "xdr"', 'surface = "wallet"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("'surface'" in e for e in report.errors))

    def test_rejects_invalid_protocol_type(self) -> None:
        bad = VALID_XDR.replace("protocol = 28", 'protocol = "28"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("'protocol'" in e for e in report.errors))

    def test_rejects_missing_input_file(self) -> None:
        bad = VALID_XDR + '\ninput_file = "does-not-exist.xdr.b64"\n'
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("does not resolve to an existing file" in e for e in report.errors))

    def test_accepts_an_existing_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "input.xdr.b64", "AAAAAA==")
            write(root, "a.toml", VALID_XDR + '\ninput_file = "input.xdr.b64"\n')
            report = validate.validate_directory(root)
        self.assertEqual(report.errors, [])

    def test_rejects_invalid_expectation_kind(self) -> None:
        bad = VALID_XDR.replace('kind = "decode-success"', 'kind = "not-a-real-kind"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("'kind'" in e for e in report.errors))

    def test_rejects_xdr_type_not_in_xdr_types(self) -> None:
        bad = VALID_XDR.replace('type = "StellarValue"', 'type = "LedgerEntry"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(
            any(
                "LedgerEntry" in e
                and "StellarValue" in e
                and "ContractExecutable" in e
                for e in report.errors
            )
        )

    def test_encode_equals_requires_expected_base64(self) -> None:
        bad = VALID_XDR.replace('kind = "decode-success"', 'kind = "encode-equals"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("expected_base64" in e for e in report.errors))

    def test_rejects_empty_source_reference(self) -> None:
        bad = VALID_XDR.replace('source_reference = "CAP-0083"', 'source_reference = ""')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("source_reference" in e for e in report.errors))

    def test_errors_on_missing_source_reference(self) -> None:
        # Every fixture must cite an authoritative upstream source (see
        # CONTRIBUTING.md and SECURITY.md). A missing source_reference is a
        # hard validation error, not a warning, so it must fail the build
        # rather than pass with a printed advisory.
        bad = VALID_XDR.replace('source_reference = "CAP-0083"\n', "")
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(
            any(
                "source_reference" in e
                and "authoritative upstream source" in e
                and "CAP-0083" in e
                for e in report.errors
            ),
            report.errors,
        )
        # It must be reported as an error only, never downgraded to a warning.
        self.assertFalse(
            any("source_reference" in w for w in report.warnings),
            report.warnings,
        )

    def test_accepts_a_present_source_reference(self) -> None:
        # The pass case for the rule above: a fixture that cites an
        # authoritative source produces no source_reference error.
        report = self.run_validation({"a.toml": VALID_XDR})
        self.assertFalse(
            any("source_reference" in e for e in report.errors), report.errors
        )

    def test_rejects_malformed_toml(self) -> None:
        report = self.run_validation({"a.toml": "not valid [[[ toml"})
        self.assertTrue(any("invalid TOML" in e for e in report.errors))

    def test_rejects_vague_category(self) -> None:
        bad = VALID_XDR.replace('category = "cap-0083"', 'category = "misc"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("too vague" in e for e in report.errors))

    def test_rejects_uppercase_id(self) -> None:
        bad = VALID_XDR.replace(
            'id = "p28-xdr-cap83-example"', 'id = "P28-XDR-CAP83-EXAMPLE"'
        )
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("lowercase" in e for e in report.errors))

    def test_rejects_non_table_assert_entry(self) -> None:
        # TOML permits an array element to be a non-table value; validate_rpc_body
        # has an explicit branch for that case. Mix a well-formed assert table
        # with a bare string so the malformed entry is the only error reported.
        bad = """
id = "p28-rpc-mixed-assert"
protocol = 28
surface = "rpc"
category = "network"
description = "example"
source_reference = "https://developers.stellar.org/docs/data/apis/rpc/api-reference/methods/getNetwork"

method = "get-network"

assert = [
    { kind = "field-equals", field = "protocolVersion", value = 28 },
    "not-a-table",
]
"""
        report = self.run_validation({"a.toml": bad})
        self.assertIn(
            "assert[1] must be a table",
            "\n".join(report.errors),
        )
        # The valid entry alongside the malformed one must not itself error.
        self.assertFalse(any("assert[0]" in e for e in report.errors))

    def test_unknown_top_level_field_is_not_an_error(self) -> None:
        # Documents current behavior: validate.py performs no top-level
        # additionalProperties check, so an unrecognized field (e.g. a typo'd
        # field name) is silently accepted rather than rejected. If this ever
        # changes, this test should fail and force a deliberate decision.
        with_unknown = VALID_XDR.replace(
            'source_reference = "CAP-0083"',
            'source_reference = "CAP-0083"\nsoure_reference = "typo"',
        )
        report = self.run_validation({"a.toml": with_unknown})
        self.assertEqual(report.errors, [])

    def test_rpc_fixture_requires_at_least_one_assert(self) -> None:
        bad = """
id = "p28-rpc-no-assert"
protocol = 28
surface = "rpc"
category = "network"
description = "example"
source_reference = "https://developers.stellar.org/docs/data/apis/rpc/api-reference/methods/getNetwork"

method = "get-network"
"""
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("at least one" in e for e in report.errors))

    def test_rejects_unrecognized_rpc_assert_kind(self) -> None:
        bad = VALID_RPC.replace('kind = "field-equals"', 'kind = "field-contains"')
        report = self.run_validation({"a.toml": bad})
        errors = [e for e in report.errors if "assert[0].kind" in e]
        self.assertEqual(len(errors), 1, report.errors)
        # The error must name the offending kind and enumerate the kinds the
        # validator does accept, so that neither widening nor narrowing
        # RPC_ASSERT_KINDS can pass unnoticed.
        self.assertIn("field-contains", errors[0])
        for supported in ("field-exists", "field-type", "field-equals"):
            self.assertIn(supported, errors[0])

    def test_soroban_fixture_requires_expect(self) -> None:
        bad = VALID_SOROBAN.replace("[expect]\nkind = \"simulation-success\"\n", "")
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("'expect'" in e for e in report.errors))

    def test_soroban_fixture_rejects_unknown_expect_kind(self) -> None:
        # [expect] is present but its kind is not in SOROBAN_EXPECT_KINDS —
        # a different branch of validate_soroban_body than the missing-
        # [expect] case above.
        bad = VALID_SOROBAN.replace(
            'kind = "simulation-success"', 'kind = "simulation-timeout"'
        )
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("expect.kind" in e for e in report.errors))

    def test_rejects_invalid_base64_in_value_base64(self) -> None:
        bad = VALID_XDR.replace('value_base64 = "AAAAAA=="', 'value_base64 = "not-valid-base64!!!"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("not valid base64" in e and "value_base64" in e for e in report.errors))

    def test_rejects_malformed_padding_base64(self) -> None:
        bad = VALID_XDR.replace('value_base64 = "AAAAAA=="', 'value_base64 = "AAAAA"')
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("not valid base64" in e and "value_base64" in e for e in report.errors))

    def test_rejects_invalid_base64_in_expected_base64(self) -> None:
        bad = (
            VALID_XDR.replace('kind = "decode-success"', 'kind = "encode-equals"')
            + 'expected_base64 = "not-valid-base64!!!"\n'
        )
        report = self.run_validation({"a.toml": bad})
        self.assertTrue(any("not valid base64" in e and "expected_base64" in e for e in report.errors))

    def test_accepts_valid_base64_in_encode_equals(self) -> None:
        good = (
            VALID_XDR.replace('kind = "decode-success"', 'kind = "encode-equals"')
            + 'expected_base64 = "AAAAAA=="\n'
        )
        report = self.run_validation({"a.toml": good})
        self.assertEqual(report.errors, [])


class QuietFlagTests(unittest.TestCase):
    """`--quiet` suppresses warnings while keeping errors and the summary.

    A missing ``source_reference`` is now an error rather than a warning, so
    no built-in validator rule currently emits a warning. To keep the flag's
    suppression path covered, these tests inject a warning into the report
    returned for the temporary root. Errors are produced by a real invalid
    fixture, so both halves of the flag's behavior are exercised together.
    """

    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validate.main(argv)
        return code, out.getvalue(), err.getvalue()

    def write_error_fixture(self, root: Path) -> None:
        # Invalid surface -> error only (source_reference is still present).
        write(root, "error.toml", VALID_XDR.replace('surface = "xdr"', 'surface = "wallet"'))

    def with_injected_warning(self):
        # Wrap the real validate_directory so the report it returns also carries
        # a warning, giving --quiet something to suppress.
        real = validate.validate_directory

        def wrapper(root: Path) -> "validate.Report":
            report = real(root)
            report.warning(Path(root) / "injected.toml", "injected warning")
            return report

        return mock.patch.object(validate, "validate_directory", side_effect=wrapper)

    def test_default_prints_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_error_fixture(root)
            with self.with_injected_warning():
                code, out, err = self.run_main([str(root)])
        self.assertIn("warning:", out)
        self.assertIn("error:", err)
        self.assertEqual(code, 1)

    def test_quiet_suppresses_warnings_but_keeps_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_error_fixture(root)
            with self.with_injected_warning():
                code, out, err = self.run_main(["--quiet", str(root)])
        self.assertNotIn("warning:", out)
        self.assertIn("error:", err)
        self.assertEqual(code, 1)

    def test_quiet_keeps_ok_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "ok.toml", VALID_XDR)
            with self.with_injected_warning():
                code, out, err = self.run_main(["--quiet", str(root)])
        self.assertNotIn("warning:", out)
        self.assertIn("OK:", out)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
