#!/usr/bin/env python3
"""Structural validator for ProtocolCanary-Fixtures.

Validates every ``*.toml`` fixture file under one or more root directories
against the fixture format actually implemented by
``StellarCanary/Protocol-Canary``'s ``canary-fixtures``/``canary-xdr``/
``canary-rpc``/``canary-soroban`` crates (see that repository's
``docs/fixture-contract.md``, which is authoritative; this script mirrors
it, not the other way around).

This tool performs structural validation only. It never executes a
fixture's assertion (no decoding, no network calls, no simulation) and
never treats a fixture field as a command to run.

Usage:
    python3 tools/validate/validate.py [--quiet] [root ...]

With no arguments, validates every protocol-*/ directory found next to
this script's repository root. Exits 0 if every fixture is valid, 1
otherwise.

Warnings (e.g. a fixture with no ``source_reference``) are printed to
stdout by default. Pass ``--quiet`` to suppress them so a fully passing
CI run is not dominated by warning noise; errors still go to stderr and
the final OK/FAILED summary is always printed.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SURFACES = {"xdr", "rpc", "soroban"}
XDR_TYPES = {"StellarValue", "ContractExecutable"}
# Set of assertion kinds supported by canary-xdr for a given XDR value.
# Must be kept in sync with canary-xdr's supported assertion kinds.
XDR_KINDS = {"decode-success", "decode-failure", "roundtrip", "encode-equals"}
RPC_METHODS = {"get-network", "get-latest-ledger"}
RPC_ASSERT_KINDS = {"field-exists", "field-type", "field-equals"}
RPC_ASSERT_TYPES = {"string", "integer", "boolean", "array", "object"}
SOROBAN_EXPECT_KINDS = {"simulation-success", "simulation-error"}
# Set of kebab-case capability strings a fixture may list in
# `required_capabilities`. Must be kept in sync with
# canary_core::Capability in StellarCanary/Protocol-Canary, whose
# kebab-case names these mirror (the same cross-reference is documented in
# schemas/fixture-v1.schema.json's required_capabilities description).
CAPABILITIES = {
    "soroban-contract",
    "rpc-client",
    "stellar-sdk-dependency",
    "wasm-artifact",
    "raw-ledger-access",
}
VAGUE_CATEGORIES = {"misc", "other", "test", "general"}


@dataclass
class Fixture:
    path: Path
    data: dict


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, path: Path, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def warning(self, path: Path, message: str) -> None:
        self.warnings.append(f"{path}: {message}")

    @property
    def ok(self) -> bool:
        return not self.errors


def find_fixture_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.toml") if p.is_file())


def load_fixture(path: Path, report: Report) -> Fixture | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(path, f"failed to read file: {exc}")
        return None
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        report.error(path, f"invalid TOML: {exc}")
        return None
    return Fixture(path=path, data=data)


def _require(data: dict, key: str, expected_type: type, path: Path, report: Report) -> bool:
    if key not in data:
        report.error(path, f"missing required field {key!r}")
        return False
    if not isinstance(data[key], expected_type):
        report.error(
            path,
            f"field {key!r} must be of type {expected_type.__name__}, "
            f"got {type(data[key]).__name__}",
        )
        return False
    return True


def validate_common_fields(fx: Fixture, report: Report) -> None:
    data, path = fx.data, fx.path

    ok_id = _require(data, "id", str, path, report)
    if ok_id and not data["id"]:
        report.error(path, "field 'id' must not be empty")
    if ok_id and data["id"] != data["id"].lower():
        report.error(path, "field 'id' must be lowercase")

    ok_protocol = _require(data, "protocol", int, path, report)
    if ok_protocol and data["protocol"] < 1:
        report.error(path, "field 'protocol' must be a positive integer")

    ok_surface = _require(data, "surface", str, path, report)
    if ok_surface and data["surface"] not in SURFACES:
        report.error(
            path,
            f"field 'surface' must be one of {sorted(SURFACES)}, got {data['surface']!r}",
        )

    ok_category = _require(data, "category", str, path, report)
    if ok_category and not data["category"]:
        report.error(path, "field 'category' must not be empty")
    if ok_category and data["category"].lower() in VAGUE_CATEGORIES:
        report.error(
            path,
            f"field 'category' is too vague ({data['category']!r}); "
            "use a specific CAP/topic slug",
        )

    _require(data, "description", str, path, report)

    if "source_reference" in data:
        if not isinstance(data["source_reference"], str) or not data["source_reference"]:
            report.error(path, "field 'source_reference', if present, must be a non-empty string")
    else:
        report.warning(
            path,
            "no 'source_reference' set; protocol-specific fixtures should cite an "
            "authoritative upstream source",
        )

    if "required_capabilities" in data:
        caps = data["required_capabilities"]
        if not isinstance(caps, list):
            report.error(path, "field 'required_capabilities' must be an array")
        else:
            for cap in caps:
                if cap not in CAPABILITIES:
                    report.error(
                        path,
                        f"unknown capability {cap!r}; expected one of {sorted(CAPABILITIES)}",
                    )

    for file_field in ("input_file", "expected_file"):
        if file_field in data:
            if not isinstance(data[file_field], str) or not data[file_field]:
                report.error(path, f"field {file_field!r}, if present, must be a non-empty string")
                continue
            referenced = (path.parent / data[file_field]).resolve()
            if not referenced.is_file():
                report.error(
                    path,
                    f"{file_field} {data[file_field]!r} does not resolve to an existing file "
                    f"(resolved: {referenced})",
                )


def _validate_base64(value: str, field_name: str, path: Path, report: Report) -> None:
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        report.error(path, f"field {field_name!r} is not valid base64: {exc}")


def validate_xdr_body(fx: Fixture, report: Report) -> None:
    data, path = fx.data, fx.path

    ok_type = _require(data, "type", str, path, report)
    if ok_type and data["type"] not in XDR_TYPES:
        report.error(
            path,
            f"field 'type' must be one of {sorted(XDR_TYPES)} (what canary-xdr currently "
            f"supports), got {data['type']!r}",
        )

    ok_kind = _require(data, "kind", str, path, report)
    if ok_kind and data["kind"] not in XDR_KINDS:
        report.error(
            path, f"field 'kind' must be one of {sorted(XDR_KINDS)}, got {data['kind']!r}"
        )

    if _require(data, "value_base64", str, path, report):
        _validate_base64(data["value_base64"], "value_base64", path, report)

    if (ok_kind and data["kind"] == "encode-equals") or "expected_base64" in data:
        if _require(data, "expected_base64", str, path, report):
            _validate_base64(data["expected_base64"], "expected_base64", path, report)


def validate_rpc_body(fx: Fixture, report: Report) -> None:
    data, path = fx.data, fx.path

    ok_method = _require(data, "method", str, path, report)
    if ok_method and data["method"] not in RPC_METHODS:
        report.error(
            path, f"field 'method' must be one of {sorted(RPC_METHODS)}, got {data['method']!r}"
        )

    if "assert" not in data:
        report.error(path, "rpc fixture must define at least one [[assert]] table")
        return
    asserts = data["assert"]
    if not isinstance(asserts, list) or not asserts:
        report.error(path, "'assert' must be a non-empty array of tables")
        return
    for i, a in enumerate(asserts):
        if not isinstance(a, dict):
            report.error(path, f"assert[{i}] must be a table")
            continue
        kind = a.get("kind")
        if kind not in RPC_ASSERT_KINDS:
            report.error(
                path,
                f"assert[{i}].kind must be one of {sorted(RPC_ASSERT_KINDS)}, got {kind!r}",
            )
        if not a.get("field"):
            report.error(path, f"assert[{i}] missing required non-empty 'field'")
        if kind == "field-equals" and "value" not in a:
            report.error(path, f"assert[{i}] with kind=field-equals requires 'value'")
        if kind == "field-type":
            expected_type = a.get("expected_type")
            if expected_type not in RPC_ASSERT_TYPES:
                report.error(
                    path,
                    f"assert[{i}].expected_type must be one of {sorted(RPC_ASSERT_TYPES)}, "
                    f"got {expected_type!r}",
                )


def validate_soroban_body(fx: Fixture, report: Report) -> None:
    data, path = fx.data, fx.path

    _require(data, "source_account", str, path, report)
    _require(data, "contract_id", str, path, report)
    _require(data, "function", str, path, report)
    _require(data, "sequence_number", int, path, report)

    if "expect" not in data:
        report.error(path, "missing required field 'expect'")
        return
    expect = data["expect"]
    if not isinstance(expect, dict):
        report.error(path, "'expect' must be a table")
        return
    kind = expect.get("kind")
    if kind not in SOROBAN_EXPECT_KINDS:
        report.error(
            path,
            f"expect.kind must be one of {sorted(SOROBAN_EXPECT_KINDS)}, got {kind!r}",
        )


def validate_body(fx: Fixture, report: Report) -> None:
    surface = fx.data.get("surface")
    if surface == "xdr":
        validate_xdr_body(fx, report)
    elif surface == "rpc":
        validate_rpc_body(fx, report)
    elif surface == "soroban":
        validate_soroban_body(fx, report)
    # An invalid/missing surface was already reported by validate_common_fields.


def validate_unique_ids(fixtures: list[Fixture], report: Report) -> None:
    seen: dict[str, Path] = {}
    for fx in fixtures:
        fid = fx.data.get("id")
        if not isinstance(fid, str):
            continue
        if fid in seen:
            report.error(
                fx.path, f"duplicate fixture id {fid!r}: already defined in {seen[fid]}"
            )
        else:
            seen[fid] = fx.path


def validate_directory(root: Path) -> Report:
    report = Report()
    fixtures: list[Fixture] = []
    for path in find_fixture_files(root):
        fx = load_fixture(path, report)
        if fx is not None:
            fixtures.append(fx)

    for fx in fixtures:
        validate_common_fields(fx, report)
        validate_body(fx, report)

    validate_unique_ids(fixtures, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate.py",
        description=(
            "Structural validator for ProtocolCanary-Fixtures. Performs structural "
            "validation only; never executes a fixture's assertion."
        ),
    )
    parser.add_argument(
        "roots",
        nargs="*",
        metavar="root",
        help=(
            "directories to scan for *.toml fixtures (default: every protocol-*/ "
            "directory next to this script)"
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help=(
            "suppress warning output; errors and the final OK/FAILED summary are "
            "still printed"
        ),
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    roots = [Path(a) for a in args.roots] if args.roots else None
    if roots is None:
        repo_root = Path(__file__).resolve().parents[2]
        roots = sorted(p for p in repo_root.glob("protocol-*") if p.is_dir())
        if not roots:
            roots = [repo_root]

    combined = Report()
    total_files = 0
    for root in roots:
        if not root.is_dir():
            combined.error(root, "not a directory")
            continue
        total_files += len(find_fixture_files(root))
        sub_report = validate_directory(root)
        combined.errors.extend(sub_report.errors)
        combined.warnings.extend(sub_report.warnings)

    if not args.quiet:
        for warning in combined.warnings:
            print(f"warning: {warning}")
    for error in combined.errors:
        print(f"error: {error}", file=sys.stderr)

    if combined.ok:
        print(f"OK: {total_files} fixture file(s) valid across {len(roots)} root(s)")
        return 0
    print(f"FAILED: {len(combined.errors)} error(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
