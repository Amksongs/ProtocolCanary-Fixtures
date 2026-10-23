#!/usr/bin/env python3
"""Guard the repository root against stray files (F-054, issue #328).

Inspects root-level entries in the repository (via ``git ls-files`` or scanning
the repository root) and ensures that every entry belongs to an explicit
allow-list of legitimate root files and directories.

Fails with exit code 1 and prints the names of any unexpected files or
directories found at the repository root.

Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

# Explicit allow-list of legitimate repository root entries.
DEFAULT_ALLOWLIST: frozenset[str] = frozenset({
    ".coveragerc",
    ".git",
    ".gitattributes",
    ".github",
    ".gitignore",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "assets",
    "docs",
    "protocol-27",
    "protocol-28",
    "protocol-29",
    "requirements-differential.txt",
    "schemas",
    "tests",
    "tools",
    "upstream-matrix.json",
})

# Pattern matching protocol pack directories (e.g. protocol-28, protocol-30).
PROTOCOL_PACK_PATTERN = re.compile(r"^protocol-\d+$")


def extract_root_entry(path_str: str | Path) -> str:
    """Extract the top-level repository root entry from a path string or Path.

    Normalizes forward/backward slashes and strips leading/trailing slashes.
    Examples:
        'tools/validate/validate.py' -> 'tools'
        'tools/'                    -> 'tools'
        'README.md'                 -> 'README.md'
        './diff.txt'                -> 'diff.txt'
    """
    normalized = str(path_str).replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/")
    if not normalized:
        return ""
    return normalized.split("/")[0]


def is_allowed(entry: str, allowlist: frozenset[str] | set[str] = DEFAULT_ALLOWLIST) -> bool:
    """Check whether a single root entry is permitted by the allow-list."""
    clean = entry.rstrip("/\\")
    if clean in allowlist:
        return True
    if PROTOCOL_PACK_PATTERN.match(clean):
        return True
    return False


def check_root_entries(
    entries: Iterable[str | Path],
    allowlist: frozenset[str] | set[str] = DEFAULT_ALLOWLIST,
) -> list[str]:
    """Inspect entries and return a sorted list of unexpected root files/directories."""
    unexpected: set[str] = set()
    for entry in entries:
        root_name = extract_root_entry(entry)
        if not root_name:
            continue
        if not is_allowed(root_name, allowlist):
            unexpected.add(root_name)
    return sorted(unexpected)


def get_root_entries(repo_root: Path | None = None) -> list[str]:
    """Retrieve root-level entries in the repository.

    First attempts to query tracked and untracked non-ignored files using git.
    If git is unavailable or repo_root is not a git worktree, scans the root directory.
    """
    if repo_root is None:
        repo_root = REPO_ROOT

    # Attempt git ls-files if inside a git repository
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        entries: set[str] = set()
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            root_entry = extract_root_entry(line)
            if root_entry:
                entries.add(root_entry)
        if entries:
            return sorted(entries)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    # Fall back to scanning repo_root directory items
    entries = set()
    try:
        for child in repo_root.iterdir():
            name = child.name
            if name in (".git", ".DS_Store"):
                continue
            entries.add(name)
    except OSError:
        pass
    return sorted(entries)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Verify that no stray or unexpected files exist in the repository root."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Path to repository root (defaults to %(default)s)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for checking root files."""
    parser = build_parser()
    args = parser.parse_args(argv)

    entries = get_root_entries(args.root)
    unexpected = check_root_entries(entries)

    if unexpected:
        print("ERROR: Unexpected file(s) found in repository root:", file=sys.stderr)
        for name in unexpected:
            print(f"  - {name}", file=sys.stderr)
        return 1

    print(f"OK: all root entries match allow-list ({len(entries)} entries checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
