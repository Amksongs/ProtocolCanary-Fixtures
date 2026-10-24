#!/usr/bin/env python3
"""Check fixture source references and header comment links on a schedule.

Scans fixture TOML files for:
  - `source_reference` field values (excluding CAP-XXXX identifiers)
  - `https://` URLs in header comments

Checks each URL with bounded redirects, timeout, 429 rate-limit handling
(treated as inconclusive), non-HTTP scheme protection, credential stripping,
and a strict address policy: only publicly routable destinations may be
contacted, on every redirect hop and on the 405 POST fallback, and the socket
dials the exact address that was validated rather than resolving the name a
second time.
Outputs a formatted markdown table suitable for the GitHub Actions job summary.

Usage:
    python3 tools/validate/check_source_links.py [roots ...]
        [--timeout TIMEOUT] [--max-redirects N] [--summary-file FILE]
"""
from __future__ import annotations

import argparse
import errno
import http.client
import ipaddress
import os
import re
import socket
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

# Regex for extracting https:// URLs from text / comments.
_HTTPS_URL_RE = re.compile(r"https://[^\s\"'<>`]+", re.IGNORECASE)

# CAP identifier pattern (these are specification identifiers, not links).
_CAP_IDENTIFIER_RE = re.compile(r"^CAP-[0-9]{4}$")

# Default request timeout in seconds.
DEFAULT_TIMEOUT = 10.0

# Default maximum number of redirects to follow.
DEFAULT_MAX_REDIRECTS = 5

# Realistic User-Agent to prevent unwarranted blocks by CDNs/hosts.
USER_AGENT = "Mozilla/5.0 (compatible; ProtocolCanary-LinkCheck/1.0; +https://github.com/StellarCanary/ProtocolCanary-Fixtures)"


class NonPublicAddressError(Exception):
    """Raised when a destination is not one this checker may contact.

    The message never contains a resolved address, so a refused host cannot
    leak the naming of an internal network through the job summary.
    """


