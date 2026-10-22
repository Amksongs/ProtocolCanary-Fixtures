#!/usr/bin/env python3
r"""Capture live read-only RPC evidence and write CF-04 verification records.

This is the script behind the scheduled read-only verification job (issue
#368). On the approved schedule it calls the approved read-only JSON-RPC
methods on the approved endpoint, saves the raw request and response as
captures, and writes one CF-04 verification record per RPC fixture that
references the capture it was made from.

What it does:

* calls only the read-only methods CF-04 section 8 names
  (``getNetwork``, ``getLatestLedger``, ``getVersionInfo``) -- a name that is
  not on that list is refused before a request is made, so a write call
  (``submitTransaction`` and friends) cannot be configured, by accident or on
  purpose;
* uses no credentials: the requests carry no token, no secret header and no
  query string, and the endpoint is a public host name;
* saves each capture in this repository's capture envelope
  (``capturedAt``, ``endpointHost``, ``request``, ``response``), the same
  shape as the hand-taken corpus in ``protocol-29/evidence/testnet/``;
* writes one record per verified fixture with ``method: "live-read-only"``,
  the SHA-256 of the fixture file as it is on disk, ``checkedAt`` equal to
  the ``capturedAt`` of the capture the record points at, ``observedProtocol``
  copied from the real ``getNetwork`` response, and ``evidenceRef`` pointing
  at that capture.

What it never does:

* it never writes a record for a capture that did not happen. A call that
  fails, times out or answers with something that is not a JSON-RPC result
  produces no capture and no record, and the run fails;
* it never derives an instant from anything but the moment of the call;
* it never marks a fixture verified from a structural check. A record here
  says what the live endpoint answered, and nothing else;
* it never invents an ``outcome``. ``matched`` means the fixture's own
  assertions hold against the live answer and the endpoint reports the
  protocol the fixture targets; anything else is ``mismatched``, and the
  reasons are printed.

The schedule, the exact endpoints and the storage design are maintainer
decisions (issue #368 lists them as still open). The endpoint list and the
output layout are therefore constants in this file, and the workflow that
calls it is one file with one cron line and one upload step.

Usage:
    python3 tools/evidence/capture_live.py PACK
        [--output-dir DIR] [--endpoint HOST] [--local-endpoint URL]
        [--capture-method METHOD] [--timeout SECONDS]
        [--verifier-version VERSION] [--dry-run]

Requires Python 3.11+ and nothing outside the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import time
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.validate import validate

# The verifier that performed the check. CF-04 section 3 asks for the exact
# thing that did the work; for a live read-only check that is this script,
# named here and pinned to the commit it was read from.
VERIFIER_NAME = "protocolcanary-fixtures-capture-live"

# The complete set of JSON-RPC methods this tool may ever call: the read-only
# methods CF-04 section 8 names. Nothing else is called -- a method that is
# not in this tuple is refused before a request is made, so a write call can
# never be configured. The committed corpus in
# protocol-29/evidence/testnet/ holds exactly these three calls.
READ_ONLY_METHODS = ("getNetwork", "getLatestLedger", "getVersionInfo")

# The fixture `method` values (canary-rpc's vocabulary) and the live JSON-RPC
# method each one calls.
FIXTURE_METHODS = {
    "get-network": "getNetwork",
    "get-latest-ledger": "getLatestLedger",
}

# The file name each capture is saved under, matching the hand-taken corpus.
CAPTURE_FILE_NAMES = {
    "getNetwork": "get-network",
    "getLatestLedger": "get-latest-ledger",
    "getVersionInfo": "get-version-info",
}

# The approved endpoints: host name -> the network name a record carries.
# The exact endpoints are a maintainer decision (issue #368); this is the
# public Testnet endpoint the committed corpus was captured from, and the
# only host the corpus test allows. A host that is not in this mapping is
# refused: the tool never calls an endpoint that was not approved here.
APPROVED_ENDPOINTS = {"soroban-testnet.stellar.org": "testnet"}

# The loopback addresses a local mock endpoint may live on.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# CF-04 section 7 and decision D-06: one RPC response is bounded at 16 MiB.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

# How long one call may take before it is treated as a failure.
DEFAULT_TIMEOUT_SECONDS = 30.0

# The User-Agent the requests carry. The public endpoint's edge refuses
# Python's default agent (it answers HTTP 403 with Cloudflare error 1010),
# so the tool identifies itself. No other header is sent: no token, no
# cookie, no credential of any kind.
USER_AGENT = "protocolcanary-fixtures-capture-live/1.0"

# Where the captures and the records go, relative to the pack. The layout
# mirrors the hand-taken corpus (protocol-29/evidence/testnet/) and the
# records directory issue #366 established (PACK/evidence/records/).
OUTPUT_DIRNAME = "evidence/live"


class CaptureError(Exception):
    """The capture could not be made. The message says why."""


@dataclass(frozen=True)
class Endpoint:
    """The endpoint a run calls, and the network name its records carry."""

    url: str
    host: str
    network: str


@dataclass
class Summary:
    """What one run did, for the report and the exit code."""

    endpoint: Endpoint
    captures: list[Path] = field(default_factory=list)
    records: list[Path] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    outcomes: list[tuple[str, str, list[str]]] = field(default_factory=list)
    documents: list[tuple[Path, dict]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def utc_now() -> str:
    """The current instant, RFC 3339 in UTC -- the form CF-04 asks for."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_revision(repo_root: Path) -> str:
    """The commit this script was read from, or ``unknown``.

    The version of a verifier has to identify the exact code that did the
    check. A checkout without git (a source archive, a vendored copy) cannot
    answer that, and says so rather than guessing.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    revision = result.stdout.strip()
    if result.returncode != 0 or len(revision) != 40:
        return "unknown"
    return revision


def resolve_endpoint(endpoint: str | None, local_endpoint: str | None) -> Endpoint:
    """The endpoint this run calls.

    Either one of the approved endpoints, or -- for the tests and for a dry
    run on a fork -- a loopback mock. A local endpoint is refused unless it
    is a loopback address, so the escape hatch cannot be pointed at a remote
    host.
    """
    if local_endpoint:
        parts = urlsplit(local_endpoint)
        host = parts.hostname or ""
        if parts.scheme != "http":
            raise CaptureError(
                f"a local endpoint must use http:// on the loopback interface, got {local_endpoint!r}"
            )
        if host not in LOOPBACK_HOSTS:
            raise CaptureError(
                f"a local endpoint must be a loopback address "
                f"({' or '.join(LOOPBACK_HOSTS)}), got {host!r}; the approved "
                f"endpoints are {sorted(APPROVED_ENDPOINTS)}"
            )
        return Endpoint(url=local_endpoint, host=host, network="local-mock")
    if endpoint is not None:
        if endpoint not in APPROVED_ENDPOINTS:
            raise CaptureError(
                f"endpoint {endpoint!r} is not approved; approved endpoints are "
                f"{sorted(APPROVED_ENDPOINTS)}"
            )
        host = endpoint
    else:
        host = sorted(APPROVED_ENDPOINTS)[0]
    return Endpoint(url=f"https://{host}", host=host, network=APPROVED_ENDPOINTS[host])


def capture_method(url: str, method: str, request_id: int, timeout: float) -> dict:
    """Call one read-only method and return the result it answered with.

    Raises :class:`CaptureError` for every failure: the method is not on the
    read-only list, the transport failed, the answer was not JSON, or the
    answer was a JSON-RPC error. The caller writes no capture and no record
    when this raises.
    """
    if method not in READ_ONLY_METHODS:
        raise CaptureError(
            f"{method!r} is not a read-only method; this tool only calls "
            f"{list(READ_ONLY_METHODS)}"
        )
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            chunks = []
            size = 0
            while size <= MAX_RESPONSE_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                # Bound each blocking socket read by the remaining overall time.
                if hasattr(response, "fp") and response.fp is not None:
                    response.fp.raw._sock.settimeout(remaining)
                chunk = response.read(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if time.monotonic() > deadline:
                    raise TimeoutError
            body = b"".join(chunks)
    except urllib.error.HTTPError as error:
        # The error carries a response body; close it, so the connection is
        # released even though the answer is discarded.
        status = f"HTTP {error.code} {error.reason}"
        error.close()
        raise CaptureError(f"{method}: the endpoint answered {status}") from None
    except TimeoutError:
        raise CaptureError(f"{method}: the endpoint did not answer within {timeout} s") from None
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise CaptureError(
                f"{method}: the endpoint did not answer within {timeout} s"
            ) from None
        raise CaptureError(f"{method}: the endpoint could not be reached ({reason})") from None
    except OSError as error:
        raise CaptureError(f"{method}: the request failed ({error})") from None

    if len(body) > MAX_RESPONSE_BYTES:
        raise CaptureError(
            f"{method}: the answer is larger than the {MAX_RESPONSE_BYTES} byte limit"
        )
    try:
        answer = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError(f"{method}: the answer was not JSON ({error})") from None
    if not isinstance(answer, dict):
        raise CaptureError(f"{method}: the answer was not a JSON-RPC object")
    if "error" in answer:
        detail = json.dumps(answer["error"], ensure_ascii=False)
        raise CaptureError(f"{method}: the endpoint answered with a JSON-RPC error ({detail})")
    if "result" not in answer:
        raise CaptureError(f"{method}: the answer carried no result")
    if answer.get("id") != request_id:
        raise CaptureError(
            f"{method}: the answer's id {answer.get('id')!r} does not match the "
            f"request's id {request_id!r}"
        )
    return answer["result"]


def build_capture(captured_at: str, host: str, method: str, request_id: int, result: object) -> dict:
    """The capture envelope: the request, the answer, the instant, the host."""
    return {
        "capturedAt": captured_at,
        "endpointHost": host,
        "request": {"jsonrpc": "2.0", "id": request_id, "method": method},
        "response": {"jsonrpc": "2.0", "id": request_id, "result": result},
    }


def json_type_name(value: object) -> str:
    """The JSON type name of a value, as ``field-type`` assertions use."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def values_equal(actual: object, expected: object) -> bool:
    """Whether two JSON values are equal, without Python's bool-is-an-int trap.

    ``True == 1`` in Python, so a boolean never equals a number here: a
    fixture that asserts a number is not satisfied by a boolean.
    """
    if isinstance(actual, bool) or isinstance(expected, bool):
        return (
            isinstance(actual, bool)
            and isinstance(expected, bool)
            and actual == expected
        )
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    if isinstance(actual, str) and isinstance(expected, str):
        return actual == expected
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            values_equal(one, other) for one, other in zip(actual, expected)
        )
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            values_equal(actual[key], expected[key]) for key in actual
        )
    return False


