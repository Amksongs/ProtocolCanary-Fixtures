"""Error-branch tests for Soroban ``[[args]]`` and StrKey validation (issue #413, F-120).

Issue #413's branch-coverage run showed that the rules below are never
executed by any test, so a refactor could change or drop them unnoticed.
Every row here is a small fixture with exactly one defect, the exact
message fragment the validator must report, and the one-line reason the
rule exists; every rejected row has a valid twin that differs only in the
defect, so a test cannot pass by rejecting everything.

Covered branches (function names, since line numbers move):

- ``_wide_integer_problem``: a literal that is not a string, a leading
  ``+`` sign, a negative value for an unsigned kind;
- ``_bytes_problem``: a length that is not a multiple of 4, more than two
  ``=`` padding characters;
- ``_validate_soroban_arg``: an entry that is not a table, a kind that is
  not a string;
- ``_validate_soroban_arg_value``: a non-integer duration, and a
  non-string symbol, bytes or address value, and a map item that is not a
  table;
- ``decode_strkey``: the wrong prefix and the wrong version byte.

The StrKey rows never invent addresses: each starts from the real
``G...``/``C...`` values that ``protocol-28/soroban/`` fixtures already
ship and changes exactly one property (the prefix character, or the
version byte with the checksum recomputed so the version byte is the only
semantic defect).

The engine cross-check at the bottom runs only when ``STELLAR_CANARY_BIN``
names a built ``stellar-canary`` and is skipped otherwise; it never
downloads or builds an engine. ``tools/validate/validate.py`` is not
modified by anything in this file.

Run with: python3 -m unittest tests.test_validate_soroban_args_errors
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"

_spec = importlib.util.spec_from_file_location(
    "validate_soroban_args_errors_target", VALIDATE_PATH
)
validate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["validate_soroban_args_errors_target"] = validate
_spec.loader.exec_module(validate)

STELLAR_CANARY_BIN = os.environ.get("STELLAR_CANARY_BIN")

# A real, already-valid pack fixture, so the StrKey rows below start from
# addresses the repository actually ships (issue #413: "do not invent
# addresses that look valid").
REAL_FIXTURE = (
    REPO_ROOT / "protocol-28" / "soroban" / "p28-soroban-sim-error-unknown-function.toml"
)


def real_strkeys() -> tuple[str, str]:
    """The (source_account, contract_id) pair a real pack fixture uses."""
    data = tomllib.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
    return data["source_account"], data["contract_id"]


def rekey_version(encoded: str, version_byte: int) -> str:
    """Re-encode a real strkey with a different version byte and a fresh CRC.

    The prefix character is unchanged (the G... version byte 6 << 3 = 48
    and its neighbours 49-51 all base32-encode to 'G...'; likewise C...
    for 16-19), so the only defect the validator can see is the version
    byte itself.
    """
    raw = bytearray(base64.b32decode(encoded))
    raw[0] = version_byte
    body = bytes(raw[:33])
    crc = validate.crc16_xmodem(body)
    return base64.b32encode(body + crc.to_bytes(2, "little")).decode("ascii")


def soroban_fixture(source_account: str, contract_id: str, args_toml: str = "") -> str:
    return f"""\
id = "p28-soroban-arg-branch"
protocol = 28
surface = "soroban"
category = "smoke"
description = "issue #413 error-branch row"
source_reference = "CAP-0083"

source_account = "{source_account}"
contract_id = "{contract_id}"
function = "transfer"
sequence_number = 1

