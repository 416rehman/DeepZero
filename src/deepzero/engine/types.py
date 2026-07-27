from enum import Enum


class Verdict(str, Enum):
    CONTINUE = "continue"
    FILTER = "filter"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    FILTERED = "filtered"
    # ran out of time rather than going wrong. Kept apart from a failure because
    # it says nothing about the sample, and is the one outcome a longer budget
    # can change - which makes it the one worth offering to run again.
    TIMED_OUT = "timed_out"


class SampleStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    FILTERED = "filtered"
    TIMED_OUT = "timed_out"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
