from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from deepzero.engine.process import kill_process_tree, run_subprocess_with_kill


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
        with pytest.raises(subprocess.TimeoutExpired):
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
            [sys.executable, "-c", "import os; print(os.environ['DEEPZERO_TEST_VAR'])"],
            timeout=10,
            env=env,
        )
        assert rc == 0
        assert b"test_val_123" in stdout


class TestKillProcessTree:
    def test_kill_already_exited(self):
        # process that exits immediately
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.wait()
        # should not raise even though process is already dead
        kill_process_tree(proc)

    @patch("deepzero.engine.process.subprocess.run")
    def test_kill_on_windows(self, mock_run):
        proc = MagicMock()
        proc.pid = 12345
        proc.wait.return_value = None

        with patch("deepzero.engine.process.sys") as mock_sys:
            mock_sys.platform = "win32"
            kill_process_tree(proc)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "taskkill" in call_args
        assert str(12345) in call_args

    @patch("deepzero.engine.process.subprocess.run", side_effect=OSError("no such process"))
    def test_kill_handles_os_error(self, mock_run):
        # on windows, taskkill raises OSError if process is gone
        proc = MagicMock()
        proc.pid = 99999
        proc.wait.return_value = None

        with patch("deepzero.engine.process.sys") as mock_sys:
            mock_sys.platform = "win32"
            # should not raise - OSError is caught
            kill_process_tree(proc)
