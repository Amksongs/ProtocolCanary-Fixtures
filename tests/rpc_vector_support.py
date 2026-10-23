"""Shared helpers for the RPC request-vector tests (issues #295 to #298).

Not a test module itself: ``unittest discover`` ignores it because its name
does not start with ``test``. Stdlib only, no network.

The vectors live under ``tests/fixtures/rpc/`` and ``tests/fixtures/rpc-errors/``.
They are kept out of the protocol packs on purpose (see the header comment of
any vector); these helpers run them through the same validator CI runs and
build mutated copies of them, so a rule is proven by a fixture that breaks it.
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_support as support  # noqa: E402

REPO_ROOT = support.REPO_ROOT
load_tool = support.load_tool
RPC_VECTORS = REPO_ROOT / "tests" / "fixtures" / "rpc"
ERROR_VECTORS = REPO_ROOT / "tests" / "fixtures" / "rpc-errors" / "error-simulation-vectors.json"

validate = support.load_tool("canary_validate_rpc_vectors", "tools/validate/validate.py")
capture_live = support.load_tool("canary_capture_live_rpc_vectors", "tools/evidence/capture_live.py")


def read_text(relative: str) -> str:
    return (RPC_VECTORS / relative).read_text(encoding="utf-8")


def load_toml(relative: str) -> dict:
    return tomllib.loads(read_text(relative))


def run_validation(files: dict[str, str]):
    """Validate ``files`` (name -> TOML text) written to a scratch directory."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        for name, contents in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        return validate.validate_directory(root)


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run ``validate.main`` the way CI does and return (exit code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = validate.main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def replace_once(text: str, old: str, new: str) -> str:
    """``text`` with exactly one ``old`` replaced; fails loudly if it is not unique.

    A mutation test that silently changes nothing proves nothing, so a missing
    or ambiguous anchor is an error in the test, not a pass.
    """
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"expected exactly one {old!r} in the vector, found {count}")
    return text.replace(old, new)


def set_limit(text: str, literal: str) -> str:
    """The vector with its ``limit = N`` line rewritten to ``limit = <literal>``."""
    return re.sub(r"(?m)^limit = .*$", f"limit = {literal}", text, count=1)
