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
import uuid


def write_bytes_atomic(path: object, data: bytes) -> None:
    """Write *data* to *path* atomically.

    The file at *path* will be replaced with *data* so that a reader of the
    final path always sees either the previous complete content or the new
    complete content -- never a truncated file.

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
    target_path = os.fspath(path)
    # An empty dirname means the current directory; opening "" for the
    # directory fsync would fail, and a relative temp path is enough for
    # os.replace to stay on the same filesystem.
    target_dir = os.path.dirname(target_path) or "."
    tmp_path = os.path.join(target_dir, _tmp_name(target_path))

    fd = None
    try:
        # Mode 0o666 lets the process umask decide the permissions, the same
        # way open(path, "wb") does for the tools that wrote these files
        # before this helper existed.
        # O_BINARY (Windows only) keeps os.write from translating "\n" into
        # "\r\n", which would corrupt the archive bytes.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        fd = os.open(tmp_path, flags, 0o666)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write while writing the temporary file")
                view = view[written:]
            # Flush the file's data to disk before it becomes the final path.
            os.fsync(fd)
        finally:
            os.close(fd)
            fd = None

        # os.replace is atomic within one filesystem: readers see either the
        # previous file or the complete new one.
        os.replace(tmp_path, target_path)

        # Make the directory entry durable on POSIX. This is best-effort:
        # some platforms do not support opening or fsyncing a directory, and
        # the data file itself has already been fsynced above.
        _fsync_directory(target_dir)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _fsync_directory(directory: str) -> None:
    """Fsync *directory* where the platform supports it."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        dir_fd = os.open(directory, flags)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        # Directory fsync is not supported on this platform; the file itself
        # has already been fsynced, so this is not an error.
        pass
    finally:
        os.close(dir_fd)


def _tmp_name(target_path: str) -> str:
    """A temporary filename that cannot collide with the final name.

    The target basename is embedded so that concurrent writers for different
    outputs in one directory never share a temporary file. The random suffix
    keeps concurrent writers for the *same* output apart.
    """
    basename = os.path.basename(target_path)
    unique = uuid.uuid4().hex[:12]
    # The leading dot keeps the temporary file out of a casual listing, and
    # the prefix makes it identifiable as ours.
    return f".canary-tmp-{basename}-{unique}"
