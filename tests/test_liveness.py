"""A run's recorded status is a claim; these cover checking it against reality."""

from __future__ import annotations

import os

from deepzero.engine import liveness


def test_this_process_is_running():
    pid = os.getpid()
    assert liveness.is_running(pid, liveness.start_token(pid)) is True


def test_a_pid_that_cannot_exist_is_not_running():
    assert liveness.is_running(999_999) is False


def test_probing_does_not_disturb_the_target():
    # os.kill(pid, 0) terminates the process on windows, so the probe must not
    # reach for it. if this ever regresses the test run itself disappears.
    pid = os.getpid()
    for _ in range(5):
        liveness.is_running(pid)
    assert liveness.is_running(pid) is True


def test_a_recycled_pid_is_not_the_original_process():
    pid = os.getpid()
    assert liveness.is_running(pid, "a-different-process") is False


def test_an_unknown_pid_cannot_be_judged():
    assert liveness.is_running(0) is None


def test_a_run_that_recorded_an_outcome_is_taken_at_its_word():
    for status, detail in (
        ("completed", "finished"),
        ("failed", "failed"),
        ("interrupted", "interrupted"),
    ):
        result = liveness.resolve(status, pid=999_999)
        assert result.state == "finished"
        assert result.detail == detail
        assert not result.is_live


def test_a_live_run_reports_running():
    pid = os.getpid()
    result = liveness.resolve(
        "running", pid=pid, host=liveness.hostname(), token=liveness.start_token(pid)
    )
    assert result.is_live


def test_a_run_whose_process_is_gone_is_reported_stopped():
    # the case the whole module exists for: nothing ever withdraws the claim,
    # so a killed run would otherwise advertise itself as running forever.
    result = liveness.resolve("running", pid=999_999, host=liveness.hostname())
    assert result.state == "stopped"
    assert not result.is_live


def test_a_run_from_another_machine_is_not_guessed_at():
    result = liveness.resolve("running", pid=os.getpid(), host="some-other-machine")
    assert result.state == "unknown"
    assert "some-other-machine" in result.detail


def test_a_status_nobody_recognises_is_not_called_running():
    assert liveness.resolve("pending", pid=os.getpid()).state == "unknown"
    assert liveness.resolve("", pid=os.getpid()).state == "unknown"
