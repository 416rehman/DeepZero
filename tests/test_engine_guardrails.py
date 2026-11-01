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
    """Concurrent dedup must keep one sample; these tests cannot guarantee a race occurs."""

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
        from deepzero.engine.state import SampleState

        store = self._store(tmp_path)
        store.save_sample(SampleState(sample_id="real1", filename="a.bin"))
        assert (tmp_path / "work" / "samples" / "real1" / "state.json").exists()
        assert store.load_sample("real1") is not None


class TestOpeningAStoreIsNotAWrite:
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


class TestAPipelineCanShipItsOwnFiles:
    """Processor setup needs the pipeline directory to resolve bundled files."""

    def test_a_blocklist_beside_the_pipeline_is_found_from_anywhere(self, tmp_path, monkeypatch):
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.hash_filter import HashExclude

        pipeline = tmp_path / "mypipe"
        pipeline.mkdir()
        (pipeline / "blocklist.txt").write_text("aaaa\nbbbb\n", encoding="utf-8")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        h = HashExclude(
            StageSpec(name="x", processor="hash_exclude", config={"hash_file": "blocklist.txt"})
        )
        h.setup({"pipeline_dir": str(pipeline)})
        assert h._exclude_hashes == {"aaaa", "bbbb"}

    def test_the_working_directory_still_wins_when_the_file_is_there(self, tmp_path, monkeypatch):
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.hash_filter import HashExclude

        pipeline = tmp_path / "mypipe"
        pipeline.mkdir()
        (pipeline / "blocklist.txt").write_text("frompipeline\n", encoding="utf-8")
        here = tmp_path / "here"
        here.mkdir()
        (here / "blocklist.txt").write_text("fromcwd\n", encoding="utf-8")
        monkeypatch.chdir(here)

        h = HashExclude(
            StageSpec(name="x", processor="hash_exclude", config={"hash_file": "blocklist.txt"})
        )
        h.setup({"pipeline_dir": str(pipeline)})
        assert h._exclude_hashes == {"fromcwd"}

    def test_the_pipeline_directory_reaches_a_processor_setup(self):
        from pathlib import Path

        from deepzero.engine.pipeline import PipelineDefinition

        cfg = PipelineDefinition(
            name="p",
            description="",
            model="",
            settings={},
            knowledge={},
            stage_specs=[],
            pipeline_dir=Path("/somewhere/mypipe"),
            raw_yaml="",
        ).to_global_config()
        assert "mypipe" in cfg["pipeline_dir"]


