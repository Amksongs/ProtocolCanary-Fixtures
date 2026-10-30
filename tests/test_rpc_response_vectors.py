"""Structural conformance tests for the live Testnet RPC response vectors.

Issue #299 / F-042. The JSON files under ``tests/vectors/rpc/`` are captured
JSON-RPC envelopes, not guessed fixtures. Three are the existing public
Testnet captures from 2026-10-18 UTC; the health and fee-stat captures were
collected from the same endpoint on 2026-10-30 UTC. This suite validates the
envelope and the documented response shape offline, then mutates valid
responses to prove that the checks fail closed.

Run with: ``python3 -m unittest tests/test_rpc_response_vectors.py``
"""
from __future__ import annotations

import base64
import binascii
import copy
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VECTOR_DIR = REPO_ROOT / "tests" / "vectors" / "rpc"
VALIDATE_PATH = REPO_ROOT / "tools" / "validate" / "validate.py"

_spec = importlib.util.spec_from_file_location("validate_rpc_captures", VALIDATE_PATH)
validate = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
sys.modules["validate_rpc_captures"] = validate
_spec.loader.exec_module(validate)

METHODS = (
    "getNetwork",
    "getLatestLedger",
    "getVersionInfo",
    "getHealth",
    "getFeeStats",
)
METHOD_BY_FILENAME = {
    "get-fee-stats.json": "getFeeStats",
    "get-health.json": "getHealth",
    "get-latest-ledger.json": "getLatestLedger",
    "get-network.json": "getNetwork",
    "get-version-info.json": "getVersionInfo",
}
CAPTURE_FIELDS = ("capturedAt", "endpointHost", "request", "response")
ALLOWED_HOST = "soroban-testnet.stellar.org"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FEE_STRING_FIELDS = {
    "max",
    "min",
    "mode",
    "p10",
    "p20",
    "p30",
    "p40",
    "p50",
    "p60",
    "p70",
    "p80",
    "p90",
    "p95",
    "p99",
    "transactionCount",
}
FEE_FIELDS = FEE_STRING_FIELDS | {"ledgerCount"}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_canonical_base64(value: object) -> bool:
    if not _is_nonempty_string(value):
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return False
    return base64.b64encode(decoded).decode("ascii") == value


def _require_keys(value: object, expected: set[str], label: str, problems: list[str]) -> dict:
    if not isinstance(value, dict):
        problems.append(f"{label} must be an object")
        return {}
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        problems.append(f"{label} is missing required field(s) {missing}")
    if extra:
        problems.append(f"{label} has unexpected field(s) {extra}")
    return value


def _check_xdr_string(value: object, label: str, problems: list[str]) -> None:
    if not _is_canonical_base64(value):
        problems.append(f"{label} must be a non-empty canonical base64 string")


def _check_result(method: str, result: object, problems: list[str]) -> None:
    if method == "getNetwork":
        data = _require_keys(
            result,
            {"friendbotUrl", "passphrase", "protocolVersion"},
            "getNetwork.result",
            problems,
        )
        if not _is_nonempty_string(data.get("friendbotUrl")):
            problems.append("getNetwork.result.friendbotUrl must be a non-empty string")
        if not _is_nonempty_string(data.get("passphrase")):
            problems.append("getNetwork.result.passphrase must be a non-empty string")
        if not _is_int(data.get("protocolVersion")) or data["protocolVersion"] < 1:
            problems.append("getNetwork.result.protocolVersion must be a positive integer")
        return

    if method == "getLatestLedger":
        data = _require_keys(
            result,
            {"id", "protocolVersion", "sequence", "closeTime", "headerXdr", "metadataXdr"},
            "getLatestLedger.result",
            problems,
        )
        if not HEX64_RE.fullmatch(data.get("id", "")):
            problems.append("getLatestLedger.result.id must be 64 lowercase hex characters")
        for key in ("protocolVersion", "sequence"):
            if not _is_int(data.get(key)) or data[key] < 1:
                problems.append(f"getLatestLedger.result.{key} must be a positive integer")
        if not _is_nonempty_string(data.get("closeTime")):
            problems.append("getLatestLedger.result.closeTime must be a non-empty string")
        _check_xdr_string(data.get("headerXdr"), "getLatestLedger.result.headerXdr", problems)
        _check_xdr_string(data.get("metadataXdr"), "getLatestLedger.result.metadataXdr", problems)
        return

    if method == "getVersionInfo":
        data = _require_keys(
            result,
            {"version", "commitHash", "buildTimestamp", "captiveCoreVersion", "protocolVersion"},
            "getVersionInfo.result",
            problems,
        )
        for key in ("version", "commitHash", "buildTimestamp", "captiveCoreVersion"):
            if not _is_nonempty_string(data.get(key)):
                problems.append(f"getVersionInfo.result.{key} must be a non-empty string")
        if not _is_int(data.get("protocolVersion")) or data["protocolVersion"] < 1:
            problems.append("getVersionInfo.result.protocolVersion must be a positive integer")
        return

    if method == "getHealth":
        data = _require_keys(
            result,
            {
                "status",
                "latestLedger",
                "latestLedgerCloseTime",
                "oldestLedger",
                "oldestLedgerCloseTime",
                "ledgerRetentionWindow",
            },
            "getHealth.result",
            problems,
        )
        if not _is_nonempty_string(data.get("status")):
            problems.append("getHealth.result.status must be a non-empty string")
        for key in ("latestLedger", "oldestLedger", "ledgerRetentionWindow"):
            if not _is_int(data.get(key)) or data[key] < 0:
                problems.append(f"getHealth.result.{key} must be a non-negative integer")
        for key in ("latestLedgerCloseTime", "oldestLedgerCloseTime"):
            if not _is_nonempty_string(data.get(key)):
                problems.append(f"getHealth.result.{key} must be a non-empty string")
        return

    if method == "getFeeStats":
        data = _require_keys(
            result,
            {"sorobanInclusionFee", "inclusionFee", "latestLedger"},
            "getFeeStats.result",
            problems,
        )
        for fee_name in ("sorobanInclusionFee", "inclusionFee"):
            fee = _require_keys(data.get(fee_name), FEE_FIELDS, f"getFeeStats.result.{fee_name}", problems)
            for key in FEE_STRING_FIELDS:
                if not _is_nonempty_string(fee.get(key)):
                    problems.append(f"getFeeStats.result.{fee_name}.{key} must be a non-empty string")
            if not _is_int(fee.get("ledgerCount")) or fee["ledgerCount"] < 0:
                problems.append(f"getFeeStats.result.{fee_name}.ledgerCount must be a non-negative integer")
        if not _is_int(data.get("latestLedger")) or data["latestLedger"] < 1:
            problems.append("getFeeStats.result.latestLedger must be a positive integer")


