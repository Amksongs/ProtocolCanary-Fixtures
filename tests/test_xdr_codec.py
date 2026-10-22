"""Unit tests for independent pure-Python XDR codec (issue #348)."""
from __future__ import annotations

import base64
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import xdr_codec


class XdrCodecUnitTests(unittest.TestCase):
    def test_stellar_value_basic_roundtrip(self) -> None:
        raw_b64 = "EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA"
        raw = base64.b64decode(raw_b64)
        val = xdr_codec.decode_stellar_value(raw)
        self.assertEqual(val.ext.ext_type, xdr_codec.STELLAR_VALUE_BASIC)
        re_encoded = xdr_codec.encode_stellar_value(val)
        self.assertEqual(raw, re_encoded)

    def test_stellar_value_signed_roundtrip(self) -> None:
        raw_b64 = "EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAABAAAAACIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiAAAAQDMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzM="
        raw = base64.b64decode(raw_b64)
        val = xdr_codec.decode_stellar_value(raw)
        self.assertEqual(val.ext.ext_type, xdr_codec.STELLAR_VALUE_SIGNED)
        re_encoded = xdr_codec.encode_stellar_value(val)
        self.assertEqual(raw, re_encoded)

    def test_stellar_value_empty_tx_set_roundtrip(self) -> None:
        raw_b64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaIwDgAAAAAAAAAACEREREREREREREREREREREREREREREREREREREREREREiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIgAAABwAAAAAMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMAAABARERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERERA=="
        raw = base64.b64decode(raw_b64)
        val = xdr_codec.decode_stellar_value(raw)
        self.assertEqual(val.ext.ext_type, xdr_codec.STELLAR_VALUE_EMPTY_TX_SET)
        re_encoded = xdr_codec.encode_stellar_value(val)
        self.assertEqual(raw, re_encoded)

    def test_contract_executable_wasm_roundtrip(self) -> None:
        raw_b64 = "AAAAAKurq6urq6urq6urq6urq6urq6urq6urq6urq6urq6ur"
        raw = base64.b64decode(raw_b64)
        val = xdr_codec.decode_contract_executable(raw)
        self.assertEqual(val.executable_type, xdr_codec.CONTRACT_EXECUTABLE_WASM)
        re_encoded = xdr_codec.encode_contract_executable(val)
        self.assertEqual(raw, re_encoded)

    def test_contract_executable_stellar_asset_roundtrip(self) -> None:
        raw_b64 = "AAAAAQ=="
        raw = base64.b64decode(raw_b64)
        val = xdr_codec.decode_contract_executable(raw)
        self.assertEqual(val.executable_type, xdr_codec.CONTRACT_EXECUTABLE_STELLAR_ASSET)
        re_encoded = xdr_codec.encode_contract_executable(val)
        self.assertEqual(raw, re_encoded)

    def test_contract_executable_external_ref_roundtrip(self) -> None:
        raw_b64 = "AAAAAgAAAAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQAAAAhmbGVldC12MQ=="
        raw = base64.b64decode(raw_b64)
        val = xdr_codec.decode_contract_executable(raw)
        self.assertEqual(val.executable_type, xdr_codec.CONTRACT_EXECUTABLE_EXTERNAL_REF)
        self.assertEqual(val.external_ref.tag, "fleet-v1")
        re_encoded = xdr_codec.encode_contract_executable(val)
        self.assertEqual(raw, re_encoded)

    def test_truncation_at_every_byte_offset(self) -> None:
        # Test on both StellarValue and ContractExecutable
        fixtures = [
            ("StellarValue", base64.b64decode("EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA")),
            ("ContractExecutable", base64.b64decode("AAAAAgAAAAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQAAAAhmbGVldC12MQ==")),
        ]
        for type_name, full_bytes in fixtures:
            for length in range(len(full_bytes)):
                truncated = full_bytes[:length]
                with self.assertRaises(xdr_codec.XdrCodecError, msg=f"{type_name} cut at offset {length}"):
                    xdr_codec.decode_xdr(type_name, truncated)

    def test_trailing_bytes_rejected(self) -> None:
        raw = base64.b64decode("AAAAAQ==")  # ContractExecutable StellarAsset (4 bytes)
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_contract_executable(raw + b"\x00")

    def test_unknown_discriminants_rejected(self) -> None:
        # ContractExecutable discriminant 99
        bad_exec = (99).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_contract_executable(bad_exec)

        # StellarValue ext discriminant 99
        # 32 bytes txSetHash + 8 bytes closeTime + 4 bytes upgrades(0) + 4 bytes ext(99)
        bad_sv = (b"\x11" * 32) + (100).to_bytes(8, "big") + (0).to_bytes(4, "big") + (99).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_stellar_value(bad_sv)

    def test_non_zero_padding_rejected(self) -> None:
        # String length 3, followed by 3 chars, plus 1 padding byte which must be 0
        writer = xdr_codec.XdrWriter()
        # ContractExecutable ExternalRef
        # Disc 2, SCAddress contract (1) + 32 bytes, string len 3 + "tag" + pad 0x01
        data = (
            (2).to_bytes(4, "big")
            + (1).to_bytes(4, "big")
            + (b"\x55" * 32)
            + (3).to_bytes(4, "big")
            + b"tag\x01"  # non-zero padding byte
        )
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_contract_executable(data)

    def test_length_prefix_larger_than_input(self) -> None:
        # Length prefix claims 1000 bytes, but buffer has 4 bytes
        bad_len = (2).to_bytes(4, "big") + (1).to_bytes(4, "big") + (b"\x55" * 32) + (1000).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_contract_executable(bad_len)

    def test_flipped_bits_rejected(self) -> None:
        # Test flipping bits in StellarValue basic
        valid = base64.b64decode("EREREREREREREREREREREREREREREREREREREREREREAAAAAaOd4AAAAAAAAAAAA")
        # Flip bit in upgrades count (offset 43) -> count becomes 1, input lacks upgrade entry
        corrupted = bytearray(valid)
        corrupted[43] ^= 1
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_stellar_value(bytes(corrupted))

        # Flip bit in ext discriminant (offset 47) -> becomes discriminant 1 (SIGNED), lacks signature
        corrupted2 = bytearray(valid)
        corrupted2[47] ^= 1
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_stellar_value(bytes(corrupted2))


