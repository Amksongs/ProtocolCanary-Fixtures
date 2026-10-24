"""Tests for tools/validate/check_source_links.py.

All tests are completely offline: tests that verify HTTP request handling,
status codes, timeouts, redirect loops, and credential stripping spin up a local
HTTP server on 127.0.0.1 and shut it down cleanly.

The address policy is tested with injected (fake) resolvers and a fake socket
layer: no test resolves a real name, connects to a real private or internal
address, or touches the real internet. The local test server is reached by
injecting a permissive policy -- the tool itself has no command-line flag or
environment variable that could weaken the policy used in CI.
"""
from __future__ import annotations

import io
import os
import socket
import tempfile
import threading
import time
import urllib.error
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from tools.validate.check_source_links import (
    AddressPolicy,
    CheckResult,
    clean_comment_url,
    check_link,
    DEFAULT_MAX_REDIRECTS,
    extract_links_from_file,
    generate_markdown_table,
    main,
    strip_credentials,
)

# The test server on 127.0.0.1 is not a public address, so the tests that use
# it inject this permissive policy. CI never does: there is no flag for it.
LOOPBACK_POLICY = AddressPolicy(allow_non_public=True)


def _public_answer(host: str, port: int, **kwargs):
    """Fake resolver: every name answers one fixed public address (no real DNS)."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))
    ]


# Strict policy with a fake resolver, for tests that use mock openers and a
# public-looking host name: the policy is exercised, DNS stays in-process.
FAKE_PUBLIC_POLICY = AddressPolicy(resolver=_public_answer)


class MockServerHandler(BaseHTTPRequestHandler):
    """Local HTTP handler for testing link checking scenarios."""

    def do_GET(self) -> None:
        path = self.path

        if path == "/200":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif path == "/redirect-to-200":
            self.send_response(302)
            self.send_header("Location", "/200")
            self.end_headers()
        elif path == "/redirect-chain-1":
            self.send_response(301)
            self.send_header("Location", "/redirect-chain-2")
            self.end_headers()
        elif path == "/redirect-chain-2":
            self.send_response(301)
            self.send_header("Location", "/redirect-chain-3")
            self.end_headers()
        elif path == "/redirect-chain-3":
            self.send_response(301)
            self.send_header("Location", "/200")
            self.end_headers()
        elif path == "/loop-a":
            self.send_response(302)
            self.send_header("Location", "/loop-b")
            self.end_headers()
        elif path == "/loop-b":
            self.send_response(302)
            self.send_header("Location", "/loop-a")
            self.end_headers()
        elif path == "/redirect-to-ftp":
            self.send_response(302)
            self.send_header("Location", "ftp://example.com/file")
            self.end_headers()
        elif path == "/429":
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Too Many Requests")
        elif path == "/404":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
        elif path == "/500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Server Error")
        elif path == "/hang":
            time.sleep(0.4)
            self.send_response(200)
            self.end_headers()
        elif path == "/auth-check":
            # Verify no Authorization header or credentials arrived
            auth = self.headers.get("Authorization")
            if auth:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"Credentials leaked in header")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"No credentials sent")
        elif path == "/rpc-endpoint":
            # Rejects GET with 405 Method Not Allowed
            self.send_response(405)
            self.end_headers()
        elif path.startswith("/redirect-status/"):
            code = int(path.split("/")[-1])
            self.send_response(code)
            self.send_header("Location", "/200")
            self.end_headers()
        elif path.startswith("/status/"):
            code = int(path.split("/")[-1])
            self.send_response(code)
            self.end_headers()
        elif path.startswith("/chain/"):
            n = int(path.split("/")[-1])
            if n == 0:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(302)
                self.send_header("Location", f"/chain/{n - 1}")
                self.end_headers()
        elif path == "/redirect-no-location":
            self.send_response(302)
            self.end_headers()
        elif path == "/redirect-relative":
            self.send_response(302)
            self.send_header("Location", "/relative-target")
            self.end_headers()
        elif path == "/relative-target":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/rpc-endpoint":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result": "ok"}')
        else:
            self.send_response(405)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Silence HTTP server logs during test execution
        pass


class TestCheckSourceLinks(unittest.TestCase):
    server: ThreadingHTTPServer
    server_thread: threading.Thread
    base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockServerHandler)
        port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def test_strip_credentials(self) -> None:
        self.assertEqual(
            strip_credentials("https://user:pass@example.com/path"),
            "https://example.com/path",
        )
        self.assertEqual(
            strip_credentials("http://alice:secret@127.0.0.1:8080/test?q=1#frag"),
            "http://127.0.0.1:8080/test?q=1#frag",
        )
        self.assertEqual(
            strip_credentials("https://user@example.com/foo"),
            "https://example.com/foo",
        )
        self.assertEqual(
            strip_credentials("ftp://admin:secret@ftp.example.com/file"),
            "ftp://ftp.example.com/file",
        )
        self.assertEqual(
            strip_credentials("https://example.com/clean"),
            "https://example.com/clean",
        )

    def test_clean_comment_url(self) -> None:
        self.assertEqual(clean_comment_url("https://example.com/foo."), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo:"), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo,"), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo;"), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo!"), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo?"), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo'"), "https://example.com/foo")
        self.assertEqual(clean_comment_url('https://example.com/foo"'), "https://example.com/foo")
        self.assertEqual(clean_comment_url("https://example.com/foo)"), "https://example.com/foo")
        # Retain closing paren when opening paren is part of the URL
        self.assertEqual(
            clean_comment_url("https://example.com/wiki/Foo_(bar)"),
            "https://example.com/wiki/Foo_(bar)",
        )

    def test_extract_links_from_file(self) -> None:
        fixture_content = """# Header comment 1 with https://example.com/comment1.
