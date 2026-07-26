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