def evaluate_asserts(asserts: object, result: object) -> list[str]:
    """The problems with a fixture's assertions against a live answer.

    The assertions are the ones the fixture itself carries, evaluated against
    the raw JSON-RPC result. The field names are the flat field names
    canary-rpc's typed models expose, so a field the engine does not model
    is not looked for here either.
    """
    if not isinstance(asserts, list):
        return ["the fixture carries no [[assert]] table to check"]
    if not isinstance(result, dict):
        return ["the endpoint's answer is not an object, so no field can be checked"]
    problems: list[str] = []
    for index, assertion in enumerate(asserts):
        if not isinstance(assertion, dict):
            problems.append(f"assert[{index}] is not a table")
            continue
        kind = assertion.get("kind")
        field_name = assertion.get("field")
        present = isinstance(field_name, str) and field_name in result
        value = result.get(field_name) if present else None
        if kind == "field-exists":
            if not present:
                problems.append(
                    f"assert[{index}] field-exists: the answer has no {field_name!r} field"
                )
        elif kind == "field-absent":
            if present:
                problems.append(
                    f"assert[{index}] field-absent: the answer has a {field_name!r} field"
                )
        elif kind == "field-type":
            expected_type = assertion.get("expected_type")
            if not present:
                problems.append(
                    f"assert[{index}] field-type: the answer has no {field_name!r} field"
                )
            elif json_type_name(value) != expected_type:
                problems.append(
                    f"assert[{index}] field-type: {field_name!r} is "
                    f"{json_type_name(value)}, expected {expected_type!r}"
                )
        elif kind == "field-equals":
            expected = assertion.get("value")
            if not present:
                problems.append(
                    f"assert[{index}] field-equals: the answer has no {field_name!r} field"
                )
            elif not values_equal(value, expected):
                problems.append(
                    f"assert[{index}] field-equals: {field_name!r} is "
                    f"{json.dumps(value, ensure_ascii=False)}, expected "
                    f"{json.dumps(expected, ensure_ascii=False)}"
                )
        elif kind == "field-number-range":
            minimum = assertion.get("min")
            maximum = assertion.get("max")
            if not present:
                problems.append(
                    f"assert[{index}] field-number-range: the answer has no {field_name!r} field"
                )
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(
                    f"assert[{index}] field-number-range: {field_name!r} is "
                    f"{json_type_name(value)}, not a number"
                )
            elif minimum is not None and value < minimum:
                problems.append(
                    f"assert[{index}] field-number-range: {field_name!r} is {value}, "
                    f"below the minimum {minimum}"
                )
            elif maximum is not None and value > maximum:
                problems.append(
                    f"assert[{index}] field-number-range: {field_name!r} is {value}, "
                    f"above the maximum {maximum}"
                )
        else:
            problems.append(f"assert[{index}] has an unknown kind {kind!r}")
    return problems