def _literal_ip_addresses(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address] | None:
    """Parse ``host`` as an IP literal, or return ``None`` when it is a name.

    Handles plain IPv4/IPv6 literals (``urlsplit`` already removes the
    brackets around IPv6) as well as the decimal, hexadecimal and octal IPv4
    forms ``inet_aton`` accepts (``2130706433``, ``0x7f.1``, ``0177.0.0.1``),
    so such URLs are judged without touching DNS.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return [ipaddress.ip_address(packed)]


def _is_globally_routable(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for addresses this checker is allowed to contact.

    Refused: loopback, private, link-local (169.254.0.0/16 and fe80::/10),
    unique-local (fc00::/7), carrier-grade NAT (100.64.0.0/10), multicast,
    reserved and unspecified addresses. IPv4-mapped IPv6 addresses
    (``::ffff:a.b.c.d``) are unwrapped first so they are judged as IPv4.

    ``is_global`` alone is not sufficient because Python reports some
    multicast ranges as global, and ``is_private`` alone is not sufficient
    because Python reports carrier-grade NAT addresses as public, so both
    the explicit categories and ``is_global`` are checked.
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    return bool(address.is_global)


class AddressPolicy:
    """Decides which URL destinations the link checker may connect to.

    ``authorize(host, port)`` resolves the host (IP literals are parsed
    without any DNS query), applies the address policy to *every* answer --
    one non-public answer refuses the whole host -- and caches the address
    that was validated. ``validated_address(host)`` returns that cached
    address so the connection layer dials exactly the validated answer
    instead of resolving the name again, when a second DNS answer could
    point somewhere else. If the connection layer asks about a host that was
    never authorized (for example a proxy host taken from the environment),
    the address is validated immediately before the dial and that very
    answer is what gets dialled.

    The strict default (``DEFAULT_ADDRESS_POLICY``) refuses every
    non-globally-routable address. ``allow_non_public=True`` exists so tests
    can point the checker at a loopback test server; there is deliberately no
    command-line flag or environment variable that can weaken the policy a
    CI job runs with.

    Args:
        resolver: callable with ``socket.getaddrinfo``'s signature; defaults
            to ``socket.getaddrinfo`` at call time. Tests inject a fake so no
            DNS query leaves the process.
        allow_non_public: permit non-public destinations. Tests only.
    """

    def __init__(
        self,
        resolver=None,
        allow_non_public: bool = False,
    ) -> None:
        self._resolver = resolver
        self._allow_non_public = allow_non_public
        self._validated: dict[str, str] = {}

    def _addresses(
        self, host: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        literal = _literal_ip_addresses(host)
        if literal is not None:
            return literal
        resolver = self._resolver if self._resolver is not None else socket.getaddrinfo
        answers = resolver(host, port, type=socket.SOCK_STREAM)
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for answer in answers:
            sockaddr = answer[4]
            try:
                address = ipaddress.ip_address(sockaddr[0])
            except ValueError:
                # Cannot be checked, so it cannot be contacted.
                raise NonPublicAddressError("destination could not be verified") from None
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise OSError("name resolution returned no address")
        return addresses

    def authorize(self, host: str, port: int) -> str:
        """Validate ``host`` for connection and return the address to dial.

        Raises ``NonPublicAddressError`` when any resolved answer is not
        publicly routable, or ``OSError`` when resolution itself fails.
        """
        addresses = self._addresses(host, port)
        if not self._allow_non_public:
            for address in addresses:
                if not _is_globally_routable(address):
                    raise NonPublicAddressError("destination is not a public address")
        chosen = str(addresses[0])
        self._validated[host.lower()] = chosen
        return chosen

    def validated_address(self, host: str, port: int) -> str:
        """Return the address a connection to ``host`` must dial.

        Prefers the address ``authorize`` validated moments earlier for the
        same request so no second lookup can change the destination.
        """
        cached = self._validated.get(host.lower())
        if cached is not None:
            return cached
        return self.authorize(host, port)


DEFAULT_ADDRESS_POLICY = AddressPolicy()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that dials an address the policy already validated.

    The host name is left untouched, so the Host header -- and, for HTTPS,
    TLS server name indication and certificate verification -- keep using the
    original name while the socket goes only to the validated address.
    """

    def __init__(self, host, policy: AddressPolicy | None = None, **kwargs) -> None:
        super().__init__(host, **kwargs)
        self._policy = policy

    def _dial_address(self) -> str:
        if self._policy is None:
            raise NonPublicAddressError("destination was never authorized")
        return self._policy.validated_address(self.host, self.port)

    def connect(self) -> None:
        address = self._dial_address()
        self.sock = socket.create_connection(
            (address, self.port), self.timeout, self.source_address
        )
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            if exc.errno != errno.ENOPROTOOPT:
                raise
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials an address the policy already validated.

    Certificate verification and server name indication use the original
    host name; only the TCP connection goes to the validated address.
    """

    def __init__(self, host, policy: AddressPolicy | None = None, **kwargs) -> None:
        super().__init__(host, **kwargs)
        self._policy = policy

    def _dial_address(self) -> str:
        if self._policy is None:
            raise NonPublicAddressError("destination was never authorized")
        return self._policy.validated_address(self.host, self.port)

    def connect(self) -> None:
        address = self._dial_address()
        sock = socket.create_connection(
            (address, self.port), self.timeout, self.source_address
        )
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    """Route plain-HTTP requests through ``_PinnedHTTPConnection``."""

    def __init__(self, policy: AddressPolicy) -> None:
        super().__init__()
        self._policy = policy

    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req, policy=self._policy)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """Route HTTPS requests through ``_PinnedHTTPSConnection``."""

    def __init__(self, policy: AddressPolicy) -> None:
        super().__init__()
        self._policy = policy

    def https_open(self, req):
        return self.do_open(
            _PinnedHTTPSConnection, req, context=self._context, policy=self._policy
        )


def _build_opener(policy: AddressPolicy) -> urllib.request.OpenerDirector:
    """Build an opener that dials only addresses ``policy`` has validated."""
    return urllib.request.build_opener(
        NoRedirectHandler,
        _PinnedHTTPHandler(policy),
        _PinnedHTTPSHandler(policy),
    )


@dataclass(frozen=True)
class CheckResult:
    status: str  # "OK", "Inconclusive", "Failed"
    detail: str = ""

    def formatted(self) -> str:
        if self.detail and self.status != "OK":
            return f"{self.status} ({self.detail})"
        return self.status


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP redirect handler that intercepts redirects so the caller can
    enforce redirect bounds, detect cycles, and strip credentials at each hop.
    """

    def http_error_301(self, req, fp, code, msg, headers):
        return fp

    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    def http_error_303(self, req, fp, code, msg, headers):
        return fp

    def http_error_307(self, req, fp, code, msg, headers):
        return fp

    def http_error_308(self, req, fp, code, msg, headers):
        return fp


