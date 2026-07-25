"""Whether the process that owns a run is still alive.

A run records the status it last wrote down. On its own that is not enough to
describe a run to somebody reading a report: a pipeline that is killed, or whose
machine reboots, never gets to write a closing status, so the last thing on
record stays "running" indefinitely. A report built from that alone advertises a
run that ended hours ago.

So a run also records which process is writing it, and that claim can be checked.
"""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass

_WINDOWS = sys.platform == "win32"


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def start_token(pid: int) -> str:
    """A stamp identifying one particular process, so a reused pid is not
    mistaken for the original. Empty when the platform will not say."""
    if pid <= 0:
        return ""
    if _WINDOWS:
        return _windows_start_token(pid)
    try:
        # field 22 of /proc/pid/stat is the start time in clock ticks. the
        # process name sits in parentheses and may itself contain spaces, so
        # split after the closing one.
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            tail = fh.read().rpartition(")")[2]
        return tail.split()[19]
    except (OSError, IndexError):
        return ""


def is_running(pid: int, token: str = "") -> bool | None:
    """True if alive, False if gone, None when it cannot be determined."""
    if pid <= 0:
        return None
    alive = _windows_alive(pid) if _WINDOWS else _posix_alive(pid)
    if alive is not True:
        return alive
    # the pid is in use, but a long-finished run's pid may since have been
    # handed to something unrelated.
    if token:
        current = start_token(pid)
        if current and current != token:
            return False
    return True


# -- windows --


def _windows_handles():  # pragma: no cover - platform specific
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.GetProcessTimes.restype = wintypes.BOOL
    return ctypes, wintypes, k32


# SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION. the limited variant is
# granted for processes owned by other users, which the full one is not.
_ACCESS = 0x00100000 | 0x1000
_WAIT_TIMEOUT = 0x00000102
_ERROR_INVALID_PARAMETER = 87


def _windows_start_token(pid: int) -> str:  # pragma: no cover - platform specific
    """Creation time of the process, which no later process with the same pid
    can repeat."""
    try:
        ctypes, wintypes, k32 = _windows_handles()
    except (ImportError, OSError):
        return ""
    handle = k32.OpenProcess(_ACCESS, False, pid)
    if not handle:
        return ""
    try:
        created = wintypes.FILETIME()
        spare = (wintypes.FILETIME * 3)()
        ok = k32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(spare[0]),
            ctypes.byref(spare[1]),
            ctypes.byref(spare[2]),
        )
        if not ok:
            return ""
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        k32.CloseHandle(handle)


def _windows_alive(pid: int) -> bool | None:  # pragma: no cover - platform specific
    try:
        ctypes, _, k32 = _windows_handles()
    except (ImportError, OSError):
        return None
    handle = k32.OpenProcess(_ACCESS, False, pid)
    if not handle:
        # no such process id at all. any other failure is a permissions or
        # policy problem and says nothing about whether it is alive.
        return False if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER else None
    try:
        # a running process never signals; an exited one signals immediately.
        return k32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        k32.CloseHandle(handle)


def _posix_alive(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return None
    return True


# -- what a reader should be told --


@dataclass(frozen=True)
class Liveness:
    state: str  # running | stopped | finished | unknown
    detail: str

    @property
    def is_live(self) -> bool:
        return self.state == "running"


_TERMINAL = {
    "completed": "finished",
    "failed": "failed",
    "interrupted": "interrupted",
    "cancelled": "cancelled",
}


def resolve(
    status: str,
    *,
    pid: int = 0,
    host: str = "",
    token: str = "",
) -> Liveness:
    """Reconcile the status a run recorded with whether its process still exists.

    A run that recorded an outcome is taken at its word - it got far enough to
    say how it ended. Only a run still claiming to be in progress needs checking,
    because that is the claim nothing revokes on its own.
    """
    stored = (status or "").strip().lower()
    if stored in _TERMINAL:
        return Liveness("finished", _TERMINAL[stored])
    if stored != "running":
        return Liveness("unknown", stored or "unknown")

    if host and hostname() and host != hostname():
        return Liveness("unknown", f"started on {host}")

    alive = is_running(pid, token)
    if alive is True:
        return Liveness("running", f"process {pid}")
    if alive is False:
        return Liveness("stopped", f"process {pid} is gone")
    return Liveness("unknown", "cannot reach the process")
