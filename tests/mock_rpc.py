"""A local mock of the read-only Soroban RPC endpoint (issue #368).

Stdlib only. Not a test module itself: ``unittest discover`` ignores it
because its name does not start with ``test``.

The mock answers the three read-only methods CF-04 section 8 names and can
be told to fail in the ways a capture has to survive: an HTTP error, an
answer that never comes in time, an answer that is not JSON, and a JSON-RPC
error. The protocol version it reports is configurable, so a test can play
an endpoint that has moved past the protocol a fixture targets.

It is also runnable, so a fork can do a dry run against it without a
network:

    python3 tests/mock_rpc.py --port 8099 &
    python3 tools/evidence/capture_live.py protocol-28 \\
        --local-endpoint http://127.0.0.1:8099 --output-dir /tmp/live-evidence
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# How a method may misbehave.
BEHAVIOR_OK = "ok"
BEHAVIOR_ERROR = "error"
BEHAVIOR_HANG = "hang"
BEHAVIOR_MALFORMED = "malformed"
BEHAVIOR_RPC_ERROR = "rpc-error"
BEHAVIOR_NO_RESULT = "no-result"
BEHAVIOR_WRONG_ID = "wrong-id"
BEHAVIOR_NOT_OBJECT = "not-object"
BEHAVIOR_NO_PASSPHRASE = "no-passphrase"
BEHAVIOR_NO_PROTOCOL = "no-protocol"
BEHAVIOR_RESULT_NOT_OBJECT = "result-not-object"

# The passphrase the public Testnet endpoint answers with.
TESTNET_PASSPHRASE = "Test SDF Network ; September 2015"


class MockRpcServer:
    """A read-only RPC endpoint on the loopback interface.

    Use it as a context manager::

        with MockRpcServer(protocol=28) as server:
            ...  # server.url is the endpoint to call
    """

    def __init__(
        self,
        protocol: int = 28,
        behaviors: dict[str, str] | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        hang_seconds: float = 5.0,
    ) -> None:
        self.protocol = protocol
        self.behaviors = dict(behaviors or {})
        self.host = host
        self.port = port
        self.hang_seconds = hang_seconds
        # The methods the mock was asked for, in order.
        self.requests: list[str] = []
        # The headers of every request the mock received.
        self.headers: list[dict[str, str]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "MockRpcServer":
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
                server._handle(self)

            def log_message(self, *args: object) -> None:
                """Keep the test output quiet."""

            def handle_one_request(self) -> None:
                # A client that gave up (the timeout case) closes the
                # connection before the answer is written; the resulting
                # broken pipe is the client's decision, not a server error.
                try:
                    super().handle_one_request()
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> bool:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=10)
        return False

    # ------------------------------------------------------------- answers

    def result(self, method: str) -> dict:
        """The answer the mock gives for a read-only method."""
        if method == "getNetwork":
            return {
                "friendbotUrl": "https://friendbot.stellar.org/",
                "passphrase": TESTNET_PASSPHRASE,
                "protocolVersion": self.protocol,
            }
        if method == "getLatestLedger":
            return {
                "id": "b14f99c1c9240f28649e681a70eb8d690d660103f384d142aaaf20ea09ef479b",
                "protocolVersion": self.protocol,
                "sequence": 4919600,
                "closeTime": "1790621587",
                "headerXdr": "AAAAHM5QXeK0Jm8nCQqJ",
                "metadataXdr": "AAAAAgAAAACxT5nBySQPKGSeaBpw",
            }
        if method == "getVersionInfo":
            return {
                "version": "28.0.0-0000000000000000000000000000000000000000",
                "commitHash": "0000000000000000000000000000000000000000",
                "buildTimestamp": "2026-09-28T00:00:00",
                "captiveCoreVersion": "stellar-core 28.0.0",
                "protocolVersion": self.protocol,
            }
        return {}

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
        self.headers.append({key.lower(): value for key, value in handler.headers.items()})
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            request = {}
        method = request.get("method") if isinstance(request, dict) else None
        request_id = request.get("id", 1) if isinstance(request, dict) else 1
        if isinstance(method, str):
            self.requests.append(method)

        behavior = self.behaviors.get(method, BEHAVIOR_OK) if method else BEHAVIOR_ERROR
        if behavior == BEHAVIOR_HANG:
            time.sleep(self.hang_seconds)
        if behavior == BEHAVIOR_ERROR:
            self._send(handler, 500, b"the endpoint could not answer")
            return
        if behavior == BEHAVIOR_MALFORMED:
            self._send(handler, 200, b"this is not JSON")
            return
        if behavior == BEHAVIOR_RPC_ERROR:
            self._send_json(
                handler,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "method not found"},
                },
            )
            return
        if behavior == BEHAVIOR_NO_RESULT:
            # A well-formed JSON-RPC message that carries no result at all.
            self._send_json(handler, {"jsonrpc": "2.0", "id": request_id})
            return
        if behavior == BEHAVIOR_WRONG_ID:
            # The answer belongs to another request.
            self._send_json(
                handler,
                {
                    "jsonrpc": "2.0",
                    "id": 999,
                    "result": self.result(method) if isinstance(method, str) else {},
                },
            )
            return
        if behavior == BEHAVIOR_NOT_OBJECT:
            # Valid JSON, but not a JSON-RPC object.
            self._send_json(handler, [1, 2, 3])
            return
        if behavior == BEHAVIOR_RESULT_NOT_OBJECT:
            # A well-formed JSON-RPC object whose result is not an object.
            self._send_json(
                handler, {"jsonrpc": "2.0", "id": request_id, "result": [1, 2, 3]}
            )
            return
        if behavior in (BEHAVIOR_NO_PASSPHRASE, BEHAVIOR_NO_PROTOCOL):
            result = self.result(method) if isinstance(method, str) else {}
            result = dict(result)
            if behavior == BEHAVIOR_NO_PASSPHRASE:
                result.pop("passphrase", None)
            else:
                result.pop("protocolVersion", None)
            self._send_json(
                handler, {"jsonrpc": "2.0", "id": request_id, "result": result}
            )
            return
        self._send_json(
            handler,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self.result(method) if isinstance(method, str) else {},
            },
        )

    @staticmethod
    def _send(handler: BaseHTTPRequestHandler, status: int, payload: bytes) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    @staticmethod
    def _send_json(handler: BaseHTTPRequestHandler, document: dict) -> None:
        MockRpcServer._send(handler, 200, json.dumps(document).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mock_rpc.py",
        description=(
            "Serve the read-only Soroban RPC methods on the loopback interface, "
            "so the capture tool can be exercised without a network."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="the address to listen on")
    parser.add_argument("--port", type=int, default=0, help="the port to listen on")
    parser.add_argument(
        "--protocol",
        type=int,
        default=28,
        help="the protocol version the endpoint reports (default: 28)",
    )
    parser.add_argument(
        "--fail-method",
        action="append",
        default=[],
        metavar="METHOD",
        help="a method that answers HTTP 500 (repeatable)",
    )
    parser.add_argument(
        "--hang-method",
        action="append",
        default=[],
        metavar="METHOD",
        help="a method that never answers in time (repeatable)",
    )
    parser.add_argument(
        "--malformed-method",
        action="append",
        default=[],
        metavar="METHOD",
        help="a method that answers with something that is not JSON (repeatable)",
    )
    parser.add_argument(
        "--rpc-error-method",
        action="append",
        default=[],
        metavar="METHOD",
        help="a method that answers with a JSON-RPC error (repeatable)",
    )
    parser.add_argument(
        "--no-result-method",
        action="append",
        default=[],
        metavar="METHOD",
        help="a method whose answer carries no result (repeatable)",
    )
    parser.add_argument(
        "--wrong-id-method",
        action="append",
        default=[],
        metavar="METHOD",
        help="a method whose answer carries another request's id (repeatable)",
    )
    args = parser.parse_args(argv)

    behaviors: dict[str, str] = {}
    for method in args.fail_method:
        behaviors[method] = BEHAVIOR_ERROR
    for method in args.hang_method:
        behaviors[method] = BEHAVIOR_HANG
    for method in args.malformed_method:
        behaviors[method] = BEHAVIOR_MALFORMED
    for method in args.rpc_error_method:
        behaviors[method] = BEHAVIOR_RPC_ERROR
    for method in args.no_result_method:
        behaviors[method] = BEHAVIOR_NO_RESULT
    for method in args.wrong_id_method:
        behaviors[method] = BEHAVIOR_WRONG_ID

    with MockRpcServer(protocol=args.protocol, behaviors=behaviors, host=args.host, port=args.port) as server:
        print(f"mock read-only endpoint on {server.url} (protocol {args.protocol})")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
