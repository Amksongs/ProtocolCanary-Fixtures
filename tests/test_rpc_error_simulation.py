"""Tests for the RPC error-simulation vectors (F-041, issue #298).

Run with: python3 -m unittest discover tests

The vectors in ``tests/fixtures/rpc-errors/error-simulation-vectors.json``
script the failure situations of CA-01 section 5 (HTTP 429, HTTP 5xx, a
timeout, JSON-RPC ``-32601``, other JSON-RPC errors, unrecognized error
formats, a body that is not JSON, a message with neither ``result`` nor
``error``, a ``result`` that is not an object) and record two things for each:

* what the engine does (``engine``): its CA-01 classification, exit code and
  retry behavior, taken from CA-01 section 5 and ``canary-rpc``'s client;
* what this repository's own capture tool, ``tools/evidence/capture_live.py``,
  does with the first reply (``capture_live``).

They are JSON and not TOML fixtures because a TOML fixture cannot do either
job: it cannot choose the endpoint or make it fail (CA-01 section 8), and it
cannot assert that an error is expected (CA-01 section 5, "a fixture never
converts an ``error`` into a pass").

No network: a scripted loopback server replays each vector's responses.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpc_vector_support as support  # noqa: E402

capture_live = support.capture_live
VECTORS = json.loads(support.ERROR_VECTORS.read_text(encoding="utf-8"))

# The rows of the CA-01 section 5 table that a scripted endpoint can play. The
# other rows are not replayable here: an assertion failure is not an error, an
# oversized body needs 16 MiB, and an invalid [request] is the validator's job.
REPLAYABLE_ROWS = {
    "Transport error, HTTP 5xx, TLS failure",
    "Timeout",
    "HTTP 429",
    "JSON-RPC error object, any code",
    "JSON-RPC code -32601",
    "Body is not JSON, or has neither result nor error, or result is not an object",
}
ENGINE_CLASSES = {"transport", "application", "protocol"}
RETRIED_CLASS = "transport"
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 0.3


class ReplayServer:
    """A loopback endpoint that plays a vector's scripted responses in order.

    The last response repeats once the script is used up, so a vector with one
    entry means "every attempt gets this".
    """

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.requests: list[dict] = []
        self._served = 0
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    def next_response(self) -> dict:
        with self._lock:
            step = self.responses[min(self._served, len(self.responses) - 1)]
            self._served += 1
            return step

    def __enter__(self) -> "ReplayServer":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                try:
                    owner.requests.append(json.loads(body.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    owner.requests.append({})
                step = owner.next_response()
                if step.get("hang_ms"):
                    time.sleep(step["hang_ms"] / 1000)
                if "body_json" in step:
                    payload = json.dumps(step["body_json"]).encode("utf-8")
                else:
                    payload = step.get("body_text", "").encode("utf-8")
                self.send_response(step["http_status"])
                self.send_header("Content-Type", "application/json")
                for name, value in step.get("headers", {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                """Keep the test output quiet."""

            def handle_one_request(self) -> None:
                # A client that gave up (the timeout vector) closes the socket
                # before the answer is written; that is its decision, not an error.
                try:
                    super().handle_one_request()
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        ThreadingHTTPServer.daemon_threads = True
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # A short poll interval keeps shutdown() from waiting half a second per server.
        threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> bool:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        return False


def call(server: ReplayServer, request_id: int = 1):
    """One capture_live call against the server, as the tool itself makes it."""
    return capture_live.capture_method(server.url, "getNetwork", request_id, TIMEOUT_SECONDS)


def capture_error(server: ReplayServer) -> str:
    with unittest.TestCase().assertRaises(capture_live.CaptureError) as caught:
        call(server)
    return str(caught.exception)


class VectorFileTests(unittest.TestCase):
    def test_the_file_declares_its_schema_sources_and_retry_policy(self) -> None:
        self.assertEqual(VECTORS["schema"], "rpc-error-simulation-vectors/1")
        self.assertRegex(VECTORS["sources"]["engine_commit"], r"^[0-9a-f]{40}$")
        for url in (VECTORS["sources"]["contract"], VECTORS["sources"]["engine_client"]):
            self.assertIn(VECTORS["sources"]["engine_commit"], url)
        policy = VECTORS["retry_policy"]
        self.assertEqual((policy["max_attempts"], policy["base_delay_ms"], policy["backoff"]), (MAX_ATTEMPTS, 200, "linear"))
        self.assertEqual(policy["retried_classes"], [RETRIED_CLASS])

    def test_every_vector_is_complete_and_ids_are_unique(self) -> None:
        ids = [vector["id"] for vector in VECTORS["vectors"]]
        self.assertEqual(len(ids), len(set(ids)))
        for vector in VECTORS["vectors"]:
            with self.subTest(vector=vector["id"]):
                self.assertRegex(vector["id"], r"^[a-z0-9][a-z0-9-]*$")
                self.assertEqual(set(vector), {"id", "summary", "ca01_row", "responses", "engine", "capture_live"})
                self.assertTrue(vector["responses"])
                for step in vector["responses"]:
                    self.assertIsInstance(step["http_status"], int)
                    self.assertTrue({"body_json", "body_text"} & set(step))

    def test_every_replayable_ca01_row_has_a_vector(self) -> None:
        rows = {vector["ca01_row"] for vector in VECTORS["vectors"]}
        self.assertEqual(rows, REPLAYABLE_ROWS)

    def test_the_engine_expectations_follow_ca01_section_5(self) -> None:
        for vector in VECTORS["vectors"]:
            engine = vector["engine"]
            with self.subTest(vector=vector["id"]):
                self.assertIn(engine["class"], ENGINE_CLASSES)
                self.assertEqual(engine["result_status"] == "error", engine["exit_code"] == 3)
                self.assertIn(engine["result_status"], {"pass", "error"})
                # Only transport-level failures are retried, and then up to the cap.
                self.assertEqual(engine["retried"], engine["class"] == RETRIED_CLASS)
                self.assertEqual(engine["attempts"], MAX_ATTEMPTS if engine["retried"] else 1)

    def test_a_rate_limit_that_clears_is_the_only_pass(self) -> None:
        passes = [v["id"] for v in VECTORS["vectors"] if v["engine"]["result_status"] == "pass"]
        self.assertEqual(passes, ["rate-limited-then-recovers"])
        recovering = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-then-recovers")
        statuses = [step["http_status"] for step in recovering["responses"]]
        self.assertEqual(statuses, [429, 429, 200])
        self.assertEqual(len(statuses), recovering["engine"]["attempts"])

    def test_an_exhausted_failure_never_ends_in_a_pass(self) -> None:
        for vector in VECTORS["vectors"]:
            if vector["id"] != "rate-limited-then-recovers":
                with self.subTest(vector=vector["id"]):
                    self.assertEqual(vector["engine"]["result_status"], "error")
                    self.assertEqual(vector["engine"]["exit_code"], 3)

    def test_a_json_rpc_error_is_never_retried_and_a_transport_error_always_is(self) -> None:
        for vector in VECTORS["vectors"]:
            klass = vector["engine"]["class"]
            with self.subTest(vector=vector["id"]):
                if vector["ca01_row"].startswith("JSON-RPC"):
                    self.assertEqual(klass, "application")
                    self.assertFalse(vector["engine"]["retried"])
                if vector["ca01_row"] in {"HTTP 429", "Timeout", "Transport error, HTTP 5xx, TLS failure"}:
                    self.assertEqual(klass, "transport")
                    self.assertTrue(vector["engine"]["retried"])


class CaptureToolClassificationTests(unittest.TestCase):
    """capture_live separates transport failures from application errors."""

    def test_each_vector_is_classified_as_its_capture_live_block_says(self) -> None:
        for vector in VECTORS["vectors"]:
            expectation = vector["capture_live"]
            with self.subTest(vector=vector["id"]), ReplayServer(vector["responses"]) as server:
                if expectation["outcome"] == "capture-error":
                    message = capture_error(server)
                    for needle in expectation["message_contains"]:
                        self.assertIn(needle, message)
                    for needle in expectation.get("message_excludes", []):
                        self.assertNotIn(needle, message)
                else:
                    result = call(server)
                    problems = capture_live.evaluate_asserts([{"kind": "field-exists", "field": "x"}], result)
                    for needle in expectation["evaluate_problem_contains"]:
                        self.assertTrue(any(needle in problem for problem in problems), problems)
                self.assertGreaterEqual(len(server.requests), 1)

    def test_a_transport_failure_and_an_application_error_never_read_alike(self) -> None:
        transport = [v for v in VECTORS["vectors"] if v["engine"]["class"] == "transport"]
        application = [v for v in VECTORS["vectors"] if v["engine"]["class"] == "application"]
        self.assertTrue(transport and application)
        for vector in transport + application:
            with self.subTest(vector=vector["id"]), ReplayServer(vector["responses"]) as server:
                message = capture_error(server)
                if vector in transport:
                    self.assertNotIn("JSON-RPC error", message)
                else:
                    self.assertIn("JSON-RPC error", message)
                    self.assertNotIn("answered HTTP", message)

    def test_method_not_found_is_reported_with_its_code_and_text(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "method-not-found")
        with ReplayServer(vector["responses"]) as server:
            message = capture_error(server)
        self.assertIn('"code": -32601', message)
        self.assertIn("method not found", message)

    def test_other_json_rpc_codes_keep_their_own_code(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "jsonrpc-error-other-code")
        with ReplayServer(vector["responses"]) as server:
            message = capture_error(server)
        self.assertIn('"code": -32602', message)
        self.assertNotIn("-32601", message)


class RateLimitSequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vector = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-then-recovers")

    def test_the_tool_surfaces_every_429_and_then_the_recovered_answer(self) -> None:
        # capture_live makes one call per method and does not retry; the engine
        # does. Played call by call the script shows both: each 429 is reported
        # as such, and the third attempt returns the real result.
        with ReplayServer(self.vector["responses"]) as server:
            first = capture_error(server)
            second = capture_error(server)
            third = call(server)
            self.assertEqual(len(server.requests), 3)
        self.assertIn("HTTP 429", first)
        self.assertIn("HTTP 429", second)
        self.assertEqual(third["protocolVersion"], 28)
        self.assertEqual(third["passphrase"], "Test SDF Network ; September 2015")

    def test_exhausted_rate_limiting_never_yields_a_result(self) -> None:
        vector = next(v for v in VECTORS["vectors"] if v["id"] == "rate-limited-exhausted")
        with ReplayServer(vector["responses"]) as server:
            for _ in range(MAX_ATTEMPTS + 2):
                self.assertIn("HTTP 429", capture_error(server))
            self.assertEqual(len(server.requests), MAX_ATTEMPTS + 2)

    def test_the_requests_are_read_only_json_rpc_posts(self) -> None:
        with ReplayServer(self.vector["responses"]) as server:
            capture_error(server)
        request = server.requests[0]
        self.assertEqual((request["jsonrpc"], request["method"], request["id"]), ("2.0", "getNetwork", 1))
        self.assertNotIn("params", request)


class UnrecognizedErrorFormatTests(unittest.TestCase):
    """An error in a shape nobody documented is still an error, never a pass."""

    def play(self, body: object):
        with ReplayServer([{"http_status": 200, "body_json": body}]) as server:
            return capture_error(server)

    def test_odd_error_values_are_reported_as_json_rpc_errors(self) -> None:
        for label, error in (
            ("string", "boom"),
            ("number", 42),
            ("null", None),
            ("empty object", {}),
            ("list", [{"code": 1}]),
            ("no code", {"message": "boom"}),
            ("code as text", {"code": "-32601", "message": "method not found"}),
        ):
            with self.subTest(error=label):
                message = self.play({"jsonrpc": "2.0", "id": 1, "error": error})
                self.assertIn("JSON-RPC error", message)

    def test_an_error_next_to_a_result_is_still_an_error(self) -> None:
        message = self.play({"jsonrpc": "2.0", "id": 1, "error": {"code": 1, "message": "x"}, "result": {"a": 1}})
        self.assertIn("JSON-RPC error", message)

    def test_shapes_that_are_not_json_rpc_at_all_are_errors(self) -> None:
        for label, body, needle in (
            ("array", [1, 2, 3], "not a JSON-RPC object"),
            ("string", "ok", "not a JSON-RPC object"),
            ("empty object", {}, "no result"),
            ("only a version", {"jsonrpc": "2.0"}, "no result"),
        ):
            with self.subTest(body=label):
                self.assertIn(needle, self.play(body))

    def test_an_answer_for_another_request_is_an_error(self) -> None:
        message = self.play({"jsonrpc": "2.0", "id": 999, "result": {"a": 1}})
        self.assertIn("does not match", message)

    def test_a_non_object_result_cannot_be_asserted_on(self) -> None:
        with ReplayServer([{"http_status": 200, "body_json": {"jsonrpc": "2.0", "id": 1, "result": "ok"}}]) as server:
            result = call(server)
        problems = capture_live.evaluate_asserts([{"kind": "field-exists", "field": "x"}], result)
        self.assertEqual(len(problems), 1)
        self.assertIn("not an object", problems[0])

    def test_other_http_statuses_are_transport_errors_not_results(self) -> None:
        for status in (400, 403, 404, 429, 500, 502, 503):
            with self.subTest(status=status), ReplayServer([{"http_status": status, "body_text": "no"}]) as server:
                message = capture_error(server)
                self.assertIn(f"HTTP {status}", message)
                self.assertNotIn("JSON-RPC error", message)


if __name__ == "__main__":
    unittest.main()
