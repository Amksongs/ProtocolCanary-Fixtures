"""ScVal recursion and depth-boundary conformance vectors (issue #303).

The pinned ``stellar-xdr = "=28.0.1"`` implementation exposes a configurable
``Limits::depth`` rather than a fixed ScVal nesting constant. These tests use
the exact configured boundary documented by the vector file and separately
prove that the default ``Limits::none()`` behavior accepts the deep valid
vectors. Malformed recursive payloads must fail even without a depth limit.

Run with: ``python3 -m unittest tests/test_scval_depth_vectors.py``
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEC_PATH = REPO_ROOT / "tests" / "scval_xdr.py"
VECTOR_PATH = REPO_ROOT / "tests" / "vectors" / "scval_depth" / "scval_depth.json"

_spec = importlib.util.spec_from_file_location("scval_depth_codec", CODEC_PATH)
scval_xdr = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
sys.modules["scval_depth_codec"] = scval_xdr
_spec.loader.exec_module(scval_xdr)


def load_vectors() -> dict:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


def vector_bytes(vector: dict) -> bytes:
    raw = vector["xdr_hex"]
    if len(raw) % 8 or not raw:
        raise AssertionError(f"{vector['name']}: XDR hex must be non-empty and 4-byte aligned")
    return bytes.fromhex(raw)


def container_depth(scval: tuple[str, object]) -> int:
    kind, value = scval
    if kind == "vec":
        if value is None or not value:
            return 1
        return 1 + max(container_depth(item) for item in value)
    if kind == "map":
        if value is None or not value:
            return 1
        return 1 + max(
            max(container_depth(key), container_depth(val)) for key, val in value
        )
    return 0


def follow_single_child(scval: tuple[str, object]) -> tuple[str, object]:
    """Follow the one-child path used by the deep Vec/Map vectors."""
    kind, value = scval
    if kind == "vec":
        if not isinstance(value, list) or len(value) != 1:
            return scval
        return follow_single_child(value[0])
    if kind == "map":
        if not isinstance(value, list) or len(value) != 1:
            return scval
        return follow_single_child(value[0][1])
    return scval


class ScValDepthVectorFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load_vectors()
        cls.vectors = cls.payload["vectors"]
        cls.by_name = {vector["name"]: vector for vector in cls.vectors}

    def test_source_and_configured_limit_are_pinned(self) -> None:
        self.assertIn("stellar-xdr", self.payload["source_reference"])
        self.assertEqual(self.payload["crate"]["version"], "28.0.1")
        self.assertEqual(self.payload["crate"]["limits_none_depth"], 2**32 - 1)
        self.assertEqual(self.payload["crate"]["configured_limits_depth"], 67)
        self.assertEqual(self.payload["crate"]["configured_container_depth"], 16)

    def test_vector_names_and_bytes_are_well_formed(self) -> None:
        self.assertEqual(len(self.vectors), len(self.by_name))
        for vector in self.vectors:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(len(vector["xdr_hex"]) % 8, 0)
                self.assertIsInstance(vector.get("note"), str)
                vector_bytes(vector)


class ScValDepthVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load_vectors()
        cls.vectors = cls.payload["vectors"]
        cls.by_name = {vector["name"]: vector for vector in cls.vectors}
        cls.decode_error = scval_xdr.XdrDecodeError

    def test_valid_vectors_decode_and_roundtrip(self) -> None:
        for vector in self.vectors:
            if vector["kind"] != "valid":
                continue
            with self.subTest(vector=vector["name"]):
                decoded = scval_xdr.decode(vector_bytes(vector))
                self.assertEqual(scval_xdr.encode(decoded), vector_bytes(vector))
                if "scval" in vector:
                    self.assertEqual(scval_xdr.to_json(decoded), vector["scval"])
                if "container_depth" in vector:
                    self.assertEqual(container_depth(decoded), vector["container_depth"])
                if "leaf" in vector:
                    self.assertEqual(scval_xdr.to_json(follow_single_child(decoded)), vector["leaf"])

    def test_nested_vectors_are_deep_without_a_depth_eight_cap(self) -> None:
        for name, expected_depth in (
            ("nested_vec_depth_16", 16),
            ("nested_map_depth_8", 8),
        ):
            with self.subTest(vector=name):
                decoded = scval_xdr.decode(vector_bytes(self.by_name[name]))
                self.assertEqual(container_depth(decoded), expected_depth)

        # The reference crate's Limits::none() is u32::MAX, so both the
        # boundary vector and the over-boundary vector are valid XDR when no
        # caller-configured depth limit is supplied.
        decoded = scval_xdr.decode(vector_bytes(self.by_name["nested_vec_depth_17_exceeds_configured_limit"]))
        self.assertEqual(container_depth(decoded), 17)

    def test_configured_stellar_xdr_depth_boundary_is_enforced(self) -> None:
        limit = self.payload["crate"]["configured_container_depth"]
        accepted = self.by_name["nested_vec_depth_16"]
        rejected = self.by_name["nested_vec_depth_17_exceeds_configured_limit"]
        self.assertEqual(
            container_depth(scval_xdr.decode(vector_bytes(accepted), max_container_depth=limit)),
            limit,
        )
        with self.assertRaises(self.decode_error):
            scval_xdr.decode(vector_bytes(rejected), max_container_depth=limit)

    def test_malformed_recursive_vectors_fail_without_a_depth_limit(self) -> None:
        for vector in self.vectors:
            if vector["kind"] != "decode-failure":
                continue
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(self.decode_error):
                    scval_xdr.decode(vector_bytes(vector))


if __name__ == "__main__":
    unittest.main()