class TestAPipelineCanLiveAnywhere:
    def _pipeline_carrying_a_processor(self, root):
        import textwrap

        pipe = root / "mypipe"
        (pipe / "processors" / "mine").mkdir(parents=True)
        (pipe / "processors" / "mine" / "mine.py").write_text(
            textwrap.dedent("""
                from deepzero.engine.stage import IngestProcessor

                class MineIngest(IngestProcessor):
                    description = "ships with its pipeline"
                    def process(self, ctx, target):
                        return []
            """),
            encoding="utf-8",
        )
        (pipe / "pipeline.yaml").write_text(
            "name: mine\nstages:\n  - name: discover\n    processor: mine/mine.py\n",
            encoding="utf-8",
        )
        return pipe

    def test_a_processor_beside_the_pipeline_resolves_from_elsewhere(self, tmp_path, monkeypatch):
        import deepzero.stages  # noqa: F401
        from deepzero.engine.pipeline import load_pipeline

        pipe = self._pipeline_carrying_a_processor(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        loaded = load_pipeline(str(pipe))
        assert type(loaded.ingest_processor).__name__ == "MineIngest"

    def test_a_shared_library_can_be_named_by_environment(self, tmp_path, monkeypatch):
        import textwrap

        from deepzero.engine.registry import resolve_processor_class

        shared = tmp_path / "shared" / "lib"
        shared.mkdir(parents=True)
        (shared / "lib.py").write_text(
            textwrap.dedent("""
                from deepzero.engine.stage import MapProcessor

                class Shared(MapProcessor):
                    def process(self, ctx, entry):
                        return None
            """),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DEEPZERO_PROCESSORS", str(tmp_path / "shared"))
        assert resolve_processor_class("lib/lib.py").__name__ == "Shared"

    def test_a_reference_that_resolves_nowhere_lists_where_it_looked(self, tmp_path, monkeypatch):
        from deepzero.engine.registry import resolve_processor_class

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DEEPZERO_PROCESSORS", raising=False)
        try:
            resolve_processor_class("nope/nope.py", tmp_path / "somepipe")
        except FileNotFoundError as exc:
            # the search path is the thing a reader needs, and it is not guessable
            assert "searched" in str(exc)
            assert "somepipe" in str(exc)
        else:
            raise AssertionError("a missing processor must not resolve")


class TestAConclusionAboutTheWholeCorpus:
    """Corpus conclusions must not be attributed to an arbitrary sample."""

    def _corpus(self, tmp_path, stage_cls, kind):
        import pathlib

        from deepzero.engine.runner import PipelineRunner
        from deepzero.engine.stage import IngestProcessor, Sample, StageSpec
        from deepzero.engine.state import RunState, StateStore

        class Two(IngestProcessor):
            def process(self, ctx, target):
                return [
                    Sample(sample_id=f"s{i}", source_path=pathlib.Path("."), filename=f"s{i}")
                    for i in range(2)
                ]

        store = StateStore(tmp_path / "work")
        spec = StageSpec(name=kind, processor=kind)
        PipelineRunner(
            Two(StageSpec(name="discover", processor="two")),
            [(spec, stage_cls(spec))],
            store,
            tmp_path,
            {},
        ).run(pathlib.Path("."), RunState(run_id="r", pipeline="p"))
        return store

    def test_a_reduce_stage_can_author_one(self, tmp_path):
        from deepzero.engine.stage import ReduceProcessor

        class Concluder(ReduceProcessor):
            def process(self, ctx, entries):
                ctx.conclude(headline="the corpus is one thing", probes=len(entries))
                return [e.sample_id for e in entries]

        store = self._corpus(tmp_path, Concluder, "reduce")
        conclusion = store.load_run().conclusion
        assert conclusion["headline"] == "the corpus is one thing"
        assert conclusion["probes"] == 2
        assert conclusion["stage"] == "reduce"

    def test_a_bulk_stage_can_author_one(self, tmp_path):
        from deepzero.engine.stage import BulkMapProcessor, ProcessorResult

        class Concluder(BulkMapProcessor):
            def process(self, ctx, entries):
                ctx.conclude(headline="seen all at once")
                return [ProcessorResult.ok() for _ in entries]

        store = self._corpus(tmp_path, Concluder, "batch")
        assert store.load_run().conclusion["headline"] == "seen all at once"

    def test_a_map_stage_cannot(self, tmp_path):
        """Parallel sample processors cannot write a stable corpus-wide conclusion."""
        from deepzero.engine.stage import MapProcessor, ProcessorResult

        class Concluder(MapProcessor):
            def process(self, ctx, entry):
                ctx.conclude(headline="I speak for everyone")
                return ProcessorResult.ok()

        store = self._corpus(tmp_path, Concluder, "map")
        assert store.load_run().conclusion == {}

    def test_a_run_that_concluded_nothing_carries_nothing(self, tmp_path):
        from deepzero.engine.stage import MapProcessor, ProcessorResult

        class Quiet(MapProcessor):
            def process(self, ctx, entry):
                return ProcessorResult.ok()

        store = self._corpus(tmp_path, Quiet, "map")
        assert store.load_run().conclusion == {}

    def test_an_older_run_without_the_field_still_loads(self, tmp_path):
        import json

        from deepzero.engine.state import StateStore

        work = tmp_path / "work"
        work.mkdir()
        (work / "run.json").write_text(
            json.dumps({"run_id": "old", "pipeline": "p", "status": "completed"}), encoding="utf-8"
        )
        loaded = StateStore(work).load_run()
        assert loaded is not None
        assert loaded.conclusion == {}
