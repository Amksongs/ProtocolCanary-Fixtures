#!/usr/bin/env python3
"""Fixture scaffolding tool (issue #353).

Generates a skeleton fixture file with the required header sections and
explicit placeholders for missing values. Untouched skeletons intentionally
fail validation until placeholders are replaced with real, verified evidence.

Usage:
    python3 tools/scaffold/new_fixture.py --surface {xdr,rpc,soroban} --protocol N --id ID --category CAT [--output-dir DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.validate import validate

_CAP_RE = re.compile(r"^cap-\d{4}$")


def validate_id_rule(fixture_id: str) -> str | None:
    """Validate fixture id following validate.py's rules."""
    if not fixture_id:
        return "id must not be empty"
    if fixture_id != fixture_id.lower():
        return "id must be lowercase"
    if " " in fixture_id:
        return "id must not contain spaces"
    filename = f"{fixture_id}.toml"
    try:
        validate.portable_names.check_segment(filename)
    except validate.portable_names.PortableNameError as err:
        return f"invalid fixture id: {err}"
    return None


def render_skeleton(surface: str, protocol: int, fixture_id: str, category: str) -> str:
    lines = [
        "# What this tests:",
        "# TODO: Describe what Stellar behavior this fixture tests.",
        "#",
        "# Why it matters:",
        "# TODO: Explain why this behavior is important.",
        "#",
        "# Introduced in:",
        "# TODO: Specify the protocol version or CAP that introduced this behavior.",
        "#",
        "# Expected result and where it comes from:",
        "# TODO: Document the expected result and the authoritative source it was derived from.",
        "#",
        "# Determinism:",
        "# TODO: Confirm whether this test is deterministic.",
        "",
        f'id = "{fixture_id}"',
        f"protocol = {protocol}",
        f'surface = "{surface}"',
        f'category = "{category}"',
        'description = "TODO: Brief description of the fixture"',
        'source_reference = "TODO-REPLACE-WITH-CHECKED-SOURCE"',
        "",
    ]

    if surface == "xdr":
        lines.extend([
            'type = "TODO-XDR-TYPE"',
            'kind = "TODO-XDR-KIND"',
            'value_base64 = "TODO-BASE64-PAYLOAD"',
        ])
    elif surface == "rpc":
        lines.extend([
            'method = "TODO-RPC-METHOD"',
            "",
            "[[assert]]",
            'kind = "TODO-ASSERT-KIND"',
            'field = "TODO-RESPONSE-FIELD"',
            'value = "TODO-EXPECTED-VALUE"',
        ])
    elif surface == "soroban":
        lines.extend([
            'source_account = "TODO-SOURCE-ACCOUNT"',
            'contract_id = "TODO-CONTRACT-ID"',
            'function = "TODO-FUNCTION-NAME"',
            'sequence_number = "TODO-SEQUENCE-NUMBER"',
            "",
            "[expect]",
            'kind = "TODO-EXPECT-KIND"',
        ])

    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scaffold a new fixture template with explicit placeholders."
    )
    parser.add_argument(
        "--surface",
        required=True,
        choices=sorted(validate.SURFACES),
        help=f"surface: {', '.join(sorted(validate.SURFACES))}",
    )
    parser.add_argument(
        "--protocol",
        required=True,
        type=int,
        help="positive protocol version integer",
    )
    parser.add_argument(
        "--id",
        required=True,
        help="stable lowercase fixture id (e.g. p28-xdr-sample)",
    )
    parser.add_argument(
        "--category",
        required=True,
        help="fixture category (e.g. cap-0083, ledger, smoke)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT),
        help="base output directory (default: repository root)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.protocol < 1:
        print(f"error: protocol must be a positive integer, got {args.protocol}", file=sys.stderr)
        return 1

    id_err = validate_id_rule(args.id)
    if id_err:
        print(f"error: {id_err}", file=sys.stderr)
        return 1

    if not args.category:
        print("error: category must not be empty", file=sys.stderr)
        return 1

    base_dir = Path(args.output_dir)
    if args.surface == "xdr" and _CAP_RE.match(args.category):
        target_dir = base_dir / f"protocol-{args.protocol}" / "xdr" / args.category
    else:
        target_dir = base_dir / f"protocol-{args.protocol}" / args.surface

    target_file = target_dir / f"{args.id}.toml"
    content = render_skeleton(args.surface, args.protocol, args.id, args.category)
    created_dirs: list[Path] = []
    missing: list[Path] = []
    parent = target_dir
    while not parent.exists():
        missing.append(parent)
        if parent.parent == parent:
            break
        parent = parent.parent
    created_dirs: list[Path] = []
    created_file = False
    try:
        for directory in reversed(missing):
            try:
                directory.mkdir()
            except FileExistsError:
                # Another process may have created it since the path walk.
                continue
            created_dirs.append(directory)
        handle = target_file.open("x", encoding="utf-8")
        created_file = True
        with handle:
            handle.write(content)
    except FileExistsError:
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        print(f"error: file already exists: {target_file}", file=sys.stderr)
        return 1
    except OSError as error:
        if created_file:
            try:
                target_file.unlink()
            except OSError:
                pass
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        print(f"error: could not create {target_file}: {error}", file=sys.stderr)
        return 1

    print(f"Created fixture skeleton at {target_file}")
    print("Next steps:")
    print("  1. Replace all TODO placeholders with checked evidence and expected results.")
    print("  2. Run 'python3 tools/validate/validate.py' to verify the fixture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
