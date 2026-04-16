from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deepzero.engine.process import _kill_process_tree, run_subprocess_with_kill


class TestRunSubprocessWithKill:
    def test_successful_run(self):
        rc, stdout, stderr = run_subprocess_with_kill(
            [sys.executable, "-c", "print('hello')"],
            timeout=10,
        )
        assert rc == 0
        assert b"hello" in stdout

    def test_nonzero_exit(self):
        rc, stdout, stderr = run_subprocess_with_kill(
            [sys.executable, "-c", "import sys; sys.exit(42)"],
            timeout=10,
        )
        assert rc == 42

    def test_stderr_capture(self):
        rc, stdout, stderr = run_subprocess_with_kill(
            [sys.executable, "-c", "import sys; sys.stderr.write('oops')"],
            timeout=10,
        )
        assert rc == 0
        assert b"oops" in stderr

    def test_timeout_raises(self):
        with pytest.raises(RuntimeError):
            run_subprocess_with_kill(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=1,
            )

    def test_cwd_argument(self, tmp_path):
        rc, stdout, _ = run_subprocess_with_kill(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            timeout=10,
            cwd=str(tmp_path),
        )
        assert rc == 0
        assert tmp_path.name.encode() in stdout

    def test_env_argument(self):
        import os

        env = {**os.environ, "DEEPZERO_TEST_VAR": "test_val_123"}
        rc, stdout, _ = run_subprocess_with_kill(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('DEEPZERO_TEST_VAR', ''))",
            ],
            timeout=10,
            env=env,
        )
        assert rc == 0
        assert b"test_val_123" in stdout


@pytest.mark.asyncio
class TestKillProcessTree:
    async def test_kill_already_exited(self):
        # process that exits immediately
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "pass",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        # should not raise even though process is already dead
        await _kill_process_tree(proc)

    @patch("deepzero.engine.process.asyncio.create_subprocess_exec")
    async def test_kill_on_windows(self, mock_create):
        # mock taskkill process
        mock_kproc = AsyncMock()
        mock_kproc.communicate.return_value = (b"", b"")
        mock_create.return_value = mock_kproc

        # simulated target process
        proc = MagicMock()
        proc.pid = 12345
        proc.wait = AsyncMock(return_value=None)

        with patch("deepzero.engine.process.sys") as mock_sys:
            mock_sys.platform = "win32"
            await _kill_process_tree(proc)

        mock_create.assert_called_once()
        call_args = mock_create.call_args[0]
        assert r"C:\Windows\System32\taskkill.exe" in call_args
        assert str(12345) in call_args

    @patch(
        "deepzero.engine.process.asyncio.create_subprocess_exec",
        side_effect=OSError("no such process"),
    )
    async def test_kill_handles_os_error(self, mock_create):
        # on windows, taskkill creation might raise OSError if path is broken
        proc = MagicMock()
        proc.pid = 99999
        proc.wait = AsyncMock(return_value=None)

        with patch("deepzero.engine.process.sys") as mock_sys:
            mock_sys.platform = "win32"
            # should not raise - OSError is caught locally or at asyncio level
            await _kill_process_tree(proc)
