from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("deepzero.process")


def run_subprocess_with_kill(
    cmd: list[str],
    timeout: int,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    # launches a subprocess in its own process group so we can kill the entire tree
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=cwd, env=env, **kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        raise


def kill_process_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError) as exc:
        log.debug("process tree kill skipped — pid %d already gone: %s", proc.pid, exc)
    except subprocess.TimeoutExpired:
        log.warning("taskkill timed out for pid %d — process may be orphaned", proc.pid)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        log.warning("process %d did not exit within 5s after kill — abandoning", proc.pid)