{args_toml}
[expect]
kind = "simulation-success"
"""


def validate_content(content: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "fixture.toml").write_text(content, encoding="utf-8")
        return validate.validate_directory(root).errors


class Row:
    """One rule: a valid twin, a defective fixture, the message, the reason."""

    def __init__(
        self,
        label: str,
        why: str,
        expected: str | tuple[str, ...],
    ) -> None:
        self.label = label
        self.why = why
        self.expected = expected

    @property
    def fragments(self) -> tuple[str, ...]:
        return (self.expected,) if isinstance(self.expected, str) else self.expected

    def good_content(self, real: tuple[str, str]) -> str:
        raise NotImplementedError

    def bad_content(self, real: tuple[str, str]) -> str:
        raise NotImplementedError


class ArgRow(Row):
    """An ``[[args]]`` row; the pair differs only in the defective value."""

    def __init__(
        self,
        label: str,
        why: str,
        good_args: str,
        bad_args: str,
        expected: str | tuple[str, ...],
    ) -> None:
        super().__init__(label, why, expected)
        self.good_args = good_args
        self.bad_args = bad_args

    def good_content(self, real: tuple[str, str]) -> str:
        return soroban_fixture(*real, self.good_args)

    def bad_content(self, real: tuple[str, str]) -> str:
        return soroban_fixture(*real, self.bad_args)


ARG_ROWS = [
    ArgRow(
        label="wide-integer literal is not a string",
        why="u128/i128/u256/i256 literals travel as strings; _wide_integer_problem "
        "rejects any other TOML type before parsing (mirrors parse_*_literal)",
        good_args='[[args]]\nkind = "u128"\nvalue = "5"\n',
        bad_args='[[args]]\nkind = "u128"\nvalue = 5\n',
        expected="args[0].value: kind 'u128' requires a decimal or 0x-prefixed "
        "hex string, got int",
    ),
    ArgRow(
        label="leading plus sign is part of the accepted literal grammar",
        why="an optional sign starts the literal the engine's split_integer_"
        "literal accepts; '+5' must parse and a lone '+' must not",
        good_args='[[args]]\nkind = "u128"\nvalue = "+5"\n',
        bad_args='[[args]]\nkind = "u128"\nvalue = "+"\n',
        expected="args[0].value: kind 'u128' requires a decimal or 0x-prefixed "
        "hex string, got '+'",
    ),
    ArgRow(
        label="negative literal for an unsigned kind",
        why="an unsigned kind's range starts at 0, so '-' is rejected by value "
        "rather than reported as below the minimum",
        good_args='[[args]]\nkind = "u128"\nvalue = "1"\n',
        bad_args='[[args]]\nkind = "u128"\nvalue = "-1"\n',
        expected="args[0].value: kind 'u128' must not be negative, got '-1'",
    ),
    ArgRow(
        label="bytes literal length is not a multiple of 4",
        why="the engine's decode_base64 accepts only standard padded base64, "
        "whose length is a multiple of 4",
        good_args='[[args]]\nkind = "bytes"\nvalue = "AAAA"\n',
        bad_args='[[args]]\nkind = "bytes"\nvalue = "AAAAA"\n',
        expected="args[0].value base64 string length must be a multiple of 4 "
        "(use '=' padding), got 'AAAAA'",
    ),
    ArgRow(
        label="bytes literal has more than two padding characters",
        why="at most two '=' characters are valid base64 padding; 'A===' would "
        "otherwise reach the engine's decode_base64",
        good_args='[[args]]\nkind = "bytes"\nvalue = "AA=="\n',
        bad_args='[[args]]\nkind = "bytes"\nvalue = "A==="\n',
        expected="args[0].value base64 string has too much padding ('A===')",
    ),
    ArgRow(
        label="argument entry is not a table",
        why="canary-soroban parses every args entry as a { kind, value } table "
        "(CONTRIBUTING.md's per-surface body table)",
        good_args='[[args]]\nkind = "u32"\nvalue = 1\n',
        bad_args='args = ["nope"]\n',
        expected="args[0] must be a table with 'kind' and 'value' keys, got str",
    ),
    ArgRow(
        label="argument kind is not a string",
        why="kind selects the ScVal constructor and is read as a string; a "
        "TOML integer cannot name one",
        good_args='[[args]]\nkind = "u32"\nvalue = 1\n',
        bad_args='[[args]]\nkind = 3\nvalue = 1\n',
        expected=(
            "args[0] must define a string 'kind'; expected one of",
            "got 3",
        ),
    ),
    ArgRow(
        label="duration value is not an integer",
        why="duration/timepoint encode a UInt64 seconds count; a string is not "
        "an integer",
        good_args='[[args]]\nkind = "duration"\nvalue = 5\n',
        bad_args='[[args]]\nkind = "duration"\nvalue = "5"\n',
        expected="args[0].value for kind 'duration' must be a non-negative "
        "integer, got str",
    ),
    ArgRow(
        label="symbol value is not a string",
        why="an ScSymbol is text; a TOML integer cannot become one",
        good_args='[[args]]\nkind = "symbol"\nvalue = "ok"\n',
        bad_args='[[args]]\nkind = "symbol"\nvalue = 5\n',
        expected="args[0].value for kind 'symbol' must be a string, got int",
    ),
    ArgRow(
        label="bytes value is not a string",
        why="bytes travel as a base64/hex string literal, never a TOML integer",
        good_args='[[args]]\nkind = "bytes"\nvalue = "AAAA"\n',
        bad_args='[[args]]\nkind = "bytes"\nvalue = 123\n',
        expected="args[0].value for kind 'bytes' must be a string, got int",
    ),
    ArgRow(
        label="address value is not a string",
        why="an address is a G.../C... strkey string; a TOML boolean is not",
        good_args='[[args]]\nkind = "address"\nvalue = "'
        f'{real_strkeys()[0]}"\n',
        bad_args='[[args]]\nkind = "address"\nvalue = true\n',
        expected="args[0].value for kind 'address' must be a string, got bool",
    ),
    ArgRow(
        label="map item is not a table",
        why="each map item is a { key, value } table of argument entries, per "
        "CONTRIBUTING.md's map row",
        good_args='[[args]]\nkind = "map"\nvalue = [{ key = { kind = "symbol", '
        'value = "k" }, value = { kind = "u32", value = 1 } }]\n',
        bad_args='[[args]]\nkind = "map"\nvalue = ["x"]\n',
        expected="args[0].value[0] must be a table with 'key' and 'value' "
        "entries, got str",
    ),
]


class StrKeyRow(Row):
    """A StrKey row whose valid twin is a real pack address, unmodified."""

    def __init__(
        self,
        label: str,
        why: str,
        field: str,
        good: str,
        bad: str,
        expected: str,
        must_keep_prefix: str | None = None,
    ) -> None:
        super().__init__(label, why, expected)
        self.field = field
        self.good = good
        self.bad = bad
        self.must_keep_prefix = must_keep_prefix

    def good_content(self, real: tuple[str, str]) -> str:
        source_account, contract_id = real
        if self.field == "source_account":
            return soroban_fixture(self.good, contract_id)
        return soroban_fixture(source_account, self.good)

    def bad_content(self, real: tuple[str, str]) -> str:
        source_account, contract_id = real
        if self.field == "source_account":
            return soroban_fixture(self.bad, contract_id)
        return soroban_fixture(source_account, self.bad)


def strkey_rows() -> list[StrKeyRow]:
    real_source, real_contract = real_strkeys()
    return [
        StrKeyRow(
            label="source_account carries a C... prefix",
            why="source_account is an account (version byte 6 << 3); a contract "
            "strkey is the wrong prefix, not a bad checksum",
            field="source_account",
            good=real_source,
            bad="C" + real_source[1:],
            expected="field 'source_account' is not a valid G... strkey: wrong "
            "prefix: expected G... account strkey, got C... contract",
        ),
        StrKeyRow(
            label="contract_id carries a G... prefix",
            why="contract_id is a contract (version byte 2 << 3); an account "
            "strkey is the wrong prefix",
            field="contract_id",
            good=real_contract,
            bad="G" + real_contract[1:],
            expected="field 'contract_id' is not a valid C... strkey: wrong "
            "prefix: expected C... contract strkey, got G... account",
        ),
        StrKeyRow(
            label="source_account carries an M... prefix",
            why="muxed accounts have no place in a Soroban invocation; decode_"
            "strkey names them explicitly before any decoding",
            field="source_account",
            good=real_source,
            bad="M" + real_source[1:],
            expected="field 'source_account' is not a valid G... strkey: wrong "
            "prefix: muxed account (M...) not supported",
        ),
        StrKeyRow(
            label="source_account version byte is not 48",
            why="the G... version byte is 6 << 3 = 48; 49 still base32-encodes "
            "to a G... prefix and carries a valid checksum, so only the "
            "version-byte check catches it",
            field="source_account",
            good=real_source,
            bad=rekey_version(real_source, 49),
            expected="field 'source_account' is not a valid G... strkey: wrong "
            "prefix / version byte: expected 48, got 49",
            must_keep_prefix="G",
        ),
        StrKeyRow(
            label="contract_id version byte is not 16",
            why="the C... version byte is 2 << 3 = 16; 17 keeps the C... prefix "
            "and a valid checksum, so only the version-byte check catches it",
            field="contract_id",
            good=real_contract,
            bad=rekey_version(real_contract, 17),
            expected="field 'contract_id' is not a valid C... strkey: wrong "
            "prefix / version byte: expected 16, got 17",
            must_keep_prefix="C",
        ),
    ]


class SorobanArgErrorBranchTests(unittest.TestCase):
    """Each rule is pinned by its exact message and a passing valid twin."""

    def test_valid_twins_pass(self) -> None:
        real = real_strkeys()
        for row in [*ARG_ROWS, *strkey_rows()]:
            with self.subTest(row=row.label):
                errors = validate_content(row.good_content(real))
                self.assertEqual(
                    errors,
                    [],
                    f"the valid twin for {row.label!r} must pass, got: {errors}",
                )

    def test_defective_rows_report_the_field_and_the_reason(self) -> None:
        real = real_strkeys()
        for row in [*ARG_ROWS, *strkey_rows()]:
            with self.subTest(row=row.label, why=row.why):
                errors = validate_content(row.bad_content(real))
                for fragment in row.fragments:
                    self.assertTrue(
                        any(fragment in e for e in errors),
                        f"expected {fragment!r} for {row.label!r} ({row.why}), "
                        f"got: {errors}",
                    )

    def test_strkey_rows_change_exactly_one_property(self) -> None:
        for row in strkey_rows():
            with self.subTest(row=row.label, why=row.why):
                self.assertNotEqual(row.bad, row.good)
                self.assertEqual(len(row.bad), len(row.good))
                if row.must_keep_prefix is not None:
                    # Version-byte rows: same prefix and the same 32-byte
                    # payload; only the version byte moved. Both values keep
                    # a valid CRC16, so the version byte is the only defect
                    # the validator can see.
                    good_raw = base64.b32decode(row.good)
                    bad_raw = base64.b32decode(row.bad)
                    self.assertEqual(row.good[0], row.must_keep_prefix)
                    self.assertEqual(row.bad[0], row.must_keep_prefix)
                    self.assertEqual(good_raw[1:33], bad_raw[1:33])
                    self.assertNotEqual(good_raw[0], bad_raw[0])
                    for raw in (good_raw, bad_raw):
                        self.assertEqual(
                            validate.crc16_xmodem(raw[:33]),
                            int.from_bytes(raw[33:35], "little"),
                        )
                else:
                    differing = [
                        i for i, (a, b) in enumerate(zip(row.good, row.bad)) if a != b
                    ]
                    self.assertEqual(
                        differing, [0], "only the prefix char may differ"
                    )


@unittest.skipUnless(
    STELLAR_CANARY_BIN,
    "STELLAR_CANARY_BIN is not set; skipping the optional engine cross-check",
)
class EngineCrossCheckTests(unittest.TestCase):
    """Replay every row against a real engine when one is available.

    The engine must reject each defective fixture the validator rejects: a
    load error (exit code 4, per docs/fixture-contract.md section 3) or a
    per-fixture failure whose summary differs from the valid twin's. No
    network beyond the deliberately unreachable RPC endpoint is needed,
    and no engine is ever downloaded or built.
    """

    def engine_verdict(self, content: str) -> tuple[int, str | None]:
        with (
            tempfile.TemporaryDirectory() as work,
            tempfile.TemporaryDirectory() as pack,
        ):
            (Path(pack) / "row.toml").write_text(content, encoding="utf-8")
            (Path(work) / ".stellar-canary.toml").write_text(
                "version = 1\nprotocol = 28\n\n"
                "[tests]\nxdr = false\nrpc = false\nsoroban = true\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    STELLAR_CANARY_BIN,
                    "check",
                    "--fixtures-dir",
                    pack,
                    "--protocol",
                    "28",
                    "--rpc-url",
                    "http://127.0.0.1:1",
                    "--rpc-timeout",
                    "1",
                    "--rpc-max-retries",
                    "0",
                    "--no-cache",
                    "--json",
                ],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=60,
            )
        summary = None
        try:
            results = json.loads(result.stdout).get("results", [])
        except Exception:  # noqa: BLE001 - unparseable output still fails the verdict
            results = []
        if results:
            summary = results[0].get("summary")
        return result.returncode, summary

    def assert_engine_rejects(self, row: Row, good: str, bad: str) -> None:
        good_rc, good_summary = self.engine_verdict(good)
        self.assertNotEqual(
            good_rc,
            4,
            f"the engine rejected the valid twin of {row.label!r} as an invalid "
            f"fixture (exit 4): summary={good_summary!r}",
        )
        bad_rc, bad_summary = self.engine_verdict(bad)
        rejected = bad_rc == 4 or bad_summary != good_summary
        self.assertTrue(
            rejected,
            f"the engine accepted {row.label!r} ({row.why}) although the "
            f"validator rejects it: rc={bad_rc} summary={bad_summary!r}; "
            f"twin: rc={good_rc} summary={good_summary!r}",
        )

    def test_engine_agrees_on_argument_rows(self) -> None:
        real = real_strkeys()
        for row in ARG_ROWS:
            with self.subTest(row=row.label):
                self.assert_engine_rejects(
                    row,
                    row.good_content(real),
                    row.bad_content(real),
                )

    def test_engine_agrees_on_strkey_rows(self) -> None:
        real = real_strkeys()
        for row in strkey_rows():
            with self.subTest(row=row.label):
                self.assert_engine_rejects(
                    row,
                    row.good_content(real),
                    row.bad_content(real),
                )


if __name__ == "__main__":
    unittest.main()
