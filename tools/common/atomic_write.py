"""Write file output atomically so that the final path is never a partial file.

On every successful write the final path ends up with the complete new content.
On any error the final path keeps its previous content (or is left absent if it
never existed), and no temporary file is left behind in the destination
directory.

The temp file is created in the *same directory* as the target so that
os.replace() is atomic (same filesystem).  On POSIX the containing directory
is fsynced after the replace so that a power failure makes the new state
persistent on disk.
"""

import os
import tempfile


def write_bytes_atomic(path: object, data: bytes) -> None:
    """Write *data* to *path* atomically.

    The file at *path* will be replaced with *data* so that a reader of the
    final path always sees either the old complete content, the previous
    complete content, or the new complete content — never a truncated file.

    The temporary file is created in the same directory as the target (same
    filesystem), so ``os.replace`` is atomic even on crash.

    On POSIX the containing directory is fsynced after the replace so that a
    power failure makes the new state persistent.

    Parameters
    ----------
    path : path-like
        The final destination path.  Must be on the same filesystem as the
        temporary file (creating the temp file in the target directory guarantees
        this).
    data : bytes
        The complete content to write.

    Raises
    ------
    OSError
        If the temporary file cannot be written, fsynced, or replaced.  The
        original ``OSError`` is raised (or a subclass such as ``PermissionError``).
    """
    if isinstance(path, str):
        path = os.fspath(path)

    # Determine the directory we will write the temp file into.  We place it
    # in the *same* directory as the target so that os.replace() is atomic
    # (same filesystem).
    target_path = path
    target_dir = os.path.dirname(target_path)

    # Generate a temporary filename that cannot collide with a final output
    # name.  We use a name incorporating the target basename to avoid
    # collisions across different outputs in the same directory.
    tmp_name = _tmp_name(target_dir, target_path)
    tmp_path = os.path.join(target_dir, tmp_name)

    # Track whether we need to clean up the temp file on error.
    # We use a flag instead of relying on fd state, because fd can be
    # reset to None in exception handlers.
    temp_file_created = False

    try:
        # Open a temporary file *without* delete=True so we can fsync and
        # replace it ourselves.  Using O_TRUNC so that if the old file exists
        # it is truncated early (but we os.replace before anything sees the
        # truncated version).
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_SYNC, 0o644)
        temp_file_created = True
        try:
            os.write(fd, data)
        except BaseException:
            # Clean up the temp file on any write error.
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # fsync the file so its data is on disk before we replace the target.
        os.fsync(fd)
        os.close(fd)
        fd = None  # already closed

        # Replace the target atomically.
        os.replace(tmp_path, target_path)

        # On POSIX fsync the containing directory so that the replace is
        # durable after a power failure.  Guard against platforms where
        # opening a directory is not supported (e.g. Windows in some builds).
        try:
            dir_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            # Directory fsync is not supported on this platform; ignore.
            pass

    except BaseException:
        # If we hit an error after the temp file was created, make sure it
        # is removed so no stray file remains.  Use the flag rather than
        # checking fd state.
        if temp_file_created:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _tmp_name(target_dir: str, target_path: str) -> str:
    """Return a temporary filename that cannot collide with the final name.

    We embed the target basename encoded to avoid collisions when multiple
    outputs are written to the same directory.
    """
    basename = os.path.basename(target_path)
    import uuid
    unique = uuid.uuid4().hex[:12]
    # Name format: .canary-tmp-<basename>-<uuidhex12>
    # The leading dot ensures the file is hidden from casual listing and is
    # guaranteed not to match any final output name.
    return f".canary-tmp-{basename}-{unique}"