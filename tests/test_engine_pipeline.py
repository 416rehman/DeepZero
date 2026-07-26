import re
from pathlib import Path

import pytest

from deepzero.engine.pipeline import corpus_segment, load_pipeline, validate_pipeline


def _pipe(tmp_path: Path, work_dir: str = "work"):
    import deepzero.stages  # noqa: F401  (populate the processor registry)

    (tmp_path / "pipeline.yaml").write_text(
        f"name: p\nsettings:\n  work_dir: {work_dir}\n"
        "stages:\n  - name: discover\n    processor: file_discovery\n"
    )
    return load_pipeline(str(tmp_path))


def test_corpus_segment_deterministic_and_safe(tmp_path: Path):
    a = tmp_path / "DP_Vendor_26061"
    a.mkdir()
    seg1 = corpus_segment(a)
    seg2 = corpus_segment(Path(str(a)))  # same path, different Path object
    assert seg1 == seg2  # stable -> a rerun resumes in place
    assert seg1.startswith("DP_Vendor_26061-")  # readable basename kept
    assert re.fullmatch(r"[A-Za-z0-9._-]+-[0-9a-f]{8}", seg1)  # filesystem-safe

    b = tmp_path / "DP_Misc_26053"
    b.mkdir()
    assert corpus_segment(b) != seg1  # different corpora never collide


def test_corpus_segment_distinguishes_same_basename(tmp_path: Path):
    (tmp_path / "x" / "drivers").mkdir(parents=True)
    (tmp_path / "y" / "drivers").mkdir(parents=True)
    # identical basename, different paths -> distinct segments (no silent sharing)
    assert corpus_segment(tmp_path / "x" / "drivers") != corpus_segment(tmp_path / "y" / "drivers")


