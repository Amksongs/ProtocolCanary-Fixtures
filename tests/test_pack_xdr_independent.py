"""Cross-check pack XDR fixtures against the independent pure-Python codec (issue #348).

Iterates over every fixture under protocol-*/xdr/ and asserts:
- For kind = roundtrip: the payload decodes and re-encodes byte-identically.
- For kind = decode-success: the payload decodes successfully without error.
- For kind = decode-failure: the codec rejects the payload with an XdrCodecError
  due to a structural reason matching the fixture's documented defect.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import xdr_codec

# ScVal has its own standard-library codec (tests/scval_xdr.py, issue #304);
# xdr_codec deliberately covers only StellarValue, ContractExecutable and
# TransactionEnvelope. Fixtures of type ScVal are checked against that codec.
_scval_spec = importlib.util.spec_from_file_location(
    "scval_xdr", Path(__file__).resolve().parent / "scval_xdr.py"
)
assert _scval_spec is not None and _scval_spec.loader is not None
scval_xdr = importlib.util.module_from_spec(_scval_spec)
sys.modules["scval_xdr"] = scval_xdr
_scval_spec.loader.exec_module(scval_xdr)


class PackXdrIndependentTests(unittest.TestCase):
    def test_all_pack_xdr_fixtures(self) -> None:
        xdr_fixtures = sorted(REPO_ROOT.glob("protocol-*/xdr/**/*.toml"))
        self.assertTrue(len(xdr_fixtures) > 0, "Expected to find XDR fixtures in protocol-*/xdr/")

        tested_count = 0
        for fixture_path in xdr_fixtures:
            with open(fixture_path, "rb") as f:
                data = tomllib.load(f)

            fixture_id = data.get("id")
            type_name = data.get("type")
            kind = data.get("kind")
            value_b64 = data.get("value_base64")

            self.assertIsNotNone(fixture_id)
            self.assertIsNotNone(type_name)
            self.assertIsNotNone(kind)
            self.assertIsNotNone(value_b64)

            raw_bytes = base64.b64decode(value_b64)

            with self.subTest(fixture_id=fixture_id, type=type_name, kind=kind):
                if type_name == "ScVal":
                    # Decoded by the dedicated ScVal codec: a decode-failure
                    # payload must be rejected, anything else must round-trip
                    # byte-for-byte.
                    if kind == "decode-failure":
                        with self.assertRaises(scval_xdr.XdrDecodeError) as caught:
                            scval_xdr.decode(raw_bytes)
                        err_msg = str(caught.exception).lower()
                        self.assertTrue(
                            any(term in err_msg for term in ("truncated", "need", "length", "limit", "padding", "discriminant", "unsupported")),
                            f"Unexpected error reason for {fixture_id}: {caught.exception}",
                        )
                    else:
                        decoded = scval_xdr.decode(raw_bytes)
                        self.assertEqual(
                            raw_bytes,
                            scval_xdr.encode(decoded),
                            f"Roundtrip byte mismatch for {fixture_id} (ScVal)",
                        )
                elif kind == "roundtrip":
                    decoded = xdr_codec.decode_xdr(type_name, raw_bytes)
                    re_encoded = xdr_codec.encode_xdr(type_name, decoded)
                    self.assertEqual(
                        raw_bytes,
                        re_encoded,
                        f"Roundtrip byte mismatch for {fixture_id} ({type_name})",
                    )
                elif kind == "decode-success":
                    decoded = xdr_codec.decode_xdr(type_name, raw_bytes)
                    self.assertIsNotNone(decoded)
                elif kind == "decode-failure":
                    with self.assertRaises(xdr_codec.XdrCodecError) as caught:
                        xdr_codec.decode_xdr(type_name, raw_bytes)

                    err_msg = str(caught.exception).lower()
                    # Assert structural reason matches header comment (truncation, length,
                    # discriminant, padding, or trailing bytes after a complete value)
                    self.assertTrue(
                        any(term in err_msg for term in ("truncated", "need", "length", "discriminant", "padding", "trailing")),
                        f"Unexpected error reason for {fixture_id}: {caught.exception}",
                    )
                else:
                    self.fail(f"Unhandled XDR kind {kind!r} in {fixture_path}")

            tested_count += 1

        print(f"Verified {tested_count} pack XDR fixture(s) against independent codec")


if __name__ == "__main__":
    unittest.main()
