"""Nonblocking cross-process locks for Ozon's shared browser session."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None


@contextmanager
def exclusive_file_lock(path):
    """Lock immediately or raise BlockingIOError; never proceed unlocked.

    Keep the lock file in place: unlinking it could let another process lock a
    different inode. Windows locks byte zero, including beyond an empty file's
    EOF, so no initialization write can race with an existing byte-range lock.
    """
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise BlockingIOError(exc.errno, str(exc)) from exc
                raise
        else:
            raise RuntimeError("No supported file-lock backend")
        acquired = True
        yield
    finally:
        try:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                else:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)
