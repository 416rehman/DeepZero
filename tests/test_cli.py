from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from deepzero.cli import main


class TestMainGroup:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "deepzero" in result.output


class TestValidateCommand:
    def test_validate_missing_pipeline(self):
        runner = CliRunner()
        result = runner.invoke(main, ["validate", "nonexistent_pipeline_xyz"])
        assert result.exit_code == 0
        assert "ERROR" in result.output or "not found" in result.output

    def test_validate_valid_pipeline(self, tmp_path):
        yaml_content = """name: test
stages:
  - name: discover
    processor: pe_ingest
"""
        pipeline_yaml = tmp_path / "pipeline.yaml"
        pipeline_yaml.write_text(yaml_content)

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 0


class TestListToolsCommand:
    def test_list_tools_shows_table(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list-processors"])
        assert result.exit_code == 0
        # should show registered tools header
        assert "registered tools" in result.output.lower() or "name" in result.output.lower()


class TestInitCommand:
    def test_init_creates_pipeline(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "my_pipeline"])
            assert result.exit_code == 0
            pipeline_dir = Path("pipelines") / "my_pipeline"
            assert pipeline_dir.exists()
            assert (pipeline_dir / "pipeline.yaml").exists()

    def test_init_existing_dir(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("pipelines/my_pipeline").mkdir(parents=True)
            result = runner.invoke(main, ["init", "my_pipeline"])
            assert result.exit_code == 0
            assert "already exists" in result.output


class TestStatusCommand:
    def test_status_no_pipeline_no_workdir(self):
        runner = CliRunner()
        result = runner.invoke(main, ["status"])
        assert (
            result.exit_code != 0
            or "must provide" in result.output.lower()
            or "Error" in result.output
        )

    def test_status_with_workdir(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["status", "-w", str(tmp_path)])
        # exits 1 because no run state exists in the empty work dir
        assert result.exit_code == 1
        assert "no run found" in result.output.lower()


class TestRunCommand:
    def test_run_missing_args(self):
        runner = CliRunner()
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0

    def test_run_missing_pipeline(self, tmp_path):
        # target exists but --pipeline is required
        target = tmp_path / "test.sys"
        target.write_bytes(b"MZ")
        runner = CliRunner()
        result = runner.invoke(main, ["run", str(target)])
        assert result.exit_code != 0
        assert "pipeline" in result.output.lower()


class TestResumeCommand:
    def test_resume_requires_pipeline(self):
        runner = CliRunner()
        result = runner.invoke(main, ["resume"])
        assert result.exit_code != 0
        assert "pipeline" in result.output.lower()


class TestServeCommand:
    def test_serve_default_port(self):
        # just verify the command is registered and parses args
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