# Header comment 2 with https://user:pass@example.com/comment2:
# (Another comment with https://example.com/comment3)
# Duplicate mention of https://example.com/comment1 in header.

id = "p28-test-fixture"
protocol = 28
surface = "xdr"
source_reference = "https://example.com/source-ref"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fp:
            fp.write(fixture_content)
            temp_path = Path(fp.name)

        try:
            links = extract_links_from_file(temp_path)
            self.assertEqual(
                links,
                [
                    "https://example.com/comment1",
                    "https://example.com/comment2",
                    "https://example.com/comment3",
                    "https://example.com/source-ref",
                ],
            )
        finally:
            temp_path.unlink()

    def test_extract_links_skips_cap_identifiers(self) -> None:
        fixture_content = """# Header with no URLs.
id = "p28-test-cap"
protocol = 28
surface = "xdr"
source_reference = "CAP-0083"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fp:
            fp.write(fixture_content)
            temp_path = Path(fp.name)

        try:
            links = extract_links_from_file(temp_path)
            self.assertEqual(links, [])
        finally:
            temp_path.unlink()

    def test_extract_links_includes_non_http_source_reference(self) -> None:
        fixture_content = """# Header with no URLs.
id = "p28-test-ftp"
source_reference = "ftp://example.com/spec.txt"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fp:
            fp.write(fixture_content)
            temp_path = Path(fp.name)

        try:
            links = extract_links_from_file(temp_path)
            self.assertEqual(links, ["ftp://example.com/spec.txt"])
        finally:
            temp_path.unlink()

    def test_extract_links_from_unreadable_file(self) -> None:
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            self.assertEqual(extract_links_from_file(Path("unreadable.toml")), [])

    def test_extract_links_keeps_header_urls_when_toml_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "broken.toml"
            path.write_text(
                "# https://example.com/header\nnot valid [[[ toml\n",
                encoding="utf-8",
            )
            self.assertEqual(
                extract_links_from_file(path), ["https://example.com/header"]
            )

    def test_check_link_200_ok(self) -> None:
        res = check_link(f"{self.base_url}/200", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "OK")
        self.assertEqual(res.formatted(), "OK")

    def test_check_link_redirect_to_200(self) -> None:
        res = check_link(f"{self.base_url}/redirect-to-200", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "OK")

    def test_check_link_429_inconclusive(self) -> None:
        res = check_link(f"{self.base_url}/429", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "Inconclusive")
        self.assertIn("429", res.formatted())

    def test_check_link_404_failed(self) -> None:
        res = check_link(f"{self.base_url}/404", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "Failed")
        self.assertIn("404", res.formatted())

    def test_check_link_500_failed(self) -> None:
        res = check_link(f"{self.base_url}/500", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "Failed")
        self.assertIn("500", res.formatted())

    def test_check_link_post_fallback_failures(self) -> None:
        url = f"{self.base_url}/rpc-endpoint"
        # An explicit empty body, not None: HTTPError is an addinfourl, and
        # on Python 3.14 that base class wraps the body in a
        # tempfile._TemporaryFileWrapper, whose __del__ warns
        # (ResourceWarning) when it is collected unclosed. check_link closes
        # what it catches and only reads `code`, so an empty body changes
        # nothing it observes.
        cases = (
            (
                urllib.error.HTTPError(url, 429, "Too Many Requests", {}, io.BytesIO(b"")),
                "Inconclusive",
                "429",
            ),
            (
                urllib.error.HTTPError(url, 503, "Unavailable", {}, io.BytesIO(b"")),
                "Failed",
                "503",
            ),
            (RuntimeError("connection reset"), "Failed", "POST fallback failed"),
        )
        for post_error, expected_status, expected_detail in cases:
            with self.subTest(error=type(post_error).__name__):
                opener = Mock()
                opener.open.side_effect = [
                    urllib.error.HTTPError(
                        url, 405, "Method Not Allowed", {}, io.BytesIO(b"")
                    ),
                    post_error,
                ]
                result = check_link(url, opener=opener, policy=LOOPBACK_POLICY)
                self.assertEqual(result.status, expected_status)
                self.assertIn(expected_detail, result.formatted())
                self.assertEqual(opener.open.call_count, 2)

    def test_check_link_network_and_unexpected_errors(self) -> None:
        cases = (
            (urllib.error.URLError("connection refused"), "network error"),
            (RuntimeError("unexpected"), "RuntimeError"),
        )
        for error, expected_detail in cases:
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                result = check_link("https://example.com/", opener=opener, policy=FAKE_PUBLIC_POLICY)
                self.assertEqual(result.status, "Failed")
                self.assertIn(expected_detail, result.formatted())

    def test_check_link_rejects_invalid_and_hostless_urls(self) -> None:
        invalid = check_link("http://[invalid")
        self.assertEqual(invalid.status, "Failed")
        self.assertIn("invalid URL", invalid.formatted())

        hostless = check_link("http:///path")
        self.assertEqual(hostless.status, "Failed")
        self.assertIn("missing host", hostless.formatted())

    def test_check_link_handles_final_status_without_http_error(self) -> None:
        for status, expected_status in ((429, "Inconclusive"), (503, "Failed")):
            with self.subTest(status=status):
                response = Mock(status=status, headers={})
                opener = Mock()
                opener.open.return_value = response
                result = check_link("https://example.com/", opener=opener, policy=FAKE_PUBLIC_POLICY)
                self.assertEqual(result.status, expected_status)
                self.assertIn(str(status), result.formatted())
                response.close.assert_called_once_with()

    def test_check_link_redirect_limit(self) -> None:
        # Chain has 3 redirects; limit of 2 should fail
        res = check_link(
            f"{self.base_url}/redirect-chain-1", max_redirects=2, policy=LOOPBACK_POLICY
        )
        self.assertEqual(res.status, "Failed")
        self.assertIn("too many redirects", res.formatted())

        # Limit of 4 should succeed
        res_ok = check_link(
            f"{self.base_url}/redirect-chain-1", max_redirects=4, policy=LOOPBACK_POLICY
        )
        self.assertEqual(res_ok.status, "OK")

    def test_every_redirect_status_followed_and_non_redirect_3xx_failed(self) -> None:
        """Every redirect status code (301, 302, 303, 307, 308) is followed to 200 OK, while 300/304 fail (F-125, issue #421)."""
        redirect_statuses = (301, 302, 303, 307, 308)
        for status in redirect_statuses:
            with self.subTest(redirect_status=status):
                res = check_link(f"{self.base_url}/redirect-status/{status}", policy=LOOPBACK_POLICY)
                self.assertEqual(res.status, "OK", f"expected status {status} to be followed to OK")
                self.assertEqual(res.formatted(), "OK")

        non_redirect_statuses = (300, 304)
        for status in non_redirect_statuses:
            with self.subTest(non_redirect_status=status):
                res = check_link(f"{self.base_url}/status/{status}", policy=LOOPBACK_POLICY)
                self.assertEqual(res.status, "Failed")
                self.assertIn(f"HTTP {status}", res.formatted())

    def test_redirect_limit_exact_boundaries(self) -> None:
        """A chain of exactly N redirects passes; N - 1 fails; max_redirects=0 with 1 redirect fails and 0 passes (F-125, issue #421)."""
        # Chain of 3 redirects
        res_exact = check_link(f"{self.base_url}/chain/3", max_redirects=3, policy=LOOPBACK_POLICY)
        self.assertEqual(res_exact.status, "OK")

        res_over = check_link(f"{self.base_url}/chain/3", max_redirects=2, policy=LOOPBACK_POLICY)
        self.assertEqual(res_over.status, "Failed")
        self.assertIn("too many redirects (exceeded limit of 2)", res_over.formatted())

        # max_redirects = 0
        res_zero_ok = check_link(f"{self.base_url}/chain/0", max_redirects=0, policy=LOOPBACK_POLICY)
        self.assertEqual(res_zero_ok.status, "OK")

        res_zero_fail = check_link(f"{self.base_url}/chain/1", max_redirects=0, policy=LOOPBACK_POLICY)
        self.assertEqual(res_zero_fail.status, "Failed")
        self.assertIn("too many redirects (exceeded limit of 0)", res_zero_fail.formatted())

    def test_default_max_redirects_boundary(self) -> None:
        """Assert DEFAULT_MAX_REDIRECTS == 5, 5 redirects pass with default, 6 fail (F-125, issue #421)."""
        self.assertEqual(DEFAULT_MAX_REDIRECTS, 5)

        res_5 = check_link(f"{self.base_url}/chain/5", policy=LOOPBACK_POLICY)
        self.assertEqual(res_5.status, "OK")

        res_6 = check_link(f"{self.base_url}/chain/6", policy=LOOPBACK_POLICY)
        self.assertEqual(res_6.status, "Failed")
        self.assertIn("too many redirects (exceeded limit of 5)", res_6.formatted())

    def test_redirect_location_handling_relative_and_missing(self) -> None:
        """Relative Location resolves against current URL; redirect without Location fails (F-125, issue #421)."""
        # Relative Location
        res_rel = check_link(f"{self.base_url}/redirect-relative", policy=LOOPBACK_POLICY)
        self.assertEqual(res_rel.status, "OK")

        # Missing Location header
        res_missing = check_link(f"{self.base_url}/redirect-no-location", policy=LOOPBACK_POLICY)
        self.assertEqual(res_missing.status, "Failed")
        self.assertIn("missing Location header", res_missing.formatted())
        self.assertIn("HTTP 302", res_missing.formatted())

    def test_check_link_redirect_loop_detection(self) -> None:
        res = check_link(f"{self.base_url}/loop-a", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "Failed")
        self.assertIn("redirect loop", res.formatted())

    def test_check_link_non_http_scheme(self) -> None:
        res_ftp = check_link("ftp://ftp.example.com/file")
        self.assertEqual(res_ftp.status, "Failed")
        self.assertIn("non-HTTP scheme", res_ftp.formatted())

        res_file = check_link("file:///etc/passwd")
        self.assertEqual(res_file.status, "Failed")
        self.assertIn("non-HTTP scheme", res_file.formatted())

    def test_check_link_redirect_to_non_http_scheme(self) -> None:
        res = check_link(f"{self.base_url}/redirect-to-ftp", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "Failed")
        self.assertIn("redirected to non-HTTP scheme", res.formatted())

    def test_check_link_credential_stripping_and_no_leak(self) -> None:
        url_with_creds = f"http://secret_user:secret_pass@127.0.0.1:{self.server.server_address[1]}/auth-check"
        res = check_link(url_with_creds, policy=LOOPBACK_POLICY)
        # Server verifies no credentials arrived and returns 200
        self.assertEqual(res.status, "OK")
        # Ensure credentials do not appear in formatted result
        self.assertNotIn("secret_user", res.formatted())
        self.assertNotIn("secret_pass", res.formatted())

    def test_check_link_timeout(self) -> None:
        res = check_link(f"{self.base_url}/hang", timeout=0.1, policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "Failed")
        self.assertIn("timed out", res.formatted().lower())

    def test_check_link_rpc_post_fallback(self) -> None:
        res = check_link(f"{self.base_url}/rpc-endpoint", policy=LOOPBACK_POLICY)
        self.assertEqual(res.status, "OK")

    def test_generate_markdown_table(self) -> None:
        rows = [
            ("https://example.com/a", "protocol-28/a.toml", CheckResult("OK")),
            ("https://example.com/b", "protocol-28/b.toml", CheckResult("Inconclusive", "HTTP 429")),
            ("https://example.com/c", "protocol-28/c.toml", CheckResult("Failed", "HTTP 404")),
        ]
        table = generate_markdown_table(rows)
        self.assertIn("| URL | Fixture File | Result |", table)
        self.assertIn("| https://example.com/a | protocol-28/a.toml | OK |", table)
        self.assertIn("| https://example.com/b | protocol-28/b.toml | Inconclusive (HTTP 429) |", table)
        self.assertIn("| https://example.com/c | protocol-28/c.toml | Failed (HTTP 404) |", table)

    def test_main_cli_passes_with_ok_and_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            f1 = Path(tmp_dir) / "f1.toml"
            f1.write_text(f'source_reference = "{self.base_url}/200"\n')

            f2 = Path(tmp_dir) / "f2.toml"
            f2.write_text(f'source_reference = "{self.base_url}/429"\n')

            summary_file = Path(tmp_dir) / "summary.md"

            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf), patch(
                "tools.validate.check_source_links.DEFAULT_ADDRESS_POLICY",
                LOOPBACK_POLICY,
            ):
                exit_code = main([tmp_dir, "--summary-file", str(summary_file)])

            # 429 is inconclusive, does not fail the job!
            self.assertEqual(exit_code, 0)
            output = stdout_buf.getvalue()
            self.assertIn("| URL | Fixture File | Result |", output)
            self.assertIn("OK", output)
            self.assertIn("Inconclusive", output)

            # Summary file was written
            self.assertTrue(summary_file.exists())
            summary_content = summary_file.read_text()
            self.assertIn("| URL | Fixture File | Result |", summary_content)

    def test_main_cli_fails_with_broken_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            f1 = Path(tmp_dir) / "f1.toml"
            f1.write_text(f'source_reference = "{self.base_url}/404"\n')

            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf), patch(
                "tools.validate.check_source_links.DEFAULT_ADDRESS_POLICY",
                LOOPBACK_POLICY,
            ):
                exit_code = main([tmp_dir])

            self.assertEqual(exit_code, 1)
            output = stdout_buf.getvalue()
            self.assertIn("Failed (HTTP 404)", output)

    def test_main_rejects_invalid_explicit_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            non_toml = root / "not-a-fixture.txt"
            non_toml.write_text("content", encoding="utf-8")
            missing = root / "missing"

            for path in (missing, non_toml):
                with self.subTest(path=path):
                    stderr_buf = io.StringIO()
                    with patch("sys.stderr", stderr_buf):
                        exit_code = main([str(path)])
                    self.assertEqual(exit_code, 2)
                    self.assertIn(str(path), stderr_buf.getvalue())

    def test_main_rejects_explicit_roots_without_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            empty = Path(tmp_dir) / "empty"
            empty.mkdir()
            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                exit_code = main([str(empty)])
            self.assertEqual(exit_code, 2)
            self.assertIn(str(empty), stderr_buf.getvalue())

    def test_main_accepts_a_toml_file_as_an_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture = Path(tmp_dir) / "fixture.toml"
            fixture.write_text('source_reference = "CAP-0083"\n', encoding="utf-8")
            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf):
                exit_code = main([str(fixture)])
            self.assertEqual(exit_code, 0)
            self.assertIn("0 checked across 1 fixture files", stdout_buf.getvalue())

    def test_main_uses_default_roots_without_rejecting_empty_packs(self) -> None:
        default_root = Path("protocol-27")
        with patch.object(Path, "glob", return_value=[default_root]), patch(
            "tools.validate.check_source_links.find_fixture_files", return_value=[]
        ) as find_files:
            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf):
                exit_code = main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("0 checked across 0 fixture files", stdout_buf.getvalue())
        find_files.assert_called_once_with(default_root)

    def test_main_warns_when_summary_file_cannot_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "fixture.toml").write_text(
                'source_reference = "CAP-0083"\n', encoding="utf-8"
            )
            stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
            with patch("sys.stdout", stdout_buf), patch("sys.stderr", stderr_buf):
                exit_code = main([tmp_dir, "--summary-file", tmp_dir])
            self.assertEqual(exit_code, 0)
            self.assertIn("Warning: could not write to summary file", stderr_buf.getvalue())