def load_rpc_fixtures(pack: Path) -> list[dict]:
    """The pack's RPC fixtures, with the facts a record needs.

    Fixtures of other surfaces (XDR, Soroban) are not returned: this job
    verifies the read-only RPC surface only, and a Soroban simulation is not
    a read-only call.
    """
    if not pack.is_dir():
        raise CaptureError(f"pack not found: {pack}")
    fixtures: list[dict] = []
    for path in validate.find_fixture_files(pack):
        scratch = validate.Report()
        loaded = validate.load_fixture(path, scratch, root=pack)
        if loaded is None:
            raise CaptureError(
                f"{path} could not be loaded: " + "; ".join(scratch.errors)
            )
        data = loaded.data
        if data.get("surface") != "rpc":
            continue
        fixture_id = validate.known_fixture_id(loaded)
        if not fixture_id:
            raise CaptureError(f"{path} has no usable id")
        method = data.get("method")
        if method not in FIXTURE_METHODS:
            raise CaptureError(
                f"{fixture_id}: the method {method!r} has no read-only live "
                f"counterpart; this tool can only check {sorted(FIXTURE_METHODS)}"
            )
        fixtures.append(
            {
                "id": fixture_id,
                "path": path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "protocol": data.get("protocol"),
                "method": method,
                "live_method": FIXTURE_METHODS[method],
                "asserts": data.get("assert", []),
            }
        )
    if not fixtures:
        raise CaptureError(f"{pack} holds no RPC fixture to verify live")
    return fixtures


