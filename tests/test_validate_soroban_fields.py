"""Tests for Soroban field validation (issue #343, F-079).

Validates source_account, contract_id and function length according to
the engine's transaction builder rules.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"

_spec = importlib.util.spec_from_file_location("validate", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate"] = validate
_spec.loader.exec_module(validate)


def encode_strkey(version_byte: int, payload: bytes) -> str:
    """Inverse of decode_strkey for testing with synthetic 32-byte payloads."""
    assert len(payload) == 32
    data = bytes([version_byte]) + payload
    crc = validate.crc16_xmodem(data)
    return base64.b32encode(data + crc.to_bytes(2, "little")).decode("ascii")


def make_soroban_fixture(
    *,
    source_account: str,
    contract_id: str,
    function: str,
    sequence_number: int = 1,
) -> str:
    return f"""
id = "test-soroban-fixture"
protocol = 28
surface = "soroban"
category = "smoke"
description = "test fixture"
source_reference = "https://github.com/stellar/stellar-protocol/blob/4db3e802b2929c865a27bd43f2544c979150137d/ecosystem/sep-0041.md"

source_account = "{source_account}"
contract_id = "{contract_id}"
function = "{function}"
sequence_number = {sequence_number}

[expect]
kind = "simulation-success"
"""


def validate_fixture_content(content: str) -> validate.Report:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = root / "fixture.toml"
        p.write_text(content, encoding="utf-8")
        return validate.validate_directory(root)


class TestValidateSorobanFields(unittest.TestCase):
    def setUp(self) -> None:
        self.valid_source = encode_strkey(6 << 3, b"\x01" * 32)
        self.valid_contract = encode_strkey(2 << 3, b"\x02" * 32)

    def test_existing_soroban_fixtures_all_validate(self) -> None:
        """Assert that every Soroban fixture in protocol-*/ validates."""
        soroban_count = 0
        for proto_dir in REPO_ROOT.glob("protocol-*"):
            for fixture_path in proto_dir.glob("**/*.toml"):
                try:
                    text = fixture_path.read_text(encoding="utf-8")
                except Exception:
                    continue
                if 'surface = "soroban"' in text:
                    soroban_count += 1
                    report = validate.Report()
                    fx = validate.load_fixture(fixture_path, report)
                    self.assertIsNotNone(fx, f"failed to load {fixture_path}: {report.errors}")
                    validate.validate_soroban_body(fx, report)
                    self.assertEqual(
                        report.errors, [], f"fixture {fixture_path} failed validation: {report.errors}"
                    )
        self.assertGreater(soroban_count, 0, "expected to find existing soroban fixtures")

    def test_synthetic_valid_strkeys_pass(self) -> None:
        content = make_soroban_fixture(
            source_account=self.valid_source,
            contract_id=self.valid_contract,
            function="transfer",
        )
        report = validate_fixture_content(content)
        self.assertEqual(report.errors, [])

    def test_boundary_function_lengths(self) -> None:
        # 32 ASCII characters passes
        fn32_ascii = "a" * 32
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_contract,
                function=fn32_ascii,
            )
        )
        self.assertEqual(report.errors, [])

        # 16 two-byte characters (32 bytes in UTF-8) passes
        fn16_twobyte = "é" * 16
        self.assertEqual(len(fn16_twobyte.encode("utf-8")), 32)
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_contract,
                function=fn16_twobyte,
            )
        )
        self.assertEqual(report.errors, [])

        # 32 bytes made of multibyte characters passes (10 3-byte + 2 1-byte)
        fn_multi = "€" * 10 + "ab"
        self.assertEqual(len(fn_multi.encode("utf-8")), 32)
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_contract,
                function=fn_multi,
            )
        )
        self.assertEqual(report.errors, [])

        # 33 ASCII characters fails
        fn33_ascii = "a" * 33
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_contract,
                function=fn33_ascii,
            )
        )
        self.assertTrue(
            any("field 'function' exceeds 32 bytes" in e for e in report.errors),
            report.errors,
        )

        # 17 two-byte characters (34 bytes in UTF-8) fails
        fn17_twobyte = "é" * 17
        self.assertEqual(len(fn17_twobyte.encode("utf-8")), 34)
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_contract,
                function=fn17_twobyte,
            )
        )
        self.assertTrue(
            any("field 'function' exceeds 32 bytes" in e for e in report.errors),
            report.errors,
        )

    def test_empty_function_fails(self) -> None:
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_contract,
                function="",
            )
        )
        self.assertTrue(
            any("field 'function' must not be empty" in e for e in report.errors),
            report.errors,
        )

    def test_invalid_strkey_not_a_key(self) -> None:
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account="GNOTAKEY",
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account' is not a valid G... strkey" in e for e in report.errors),
            report.errors,
        )

        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id="CNOTAKEY",
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'contract_id' is not a valid C... strkey" in e for e in report.errors),
            report.errors,
        )

    def test_muxed_account_rejected(self) -> None:
        muxed = encode_strkey(12 << 3, b"\x03" * 32)
        self.assertTrue(muxed.startswith("M"))
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=muxed,
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "muxed account" in e for e in report.errors),
            report.errors,
        )

    def test_secret_seed_rejected_without_leaking_value(self) -> None:
        secret = encode_strkey(18 << 3, b"\x04" * 32)
        self.assertTrue(secret.startswith("S"))
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=secret,
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "secret seed" in e for e in report.errors),
            report.errors,
        )
        # Ensure the secret seed value is NEVER echoed
        for error in report.errors:
            self.assertNotIn(secret, error)

    def test_cross_prefix_rejected(self) -> None:
        # C... in source_account
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_contract,
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "expected G..." in e for e in report.errors),
            report.errors,
        )

        # G... in contract_id
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=self.valid_source,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'contract_id'" in e and "expected C..." in e for e in report.errors),
            report.errors,
        )

    def test_checksum_failure(self) -> None:
        # Mutate last character
        bad_char = "E" if self.valid_source[-1] != "E" else "F"
        mutated_source = self.valid_source[:-1] + bad_char
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=mutated_source,
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "bad checksum" in e for e in report.errors),
            report.errors,
        )

        bad_contract_char = "E" if self.valid_contract[-1] != "E" else "F"
        mutated_contract = self.valid_contract[:-1] + bad_contract_char
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source,
                contract_id=mutated_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'contract_id'" in e and "bad checksum" in e for e in report.errors),
            report.errors,
        )

    def test_wrong_lengths_and_whitespace(self) -> None:
        # Trailing whitespace (57 characters)
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source + " ",
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "wrong length" in e for e in report.errors),
            report.errors,
        )

        # 55-character key
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source[:-1],
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "wrong length" in e for e in report.errors),
            report.errors,
        )

        # 57-character key
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source + "A",
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "wrong length" in e for e in report.errors),
            report.errors,
        )

    def test_lowercase_and_non_base32(self) -> None:
        # Lowercase
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=self.valid_source.lower(),
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "lower-case" in e for e in report.errors),
            report.errors,
        )

        # Non-base32 (e.g. contains 8 or 9)
        bad_b32 = self.valid_source[:10] + "8" + self.valid_source[11:]
        report = validate_fixture_content(
            make_soroban_fixture(
                source_account=bad_b32,
                contract_id=self.valid_contract,
                function="transfer",
            )
        )
        self.assertTrue(
            any("field 'source_account'" in e and "non-base32" in e for e in report.errors),
            report.errors,
        )

    def test_soroban_integer_ranges_table_driven(self) -> None:
        """Test Soroban argument integer ranges at their exact limits (F-124, issue #420)."""
        def make_arg_fx(kind: str, val_repr: str, protocol: int = 28) -> str:
            return f"""
id = "test-soroban-fixture"
protocol = {protocol}
surface = "soroban"
category = "smoke"
description = "test fixture"
source_reference = "CAP-0083"

source_account = "{self.valid_source}"
contract_id = "{self.valid_contract}"
function = "transfer"
sequence_number = 1

[[args]]
kind = "{kind}"
value = {val_repr}

[expect]
kind = "simulation-success"
"""

        rows = [
            # kind, val_repr, is_accepted, expected_fragment, label
            ("u32", "0", True, None, "u32 lower bound"),
            ("u32", "-1", False, "allowed range", "u32 below lower bound"),
            ("u32", "4294967295", True, None, "u32 upper bound"),
            ("u32", "4294967296", False, "allowed range", "u32 above upper bound"),

            ("i32", "-2147483648", True, None, "i32 lower bound"),
            ("i32", "-2147483649", False, "allowed range", "i32 below lower bound"),
            ("i32", "2147483647", True, None, "i32 upper bound"),
            ("i32", "2147483648", False, "allowed range", "i32 above upper bound"),

            ("i64", "-9223372036854775808", True, None, "i64 lower bound"),
            ("i64", "9223372036854775807", True, None, "i64 upper bound"),
            ("i64", "9223372036854775808", False, "outside the signed 64-bit range", "i64 above signed 64-bit range"),

            ("u64", "0", True, None, "u64 lower bound"),
            ("u64", "-1", False, "allowed range", "u64 below lower bound"),
            ("u64", "9223372036854775807", True, None, "u64 signed 64-bit max"),
            ("u64", "9223372036854775808", False, "outside the signed 64-bit range", "u64 above signed 64-bit range"),

            ("duration", "0", True, None, "duration lower bound"),
            ("duration", "-1", False, "must be a non-negative", "duration below lower bound"),
            ("duration", "9223372036854775807", True, None, "duration signed 64-bit max"),
            ("duration", "9223372036854775808", False, "outside the signed 64-bit range", "duration above signed 64-bit range"),

            ("timepoint", "0", True, None, "timepoint lower bound"),
            ("timepoint", "-1", False, "must be a non-negative", "timepoint below lower bound"),
            ("timepoint", "9223372036854775807", True, None, "timepoint signed 64-bit max"),
            ("timepoint", "9223372036854775808", False, "outside the signed 64-bit range", "timepoint above signed 64-bit range"),

            ("i128", '"-170141183460469231731687303715884105728"', True, None, "i128 decimal lower bound"),
            ("i128", '"-170141183460469231731687303715884105729"', False, "below the minimum", "i128 decimal below lower bound"),
            ("i128", '"170141183460469231731687303715884105727"', True, None, "i128 decimal upper bound"),
            ("i128", '"170141183460469231731687303715884105728"', False, "above the maximum", "i128 decimal above upper bound"),
            ("i128", f'"{hex(2**127 - 1)}"', True, None, "i128 hex upper bound"),
            ("i128", f'"-{hex(2**127)}"', True, None, "i128 hex lower bound"),

            ("u128", '"0"', True, None, "u128 decimal lower bound"),
            ("u128", '"-1"', False, "must not be negative", "u128 negative decimal"),
            ("u128", '"340282366920938463463374607431768211455"', True, None, "u128 decimal upper bound"),
            ("u128", '"340282366920938463463374607431768211456"', False, "above the maximum", "u128 decimal above upper bound"),
            ("u128", f'"{hex(2**128 - 1)}"', True, None, "u128 hex upper bound"),

            ("i256", f'"{-(2**255)}"', True, None, "i256 decimal lower bound"),
            ("i256", f'"{-(2**255) - 1}"', False, "below the minimum", "i256 decimal below lower bound"),
            ("i256", f'"{2**255 - 1}"', True, None, "i256 decimal upper bound"),
            ("i256", f'"{2**255}"', False, "above the maximum", "i256 decimal above upper bound"),
            ("i256", f'"{hex(2**255 - 1)}"', True, None, "i256 hex upper bound"),
            ("i256", f'"-{hex(2**255)}"', True, None, "i256 hex lower bound"),

            ("u256", '"0"', True, None, "u256 decimal lower bound"),
            ("u256", '"-1"', False, "must not be negative", "u256 negative decimal"),
            ("u256", f'"{2**256 - 1}"', True, None, "u256 decimal upper bound"),
            ("u256", f'"{2**256}"', False, "above the maximum", "u256 decimal above upper bound"),
            ("u256", f'"{hex(2**256 - 1)}"', True, None, "u256 hex upper bound"),
        ]

        for kind, val_repr, is_accepted, expected_fragment, label in rows:
            with self.subTest(label=label, kind=kind, val_repr=val_repr):
                content = make_arg_fx(kind, val_repr)
                report = validate_fixture_content(content)
                if is_accepted:
                    self.assertEqual(report.errors, [], f"expected {label} to be accepted: {report.errors}")
                else:
                    self.assertTrue(
                        any(expected_fragment in e for e in report.errors),
                        f"expected {expected_fragment!r} in errors for {label}, got: {report.errors}",
                    )

    def test_soroban_nesting_depth_exact_limits(self) -> None:
        """Test vec and map nesting depth at exact limits of 8 (accepted) and 9 (rejected) (F-124, issue #420)."""
        def to_toml_val(obj: object) -> str:
            if isinstance(obj, dict):
                items = [f"{k} = {to_toml_val(v)}" for k, v in obj.items()]
                return "{ " + ", ".join(items) + " }"
            elif isinstance(obj, list):
                items = [to_toml_val(x) for x in obj]
                return "[ " + ", ".join(items) + " ]"
            elif isinstance(obj, str):
                return json.dumps(obj)
            elif isinstance(obj, int):
                return str(obj)
            raise ValueError(f"unsupported type {type(obj)}")

        def make_fixture(kind: str, val_repr: str) -> str:
            return f"""
id = "test-soroban-fixture"
protocol = 28
surface = "soroban"
category = "smoke"
description = "test fixture"
source_reference = "CAP-0083"

source_account = "{self.valid_source}"
contract_id = "{self.valid_contract}"
function = "transfer"
sequence_number = 1

[[args]]
kind = "{kind}"
value = {val_repr}

[expect]
kind = "simulation-success"
"""

        # Vec nesting depth
        def build_vec(depth: int) -> list:
            val = [{"kind": "u32", "value": 1}]
            for _ in range(depth - 1):
                val = [{"kind": "vec", "value": val}]
            return val

        # Vec depth 8: accepted
        rep_vec8 = validate_fixture_content(make_fixture("vec", to_toml_val(build_vec(8))))
        self.assertEqual(rep_vec8.errors, [], f"vec depth 8 failed: {rep_vec8.errors}")

        # Vec depth 9: rejected
        rep_vec9 = validate_fixture_content(make_fixture("vec", to_toml_val(build_vec(9))))
        self.assertTrue(
            any("vec/map arguments are nested deeper than the limit of 8 levels" in e for e in rep_vec9.errors),
            f"expected depth 9 rejection, got: {rep_vec9.errors}",
        )

        # Map nesting depth
        def build_map(depth: int) -> list:
            val = [{"key": {"kind": "symbol", "value": "x"}, "value": {"kind": "u32", "value": 1}}]
            for i in range(depth - 1):
                val = [{"key": {"kind": "symbol", "value": f"k{i}"}, "value": {"kind": "map", "value": val}}]
            return val

        # Map depth 8: accepted
        rep_map8 = validate_fixture_content(make_fixture("map", to_toml_val(build_map(8))))
        self.assertEqual(rep_map8.errors, [], f"map depth 8 failed: {rep_map8.errors}")

        # Map depth 9: rejected
        rep_map9 = validate_fixture_content(make_fixture("map", to_toml_val(build_map(9))))
        self.assertTrue(
            any("vec/map arguments are nested deeper than the limit of 8 levels" in e for e in rep_map9.errors),
            f"expected depth 9 rejection, got: {rep_map9.errors}",
        )

    def test_soroban_protocol_positive_integer_limits(self) -> None:
        """Test protocol field positive integer limits: 1 accepted, 0 and negative rejected (F-124, issue #420)."""
        def make_proto_fx(protocol: int) -> str:
            return f"""
id = "test-soroban-fixture"
protocol = {protocol}
surface = "soroban"
category = "smoke"
description = "test fixture"
source_reference = "CAP-0083"

source_account = "{self.valid_source}"
contract_id = "{self.valid_contract}"
function = "transfer"
sequence_number = 1

[expect]
kind = "simulation-success"
"""

        # Protocol 1: accepted
        rep1 = validate_fixture_content(make_proto_fx(1))
        self.assertEqual(rep1.errors, [])

        # Protocol 0: rejected
        rep0 = validate_fixture_content(make_proto_fx(0))
        self.assertTrue(
            any("field 'protocol' must be a positive integer" in e for e in rep0.errors),
            rep0.errors,
        )

        # Protocol -1: rejected
        rep_neg = validate_fixture_content(make_proto_fx(-1))
        self.assertTrue(
            any("field 'protocol' must be a positive integer" in e for e in rep_neg.errors),
            rep_neg.errors,
        )


class TestEngineSorobanVerification(unittest.TestCase):
    def test_engine_rejects_four_failing_cases(self) -> None:
        """If STELLAR_CANARY_BIN is set, verify that stellar-canary check rejects the 4 failing cases."""
        engine_bin = os.environ.get("STELLAR_CANARY_BIN")
        if not engine_bin or not os.path.exists(engine_bin):
            self.skipTest("STELLAR_CANARY_BIN is not set or does not exist")

        valid_source = encode_strkey(6 << 3, b"\x01" * 32)
        valid_contract = encode_strkey(2 << 3, b"\x02" * 32)

        failing_cases = [
            ("GNOTAKEY", valid_contract, "transfer"),
            (valid_source, "CNOTAKEY", "transfer"),
            (valid_source, valid_contract, "a" * 33),
            (valid_source, valid_contract, "é" * 17),
        ]

        for src, contract, func in failing_cases:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                (work / ".stellar-canary.toml").write_text(
                    "version = 1\nprotocol = 28\n\n[tests]\nxdr = false\nrpc = false\nsoroban = true\n",
                    encoding="utf-8",
                )
                pack = work / "pack"
                fx_dir = pack / "soroban"
                fx_dir.mkdir(parents=True, exist_ok=True)
                (fx_dir / "test.toml").write_text(
                    make_soroban_fixture(
                        source_account=src,
                        contract_id=contract,
                        function=func,
                    ),
                    encoding="utf-8",
                )

                proc = subprocess.run(
                    [
                        engine_bin,
                        "check",
                        "--fixtures-dir",
                        str(pack),
                        "--protocol",
                        "28",
                        "--json",
                        "--no-cache",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=work,
                )
                try:
                    data = json.loads(proc.stdout)
                except Exception as e:
                    self.fail(f"failed to parse stellar-canary output: {e}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
                results = data.get("results", [])
                self.assertTrue(results, f"no results in output: {data}")
                self.assertEqual(
                    results[0].get("summary"),
                    "failed to build the invocation transaction envelope",
                    f"unexpected summary in result: {results[0]}",
                )


if __name__ == "__main__":
    unittest.main()
