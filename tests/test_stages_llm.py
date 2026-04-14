from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from deepzero.engine.stage import StageContext, StageSpec
from deepzero.engine.state import StageOutput
from deepzero.stages.llm import GenericLLM


def _make_ctx(tmp_path, config=None, llm=None, history_data=None):
    sample_path = tmp_path / "test.sys"
    sample_path.write_bytes(b"MZ")

    sample_dir = tmp_path / "samples" / "abc123"
    sample_dir.mkdir(parents=True)

    discover_data = history_data or {"sha256": "abc123", "filename": "test.sys"}
    history = {"discover": StageOutput(status="completed", data=discover_data)}

    return StageContext(
        sample_path=sample_path,
        sample_dir=sample_dir,
        history=history,
        config=config or {},
        pipeline_dir=tmp_path,
        global_config={},
        llm=llm,
    )


class TestGenericLLMProcess:
    def _make_tool(self):
        spec = StageSpec(name="assess", tool="generic_llm")
        return GenericLLM(spec)

    def test_no_llm_returns_failed(self, tmp_path):
        tool = self._make_tool()
        ctx = _make_ctx(tmp_path, config={"prompt": "analyze this"}, llm=None)
        result = tool.process(ctx)
        assert result.status == "failed"
        assert "no llm" in result.error

    def test_no_prompt_returns_failed(self, tmp_path):
        tool = self._make_tool()
        mock_llm = MagicMock()
        ctx = _make_ctx(tmp_path, config={}, llm=mock_llm)
        result = tool.process(ctx)
        assert result.status == "failed"
        assert "prompt" in result.error

    def test_successful_assessment(self, tmp_path):
        tool = self._make_tool()
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "this driver is vulnerable"

        ctx = _make_ctx(
            tmp_path,
            config={"prompt": "analyze {{sample_name}}", "output_file": "result.md"},
            llm=mock_llm,
        )
        result = tool.process(ctx)
        assert result.status == "completed"
        assert result.artifacts["llm_output"] == "result.md"

        # verify output was written
        output = ctx.sample_dir / "result.md"
        assert output.exists()
        assert output.read_text() == "this driver is vulnerable"

    def test_cached_output_skips_llm_call(self, tmp_path):
        tool = self._make_tool()
        mock_llm = MagicMock()

        ctx = _make_ctx(
            tmp_path,
            config={"prompt": "analyze", "output_file": "result.md"},
            llm=mock_llm,
        )
        # pre-create the cache
        (ctx.sample_dir / "result.md").write_text("cached result")

        result = tool.process(ctx)
        assert result.status == "completed"
        mock_llm.complete.assert_not_called()


class TestGenericLLMClassify:
    def _make_tool(self):
        spec = StageSpec(name="assess", tool="generic_llm")
        return GenericLLM(spec)

    def test_classify_by_pattern(self, tmp_path):
        tool = self._make_tool()
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "[VULNERABLE] buffer overflow found"

        ctx = _make_ctx(
            tmp_path,
            config={
                "prompt": "analyze",
                "classify_by": r"\[(VULNERABLE|NOT_VULNERABLE)\]",
            },
            llm=mock_llm,
        )
        result = tool.process(ctx)
        assert result.data.get("classification") == "vulnerable"

    def test_no_classification_without_match(self, tmp_path):
        tool = self._make_tool()
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "no classification marker here"

        ctx = _make_ctx(
            tmp_path,
            config={"prompt": "analyze", "classify_by": r"\[EXPLOIT\]"},
            llm=mock_llm,
        )
        result = tool.process(ctx)
        assert "classification" not in result.data


class TestGenericLLMTemplateVars:
    def _make_tool(self):
        spec = StageSpec(name="assess", tool="generic_llm")
        return GenericLLM(spec)

    def test_builds_template_vars_from_history(self, tmp_path):
        tool = self._make_tool()
        ctx = _make_ctx(
            tmp_path,
            config={},
            history_data={"sha256": "abc123", "filename": "test.sys", "size_bytes": 1024},
        )
        vars = tool._build_template_vars(ctx)
        assert vars["sample_name"] == "test.sys"
        assert vars["sha256"] == "abc123"
        assert vars["size_bytes"] == 1024

    def test_loads_json_artifacts(self, tmp_path):
        tool = self._make_tool()
        ctx = _make_ctx(tmp_path)

        # create a json artifact in sample_dir
        artifact = ctx.sample_dir / "analysis_result.json"
        artifact.write_text(json.dumps({"verdict": "safe"}))

        vars = tool._build_template_vars(ctx)
        assert vars["analysis_result_json"]["verdict"] == "safe"

    def test_loads_text_artifacts(self, tmp_path):
        tool = self._make_tool()
        ctx = _make_ctx(tmp_path)

        # create a text artifact in sample_dir
        artifact = ctx.sample_dir / "decompiled.c"
        artifact.write_text("int main() { return 0; }")

        vars = tool._build_template_vars(ctx)
        assert "int main()" in vars["decompiled_c"]

    def test_truncates_large_artifacts(self, tmp_path):
        tool = self._make_tool()
        ctx = _make_ctx(tmp_path, config={"max_context_tokens": 10})

        artifact = ctx.sample_dir / "large.txt"
        artifact.write_text("x" * 1000)

        vars = tool._build_template_vars(ctx)
        assert len(vars["large_txt"]) < 1000
        assert "truncated" in vars["large_txt"]


class TestGenericLLMResolveTemplate:
    def _make_tool(self):
        spec = StageSpec(name="assess", tool="generic_llm")
        return GenericLLM(spec)

    def test_returns_none_for_plain_string(self):
        tool = self._make_tool()
        result = tool._resolve_template("just a prompt string")
        assert result is None

    def test_resolves_absolute_path(self, tmp_path):
        tool = self._make_tool()
        f = tmp_path / "prompt.j2"
        f.write_text("template content")
        result = tool._resolve_template(str(f))
        assert result == f

    def test_returns_none_for_missing_absolute(self):
        tool = self._make_tool()
        result = tool._resolve_template("/nonexistent/path/prompt.j2")
        assert result is None
