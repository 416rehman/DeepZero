from __future__ import annotations

from pathlib import Path

# -- metadata filter (builtin map processor) --


class TestMetadataFilter:
    def _make_ctx(self, data: dict, config: dict, tmp_path=None):
        if tmp_path is None:
            tmp_path = Path(__import__("tempfile").gettempdir())
        from deepzero.engine.stage import ProcessorContext
        from deepzero.engine.state import StageOutput

        history = {"discover": StageOutput(status="completed", data=data)}
        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=locals().get("llm"))
        from deepzero.engine.stage import ProcessorEntry

        try:
            hist = history
        except NameError:
            hist = {}

        class MockStore:
            def __init__(self, history):
                self._history = history

            def load_sample(self, sid):
                class S:
                    def __init__(self, history):
                        self._history = history

                    @property
                    def history(self):
                        return self._history

                return S(self._history)

        try:
            sample_path_val = sample_path
        except NameError:
            sample_path_val = tmp_path / "test.bin"

        try:
            sample_dir_val = sample_dir
        except NameError:
            sample_dir_val = tmp_path

        entry = ProcessorEntry(
            sample_id="test_sample",
            source_path=sample_path_val,
            filename=sample_path_val.name,
            sample_dir=sample_dir_val,
            _store=MockStore(hist),
        )
        return ctx, entry

    def _make_filter(self, config: dict | None = None):
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.filter import MetadataFilter

        spec = StageSpec(name="test_filter", processor="metadata_filter", config=config or {})
        return MetadataFilter(spec)

    def test_passes_when_requirements_met(self):
        f = self._make_filter({"require": {"is_kernel_driver": True}})
        ctx, entry = self._make_ctx(
            {"is_kernel_driver": True}, {"require": {"is_kernel_driver": True}}
        )
        result = f.process(ctx, entry)
        assert result.verdict == "continue"

    def test_skips_when_requirement_not_met(self):
        f = self._make_filter({"require": {"is_kernel_driver": True}})
        ctx, entry = self._make_ctx(
            {"is_kernel_driver": False}, {"require": {"is_kernel_driver": True}}
        )
        result = f.process(ctx, entry)
        assert result.verdict == "filter"

    def test_min_threshold(self):
        f = self._make_filter({"min_priority_score": 5.0})
        ctx, entry = self._make_ctx({"priority_score": 2.0}, {"min_priority_score": 5.0})
        result = f.process(ctx, entry)
        assert result.verdict == "filter"

    def test_max_threshold(self):
        f = self._make_filter({"max_size_bytes": 10000})
        ctx, entry = self._make_ctx({"size_bytes": 50000}, {"max_size_bytes": 10000})
        result = f.process(ctx, entry)
        assert result.verdict == "filter"

    def test_dedup_first_pass(self):
        f = self._make_filter({"dedup_field": "sha256"})
        ctx, entry = self._make_ctx({"sha256": "abc123"}, {"dedup_field": "sha256"})
        result = f.process(ctx, entry)
        assert result.verdict == "continue"

    def test_dedup_second_pass_skips(self):
        f = self._make_filter({"dedup_field": "sha256"})
        ctx1, entry1 = self._make_ctx({"sha256": "abc123"}, {"dedup_field": "sha256"})
        ctx2, entry2 = self._make_ctx({"sha256": "abc123"}, {"dedup_field": "sha256"})
        f.process(ctx1, entry1)
        result = f.process(ctx2, entry2)
        assert result.verdict == "filter"
        assert "duplicate" in result.data.get("filter_reason", "")


# -- hash exclude (builtin map processor) --


class TestHashExclude:
    def _make_ctx(self, data: dict, config: dict, tmp_path=None):
        if tmp_path is None:
            tmp_path = Path(__import__("tempfile").gettempdir())
        from deepzero.engine.stage import ProcessorContext
        from deepzero.engine.state import StageOutput

        history = {"discover": StageOutput(status="completed", data=data)}
        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=locals().get("llm"))
        from deepzero.engine.stage import ProcessorEntry

        try:
            hist = history
        except NameError:
            hist = {}

        class MockStore:
            def __init__(self, history):
                self._history = history

            def load_sample(self, sid):
                class S:
                    def __init__(self, history):
                        self._history = history

                    @property
                    def history(self):
                        return self._history

                return S(self._history)

        try:
            sample_path_val = sample_path
        except NameError:
            sample_path_val = tmp_path / "test.bin"

        try:
            sample_dir_val = sample_dir
        except NameError:
            sample_dir_val = tmp_path

        entry = ProcessorEntry(
            sample_id="test_sample",
            source_path=sample_path_val,
            filename=sample_path_val.name,
            sample_dir=sample_dir_val,
            _store=MockStore(hist),
        )
        return ctx, entry

    def test_inline_hashes_exclude(self):
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.hash_filter import HashExclude

        spec = StageSpec(
            name="hash_test", processor="hash_exclude", config={"hashes": ["ABCD1234"]}
        )
        f = HashExclude(spec)
        f.setup({})
        ctx, entry = self._make_ctx({"sha256": "abcd1234"}, {"hash_field": "sha256"})
        result = f.process(ctx, entry)
        assert result.verdict == "filter"

    def test_hash_not_in_list_passes(self):
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.hash_filter import HashExclude

        spec = StageSpec(
            name="hash_test", processor="hash_exclude", config={"hashes": ["ABCD1234"]}
        )
        f = HashExclude(spec)
        f.setup({})
        ctx, entry = self._make_ctx({"sha256": "ffffff"}, {"hash_field": "sha256"})
        result = f.process(ctx, entry)
        assert result.verdict == "continue"


# -- top-k selector (builtin reduce processor) --


class TestTopKSelector:
    def test_keeps_top_k(self):
        from pathlib import Path

        from deepzero.engine.stage import ProcessorContext, ProcessorEntry, StageSpec
        from deepzero.engine.state import StageOutput
        from deepzero.stages.top_k import TopKSelector

        spec = StageSpec(
            name="pick",
            processor="top_k",
            config={
                "metric_path": "scan.finding_count",
                "keep_top": 2,
                "sort_order": "desc",
            },
        )
        processor = TopKSelector(spec)

        import tempfile

        ctx = ProcessorContext(pipeline_dir=Path(tempfile.gettempdir()), global_config={}, llm=None)

        entries = []
        for i in range(5):
            entry = ProcessorEntry(
                sample_id=f"s{i}",
                source_path=Path(tempfile.gettempdir()) / f"s{i}.sys",
                filename=f"s{i}.sys",
                sample_dir=Path(tempfile.gettempdir()) / f"s{i}",
                _store=None,
            )
            entry._history = {"scan": StageOutput(status="completed", data={"finding_count": i})}
            entries.append(entry)

        active_ids = processor.process(ctx, entries)

        assert len(active_ids) == 2
        assert "s4" in active_ids
        assert "s3" in active_ids

    def test_passthrough_without_metric(self):
        from pathlib import Path

        from deepzero.engine.stage import ProcessorContext, StageSpec
        from deepzero.stages.top_k import TopKSelector

        spec = StageSpec(name="pick", processor="top_k", config={})
        processor = TopKSelector(spec)
        import tempfile

        ctx = ProcessorContext(pipeline_dir=Path(tempfile.gettempdir()), global_config={}, llm=None)

        errors = processor.validate(ctx)
        assert len(errors) == 1
        assert "requires 'metric_path'" in errors[0]