def capture_problems(capture: object, expected_method: str | None = None) -> list[str]:
    """Return structural problems for one captured JSON-RPC response."""
    if not isinstance(capture, dict):
        return ["a capture must be a JSON object"]

    problems: list[str] = []
    if set(capture) != set(CAPTURE_FIELDS):
        problems.append("capture fields must be exactly capturedAt, endpointHost, request, response")
    if "capturedAt" in capture:
        instant_problem = validate._check_instant(capture["capturedAt"])
        if instant_problem:
            problems.append(instant_problem.replace("checkedAt", "capturedAt", 1))
    if capture.get("endpointHost") != ALLOWED_HOST:
        problems.append(f"endpointHost must be {ALLOWED_HOST!r}")

    request = _require_keys(capture.get("request"), {"jsonrpc", "id", "method"}, "request", problems)
    method = request.get("method")
    if request.get("jsonrpc") != "2.0":
        problems.append("request.jsonrpc must be '2.0'")
    if method not in METHODS:
        problems.append(f"request.method must be one of {list(METHODS)}")
    if expected_method is not None and method != expected_method:
        problems.append(f"request.method {method!r} does not match expected {expected_method!r}")

    response = _require_keys(capture.get("response"), {"jsonrpc", "id", "result"}, "response", problems)
    if response.get("jsonrpc") != "2.0":
        problems.append("response.jsonrpc must be '2.0'")
    if "id" in request and response.get("id") != request.get("id"):
        problems.append("response.id must match request.id")
    if "result" in response and method in METHODS:
        _check_result(method, response["result"], problems)
    return problems


def load_captures() -> dict[str, dict]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(VECTOR_DIR.glob("*.json"))
    }


class RpcResponseVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.captures = load_captures()

    def test_corpus_covers_exactly_the_five_supported_methods(self) -> None:
        self.assertEqual(
            sorted(self.captures),
            [
                "get-fee-stats.json",
                "get-health.json",
                "get-latest-ledger.json",
                "get-network.json",
                "get-version-info.json",
            ],
        )
        self.assertEqual(
            {capture["request"]["method"] for capture in self.captures.values()},
            set(METHODS),
        )

    def test_every_live_capture_matches_its_method_schema(self) -> None:
        for filename, capture in self.captures.items():
            expected = METHOD_BY_FILENAME[filename]
            with self.subTest(vector=filename):
                self.assertEqual(capture_problems(capture, expected), [], capture)

    def test_captures_are_public_uncredentialed_testnet_records(self) -> None:
        for filename, capture in self.captures.items():
            with self.subTest(vector=filename):
                self.assertEqual(capture["endpointHost"], ALLOWED_HOST)
                raw = json.dumps(capture, sort_keys=True).lower()
                for forbidden in ("authorization", "bearer", "api_key", "apikey", "secret", "password"):
                    self.assertNotIn(forbidden, raw)
        self.assertEqual(self.captures["get-network.json"]["response"]["result"]["protocolVersion"], 29)

    def test_mutated_missing_field_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.captures["get-health.json"])
        del mutated["response"]["result"]["status"]
        problems = capture_problems(mutated, "getHealth")
        self.assertTrue(any("status" in problem for problem in problems), problems)

    def test_mutated_wrong_type_is_rejected(self) -> None:
        mutated = copy.deepcopy(self.captures["get-fee-stats.json"])
        mutated["response"]["result"]["latestLedger"] = "5469717"
        problems = capture_problems(mutated, "getFeeStats")
        self.assertTrue(any("latestLedger" in problem for problem in problems), problems)

    def test_mutated_method_and_jsonrpc_envelope_are_rejected(self) -> None:
        mutated = copy.deepcopy(self.captures["get-network.json"])
        mutated["request"]["method"] = "getHealth"
        mutated["response"]["jsonrpc"] = "1.0"
        problems = capture_problems(mutated, "getNetwork")
        self.assertTrue(any("does not match" in problem for problem in problems), problems)
        self.assertTrue(any("response.jsonrpc" in problem for problem in problems), problems)


if __name__ == "__main__":
    unittest.main()
