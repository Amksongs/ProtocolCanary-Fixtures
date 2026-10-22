"""Tests for tools/evidence/capture_live.py (issue #368).

Stdlib only, and no network: every test runs against the local mock
endpoint in ``tests/mock_rpc.py``. The mock can fail the way a real
endpoint can -- an HTTP error, an answer that never comes, an answer that
is not JSON -- and can report a protocol other than the one a fixture
targets.

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_rpc  # noqa: E402
import pack_support as support  # noqa: E402

capture_live = support.load_tool("canary_capture_live", "tools/evidence/capture_live.py")
REPO_ROOT = support.REPO_ROOT
TOOL = REPO_ROOT / "tools" / "evidence" / "capture_live.py"
VALIDATOR = REPO_ROOT / "tools" / "validate" / "validate.py"
PACK = REPO_ROOT / "protocol-28"


class CaptureLiveTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.output = Path(scratch.name) / "live"

    def records(self) -> list[Path]:
        directory = self.output / "records"
        return sorted(directory.glob("*.json")) if directory.is_dir() else []

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------------------------------------------------------- the happy path

    def test_a_successful_capture_writes_the_captures_and_the_records(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            summary = capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertEqual(summary.failures, [])
        self.assertEqual(
            sorted(path.name for path in (self.output / "captures").glob("*.json")),
            ["get-latest-ledger.json", "get-network.json"],
        )
        self.assertEqual(
            [path.name for path in self.records()],
            [
                "p28-rpc-latest-ledger.live-read-only.json",
                "p28-rpc-network.live-read-only.json",
            ],
        )

    def test_a_capture_holds_the_request_the_answer_the_instant_and_the_host(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        capture = self.read_json(self.output / "captures" / "get-network.json")
        # The same closed envelope the hand-taken corpus uses.
        self.assertEqual(
            sorted(capture), ["capturedAt", "endpointHost", "request", "response"]
        )
        self.assertEqual(capture["endpointHost"], "127.0.0.1")
        self.assertEqual(capture["request"]["jsonrpc"], "2.0")
        self.assertEqual(capture["request"]["method"], "getNetwork")
        self.assertEqual(capture["response"]["id"], capture["request"]["id"])
        self.assertEqual(capture["response"]["result"]["protocolVersion"], 28)

    def test_a_record_names_the_fixture_the_capture_and_the_verifier(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        record = self.read_json(self.output / "records" / "p28-rpc-network.live-read-only.json")
        self.assertEqual(record["verificationVersion"], 1)
        self.assertEqual(record["fixtureId"], "p28-rpc-network")
        self.assertEqual(
            record["fixtureSha256"],
            hashlib.sha256((PACK / "rpc" / "p28-rpc-network.toml").read_bytes()).hexdigest(),
        )
        self.assertEqual(record["method"], "live-read-only")
        self.assertEqual(record["outcome"], "matched")
        self.assertEqual(
            record["verifier"],
            {"name": "protocolcanary-fixtures-capture-live", "version": record["verifier"]["version"]},
        )
        self.assertTrue(record["verifier"]["version"])

    def test_a_record_copies_the_observed_protocol_from_the_answer(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        record = self.read_json(self.output / "records" / "p28-rpc-network.live-read-only.json")
        self.assertEqual(
            record["network"],
            {
                "name": "local-mock",
                "passphrase": mock_rpc.TESTNET_PASSPHRASE,
                "observedProtocol": 28,
            },
        )
        self.assertEqual(record["endpointHost"], "127.0.0.1")

    def test_the_checked_at_is_the_capture_time_of_the_capture_it_points_at(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        record = self.read_json(self.output / "records" / "p28-rpc-network.live-read-only.json")
        reference = record["evidenceRef"]
        self.assertFalse(reference.startswith("/"))
        self.assertNotIn("..", reference)
        capture = self.read_json(self.output / reference)
        self.assertEqual(record["checkedAt"], capture["capturedAt"])
        self.assertEqual(capture["request"]["method"], "getNetwork")

    def test_the_records_pass_the_validator(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                str(PACK),
                "--evidence",
                str(self.output / "records"),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_record_is_checked_against_the_fixture_it_names(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        record = self.read_json(self.output / "records" / "p28-rpc-network.live-read-only.json")
        self.assertEqual(capture_live.validate.validate_evidence(record), [])
        hashes = capture_live.validate.fixture_hashes([PACK])
        report = capture_live.validate.Report()
        capture_live.validate.check_evidence_against_fixtures(
            Path("record.json"), record, hashes, report
        )
        self.assertEqual(report.errors, [])

    def test_only_the_read_only_methods_are_called(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(
                PACK,
                output_dir=self.output,
                local_endpoint=server.url,
                capture_methods=["getVersionInfo"],
            )
            self.assertEqual(set(server.requests), set(capture_live.READ_ONLY_METHODS))
        self.assertTrue((self.output / "captures" / "get-version-info.json").is_file())

    def test_the_captures_carry_no_credentials(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        for path in (self.output / "captures").glob("*.json"):
            raw = path.read_text(encoding="utf-8").lower()
            for token in (
                "authorization",
                "bearer",
                "api_key",
                "apikey",
                "secret",
                "password",
                "seed",
                "@",
            ):
                self.assertNotIn(token, raw, f"{path.name} carries {token!r}")

    def test_the_request_carries_a_user_agent_and_no_credential(self) -> None:
        # The public endpoint's edge refuses Python's default agent (HTTP
        # 403), so the tool identifies itself -- and sends nothing else: no
        # token, no cookie, no authorization header.
        with mock_rpc.MockRpcServer(protocol=28) as server:
            capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
            self.assertTrue(server.headers)
            for headers in server.headers:
                self.assertEqual(headers.get("user-agent"), capture_live.USER_AGENT)
                self.assertNotIn("authorization", headers)
                self.assertNotIn("cookie", headers)
                self.assertNotIn("x-api-key", headers)

    # ------------------------------------------------------------- the failures

    def test_an_http_error_produces_no_record_and_no_capture(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_ERROR}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            summary = capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertEqual(len(summary.failures), 1)
        self.assertIn("HTTP 500", summary.failures[0][1])
        self.assertFalse((self.output / "captures" / "get-latest-ledger.json").exists())
        self.assertFalse(
            (self.output / "records" / "p28-rpc-latest-ledger.live-read-only.json").exists()
        )
        # The fixture whose own call worked still has its record.
        self.assertTrue(
            (self.output / "records" / "p28-rpc-network.live-read-only.json").is_file()
        )

    def test_a_timeout_produces_no_record(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_HANG}
        with mock_rpc.MockRpcServer(
            protocol=28, behaviors=behaviors, hang_seconds=2.0
        ) as server:
            summary = capture_live.run(
                PACK, output_dir=self.output, local_endpoint=server.url, timeout=0.5
            )
        self.assertEqual(len(summary.failures), 1)
        self.assertIn("did not answer", summary.failures[0][1])
        self.assertFalse(
            (self.output / "records" / "p28-rpc-latest-ledger.live-read-only.json").exists()
        )

    def test_a_malformed_answer_produces_no_record(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_MALFORMED}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            summary = capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertEqual(len(summary.failures), 1)
        self.assertIn("not JSON", summary.failures[0][1])
        self.assertFalse(
            (self.output / "records" / "p28-rpc-latest-ledger.live-read-only.json").exists()
        )

    def test_a_json_rpc_error_produces_no_record(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_RPC_ERROR}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            summary = capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertEqual(len(summary.failures), 1)
        self.assertIn("JSON-RPC error", summary.failures[0][1])

    def test_a_failed_network_call_produces_no_record_at_all(self) -> None:
        behaviors = {"getNetwork": mock_rpc.BEHAVIOR_ERROR}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertIn("getNetwork", str(raised.exception))
        self.assertEqual(self.records(), [])

    def test_the_cli_fails_when_a_capture_fails(self) -> None:
        behaviors = {"getNetwork": mock_rpc.BEHAVIOR_ERROR}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(PACK),
                    "--local-endpoint",
                    server.url,
                    "--output-dir",
                    str(self.output),
                ],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED", result.stderr)
        self.assertEqual(self.records(), [])

    # ------------------------------------------------------------ the refusals

    def test_a_write_method_is_refused_before_a_request_is_made(self) -> None:
        with mock_rpc.MockRpcServer() as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.capture_method(server.url, "submitTransaction", 1, 2.0)
            self.assertEqual(server.requests, [])
        self.assertIn("read-only", str(raised.exception))

    def test_the_cli_refuses_a_write_method(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                str(PACK),
                "--capture-method",
                "submitTransaction",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("read-only", result.stderr)

    def test_an_endpoint_that_is_not_approved_is_refused(self) -> None:
        with self.assertRaises(capture_live.CaptureError) as raised:
            capture_live.resolve_endpoint("mainnet.sorobanrpc.com", None)
        self.assertIn("not approved", str(raised.exception))

    def test_a_local_endpoint_that_is_not_a_loopback_address_is_refused(self) -> None:
        with self.assertRaises(capture_live.CaptureError) as raised:
            capture_live.resolve_endpoint(None, "http://example.com")
        self.assertIn("loopback", str(raised.exception))
        with self.assertRaises(capture_live.CaptureError):
            capture_live.resolve_endpoint(None, "https://127.0.0.1:8099")

    # ------------------------------------------------------------- the dry run

    def test_a_dry_run_writes_nothing(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            summary = capture_live.run(
                PACK, output_dir=self.output, local_endpoint=server.url, dry_run=True
            )
        self.assertFalse(self.output.exists())
        self.assertTrue(summary.documents)
        kinds = {path.name for path, _ in summary.documents}
        self.assertIn("get-network.json", kinds)
        self.assertIn("p28-rpc-network.live-read-only.json", kinds)

    def test_the_cli_dry_run_prints_the_documents_it_would_write(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(PACK),
                    "--local-endpoint",
                    server.url,
                    "--output-dir",
                    str(self.output),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("p28-rpc-network.live-read-only.json", result.stdout)
        self.assertIn('"method": "live-read-only"', result.stdout)
        self.assertFalse(self.output.exists())


class CaptureLiveUnitTests(unittest.TestCase):
    """The tool's own branches, exercised in-process.

    The end-to-end tests above run the tool in a subprocess, which the
    coverage measurement does not see. These call the functions directly,
    so every refusal and every malformed answer is a measured line.
    """

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.output = Path(scratch.name) / "live"

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------- the pure helpers

    def test_json_type_name_names_every_json_type(self) -> None:
        self.assertEqual(capture_live.json_type_name(None), "null")
        self.assertEqual(capture_live.json_type_name(True), "bool")
        self.assertEqual(capture_live.json_type_name(1), "number")
        self.assertEqual(capture_live.json_type_name(1.5), "number")
        self.assertEqual(capture_live.json_type_name("x"), "string")
        self.assertEqual(capture_live.json_type_name([1]), "array")
        self.assertEqual(capture_live.json_type_name({}), "object")
        self.assertEqual(capture_live.json_type_name(object()), "object")

    def test_a_boolean_never_equals_a_number(self) -> None:
        # True == 1 in Python, so a boolean must not satisfy a number
        # assertion -- and the other way round either.
        self.assertFalse(capture_live.values_equal(True, 1))
        self.assertFalse(capture_live.values_equal(1, True))
        self.assertTrue(capture_live.values_equal(True, True))
        self.assertFalse(capture_live.values_equal(True, False))
        self.assertTrue(capture_live.values_equal(1, 1.0))
        self.assertTrue(capture_live.values_equal("a", "a"))
        self.assertFalse(capture_live.values_equal("a", "b"))
        self.assertTrue(capture_live.values_equal([1, [2]], [1, [2]]))
        self.assertFalse(capture_live.values_equal([1], [1, 2]))
        self.assertTrue(capture_live.values_equal({"a": 1}, {"a": 1}))
        self.assertFalse(capture_live.values_equal({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(capture_live.values_equal({"a": 1}, {"b": 1}))
        # Two values of different types are never equal.
        self.assertFalse(capture_live.values_equal(1, "1"))
        self.assertFalse(capture_live.values_equal([1], {"0": 1}))

    def test_every_assertion_kind_is_evaluated(self) -> None:
        result = {
            "name": "x",
            "count": 3,
            "flag": True,
            "items": [1, 2],
        }
        # field-exists
        self.assertEqual(
            capture_live.evaluate_asserts(
                [{"kind": "field-exists", "field": "name"}], result
            ),
            [],
        )
        self.assertIn(
            "no 'missing' field",
            capture_live.evaluate_asserts(
                [{"kind": "field-exists", "field": "missing"}], result
            )[0],
        )
        # field-absent
        self.assertEqual(
            capture_live.evaluate_asserts(
                [{"kind": "field-absent", "field": "missing"}], result
            ),
            [],
        )
        self.assertIn(
            "has a 'name' field",
            capture_live.evaluate_asserts(
                [{"kind": "field-absent", "field": "name"}], result
            )[0],
        )
        # field-type
        self.assertEqual(
            capture_live.evaluate_asserts(
                [{"kind": "field-type", "field": "count", "expected_type": "number"}],
                result,
            ),
            [],
        )
        self.assertIn(
            "expected 'string'",
            capture_live.evaluate_asserts(
                [{"kind": "field-type", "field": "count", "expected_type": "string"}],
                result,
            )[0],
        )
        self.assertIn(
            "no 'missing' field",
            capture_live.evaluate_asserts(
                [{"kind": "field-type", "field": "missing", "expected_type": "number"}],
                result,
            )[0],
        )
        # field-equals
        self.assertEqual(
            capture_live.evaluate_asserts(
                [{"kind": "field-equals", "field": "name", "value": "x"}], result
            ),
            [],
        )
        self.assertIn(
            "expected",
            capture_live.evaluate_asserts(
                [{"kind": "field-equals", "field": "name", "value": "y"}], result
            )[0],
        )
        self.assertIn(
            "no 'missing' field",
            capture_live.evaluate_asserts(
                [{"kind": "field-equals", "field": "missing", "value": "y"}], result
            )[0],
        )
        # field-number-range
        self.assertEqual(
            capture_live.evaluate_asserts(
                [{"kind": "field-number-range", "field": "count", "min": 1, "max": 5}],
                result,
            ),
            [],
        )
        self.assertIn(
            "below the minimum",
            capture_live.evaluate_asserts(
                [{"kind": "field-number-range", "field": "count", "min": 5}], result
            )[0],
        )
        self.assertIn(
            "above the maximum",
            capture_live.evaluate_asserts(
                [{"kind": "field-number-range", "field": "count", "max": 1}], result
            )[0],
        )
        self.assertIn(
            "not a number",
            capture_live.evaluate_asserts(
                [{"kind": "field-number-range", "field": "name", "min": 1}], result
            )[0],
        )
        self.assertIn(
            "no 'missing' field",
            capture_live.evaluate_asserts(
                [{"kind": "field-number-range", "field": "missing", "min": 1}], result
            )[0],
        )
        # An unknown kind is reported, never ignored.
        self.assertIn(
            "unknown kind",
            capture_live.evaluate_asserts(
                [{"kind": "field-magic", "field": "name"}], result
            )[0],
        )

    def test_an_assertion_that_is_not_a_table_is_reported(self) -> None:
        problems = capture_live.evaluate_asserts(["not a table"], {})
        self.assertIn("is not a table", problems[0])

    def test_asserts_that_are_not_a_list_are_reported(self) -> None:
        problems = capture_live.evaluate_asserts({"kind": "field-exists"}, {})
        self.assertIn("no [[assert]] table", problems[0])

    def test_an_answer_that_is_not_an_object_is_reported(self) -> None:
        problems = capture_live.evaluate_asserts(
            [{"kind": "field-exists", "field": "name"}], [1, 2, 3]
        )
        self.assertIn("not an object", problems[0])

    # ---------------------------------------------------- the endpoint rules

    def test_the_approved_endpoint_is_the_default(self) -> None:
        endpoint = capture_live.resolve_endpoint(None, None)
        self.assertEqual(endpoint.host, sorted(capture_live.APPROVED_ENDPOINTS)[0])
        self.assertTrue(endpoint.url.startswith("https://"))
        self.assertEqual(endpoint.network, capture_live.APPROVED_ENDPOINTS[endpoint.host])

    def test_an_approved_endpoint_can_be_named(self) -> None:
        endpoint = capture_live.resolve_endpoint(
            sorted(capture_live.APPROVED_ENDPOINTS)[0], None
        )
        self.assertEqual(endpoint.url, f"https://{sorted(capture_live.APPROVED_ENDPOINTS)[0]}")

    def test_a_local_endpoint_must_be_http_on_the_loopback(self) -> None:
        endpoint = capture_live.resolve_endpoint(None, "http://127.0.0.1:8099")
        self.assertEqual(endpoint.host, "127.0.0.1")
        self.assertEqual(endpoint.network, "local-mock")
        # The IPv6 loopback is a loopback address too.
        self.assertEqual(
            capture_live.resolve_endpoint(None, "http://[::1]:8099").host, "::1"
        )
        # A routable address is not.
        with self.assertRaises(capture_live.CaptureError):
            capture_live.resolve_endpoint(None, "http://[2001:db8::1]:8099")
        with self.assertRaises(capture_live.CaptureError):
            capture_live.resolve_endpoint(None, "not a url")

    def test_the_version_of_the_verifier_is_the_commit_or_unknown(self) -> None:
        revision = capture_live.git_revision(REPO_ROOT)
        self.assertTrue(revision == "unknown" or len(revision) == 40)
        # A directory that is not a checkout cannot answer, and says so
        # rather than guessing a revision.
        with tempfile.TemporaryDirectory() as scratch:
            self.assertEqual(capture_live.git_revision(Path(scratch)), "unknown")

    def test_a_checkout_without_git_says_the_version_is_unknown(self) -> None:
        with mock.patch.object(
            capture_live.subprocess, "run", side_effect=OSError("no git here")
        ):
            self.assertEqual(capture_live.git_revision(REPO_ROOT), "unknown")
        with mock.patch.object(
            capture_live.subprocess, "run", side_effect=capture_live.subprocess.TimeoutExpired("git", 1)
        ):
            self.assertEqual(capture_live.git_revision(REPO_ROOT), "unknown")
        with mock.patch.object(
            capture_live.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout="not-a-revision\n", stderr=""),
        ):
            self.assertEqual(capture_live.git_revision(REPO_ROOT), "unknown")

    def test_a_summary_knows_whether_it_failed(self) -> None:
        endpoint = capture_live.Endpoint(url="http://127.0.0.1:1", host="127.0.0.1", network="local-mock")
        summary = capture_live.Summary(endpoint=endpoint)
        self.assertTrue(summary.ok)
        summary.failures.append(("getNetwork", "it failed"))
        self.assertFalse(summary.ok)

    def test_the_instant_is_an_rfc_3339_utc_instant(self) -> None:
        instant = capture_live.utc_now()
        self.assertRegex(instant, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    # -------------------------------------------------- the transport errors

    def test_an_unreachable_endpoint_is_reported(self) -> None:
        with self.assertRaises(capture_live.CaptureError) as raised:
            capture_live.capture_method(
                "http://127.0.0.1:1", "getNetwork", 1, 2.0
            )
        self.assertIn("could not be reached", str(raised.exception))

    def test_a_transport_error_is_reported(self) -> None:
        with mock.patch.object(
            capture_live.urllib.request, "urlopen", side_effect=OSError("broken pipe")
        ):
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.capture_method("http://127.0.0.1:8099", "getNetwork", 1, 2.0)
        self.assertIn("the request failed", str(raised.exception))

    def test_a_url_error_with_a_timeout_is_reported_as_a_timeout(self) -> None:
        error = urllib.error.URLError(TimeoutError("timed out"))
        with mock.patch.object(
            capture_live.urllib.request, "urlopen", side_effect=error
        ):
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.capture_method("http://127.0.0.1:8099", "getNetwork", 1, 2.0)
        self.assertIn("did not answer", str(raised.exception))

    def test_an_answer_that_is_not_a_json_rpc_object_is_refused(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_NOT_OBJECT}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.capture_method(server.url, "getLatestLedger", 1, 2.0)
        self.assertIn("not a JSON-RPC object", str(raised.exception))

    def test_an_answer_without_a_result_is_refused(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_NO_RESULT}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.capture_method(server.url, "getLatestLedger", 1, 2.0)
        self.assertIn("carried no result", str(raised.exception))

    def test_an_answer_with_another_request_id_is_refused(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_WRONG_ID}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.capture_method(server.url, "getLatestLedger", 1, 2.0)
        self.assertIn("does not match", str(raised.exception))

    def test_an_answer_over_the_size_limit_is_refused(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            with mock.patch.object(capture_live, "MAX_RESPONSE_BYTES", 8):
                with self.assertRaises(capture_live.CaptureError) as raised:
                    capture_live.capture_method(server.url, "getNetwork", 1, 2.0)
        self.assertIn("larger than", str(raised.exception))

    # ------------------------------------------------------ the pack handling

    def test_a_pack_that_is_not_a_directory_is_refused(self) -> None:
        with self.assertRaises(capture_live.CaptureError) as raised:
            capture_live.load_rpc_fixtures(Path("/nonexistent/pack"))
        self.assertIn("pack not found", str(raised.exception))

    def test_a_pack_without_an_rpc_fixture_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            pack = Path(scratch) / "pack"
            pack.mkdir()
            (pack / "p28-xdr-a.toml").write_text(
                'id = "p28-xdr-a"\nprotocol = 28\nsurface = "xdr"\n', encoding="utf-8"
            )
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.load_rpc_fixtures(pack)
        self.assertIn("no RPC fixture", str(raised.exception))

    def test_a_fixture_that_cannot_be_loaded_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            pack = Path(scratch) / "pack"
            pack.mkdir()
            (pack / "broken.toml").write_text("not valid [[[ toml", encoding="utf-8")
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.load_rpc_fixtures(pack)
        self.assertIn("could not be loaded", str(raised.exception))

    def test_a_fixture_without_a_usable_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            pack = Path(scratch) / "pack"
            pack.mkdir()
            (pack / "no-id.toml").write_text(
                'protocol = 28\nsurface = "rpc"\nmethod = "get-network"\n', encoding="utf-8"
            )
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.load_rpc_fixtures(pack)
        self.assertIn("no usable id", str(raised.exception))

    def test_a_fixture_whose_method_has_no_live_counterpart_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            pack = Path(scratch) / "pack"
            pack.mkdir()
            (pack / "other.toml").write_text(
                'id = "p28-rpc-other"\nprotocol = 28\nsurface = "rpc"\n'
                'method = "get-something-else"\n',
                encoding="utf-8",
            )
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.load_rpc_fixtures(pack)
        self.assertIn("no read-only live counterpart", str(raised.exception))

    def test_a_fixture_that_is_not_rpc_is_not_verified_live(self) -> None:
        fixtures = capture_live.load_rpc_fixtures(PACK)
        self.assertEqual(
            sorted(fixture["id"] for fixture in fixtures),
            ["p28-rpc-latest-ledger", "p28-rpc-network"],
        )
        for fixture in fixtures:
            self.assertIn(fixture["live_method"], capture_live.READ_ONLY_METHODS)
            self.assertRegex(fixture["sha256"], r"^[0-9a-f]{64}$")

    # -------------------------------------------------------- the run failures

    def test_a_get_network_answer_that_is_not_an_object_writes_no_record(self) -> None:
        behaviors = {"getNetwork": mock_rpc.BEHAVIOR_RESULT_NOT_OBJECT}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertIn("not an object", str(raised.exception))
        self.assertFalse(self.output.exists())

    def test_a_get_network_answer_without_a_passphrase_writes_no_record(self) -> None:
        behaviors = {"getNetwork": mock_rpc.BEHAVIOR_NO_PASSPHRASE}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertIn("no passphrase", str(raised.exception))
        self.assertFalse(self.output.exists())

    def test_a_get_network_answer_without_a_protocol_writes_no_record(self) -> None:
        behaviors = {"getNetwork": mock_rpc.BEHAVIOR_NO_PROTOCOL}
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertIn("no protocolVersion", str(raised.exception))
        self.assertFalse(self.output.exists())

    def test_a_fixture_that_targets_another_protocol_is_mismatched(self) -> None:
        # The endpoint has moved past protocol 28, so the fixtures that
        # target 28 are honestly reported as mismatched.
        with mock_rpc.MockRpcServer(protocol=29) as server:
            summary = capture_live.run(PACK, output_dir=self.output, local_endpoint=server.url)
        self.assertEqual(summary.failures, [])
        for _fixture_id, outcome, problems in summary.outcomes:
            self.assertEqual(outcome, "mismatched")
            self.assertTrue(any("protocol 29" in problem for problem in problems))
        record = self.read_json(self.output / "records" / "p28-rpc-network.live-read-only.json")
        self.assertEqual(record["outcome"], "mismatched")
        self.assertEqual(record["network"]["observedProtocol"], 29)

    def test_a_record_the_validator_refuses_is_not_written(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            with mock.patch.object(
                capture_live.validate, "validate_evidence", return_value=["not a real record"]
            ):
                with self.assertRaises(capture_live.CaptureError) as raised:
                    capture_live.run(
                        PACK, output_dir=self.output, local_endpoint=server.url
                    )
        self.assertIn("does not satisfy the CF-04 rules", str(raised.exception))
        self.assertFalse(self.output.exists())

    def test_an_extra_method_that_is_not_read_only_is_refused(self) -> None:
        with mock_rpc.MockRpcServer(protocol=28) as server:
            with self.assertRaises(capture_live.CaptureError) as raised:
                capture_live.run(
                    PACK,
                    output_dir=self.output,
                    local_endpoint=server.url,
                    capture_methods=["submitTransaction"],
                )
            self.assertEqual(server.requests, [])
        self.assertIn("read-only", str(raised.exception))

    def test_a_capture_that_cannot_be_written_is_reported(self) -> None:
        with self.assertRaises(capture_live.CaptureError) as raised:
            capture_live.write_documents(
                [(Path("/proc/nonexistent/capture.json"), {"a": 1})]
            )
        self.assertIn("could not write", str(raised.exception))

    def test_an_evidence_reference_outside_the_repository_is_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            outside = Path(scratch) / "capture.json"
            reference = capture_live.evidence_reference(outside, Path(scratch) / "live")
        self.assertTrue(reference.startswith("/"))
        self.assertNotIn("..", reference)

    # ------------------------------------------------------------- the command

    def test_the_command_reports_a_failure_on_stderr_and_returns_one(self) -> None:
        behaviors = {"getLatestLedger": mock_rpc.BEHAVIOR_ERROR}
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock_rpc.MockRpcServer(protocol=28, behaviors=behaviors) as server:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = capture_live.main(
                    [
                        str(PACK),
                        "--local-endpoint",
                        server.url,
                        "--output-dir",
                        str(self.output),
                    ]
                )
        self.assertEqual(code, 1)
        self.assertIn("FAILED", stderr.getvalue())
        self.assertIn("Captures: 1", stdout.getvalue())

    def test_the_command_prints_the_reasons_a_fixture_did_not_match(self) -> None:
        # The endpoint has moved past protocol 28, so the fixtures that
        # target 28 are reported as mismatched, with the reasons.
        stdout = io.StringIO()
        with mock_rpc.MockRpcServer(protocol=29) as server:
            with contextlib.redirect_stdout(stdout):
                code = capture_live.main(
                    [
                        str(PACK),
                        "--local-endpoint",
                        server.url,
                        "--output-dir",
                        str(self.output),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertIn("p28-rpc-network: mismatched", stdout.getvalue())
        self.assertIn("the endpoint reports protocol 29", stdout.getvalue())

    def test_the_command_reports_a_capture_error_on_stderr_and_returns_one(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = capture_live.main(
                [str(PACK), "--endpoint", "example.invalid", "--output-dir", str(self.output)]
            )
        self.assertEqual(code, 1)
        self.assertIn("not approved", stderr.getvalue())
        self.assertIn("no record was written", stderr.getvalue())

    def test_the_command_succeeds_and_prints_what_it_did(self) -> None:
        stdout = io.StringIO()
        with mock_rpc.MockRpcServer(protocol=28) as server:
            with contextlib.redirect_stdout(stdout):
                code = capture_live.main(
                    [
                        str(PACK),
                        "--local-endpoint",
                        server.url,
                        "--output-dir",
                        str(self.output),
                        "--verifier-version",
                        "test-version",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertIn("OK: the captures and the records are written", stdout.getvalue())
        record = self.read_json(self.output / "records" / "p28-rpc-network.live-read-only.json")
        self.assertEqual(record["verifier"]["version"], "test-version")

    def test_the_command_prints_the_documents_of_a_dry_run(self) -> None:
        stdout = io.StringIO()
        with mock_rpc.MockRpcServer(protocol=28) as server:
            with contextlib.redirect_stdout(stdout):
                code = capture_live.main(
                    [
                        str(PACK),
                        "--local-endpoint",
                        server.url,
                        "--output-dir",
                        str(self.output),
                        "--dry-run",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertIn("Dry run: nothing was written", stdout.getvalue())
        self.assertIn("p28-rpc-network.live-read-only.json", stdout.getvalue())
        self.assertFalse(self.output.exists())

    def test_the_command_rejects_an_unknown_option(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stderr(io.StringIO()):
                capture_live.main([str(PACK), "--not-an-option"])
        self.assertEqual(raised.exception.code, 2)

    def test_the_command_reports_a_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stderr(io.StringIO()):
                capture_live.main(["--help"])
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
