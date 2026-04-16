from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("deepzero.process")


async def _run_async(
    cmd: list[str],
    timeout: int,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    env_dict = None
    if env is not None:
        env_dict = dict(os.environ)
        env_dict.update(env)

    proc = await asyncio.create_subprocess_exec(
        cmd[0],
        *cmd[1:],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env_dict,
        **kwargs,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode if proc.returncode is not None else -1, stdout, stderr
    except asyncio.TimeoutError:
        await _kill_process_tree(proc)
        raise TimeoutError("process timed out")


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    try:
        if sys.platform == "win32":
            kproc = await asyncio.create_subprocess_exec(
                r"C:\Windows\System32\taskkill.exe",
                "/T",
                "/F",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(kproc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                log.warning("taskkill timed out for pid %d - process may be orphaned", proc.pid)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError) as exc:
        log.debug("process tree kill skipped - pid %d already gone: %s", proc.pid, exc)
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        log.warning("process %d did not exit within 5s after kill - abandoning", proc.pid)


def run_subprocess_with_kill(
    cmd: list[str],
    timeout: int,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    # Use asyncio.run to seamlessly bridge synchronous execution to native safety
    try:
        return asyncio.run(_run_async(cmd, timeout, cwd, env))
    except TimeoutError as exc:
        # Compatibility with the caller assuming a generic exception or specific structure
        raise RuntimeError("Subprocess execution timed out") from exc
