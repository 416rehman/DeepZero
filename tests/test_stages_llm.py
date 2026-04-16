from __future__ import annotations

import json
from unittest.mock import MagicMock

from deepzero.engine.stage import ProcessorContext, StageSpec
from deepzero.engine.state import StageOutput
from deepzero.stages.llm import GenericLLM


def _make_ctx(tmp_path, config=None, llm=None, history_data=None):
    sample_path = tmp_path / "test.sys"
    sample_path.write_bytes(b"MZ")

    sample_dir = tmp_path / "samples" / "abc123"
    sample_dir.mkdir(parents=True)

    discover_data = history_data or {"sha256": "abc123", "filename": "test.sys"}
    history = {"discover": StageOutput(status="completed", data=discover_data)}
    ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=llm)
    from deepzero.engine.stage import ProcessorEntry

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

    entry = ProcessorEntry(
        sample_id="test_sample",
        source_path=sample_path,
        filename=sample_path.name,
        sample_dir=sample_dir,
        _store=MockStore(history),
    )
    return ctx, entry


class TestGenericLLMProcess:
    def _make_tool(self, config=None):
        spec = StageSpec(name="assess", processor="generic_llm", config=config or {})
        return GenericLLM(spec)

    def test_no_llm_returns_failed(self, tmp_path):
        processor = self._make_tool(config={"prompt": "analyze this"})
        ctx, entry = _make_ctx(tmp_path, llm=None)
        result = processor.process(ctx, entry)
        assert result.status == "failed"
        assert "no llm" in result.error

    def test_no_prompt_returns_failed(self, tmp_path):
        processor = self._make_tool(config={})
        mock_llm = MagicMock()
        ctx, entry = _make_ctx(tmp_path, llm=mock_llm)
        errors = processor.validate(ctx)
        assert any("prompt" in e for e in errors)

    def test_successful_assessment(self, tmp_path):
        processor = self._make_tool(
            config={"prompt": "analyze {{sample_name}}", "output_file": "result.md"}
        )
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "this driver is vulnerable"

        ctx, entry = _make_ctx(
            tmp_path,
            llm=mock_llm,
        )
        result = processor.process(ctx, entry)
        assert result.status == "completed"
        assert result.artifacts["llm_output"] == "result.md"

        # verify output was written
        output = entry.sample_dir / "result.md"
        assert output.exists()
        assert output.read_text() == "this driver is vulnerable"

    def test_cached_output_skips_llm_call(self, tmp_path):
        processor = self._make_tool(config={"prompt": "analyze", "output_file": "result.md"})
        mock_llm = MagicMock()

        ctx, entry = _make_ctx(
            tmp_path,
            llm=mock_llm,
        )
        # pre-create the cache
        (entry.sample_dir / "result.md").write_text("cached result")

        result = processor.process(ctx, entry)
        assert result.status == "completed"
        mock_llm.complete.assert_not_called()


class TestGenericLLMClassify:
    def _make_tool(self, config=None):
        spec = StageSpec(name="assess", processor="generic_llm", config=config or {})
        return GenericLLM(spec)

    def test_classify_by_pattern(self, tmp_path):
        processor = self._make_tool(
            config={
                "prompt": "analyze",
                "classify_by": r"\[(VULNERABLE|NOT_VULNERABLE)\]",
            }
        )
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "[VULNERABLE] buffer overflow found"

        ctx, entry = _make_ctx(
            tmp_path,
            llm=mock_llm,
        )
        result = processor.process(ctx, entry)
        assert result.data.get("classification") == "vulnerable"

    def test_no_classification_without_match(self, tmp_path):
        processor = self._make_tool(config={"prompt": "analyze", "classify_by": r"\[EXPLOIT\]"})
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "no classification marker here"

        ctx, entry = _make_ctx(
            tmp_path,
            llm=mock_llm,
        )
        result = processor.process(ctx, entry)
        assert "classification" not in result.data


class TestGenericLLMTemplateVars:
    def _make_tool(self, config=None):
        spec = StageSpec(name="assess", processor="generic_llm", config=config or {})
        return GenericLLM(spec)

    def test_builds_template_vars_from_history(self, tmp_path):
        processor = self._make_tool(config={})
        ctx, entry = _make_ctx(
            tmp_path,
            config={},
            history_data={
                "sha256": "abc123",
                "filename": "test.sys",
                "size_bytes": 1024,
            },
        )
        vars = processor._build_template_vars(ctx, entry)
        assert vars["sample_name"] == "test.sys"
        assert vars["sha256"] == "abc123"
        assert vars["size_bytes"] == 1024

    def test_loads_json_artifacts(self, tmp_path):
        processor = self._make_tool(config={})
        ctx, entry = _make_ctx(tmp_path)

        # create a json artifact in sample_dir
        artifact = entry.sample_dir / "analysis_result.json"
        artifact.write_text(json.dumps({"verdict": "safe"}))

        vars = processor._build_template_vars(ctx, entry)
        assert vars["analysis_result_json"]["verdict"] == "safe"

    def test_loads_text_artifacts(self, tmp_path):
        processor = self._make_tool(config={})
        ctx, entry = _make_ctx(tmp_path)

        # create a text artifact in sample_dir
        artifact = entry.sample_dir / "decompiled.c"
        artifact.write_text("int main() { return 0; }")

        vars = processor._build_template_vars(ctx, entry)
        assert "int main()" in vars["decompiled_c"]

    def test_truncates_large_artifacts(self, tmp_path):
        processor = self._make_tool(config={"max_context_tokens": 10})
        ctx, entry = _make_ctx(tmp_path)

        artifact = entry.sample_dir / "large.txt"
        artifact.write_text("x" * 1000)

        vars = processor._build_template_vars(ctx, entry)
        assert len(vars["large_txt"]) < 1000
        assert "truncated" in vars["large_txt"]


class TestGenericLLMResolveTemplate:
    def _make_tool(self, config=None):
        spec = StageSpec(name="assess", processor="generic_llm", config=config or {})
        return GenericLLM(spec)

    def test_returns_none_for_plain_string(self):
        processor = self._make_tool(config={})
        result = processor._resolve_template("just a prompt string")
        assert result is None

    def test_resolves_absolute_path(self, tmp_path):
        processor = self._make_tool(config={})
        f = tmp_path / "prompt.j2"
        f.write_text("template content")
        result = processor._resolve_template(str(f))
        assert result == f

    def test_returns_none_for_missing_absolute(self):
        processor = self._make_tool(config={})
        result = processor._resolve_template("/nonexistent/path/prompt.j2")
        assert result is None
