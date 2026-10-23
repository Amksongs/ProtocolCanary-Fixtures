"""Path identity and safety utilities (issue #410, F-117).

Prevents tools from overwriting protected input files, archives, directories or devices.
"""
from __future__ import annotations

import os
from pathlib import Path


def canonical_path(path: Path | str) -> str:
    """Return the real, normalized path for a target, even if it does not exist yet.

    If the file exists, resolves symbolic links via os.path.realpath.
    If it does not exist yet, os.path.realpath resolves symlinks across all existing
    leading path components and appends the non-existing leaf.
    Uses os.path.normcase to ensure case-insensitive equivalence on supported platforms.
    """
    p = Path(path)
    real = os.path.realpath(str(p))
    return os.path.normcase(real)


def is_same_file(target: Path | str, source: Path | str) -> bool:
    """Decide whether target and source refer to the same filesystem location.

    Uses real file identity:
    - If both exist, compares using os.path.samefile (which checks (st_dev, st_ino),
      catching hard links, bind-mount aliases, and symlinks).
    - If one or both do not exist, falls back to canonical_path comparison
      (resolving symlinks and case normalization).
    """
    target_path = Path(target)
    source_path = Path(source)

    if target_path.exists() and source_path.exists():
        try:
            if os.path.samefile(target_path, source_path):
                return True
        except (OSError, ValueError):
            pass

    return canonical_path(target_path) == canonical_path(source_path)


def check_target_safety(
    target: Path | str,
    protected_inputs: list[tuple[Path | str, str]],
) -> None:
    """Check that target does not overwrite any protected input or invalid file type.

    protected_inputs is a list of (path, role) tuples, e.g.:
      [(pack_dir, "the pack directory"), (fixture_path, "a pack fixture"), ...]

    Raises ValueError if:
    - target refers to the same file as one of the protected inputs.
    - target already exists and is a directory or non-regular file (device, fifo).
    """
    target_path = Path(target)

    for protected_path, role in protected_inputs:
        protected = Path(protected_path)
        if is_same_file(target_path, protected):
            if str(target) == str(protected):
                raise ValueError(
                    f"refusing to write {target}: it is the same file as {role}"
                )
            else:
                raise ValueError(
                    f"refusing to write {target}: it is the same file as {role} ({protected})"
                )

    if target_path.exists():
        if target_path.is_dir():
            raise ValueError(f"refusing to write {target}: target is a directory")
        if not target_path.is_file():
            raise ValueError(f"refusing to write {target}: target is not a regular file")
