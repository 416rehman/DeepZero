from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from deepzero.engine.locking import RunLock, RunLockedError


def test_a_second_writer_is_refused_until_the_first_releases(tmp_path):
    path = tmp_path / ".locks" / "corpus.lock"
    first, second = RunLock(path), RunLock(path)
    with first:
        with pytest.raises(RunLockedError, match="another process"):
            second.acquire()
    with second:
        with pytest.raises(RunLockedError):
            first.acquire()
    # A leftover lock file is safe: ownership comes from the OS, not existence.
    assert path.is_file()
    with RunLock(path):
        pass


@pytest.mark.parametrize("ending", ["exit", "kill"])
def test_os_releases_the_lock_when_a_writer_exits(tmp_path, ending):
    path = tmp_path / "corpus.lock"
    ready = tmp_path / "ready"
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from deepzero.engine.locking import RunLock\n"
        "lock = RunLock(Path(sys.argv[2])).acquire()\n"
        "Path(sys.argv[3]).write_text('ready')\n"
        "sys.stdin.read()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(source_root), str(path), str(ready)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "child writer did not acquire its lock"
        with pytest.raises(RunLockedError):
            RunLock(path).acquire()

        if ending == "kill":
            proc.kill()
        proc.communicate(input=b"", timeout=10)
        with RunLock(path):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=10)
