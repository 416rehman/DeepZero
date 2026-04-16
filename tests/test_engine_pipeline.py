import pytest
from pathlib import Path
from deepzero.engine.pipeline import load_pipeline, validate_pipeline


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