class TransactionEnvelopeCodecTests(unittest.TestCase):
    """Codec-level tests for the TransactionEnvelope codec (F-089).

    The round-trip payloads are the pack's own crate-produced fixtures
    (``protocol-28/xdr/transaction-envelope/*.toml``): each ``value_base64``
    was produced by the official ``stellar-xdr`` 28.0.1 crate (features
    base64 and alloc) from the typed value whose generating expression is
    recorded in the fixture's header comment.  The fixture headers are the
    single source of truth for the bytes, so this file does not duplicate
    them.  The full generating program is quoted in the pull request that
    adds the fixtures.
    """

    FIXTURE_DIR = REPO_ROOT / "protocol-28" / "xdr" / "transaction-envelope"

    def _fixture_bytes(self, name: str) -> bytes:
        path = self.FIXTURE_DIR / name
        with open(path, "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["type"], "TransactionEnvelope")
        return base64.b64decode(data["value_base64"])

    def test_pack_roundtrip_fixtures_decode_and_re_encode(self) -> None:
        fixtures = {
            "p28-xdr-transaction-envelope-v0-roundtrip.toml": xdr_codec.ENVELOPE_TYPE_TX_V0,
            "p28-xdr-transaction-envelope-v1-roundtrip.toml": xdr_codec.ENVELOPE_TYPE_TX,
            "p28-xdr-transaction-envelope-soroban-invoke-roundtrip.toml": xdr_codec.ENVELOPE_TYPE_TX,
            "p28-xdr-transaction-envelope-fee-bump-roundtrip.toml": xdr_codec.ENVELOPE_TYPE_TX_FEE_BUMP,
        }
        for name, envelope_type in fixtures.items():
            with self.subTest(fixture=name):
                raw = self._fixture_bytes(name)
                envelope = xdr_codec.decode_xdr("TransactionEnvelope", raw)
                self.assertEqual(envelope.envelope_type, envelope_type)
                self.assertEqual(
                    xdr_codec.encode_xdr("TransactionEnvelope", envelope), raw
                )

    def test_v0_envelope_fields(self) -> None:
        raw = self._fixture_bytes("p28-xdr-transaction-envelope-v0-roundtrip.toml")
        envelope = xdr_codec.decode_transaction_envelope(raw)
        tx = envelope.v0.tx
        self.assertEqual(tx.fee, 100)
        self.assertEqual(tx.seq_num, 1_234_567)
        self.assertEqual(tx.memo.memo_type, xdr_codec.MEMO_NONE)
        self.assertIsNotNone(tx.time_bounds)
        self.assertEqual(tx.time_bounds.max_time, 1_760_000_000)
        self.assertEqual(len(tx.operations), 1)
        payment = tx.operations[0].body.payment
        self.assertEqual(tx.operations[0].body.op_type, xdr_codec.OPERATION_TYPE_PAYMENT)
        self.assertEqual(payment.amount, 1_000)
        self.assertEqual(payment.asset.asset_type, xdr_codec.ASSET_TYPE_NATIVE)

    def test_fee_bump_envelope_nests_an_inner_v1_envelope(self) -> None:
        raw = self._fixture_bytes("p28-xdr-transaction-envelope-fee-bump-roundtrip.toml")
        envelope = xdr_codec.decode_transaction_envelope(raw)
        fee_bump = envelope.fee_bump.tx
        self.assertEqual(fee_bump.fee, 200_000)
        self.assertEqual(
            fee_bump.inner_tx.tx.source_account.key_type, xdr_codec.KEY_TYPE_ED25519
        )
        self.assertEqual(fee_bump.inner_tx.tx.ext.ext_type, 0)

    def test_soroban_envelope_decodes_resources(self) -> None:
        raw = self._fixture_bytes(
            "p28-xdr-transaction-envelope-soroban-invoke-roundtrip.toml"
        )
        envelope = xdr_codec.decode_transaction_envelope(raw)
        tx = envelope.v1.tx
        self.assertEqual(tx.ext.ext_type, 1)
        soroban = tx.ext.soroban_data
        self.assertEqual(soroban.resource_fee, 1_000)
        self.assertEqual(soroban.resources.instructions, 1_000)
        self.assertEqual(soroban.resources.disk_read_bytes, 100)
        self.assertEqual(soroban.resources.write_bytes, 100)
        invoke = tx.operations[0].body.invoke_host_function
        self.assertEqual(
            invoke.host_function.host_function_type,
            xdr_codec.HOST_FUNCTION_TYPE_INVOKE_CONTRACT,
        )
        self.assertEqual(invoke.host_function.invoke_contract.function_name, "hello")

    def test_truncation_at_every_byte_offset(self) -> None:
        for name in (
            "p28-xdr-transaction-envelope-v0-roundtrip.toml",
            "p28-xdr-transaction-envelope-v1-roundtrip.toml",
            "p28-xdr-transaction-envelope-soroban-invoke-roundtrip.toml",
            "p28-xdr-transaction-envelope-fee-bump-roundtrip.toml",
        ):
            full = self._fixture_bytes(name)
            for length in range(len(full)):
                with self.subTest(fixture=name, offset=length):
                    with self.assertRaises(xdr_codec.XdrCodecError):
                        xdr_codec.decode_xdr("TransactionEnvelope", full[:length])

    def test_trailing_bytes_rejected(self) -> None:
        raw = self._fixture_bytes("p28-xdr-transaction-envelope-v1-roundtrip.toml")
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_xdr("TransactionEnvelope", raw + b"\x00")

    def test_unknown_envelope_type_rejected(self) -> None:
        raw = self._fixture_bytes("p28-xdr-transaction-envelope-v1-roundtrip.toml")
        mutated = bytearray(raw)
        mutated[0:4] = (63).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError) as caught:
            xdr_codec.decode_xdr("TransactionEnvelope", bytes(mutated))
        self.assertIn("discriminant", str(caught.exception))

    def test_unsupported_operation_arm_rejected(self) -> None:
        # OperationType 8 is ACCOUNT_MERGE, an arm the codec does not model.
        raw = self._fixture_bytes("p28-xdr-transaction-envelope-v0-roundtrip.toml")
        mutated = bytearray(raw)
        mutated[80:84] = (8).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError) as caught:
            xdr_codec.decode_xdr("TransactionEnvelope", bytes(mutated))
        self.assertIn("unsupported OperationType arm", str(caught.exception))

    def test_unsupported_preconditions_arm_rejected(self) -> None:
        # PreconditionType 2 is PRECOND_V2, an arm the codec does not model.
        raw = self._fixture_bytes("p28-xdr-transaction-envelope-v1-roundtrip.toml")
        mutated = bytearray(raw)
        mutated[52:56] = (2).to_bytes(4, "big")
        with self.assertRaises(xdr_codec.XdrCodecError) as caught:
            xdr_codec.decode_xdr("TransactionEnvelope", bytes(mutated))
        self.assertIn("unsupported Preconditions arm", str(caught.exception))

    def test_unsupported_type_name_rejected(self) -> None:
        with self.assertRaises(xdr_codec.XdrCodecError):
            xdr_codec.decode_xdr("LedgerEntry", b"\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