class NonPublicDestinationTests(unittest.TestCase):
    """The address policy refuses non-public destinations before any connect.

    DNS and the socket layer are replaced by fakes here: no test resolves a
    real name, connects to a real private or internal address, or touches the
    real internet.
    """

    NON_PUBLIC_ANSWERS = (
        "127.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "fe80::1",
        "fd00::1",
        "100.64.0.1",
        "0.0.0.0",
    )

    @staticmethod
    def answer(address: str, port: int):
        """One getaddrinfo-shaped answer for ``address``."""
        if ":" in address:
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (address, port, 0, 0),
                )
            ]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
        ]

    @staticmethod
    def fake_socket():
        """A fake socket layer that fails the test if it is ever asked to connect."""
        return Mock(
            side_effect=AssertionError("the fake socket layer must not be asked to connect")
        )

    @staticmethod
    def resolver(*addresses):
        """A fake resolver answering with ``addresses``; also records its calls."""
        calls: list[tuple[str, int]] = []

        def resolve(host: str, port: int, **kwargs):
            calls.append((host, port))
            answers = []
            for address in addresses:
                answers.extend(NonPublicDestinationTests.answer(address, port))
            return answers

        return resolve, calls

    def test_refuses_hosts_that_resolve_to_non_public_addresses(self) -> None:
        for address in self.NON_PUBLIC_ANSWERS:
            with self.subTest(address=address):
                resolve, calls = self.resolver(address)
                fake_socket = self.fake_socket()
                with patch("socket.create_connection", fake_socket):
                    result = check_link(
                        "https://metadata.internal/latest/meta-data/",
                        policy=AddressPolicy(resolver=resolve),
                    )
                self.assertEqual(result.status, "Failed")
                self.assertEqual(result.formatted(), "Failed (refused: non-public address)")
                # Refused before any connection was attempted, and the
                # resolved address is not disclosed in the reported reason.
                fake_socket.assert_not_called()
                self.assertNotIn(address, result.formatted())
                self.assertEqual(calls, [("metadata.internal", 443)])

    def test_refuses_host_with_one_public_and_one_private_answer(self) -> None:
        resolve, _ = self.resolver("93.184.216.34", "10.0.0.5")
        fake_socket = self.fake_socket()
        with patch("socket.create_connection", fake_socket):
            result = check_link(
                "https://mixed.example/page", policy=AddressPolicy(resolver=resolve)
            )
        self.assertEqual(result.formatted(), "Failed (refused: non-public address)")
        fake_socket.assert_not_called()

    def test_refuses_ip_literal_urls_without_any_dns(self) -> None:
        urls = (
            "http://2130706433/",
            "http://0x7f.1/",
            "http://0177.0.0.1/",
            "http://[::1]/",
        )
        for url in urls:
            with self.subTest(url=url):
                fake_socket = self.fake_socket()
                with patch("socket.create_connection", fake_socket), patch(
                    "socket.getaddrinfo",
                    side_effect=AssertionError("DNS must not be queried for an IP literal"),
                ):
                    result = check_link(url)
                self.assertEqual(result.formatted(), "Failed (refused: non-public address)")
                fake_socket.assert_not_called()

    def test_refuses_redirect_hop_to_non_public_destination(self) -> None:
        resolve, calls = self.resolver("93.184.216.34")
        policy = AddressPolicy(resolver=resolve)
        redirect = Mock(
            status=302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
        )
        opener = Mock()
        opener.open.return_value = redirect

        result = check_link("https://example.org/start", opener=opener, policy=policy)

        self.assertEqual(result.formatted(), "Failed (refused: non-public address)")
        # Refused at the redirect hop, before a second request was made, and
        # the private hop never reached the resolver either.
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(calls, [("example.org", 443)])
        redirect.close.assert_called_once_with()

    def test_post_fallback_applies_the_same_policy(self) -> None:
        calls: list[str] = []

        def resolve(host: str, port: int, **kwargs):
            calls.append(host)
            address = "93.184.216.34" if len(calls) == 1 else "10.0.0.5"
            return self.answer(address, port)

        url = "https://rpc.example.org/methods"
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            url, 405, "Method Not Allowed", {}, None
        )

        result = check_link(url, opener=opener, policy=AddressPolicy(resolver=resolve))

        self.assertEqual(result.formatted(), "Failed (refused: non-public address)")
        # Only the GET ran; the POST fallback never sent a request.
        self.assertEqual(opener.open.call_count, 1)

    def test_connects_only_to_the_first_validated_address(self) -> None:
        calls: list[str] = []

        def resolve(host: str, port: int, **kwargs):
            calls.append(host)
            # Public on the first lookup, private on the second: the second
            # answer must never be looked up, let alone dialled.
            address = "93.184.216.34" if len(calls) == 1 else "10.0.0.5"
            return self.answer(address, port)

        dialed: list[tuple] = []

        def fake_connect(address, *args, **kwargs):
            dialed.append(address)
            raise OSError("connection blocked by test")

        with patch("socket.create_connection", side_effect=fake_connect):
            result = check_link(
                "https://example.org/page", policy=AddressPolicy(resolver=resolve)
            )

        self.assertEqual(result.status, "Failed")
        self.assertEqual(dialed, [("93.184.216.34", 443)])
        self.assertEqual(len(calls), 1)

    def test_main_refuses_a_non_public_source_reference_without_any_flag(self) -> None:
        # No command-line flag and no environment variable can weaken the
        # policy: the default one refuses this fixture's link outright.
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "fixture.toml").write_text(
                'source_reference = "http://169.254.169.254/latest/meta-data/"\n',
                encoding="utf-8",
            )
            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf), patch(
                "socket.create_connection", self.fake_socket()
            ):
                exit_code = main([tmp_dir])
        self.assertEqual(exit_code, 1)
        self.assertIn("refused: non-public address", stdout_buf.getvalue())


