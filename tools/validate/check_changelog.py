#!/usr/bin/env python3
"""Check that pull requests modifying fixtures, schemas, or tools include a CHANGELOG entry.

Rule [F-055]:
A changelog entry (CHANGELOG.md) is required under '## [Unreleased]' whenever a pull
request modifies governed files:
  - Protocol packs (`protocol-*/`)
  - Schemas (`schemas/`)
  - Tools/scripts (`tools/`)

Exemptions:
  - Changes affecting only documentation (`docs/`, root `*.md`), tests (`tests/`),
    or workflow/CI files (`.github/`).
  - Pull requests with the explicit opt-out label `no-changelog` (via GitHub event
    payload, PR_LABELS env var, or --label flag).
  - Pull requests where `CHANGELOG.md` itself is modified.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Optical opt-out label name
OPT_OUT_LABEL = "no-changelog"

# Rule identifier
RULE_ID = "F-055"


@dataclass(frozen=True)
class ChangelogCheckResult:
    passed: bool
    governed_files: list[str]
    has_changelog: bool
    has_opt_out: bool
    message: str


def normalize_path(path: str | Path, repo_root: Path | None = None) -> str:
    """Normalize a path to a repository-relative forward-slash POSIX path."""
    raw = str(path).strip().strip("'\"").replace("\\", "/")
    if not raw:
        return ""

    # If path is absolute, try making it relative to repo_root
    if os.path.isabs(raw):
        if repo_root is not None:
            try:
                raw = os.path.relpath(raw, str(repo_root)).replace("\\", "/")
            except ValueError:
                pass
        else:
            # Fall back to cwd
            try:
                raw = os.path.relpath(raw, os.getcwd()).replace("\\", "/")
            except ValueError:
                pass

    # Clean leading ./
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.lstrip("/")
    return os.path.normpath(raw).replace("\\", "/") if raw else ""


def is_changelog_file(path: str | Path) -> bool:
    """Check if the given path is the repository CHANGELOG.md file."""
    norm = normalize_path(path)
    return norm.lower() in ("changelog.md", "changelog.markdown", "changelog")


def is_governed_path(path: str | Path) -> bool:
    """Determine whether a path falls under governed categories:
    - Protocol packs (`protocol-*/`)
    - Schemas (`schemas/`)
    - Tools/scripts (`tools/`)
    """
    norm = normalize_path(path)
    if not norm:
        return False

    # The changelog file itself is not a governed fixture/tool/schema
    if is_changelog_file(norm):
        return False

    parts = norm.split("/")
    first = parts[0]

    # Schemas: schemas/...
    if first == "schemas":
        return True

    # Tools: tools/...
    if first == "tools":
        return True

    # Protocol packs: protocol-*/...
    # Must start with protocol- and either have a child path or be a pack directory name
    if first.startswith("protocol-"):
        # Top-level standalone non-directory files like 'protocol-notes.txt' are not packs
        if len(parts) > 1 or norm.endswith("/") or not ("." in first):
            return True

    return False


def parse_changed_file_line(line: str) -> list[str]:
    """Parse a single line from git diff or file list into candidate file paths."""
    line = line.strip()
    if not line or line.startswith("#"):
        return []

    # git diff --name-status output: "M\tpath/to/file" or "R100\told/path\tnew/path"
    if "\t" in line:
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) >= 2 and re.match(r"^[MADRCTU][0-9]*$", parts[0]):
            return parts[1:]
        return parts

    # git diff rename arrow: "old_path -> new_path"
    if " -> " in line:
        return [p.strip() for p in line.split(" -> ") if p.strip()]

    return [line]


def extract_labels_from_event(event_path: str | Path) -> set[str]:
    """Extract PR labels from GitHub Actions event payload JSON."""
    path = Path(event_path)
    if not path.is_file():
        return set()

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()

    labels: set[str] = set()
    pr = data.get("pull_request")
    if isinstance(pr, dict):
        raw_labels = pr.get("labels", [])
        if isinstance(raw_labels, list):
            for item in raw_labels:
                if isinstance(item, dict) and "name" in item:
                    labels.add(str(item["name"]).strip().lower())
                elif isinstance(item, str):
                    labels.add(item.strip().lower())
    return labels


def parse_labels_string(s: str) -> set[str]:
    """Parse labels from comma/space-separated string or JSON array string."""
    s = s.strip()
    if not s:
        return set()
    if s.startswith("[") and s.endswith("]"):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return {str(x).strip().lower() for x in arr if x}
        except Exception:
            pass
    parts = re.split(r"[,\s]+", s)
    return {p.strip().lower() for p in parts if p.strip()}


def get_git_diff_files(base_ref: str, repo_root: Path | None = None) -> list[str]:
    """Retrieve changed files from git diff between base_ref and HEAD."""
    cwd = str(repo_root) if repo_root else os.getcwd()

    candidates = [base_ref]
    if base_ref.startswith("origin/"):
        candidates.append(base_ref[len("origin/") :])
    candidates.extend(["FETCH_HEAD", "origin/main", "main"])

    last_error = ""
    for ref in candidates:
        for diff_args in ([f"{ref}...HEAD"], [ref, "HEAD"]):
            cmd = ["git", "diff", "--name-only", *diff_args]
            try:
                res = subprocess.run(
                    cmd,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                raise RuntimeError("git executable not found in PATH")
            if res.returncode == 0:
                return [line.strip() for line in res.stdout.splitlines() if line.strip()]
            last_error = res.stderr.strip()

    raise RuntimeError(f"git diff failed for base ref '{base_ref}': {last_error}")


def check_changelog(
    changed_files: Sequence[str | Path],
    labels: Sequence[str] = (),
    repo_root: Path | None = None,
) -> ChangelogCheckResult:
    """Evaluate whether changed files satisfy the changelog requirement [F-055]."""
    normalized_files: list[str] = []
    for f in changed_files:
        for candidate in parse_changed_file_line(str(f)):
            norm = normalize_path(candidate, repo_root=repo_root)
            if norm and norm not in normalized_files:
                normalized_files.append(norm)

    has_changelog = any(is_changelog_file(f) for f in normalized_files)
    governed_files = [f for f in normalized_files if is_governed_path(f)]

    # Normalized labels
    label_set = {str(l).strip().lower() for l in labels}
    has_opt_out = OPT_OUT_LABEL in label_set

    if not governed_files:
        msg = "OK: No governed files (fixtures, schemas, tools) were modified; CHANGELOG.md is not required."
        return ChangelogCheckResult(
            passed=True,
            governed_files=[],
            has_changelog=has_changelog,
            has_opt_out=has_opt_out,
            message=msg,
        )

    if has_changelog:
        msg = (
            f"OK: Governed file(s) were modified, and CHANGELOG.md has been updated "
            f"({len(governed_files)} governed file(s) changed)."
        )
        return ChangelogCheckResult(
            passed=True,
            governed_files=governed_files,
            has_changelog=True,
            has_opt_out=has_opt_out,
            message=msg,
        )

    if has_opt_out:
        msg = (
            f"OK: Governed file(s) were modified ({len(governed_files)} file(s)), "
            f"but changelog requirement is bypassed by '{OPT_OUT_LABEL}' label."
        )
        return ChangelogCheckResult(
            passed=True,
            governed_files=governed_files,
            has_changelog=False,
            has_opt_out=True,
            message=msg,
        )

    # Failed check
    file_list_str = "".join(f"  - {f}\n" for f in governed_files)
    msg = (
        f"ERROR: [{RULE_ID}] Pull requests modifying fixtures ('protocol-*/'), schemas ('schemas/'), "
        f"or tools ('tools/') require a CHANGELOG entry under '## [Unreleased]'.\n\n"
        f"The following {len(governed_files)} governed file(s) were changed without an update to CHANGELOG.md:\n"
        f"{file_list_str}\n"
        f"To resolve this failure, please either:\n"
        f"  1. Add an entry describing your changes to CHANGELOG.md under '## [Unreleased]'.\n"
        f"  2. Apply the '{OPT_OUT_LABEL}' label to this pull request if exempt "
        f"(e.g., internal refactoring or no user-facing changes)."
    )
    return ChangelogCheckResult(
        passed=False,
        governed_files=governed_files,
        has_changelog=False,
        has_opt_out=False,
        message=msg,
    )


def build_markdown_summary(result: ChangelogCheckResult) -> str:
    """Generate a markdown report suitable for GitHub Step Summary."""
    status_icon = "✅" if result.passed else "❌"
    title = f"### {status_icon} CHANGELOG Validation [{RULE_ID}]"
    lines = [title, ""]
    if result.passed:
        lines.append(f"**Status:** PASSED")
        lines.append(f"\n{result.message}\n")
    else:
        lines.append(f"**Status:** FAILED")
        lines.append(
            "\nA CHANGELOG entry is required for pull requests that change fixtures, schemas, or tools."
        )
        lines.append("\n**Governed files modified:**")
        for f in result.governed_files:
            lines.append(f"- `{f}`")
        lines.append(
            f"\n*If this pull request does not need a changelog entry, apply the `{OPT_OUT_LABEL}` label.*"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that PRs modifying fixtures, schemas, or tools include a CHANGELOG.md entry [F-055]."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Changed file paths to validate (optional; can also use --base or stdin).",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        dest="flag_files",
        help="Explicit list of changed file paths.",
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="Git base reference to diff against (e.g. 'origin/main' or 'origin/pr-base').",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read list of changed file paths from stdin.",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help="PR label (can be specified multiple times).",
    )
    parser.add_argument(
        "--labels",
        dest="labels_str",
        help="Comma-separated or JSON list of PR labels.",
    )
    parser.add_argument(
        "--event-path",
        metavar="PATH",
        help="Path to GitHub event payload JSON (defaults to $GITHUB_EVENT_PATH).",
    )
    parser.add_argument(
        "--summary-file",
        metavar="FILE",
        help="Path to write GitHub Step Summary markdown.",
    )
    parser.add_argument(
        "--repo-root",
        metavar="DIR",
        type=Path,
        help="Repository root directory.",
    )

    args = parser.parse_args(argv)

    # Collect labels
    all_labels: set[str] = set()
    for l in args.labels:
        all_labels.add(l.strip().lower())
    if args.labels_str:
        all_labels.update(parse_labels_string(args.labels_str))

    # Check env PR_LABELS
    env_labels = os.environ.get("PR_LABELS")
    if env_labels:
        all_labels.update(parse_labels_string(env_labels))

    # Check GitHub event path
    event_path = args.event_path or os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        all_labels.update(extract_labels_from_event(event_path))

    # Collect changed files
    changed_files: list[str] = []
    if args.flag_files:
        changed_files.extend(args.flag_files)
    if args.files:
        changed_files.extend(args.files)

    if args.base:
        try:
            diff_files = get_git_diff_files(args.base, repo_root=args.repo_root)
            changed_files.extend(diff_files)
        except (RuntimeError, subprocess.SubprocessError, subprocess.CalledProcessError) as e:
            print(f"Error determining changed files via git: {e}", file=sys.stderr)
            return 2

    if args.stdin or ("-" in changed_files):
        if "-" in changed_files:
            changed_files.remove("-")
        for line in sys.stdin:
            line_str = line.strip()
            if line_str:
                changed_files.append(line_str)
    elif not changed_files and not sys.stdin.isatty():
        # Input piped in via stdin
        for line in sys.stdin:
            line_str = line.strip()
            if line_str:
                changed_files.append(line_str)

    # If still no files provided and not piped, attempt git diff against origin/main if in repo
    if not changed_files and not args.stdin:
        # Check if we can fallback to git diff origin/main...HEAD
        try:
            diff_files = get_git_diff_files("origin/main", repo_root=args.repo_root)
            changed_files.extend(diff_files)
        except Exception:
            pass

    result = check_changelog(
        changed_files=changed_files,
        labels=list(all_labels),
        repo_root=args.repo_root,
    )

    # Summary file if requested
    if args.summary_file:
        try:
            summary_md = build_markdown_summary(result)
            summary_path = Path(args.summary_file)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("a" if summary_path.exists() else "w", encoding="utf-8") as f:
                f.write(summary_md)
        except Exception as e:
            print(f"Warning: could not write summary file: {e}", file=sys.stderr)

    if result.passed:
        print(result.message)
        return 0
    else:
        print(result.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