def strip_credentials(url: str) -> str:
    """Strip userinfo (username and password) from a URL.

    Ensures that credentials are never transmitted over the wire or leaked
    into logs, tables, or step summaries.
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url

    if parts.username is not None or parts.password is not None or (parts.netloc and "@" in parts.netloc):
        netloc = parts.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


def clean_comment_url(url: str) -> str:
    """Trim surrounding punctuation commonly found after URLs in comments."""
    while url and url[-1] in ".,;:!?'\")":
        if url[-1] == ")" and "(" in url:
            break
        url = url[:-1]
    return url


def extract_links_from_file(path: Path) -> list[str]:
    """Extract source_reference values and header comment https:// URLs from a fixture file.

    Returns a sorted list of unique sanitized URLs.
    """
    try:
        with open(path, "rb") as fp:
            content = fp.read()
    except OSError:
        return []

    text = content.decode("utf-8", errors="replace")
    found_urls: set[str] = set()

    # 1. Header comments: comments at the top of the file before the first TOML body key.
    header_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            header_lines.append(stripped)
        else:
            break

    for comment in header_lines:
        for match in _HTTPS_URL_RE.findall(comment):
            cleaned = clean_comment_url(match)
            if cleaned:
                found_urls.add(strip_credentials(cleaned))

    # 2. Parse TOML to read `source_reference`
    try:
        data = tomllib.loads(text)
        src = data.get("source_reference")
        if isinstance(src, str) and src.strip():
            src_str = src.strip()
            # If it's a CAP identifier (e.g. CAP-0083), it's not a link.
            if not _CAP_IDENTIFIER_RE.match(src_str):
                found_urls.add(strip_credentials(src_str))
    except Exception:
        # If TOML decoding fails, any header URLs found above are still checked.
        pass

    return sorted(found_urls)


def check_link(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    opener: urllib.request.OpenerDirector | None = None,
    policy: AddressPolicy | None = None,
) -> CheckResult:
    """Check a URL with bounded redirects, timeout, 429 handling, and non-HTTP scheme guards.

    ``policy`` is the address policy applied to the destination before every
    request -- the first URL, every redirect hop and the 405 POST fallback.
    It defaults to ``DEFAULT_ADDRESS_POLICY``, which only allows publicly
    routable destinations. There is no command-line flag or environment
    variable that can weaken it; tests inject a permissive policy instead.

    When ``opener`` is omitted, an opener whose connections dial the exact
    address the policy validated is built, so a second DNS answer cannot
    change the destination between validation and connection. A caller-
    supplied ``opener`` still has the policy applied to every URL before the
    request is made, but its own connection layer is the caller's concern.
    """
    sanitized_url = strip_credentials(url)
    try:
        parts = urlsplit(sanitized_url)
    except Exception as exc:
        return CheckResult("Failed", f"invalid URL: {exc}")

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return CheckResult("Failed", f"non-HTTP scheme: {scheme or 'none'}")

    if not parts.hostname:
        return CheckResult("Failed", "missing host")

    if policy is None:
        policy = DEFAULT_ADDRESS_POLICY
    if opener is None:
        opener = _build_opener(policy)

    def apply_policy(request_url: str) -> CheckResult | None:
        """Apply ``policy`` to ``request_url``'s destination.

        Returns a Failed result when the destination must not be contacted,
        ``None`` when it may be. Runs before every request so the decision is
        made against the DNS answer that is current for that request.
        """
        try:
            hop_parts = urlsplit(request_url)
        except Exception as exc:
            return CheckResult("Failed", f"invalid URL: {exc}")
        hop_scheme = (hop_parts.scheme or "").lower()
        if hop_scheme not in ("http", "https"):
            return CheckResult("Failed", f"non-HTTP scheme: {hop_scheme or 'none'}")
        hop_host = hop_parts.hostname
        if not hop_host:
            return CheckResult("Failed", "missing host")
        try:
            hop_port = hop_parts.port
        except ValueError:
            return CheckResult("Failed", "invalid URL: invalid port number")
        if hop_port is None:
            hop_port = 443 if hop_scheme == "https" else 80
        try:
            policy.authorize(hop_host, hop_port)
        except NonPublicAddressError:
            return CheckResult("Failed", "refused: non-public address")
        except OSError as exc:
            return CheckResult("Failed", f"network error: {exc}")
        return None

    current_url = sanitized_url
    visited: set[str] = set()
    redirects_followed = 0

    while True:
        refused = apply_policy(current_url)
        if refused is not None:
            return refused

        visited.add(current_url)
        req = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            },
        )

        try:
            resp = opener.open(req, timeout=timeout)
        except NonPublicAddressError:
            return CheckResult("Failed", "refused: non-public address")
        except urllib.error.HTTPError as exc:
            # The error carries the response body. Close it here, so the
            # connection is released now rather than by the garbage
            # collector; since Python 3.12 an implicitly cleaned-up
            # response warns (ResourceWarning) at whatever later point the
            # collection happens to land.
            code = exc.code
            exc.close()
            if code == 429:
                return CheckResult("Inconclusive", "HTTP 429 Too Many Requests")
            if code == 405:
                # Some RPC endpoints (e.g., soroban-testnet) reject GET with 405 Method Not Allowed.
                # Try POST with empty payload as a fallback check. The address
                # policy is applied again: the POST is a new request to the
                # same destination and must pass the same check.
                refused = apply_policy(current_url)
                if refused is not None:
                    return refused
                try:
                    post_req = urllib.request.Request(
                        current_url,
                        data=b"",
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "*/*",
                        },
                    )
                    resp = opener.open(post_req, timeout=timeout)
                except urllib.error.HTTPError as post_exc:
                    post_code = post_exc.code
                    post_exc.close()
                    if post_code == 429:
                        return CheckResult("Inconclusive", "HTTP 429 Too Many Requests")
                    return CheckResult("Failed", f"HTTP {post_code}")
                except Exception as post_err:
                    return CheckResult("Failed", f"POST fallback failed: {post_err}")
            else:
                return CheckResult("Failed", f"HTTP {code}")
        except (TimeoutError, urllib.error.URLError) as exc:
            reason = getattr(exc, "reason", str(exc))
            if "timed out" in str(reason).lower() or isinstance(exc, TimeoutError):
                return CheckResult("Failed", f"timed out after {timeout}s")
            return CheckResult("Failed", f"network error: {reason}")
        except Exception as exc:
            return CheckResult("Failed", f"{type(exc).__name__}: {exc}")

        status = resp.status
        try:
            if status in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    return CheckResult("Failed", f"HTTP {status} missing Location header")

                next_url = strip_credentials(urljoin(current_url, location))
                next_parts = urlsplit(next_url)
                next_scheme = (next_parts.scheme or "").lower()
                if next_scheme not in ("http", "https"):
                    return CheckResult("Failed", f"redirected to non-HTTP scheme: {next_scheme or 'none'}")

                if next_url in visited:
                    return CheckResult("Failed", "redirect loop detected")

                redirects_followed += 1
                if redirects_followed > max_redirects:
                    return CheckResult("Failed", f"too many redirects (exceeded limit of {max_redirects})")

                current_url = next_url
                continue
            elif status == 200:
                return CheckResult("OK")
            elif status == 429:
                return CheckResult("Inconclusive", "HTTP 429 Too Many Requests")
            else:
                return CheckResult("Failed", f"HTTP {status}")
        finally:
            resp.close()


def find_fixture_files(root: Path) -> list[Path]:
    """Find all .toml fixture files under root."""
    if root.is_file():
        return [root] if root.suffix == ".toml" else []
    return sorted(p for p in root.rglob("*.toml") if p.is_file())


# Line breakers become one space (CRLF is collapsed first in the function
# below), mirroring the boundaries ``str.splitlines`` recognises, so no value
# can split a table row across lines.
_CELL_LINE_BREAKS = str.maketrans(
    {
        "\n": " ",
        "\r": " ",
        "\v": " ",
        "\f": " ",
        "\x1c": " ",
        "\x1d": " ",
        "\x1e": " ",
        "\x85": " ",
        "\u2028": " ",
        "\u2029": " ",
    }
)

# Backslash is translated before the entities below so an odd trailing
# backslash in a value cannot interact with the ``\|`` pipe escape.
_CELL_ENTITIES = str.maketrans(
    {
        "\\": "&#92;",
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "[": "&#91;",
        "]": "&#93;",
        "`": "&#96;",
    }
)


def _escape_markdown_cell(value: str) -> str:
    """Neutralise ``value`` so it stays inside one Markdown table cell.

    The chosen approach (see ``generate_markdown_table``'s docstring):

    * line breaks (CRLF, LF, CR and the Unicode line separators) become a
      single space, so a value can never split a row across lines;
    * ``\\`` becomes ``&#92;`` first, so the only backslash left in the cell
      is the escape this function itself inserts;
    * ``&``, ``<``, ``>``, ``[``, ``]`` and backticks become HTML entities
      (``&amp;``, ``&lt;``, ``&gt;``, ``&#91;``, ``&#93;``, ``&#96;``), which
      GitHub's Markdown renderer displays literally: no raw tag, link or code
      span can be formed from fixture-controlled text;
    * ``|`` becomes ``\\|``, the Markdown table-cell escape, so a pipe in a
      URL or file name cannot add a column.
    """
    text = str(value).replace("\r\n", "\n").translate(_CELL_LINE_BREAKS)
    text = text.translate(_CELL_ENTITIES)
    return text.replace("|", "\\|")


def generate_markdown_table(rows: list[tuple[str, str, CheckResult]]) -> str:
    """Generate a Markdown table from a list of (url, fixture_file, result) tuples.

    Every interpolated value -- URL, fixture file name and result detail --
    comes from fixture content, file names or exception text, all of which a
    fixture author influences, so each one is passed through
    ``_escape_markdown_cell``: line breaks become spaces (every row occupies
    exactly one line), ``&``, ``<``, ``>``, ``[``, ``]``, backticks and
    backslashes become HTML entities, and ``|`` becomes ``\\|``. The result
    is that every row keeps exactly three cells and nothing in a cell can
    form a link, an HTML tag or a code span in the rendered job summary.
    Ordinary URLs (for example ``https://example.org/a?b=c``) contain none of
    those characters and stay exactly as written.
    """
    lines = [
        "| URL | Fixture File | Result |",
        "|---|---|---|",
    ]
    for url, fixture_file, result in rows:
        lines.append(
            f"| {_escape_markdown_cell(url)} "
            f"| {_escape_markdown_cell(fixture_file)} "
            f"| {_escape_markdown_cell(result.formatted())} |"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check links in fixture source_reference fields and header comments on a schedule."
    )
    parser.add_argument(
        "roots",
        nargs="*",
        help="Directories or .toml files to scan. Defaults to protocol-* directories in the repo root.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT}s)",
    )
    parser.add_argument(
        "--max-redirects",
        type=int,
        default=DEFAULT_MAX_REDIRECTS,
        help=f"Maximum number of redirects to follow (default: {DEFAULT_MAX_REDIRECTS})",
    )
    parser.add_argument(
        "--summary-file",
        help="Optional path to append the markdown table to (e.g. $GITHUB_STEP_SUMMARY)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    if args.roots:
        scan_paths = [Path(r) for r in args.roots]
        for scan_path in scan_paths:
            if not scan_path.exists():
                sys.stderr.write(f"Error: root does not exist: {scan_path}\n")
                return 2
            if not scan_path.is_dir() and not (
                scan_path.is_file() and scan_path.suffix == ".toml"
            ):
                sys.stderr.write(
                    f"Error: root must be a directory or .toml file: {scan_path}\n"
                )
                return 2
    else:
        scan_paths = sorted(p for p in repo_root.glob("protocol-*") if p.is_dir())
        if not scan_paths:
            scan_paths = [repo_root]

    fixture_files: list[Path] = []
    for sp in scan_paths:
        fixture_files.extend(find_fixture_files(sp))

    if args.roots and not fixture_files:
        roots = ", ".join(str(path) for path in scan_paths)
        sys.stderr.write(f"Error: no .toml fixture files found in explicit roots: {roots}\n")
        return 2

    # Remove duplicates while preserving order
    unique_files: list[Path] = []
    seen_files: set[Path] = set()
    for f in fixture_files:
        resolved = f.resolve()
        if resolved not in seen_files:
            seen_files.add(resolved)
            unique_files.append(f)

    # Collect pairs of (url, file_display_path)
    links_to_check: list[tuple[str, str]] = []
    for file_path in unique_files:
        try:
            rel_path = file_path.relative_to(repo_root)
        except ValueError:
            try:
                rel_path = file_path.relative_to(Path.cwd())
            except ValueError:
                rel_path = file_path
        urls = extract_links_from_file(file_path)
        for u in urls:
            links_to_check.append((u, str(rel_path)))

    # Sort deterministically
    links_to_check.sort(key=lambda item: (item[1], item[0]))

    # Check URLs with caching
    url_cache: dict[str, CheckResult] = {}
    rows: list[tuple[str, str, CheckResult]] = []
    ok_count = 0
    inconclusive_count = 0
    failed_count = 0

    # One opener and one address policy for every URL: the opener dials only
    # addresses the policy has validated.
    policy = DEFAULT_ADDRESS_POLICY
    opener = _build_opener(policy)

    for url, file_path in links_to_check:
        if url not in url_cache:
            url_cache[url] = check_link(
                url,
                timeout=args.timeout,
                max_redirects=args.max_redirects,
                opener=opener,
                policy=policy,
            )
        result = url_cache[url]
        rows.append((url, file_path, result))

        if result.status == "OK":
            ok_count += 1
        elif result.status == "Inconclusive":
            inconclusive_count += 1
        else:
            failed_count += 1

    table = generate_markdown_table(rows)
    summary_text = (
        f"\n\n**Source Reference Links Check Summary**: "
        f"{len(rows)} checked across {len(unique_files)} fixture files "
        f"({ok_count} OK, {inconclusive_count} Inconclusive, {failed_count} Failed).\n"
    )

    full_output = table + summary_text
    print(full_output)

    # Write to summary file if specified or present in environment
    summary_file = args.summary_file or os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a", encoding="utf-8") as fp:
                fp.write(full_output)
        except OSError as exc:
            sys.stderr.write(f"Warning: could not write to summary file {summary_file}: {exc}\n")

    # Inconclusive (429) does not fail the job; only Failed fails the job.
    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
