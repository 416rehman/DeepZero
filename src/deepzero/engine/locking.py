from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


class RunLockedError(RuntimeError):
    """Another process already holds this run's writer lock."""


class RunLock:
    """Hold a nonblocking OS lock until its handle closes.

    Keep the file outside the corpus: --clean may rename that directory.
    The file remains after release; its existence does not imply ownership.
    """

    def __init__(self, path: Path):
        self.path = path
        self._handle: BinaryIO | None = None

    def acquire(self) -> RunLock:
        if self._handle is not None:
            return self

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                # Every opener must lock byte 0, including in a newly created file.
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise RunLockedError(f"another process is writing this run: {self.path}") from exc
            raise
        except BaseException:
            handle.close()
            raise

        self._handle = handle
        return self

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> RunLock:
        return self.acquire()

    def __exit__(self, *_exc_info: object) -> None:
        self.release()