class MarkdownTableEscapingTests(unittest.TestCase):
    """F-107: hostile fixture text must not reshape the job summary table.

    URLs, file names and result details all originate from fixture content or
    exception text a fixture author influences, so every interpolated value
    must stay inside exactly one cell of exactly one line.
    """

    HOSTILE_ROWS = [
        ("https://a.example/x|y", "f.toml", CheckResult("Failed", "a|b\nc")),
        (
            "https://b.example/[x](https://evil.example)<script>",
            "b|c.toml",
            CheckResult("OK"),
        ),
        (
            "https://c.example/a?b=c",
            "plain name.toml",
            CheckResult("Inconclusive", "tick `code` & slash \\ end"),
        ),
    ]

    @staticmethod
    def cells(line: str) -> list[str]:
        """Split a table line into cells; escaped pipes are not separators."""
        # "| a | b | c |" -> ['', ' a ', ' b ', ' c ', '']
        return line.replace("\\|", "").split("|")[1:-1]

    def test_header_and_separator_are_exact(self) -> None:
        table = generate_markdown_table(list(self.HOSTILE_ROWS))
        lines = table.split("\n")
        self.assertEqual(lines[0], "| URL | Fixture File | Result |")
        self.assertEqual(lines[1], "|---|---|---|")
        # One line per row: no value's line break split a row in two.
        self.assertEqual(len(lines), 2 + len(self.HOSTILE_ROWS))

    def test_every_row_has_exactly_three_cells(self) -> None:
        table = generate_markdown_table(list(self.HOSTILE_ROWS))
        for line in table.split("\n"):
            with self.subTest(line=line):
                self.assertEqual(len(self.cells(line)), 3)

    def test_pipes_in_values_do_not_add_columns(self) -> None:
        table = generate_markdown_table(list(self.HOSTILE_ROWS))
        self.assertIn("https://a.example/x\\|y", table)
        self.assertIn("b\\|c.toml", table)
        self.assertIn("Failed (a\\|b c)", table)

    def test_markup_is_neutralised_but_plain_urls_stay_readable(self) -> None:
        table = generate_markdown_table(list(self.HOSTILE_ROWS))
        # No live HTML tag, Markdown link or code span survives.
        self.assertNotIn("<script>", table)
        self.assertNotIn("[x](https://evil.example)", table)
        self.assertNotIn("`code`", table)
        self.assertIn("&lt;script&gt;", table)
        self.assertIn("&#91;x&#93;", table)
        self.assertIn("&#96;code&#96;", table)
        self.assertIn("&amp;", table)
        # Ordinary URLs and names are untouched.
        self.assertIn("https://c.example/a?b=c", table)
        self.assertIn("plain name.toml", table)

    def test_count_of_rows_matches_input(self) -> None:
        table = generate_markdown_table(list(self.HOSTILE_ROWS))
        self.assertEqual(len(table.split("\n")) - 2, len(self.HOSTILE_ROWS))
        empty = generate_markdown_table([])
        self.assertEqual(len(empty.split("\n")), 2)


if __name__ == "__main__":
    unittest.main()
