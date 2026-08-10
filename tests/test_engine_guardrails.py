"""Rails that stop an extension author losing data without being told.

Both behaviours here were latent bugs found while building a second ingest
processor. Neither raised an error; both quietly produced a smaller or wrong
corpus than the run reported, which is the worst failure mode a research tool
has, because the number it prints is the number that gets believed.
"""

from __future__ import annotations

import threading

from deepzero.engine.stage import ProcessorContext, ProcessorEntry, StageSpec
from deepzero.engine.types import Verdict
from deepzero.stages.filter import MetadataFilter


def _ctx(tmp_path):
    return ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)


def _entry(sample_id: str, value: str):
    e = ProcessorEntry(sample_id=sample_id, source_path=None, filename=f"{sample_id}.bin")
    e._history = {}
    from deepzero.engine.state import StageOutput

    out = StageOutput()
    out.data = {"sha256": value}
    e._history = {"discover": out}
    return e


class TestDedupKeepsExactlyOne:
    """MapProcessor runs across a thread pool and its own docs require thread
    safety. Dedup is the one condition here that remembers other samples, and it
    was a check-then-act on an unguarded set.

    Being straight about what these tests do and do not establish: the window
    between the membership test and the add is two bytecodes, and CPython's
    interpreter switch interval makes losing that race so unlikely that it does
    not reproduce in hundreds of forced-contention trials. So these tests pin
    the behaviour (exactly one survivor, whatever the concurrency) rather than
    proving the race. The lock is still worth having, because correctness that
    holds only because of an interpreter implementation detail is not
    correctness, and a future processor copying this pattern for something
    slower than a set lookup would lose the race for real."""

    def _filter(self):
        return MetadataFilter(
            StageSpec(name="dedup", processor="metadata_filter", config={"dedup_field": "sha256"})
        )

    def test_one_of_two_identical_samples_is_filtered(self, tmp_path):
        f = self._filter()
        ctx = _ctx(tmp_path)
        a = f.process(ctx, _entry("a", "same"))
        b = f.process(ctx, _entry("b", "same"))
        verdicts = sorted([a.verdict, b.verdict], key=str)
        assert Verdict.FILTER in verdicts and Verdict.CONTINUE in verdicts

    def test_exactly_one_survives_under_concurrency(self, tmp_path):
        """many threads, one value, released together. Anything other than
        exactly one survivor means dedup silently did not dedup."""
        f = self._filter()
        ctx = _ctx(tmp_path)
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(16)

        def run(i):
            barrier.wait()  # maximise the overlap on the check-then-act
            r = f.process(ctx, _entry(f"s{i}", "collide"))
            with lock:
                results.append(r.verdict)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(Verdict.CONTINUE) == 1
        assert results.count(Verdict.FILTER) == 15

    def test_distinct_values_all_survive(self, tmp_path):
        f = self._filter()
        ctx = _ctx(tmp_path)
        out = [f.process(ctx, _entry(f"s{i}", f"v{i}")).verdict for i in range(5)]
        assert all(v == Verdict.CONTINUE for v in out)


class TestReadingDoesNotCreate:
    """Resolving a path for a sample that does not exist must not bring it into
    being. The report resolves one per rendered row and the api resolves one per
    request, and the cli will bind that api to every interface on request, so a
    creating read is an unauthenticated way to fill a disk with empty
    directories."""

    def _store(self, tmp_path):
        from deepzero.engine.state import StateStore

        return StateStore(tmp_path / "work")

    def test_loading_an_unknown_sample_leaves_nothing_behind(self, tmp_path):
        store = self._store(tmp_path)
        samples = tmp_path / "work" / "samples"
        samples.mkdir(parents=True, exist_ok=True)
        before = {p.name for p in samples.iterdir()}
        for i in range(10):
            assert store.load_sample(f"ghost-{i}") is None
        assert {p.name for p in samples.iterdir()} == before

    def test_asking_where_a_sample_would_live_is_not_a_write(self, tmp_path):
        store = self._store(tmp_path)
        samples = tmp_path / "work" / "samples"
        samples.mkdir(parents=True, exist_ok=True)
        path = store.sample_dir("never-seen", create=False)
        assert not path.exists()

    def test_saving_still_creates_what_it_needs(self, tmp_path):
        """the guard must not break the write path it shares."""
        from deepzero.engine.state import SampleState

        store = self._store(tmp_path)
        store.save_sample(SampleState(sample_id="real1", filename="a.bin"))
        assert (tmp_path / "work" / "samples" / "real1" / "state.json").exists()
        assert store.load_sample("real1") is not None


class TestOpeningAStoreIsNotAWrite:
    """Every command opens a store before it knows whether there is anything to
    read, so creating on open turned a mistyped path into a new empty tree and
    then reported finding no run in it."""

    def test_opening_a_store_creates_nothing(self, tmp_path):
        from deepzero.engine.state import StateStore

        ghost = tmp_path / "typo"
        StateStore(ghost)
        assert not ghost.exists()

    def test_the_first_write_creates_what_it_needs(self, tmp_path):
        from deepzero.engine.state import RunState, StateStore
        from deepzero.engine.types import RunStatus

        work = tmp_path / "later"
        store = StateStore(work)
        store.save_run(RunState(run_id="r", pipeline="p", status=RunStatus.COMPLETED))
        assert (work / "run.json").exists()
        assert store.load_run() is not None

    def test_listing_an_absent_store_is_empty_not_an_error(self, tmp_path):
        from deepzero.engine.state import StateStore

        assert StateStore(tmp_path / "nothing").list_samples() == []