def test_work_dir_scoped_by_corpus(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipe = _pipe(tmp_path)
    base = pipe.base_work_dir
    assert base.name == "p"
    # unbound: work_dir is the pipeline root itself
    assert pipe.work_dir == base

    target = tmp_path / "corpusA"
    target.mkdir()
    pipe.bind_corpus(target)
    assert pipe.work_dir == base / corpus_segment(target)
    assert pipe.work_dir.parent == base  # corpus dir sits directly under the base

    # a second corpus through the same pipeline gets its own isolated dir
    pipe2 = _pipe(tmp_path)
    other = tmp_path / "corpusB"
    other.mkdir()
    pipe2.bind_corpus(other)
    assert pipe2.work_dir != pipe.work_dir
    assert pipe2.base_work_dir == base


def test_load_pipeline_valid(tmp_path: Path):
    yaml_content = """name: test_pipe
settings:
  work_dir: test_work
stages:
  - name: discover
    processor: file_discovery
"""
    yaml_file = tmp_path / "pipeline.yaml"
    yaml_file.write_text(yaml_content)

    pipe = load_pipeline(str(tmp_path))
    assert pipe.name == "test_pipe"
    assert pipe.stage_names == ["discover"]


def test_load_pipeline_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_pipeline(str(tmp_path / "missing.yaml"))


def test_validate_pipeline(tmp_path: Path):
    yaml_content = """name: test_pipe
stages:
  - name: discover
    processor: file_discovery
"""
    yaml_file = tmp_path / "pipeline.yaml"
    yaml_file.write_text(yaml_content)

    warnings = validate_pipeline(str(tmp_path))
    assert isinstance(warnings, list)
    assert any("no map" in w.lower() for w in warnings)


class TestPromptsAreCheckedBeforeARun:
    """a prompt naming a value no stage produces renders as nothing, and the
    model then answers about an empty payload - which reads like a real run."""

    def _pipeline(self, tmp_path: Path, template: str) -> Path:
        import deepzero.stages  # noqa: F401  (populate the processor registry)

        (tmp_path / "assess.j2").write_text(template, encoding="utf-8")
        (tmp_path / "pipeline.yaml").write_text(
            "name: p\nmodel: test/model\n"
            "stages:\n"
            "  - name: discover\n    processor: file_discovery\n"
            "  - name: assess\n    processor: generic_llm\n"
            "    config:\n      prompt: assess.j2\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_a_value_no_stage_produces_is_an_error(self, tmp_path: Path):
        p = self._pipeline(tmp_path, "Payload:\n{{ dispatch_code }}\n")
        errors = [w for w in validate_pipeline(str(p)) if w.startswith("ERROR")]
        assert len(errors) == 1
        # the name at fault, and what could have been used instead
        assert "dispatch_code" in errors[0]
        assert "sample_name" in errors[0]

    def test_values_every_prompt_gets_are_accepted(self, tmp_path: Path):
        p = self._pipeline(tmp_path, "{{ sample_name }} at {{ sample_path }}\n")
        assert not [w for w in validate_pipeline(str(p)) if w.startswith("ERROR")]

    def test_a_value_an_earlier_stage_declares_is_accepted(self, tmp_path: Path):
        import deepzero.stages  # noqa: F401
        from deepzero.engine.stage import get_registered_processors

        provided = getattr(get_registered_processors()["file_discovery"], "provides", ())
        if not provided:
            pytest.skip("file_discovery declares no values to test against")
        p = self._pipeline(tmp_path, "{{ %s }}\n" % provided[0])
        assert not [w for w in validate_pipeline(str(p)) if w.startswith("ERROR")]

    def test_a_prompt_that_does_not_exist_is_reported(self, tmp_path: Path):
        p = self._pipeline(tmp_path, "{{ sample_name }}")
        (p / "assess.j2").unlink()
        errors = [w for w in validate_pipeline(str(p)) if w.startswith("ERROR")]
        assert any("does not exist" in e for e in errors)

    def test_a_prompt_named_without_a_path_still_loads_the_file(self, tmp_path: Path):
        """validate accepts a filename sitting next to the pipeline, so rendering
        has to load that file rather than treating the name as the prompt."""
        import deepzero.stages  # noqa: F401
        from deepzero.engine.stage import StageSpec
        from deepzero.stages.llm import GenericLLM

        self._pipeline(tmp_path, "assessment body")
        stage = GenericLLM(StageSpec(name="assess", processor="generic_llm", config={}))

        class _Ctx:
            pipeline_dir = tmp_path

        assert stage._resolve_template("assess.j2", _Ctx()) == (tmp_path / "assess.j2").resolve()

    def test_a_prompt_that_will_not_parse_is_reported(self, tmp_path: Path):
        p = self._pipeline(tmp_path, "{% if %}")
        errors = [w for w in validate_pipeline(str(p)) if w.startswith("ERROR")]
        assert any("will not parse" in e for e in errors)

    def test_a_stage_cannot_use_what_it_produces_itself(self, tmp_path: Path):
        # a value becomes available to the stages after the one recording it, so
        # a prompt cannot reach its own stage's output
        p = self._pipeline(tmp_path, "{{ llm_output_file }}")
        errors = [w for w in validate_pipeline(str(p)) if w.startswith("ERROR")]
        assert any("llm_output_file" in e for e in errors)


def test_the_bundled_pipeline_prompt_resolves():
    """the shipped pipeline is the one users run first, so its prompt has to
    reference only values its own stages record.

    Checked against the stages' declarations rather than through
    validate_pipeline, because that also demands a Ghidra install and a signed-in
    model backend. Those say nothing about whether the prompt is correct, and
    requiring them would mean this never ran anywhere it mattered.
    """
    import jinja2
    import yaml as _yaml
    from jinja2 import meta

    import deepzero.stages  # noqa: F401
    from deepzero.engine.pipeline import resolve_processor_class
    from deepzero.engine.stage import ALWAYS_PROVIDED

    bundled = Path(__file__).resolve().parent.parent / "pipelines" / "loldrivers"
    if not (bundled / "pipeline.yaml").exists():
        pytest.skip("bundled pipeline not present in this checkout")

    spec = _yaml.safe_load((bundled / "pipeline.yaml").read_text(encoding="utf-8"))
    available = set(ALWAYS_PROVIDED)
    for stage in spec["stages"]:
        available |= set(getattr(resolve_processor_class(stage["processor"]), "provides", ()))

    template = (bundled / "assessment.j2").read_text(encoding="utf-8")
    used = meta.find_undeclared_variables(
        jinja2.Environment(autoescape=jinja2.select_autoescape()).parse(template)
    )
    assert sorted(used - available) == []