def build_record(
    fixture_id: str,
    fixture_sha256: str,
    checked_at: str,
    version: str,
    outcome: str,
    network: dict,
    host: str,
    evidence_ref: str,
) -> dict:
    """One live verification record for a fixture that was really checked."""
    return {
        "verificationVersion": validate.EVIDENCE_VERSION,
        "fixtureId": fixture_id,
        "fixtureSha256": fixture_sha256,
        "method": "live-read-only",
        "checkedAt": checked_at,
        "verifier": {"name": VERIFIER_NAME, "version": version},
        "outcome": outcome,
        "network": network,
        "endpointHost": host,
        "evidenceRef": evidence_ref,
    }


def render_json(document: dict) -> str:
    """UTF-8, LF, two-space indent, one trailing newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def evidence_reference(capture_path: Path, output_dir: Path) -> str:
    """The path a record points at to find its capture.

    CF-04 section 3 asks for a path inside the repository, so the reference
    is the capture's path relative to the repository root. When the output
    directory is outside the repository -- as it is in the tests -- the
    reference is relative to the output directory instead, which keeps it
    usable there without pretending the file is in the repository.
    """
    resolved = capture_path.resolve()
    for base in (REPO_ROOT.resolve(), output_dir.resolve()):
        try:
            return resolved.relative_to(base).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def write_documents(documents: list[tuple[Path, dict]]) -> list[Path]:
    """Write the captures and the records. Returns the paths written."""
    written: list[Path] = []
    for path, document in documents:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(render_json(document).encode("utf-8"))
        except OSError as error:
            raise CaptureError(f"could not write {path}: {error}") from None
        written.append(path)
    return written


def run(
    pack: Path,
    output_dir: Path | None = None,
    endpoint: str | None = None,
    local_endpoint: str | None = None,
    capture_methods: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    version: str | None = None,
    dry_run: bool = False,
) -> Summary:
    """Capture, check and record. Returns what the run did."""
    target = resolve_endpoint(endpoint, local_endpoint)
    fixtures = load_rpc_fixtures(pack)

    extra = list(capture_methods or [])
    for method in extra:
        if method not in READ_ONLY_METHODS:
            raise CaptureError(
                f"{method!r} is not a read-only method; this tool only calls "
                f"{list(READ_ONLY_METHODS)}"
            )

    # The calls this run makes: the network facts are always needed, every
    # fixture's own method is needed, and the extra methods are captured on
    # request. Nothing outside the read-only list is ever called.
    methods: list[str] = []
    for method in ["getNetwork"] + [f["live_method"] for f in fixtures] + extra:
        if method not in methods:
            methods.append(method)

    target_dir = output_dir if output_dir is not None else pack / OUTPUT_DIRNAME
    summary = Summary(endpoint=target)

    captures: dict[str, tuple[dict, object]] = {}
    for request_id, method in enumerate(methods, start=1):
        try:
            result = capture_method(target.url, method, request_id, timeout)
        except CaptureError as error:
            summary.failures.append((method, str(error)))
            continue
        captured_at = utc_now()
        capture = build_capture(captured_at, target.host, method, request_id, result)
        captures[method] = (capture, result)
        summary.captures.append(target_dir / "captures" / f"{CAPTURE_FILE_NAMES[method]}.json")

    if "getNetwork" not in captures:
        reason = "; ".join(message for _, message in summary.failures)
        raise CaptureError(
            "the getNetwork call failed, so the network facts are unknown and no "
            f"record was written ({reason})"
        )

    network_result = captures["getNetwork"][1]
    if not isinstance(network_result, dict):
        raise CaptureError("the getNetwork answer is not an object, so no record was written")
    passphrase = network_result.get("passphrase")
    observed = network_result.get("protocolVersion")
    if not isinstance(passphrase, str) or not passphrase:
        raise CaptureError(
            "the getNetwork answer carries no passphrase, so no record was written"
        )
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
        raise CaptureError(
            "the getNetwork answer carries no protocolVersion, so no record was written"
        )
    network = {
        "name": target.network,
        "passphrase": passphrase,
        "observedProtocol": observed,
    }

    verifier_version = version if version else git_revision(REPO_ROOT)
    documents: list[tuple[Path, dict]] = []
    for method in methods:
        if method not in captures:
            continue
        documents.append(
            (target_dir / "captures" / f"{CAPTURE_FILE_NAMES[method]}.json", captures[method][0])
        )

    for fixture in fixtures:
        method = fixture["live_method"]
        if method not in captures:
            # The capture failed: no record is written for this fixture, and
            # the failure is already in the summary.
            continue
        capture, result = captures[method]
        problems = evaluate_asserts(fixture["asserts"], result)
        protocol = fixture["protocol"]
        if isinstance(protocol, int) and protocol != observed:
            problems.append(
                f"the endpoint reports protocol {observed}, the fixture targets "
                f"protocol {protocol}"
            )
        outcome = "matched" if not problems else "mismatched"
        checked_at = capture["capturedAt"]
        reference = evidence_reference(
            target_dir / "captures" / f"{CAPTURE_FILE_NAMES[method]}.json", target_dir
        )
        record = build_record(
            fixture["id"],
            fixture["sha256"],
            checked_at,
            verifier_version,
            outcome,
            network,
            target.host,
            reference,
        )
        record_path = target_dir / "records" / f"{fixture['id']}.live-read-only.json"
        documents.append((record_path, record))
        summary.records.append(record_path)
        summary.outcomes.append((fixture["id"], outcome, problems))

    # A record is only useful if the validator accepts it, so every record is
    # checked with the validator's own rules before it is written.
    for path, document in documents:
        if path.parent.name != "records":
            continue
        problems = validate.validate_evidence(document)
        if problems:
            raise CaptureError(
                f"the record for {path.name} does not satisfy the CF-04 rules: "
                + "; ".join(problems)
            )

    summary.documents = documents
    if not dry_run:
        write_documents(documents)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capture_live.py",
        description=(
            "Capture live read-only RPC evidence and write CF-04 verification "
            "records for the RPC fixtures of a pack (issue #368). Only the "
            "approved read-only methods are called, no credentials are used, and "
            "a record is written only for a capture that actually happened."
        ),
    )
    parser.add_argument(
        "pack",
        type=Path,
        help="the pack directory whose RPC fixtures are verified live",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        metavar="DIR",
        help=f"where to write the captures and the records (default: PACK/{OUTPUT_DIRNAME})",
    )
    parser.add_argument(
        "--endpoint",
        metavar="HOST",
        help=(
            "the approved endpoint to call (default: "
            f"{sorted(APPROVED_ENDPOINTS)[0]})"
        ),
    )
    parser.add_argument(
        "--local-endpoint",
        metavar="URL",
        help=(
            "a loopback mock endpoint to call instead of an approved one, for "
            "the tests and for a dry run on a fork"
        ),
    )
    parser.add_argument(
        "--capture-method",
        action="append",
        default=[],
        metavar="METHOD",
        help=(
            "an extra read-only method to capture, on top of the ones the "
            "pack's fixtures need (repeatable)"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=(
            "how long one call may take before it is a failure "
            f"(default: {DEFAULT_TIMEOUT_SECONDS:g})"
        ),
    )
    parser.add_argument(
        "--verifier-version",
        metavar="VERSION",
        help=(
            "the version to record for the verifier (default: the commit this "
            "script was read from)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="make the calls and print what would be written, but write nothing",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run(
            args.pack,
            output_dir=args.output_dir,
            endpoint=args.endpoint,
            local_endpoint=args.local_endpoint,
            capture_methods=args.capture_method,
            timeout=args.timeout,
            version=args.verifier_version,
            dry_run=args.dry_run,
        )
    except CaptureError as error:
        print(f"error: {error}", file=sys.stderr)
        print("FAILED: no record was written", file=sys.stderr)
        return 1

    print(f"Endpoint: {summary.endpoint.host} ({summary.endpoint.network})")
    print(f"Captures: {len(summary.captures)}")
    for path in summary.captures:
        print(f"  {path}")
    print(f"Records: {len(summary.records)}")
    for fixture_id, outcome, problems in summary.outcomes:
        print(f"  {fixture_id}: {outcome}")
        for problem in problems:
            print(f"    - {problem}")
    if args.dry_run:
        print("Dry run: nothing was written. The documents would be:")
        for path, document in summary.documents:
            print(f"--- {path}")
            print(render_json(document), end="")
    if summary.failures:
        for method, message in summary.failures:
            print(f"FAILED: {message}", file=sys.stderr)
        print(
            f"FAILED: {len(summary.failures)} capture(s) failed; no record was "
            "written for them",
            file=sys.stderr,
        )
        return 1
    print("OK: the captures and the records are written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
