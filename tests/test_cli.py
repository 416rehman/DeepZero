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

    def test_run_garbage_collection_cleans_trash(self, tmp_path, monkeypatch):
        import threading

        def mock_thread(target, daemon=False, args=()):
            class FakeThread:
                def start(self):
                    target(*args)

            return FakeThread()

        monkeypatch.setattr(threading, "Thread", mock_thread)

        yaml_content = "name: test\nstages:\n  - name: discover\n    processor: file_discovery\n"
        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(yaml_content)

        work_root = tmp_path / "work"
        pipeline_work_dir = work_root / "test"
        pipeline_work_dir.mkdir(parents=True)
        trash_dir = pipeline_work_dir.with_name("trash_test_123")
        trash_dir.mkdir()

        target = tmp_path / "test.sys"
        target.write_bytes(b"MZ")

        runner = CliRunner()
        result = runner.invoke(
            main, ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root)]
        )

        if result.exit_code != 0:
            print(result.output)
        assert result.exit_code == 0

        # Assert GC wiped out the dummy trash_ directory we created
        assert not trash_dir.exists()

    def test_run_clean_flag_atomic_move(self, tmp_path, monkeypatch):
        import threading

        def mock_thread(target, daemon=False, args=()):
            class FakeThread:
                def start(self):
                    target(*args)

            return FakeThread()

        monkeypatch.setattr(threading, "Thread", mock_thread)

        yaml_content = "name: test\nstages:\n  - name: discover\n    processor: file_discovery\n"
        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(yaml_content)

        work_root = tmp_path / "work"
        pipeline_work_dir = work_root / "test"
        pipeline_work_dir.mkdir(parents=True)

        # Inject dummy file to prove deletion
        (pipeline_work_dir / "dummy.txt").write_text("keep")

        target = tmp_path / "test.sys"
        target.write_bytes(b"MZ")

        runner = CliRunner()
        # Pass --clean flag to initiate force reset
        result = runner.invoke(
            main, ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root), "--clean"]
        )

        if result.exit_code != 0:
            print(result.output)
        assert result.exit_code == 0
        assert "purging" in result.output

        # The clean flag moves the original workdir to a trash directory which is then recursively wiped
        # Since we ran synchronously via mock, the directory should be completely empty and devoid of dummy.txt
        assert not (pipeline_work_dir / "dummy.txt").exists()


class TestServeCommand:
    def test_serve_default_port(self):
        # just verify the command is registered and parses args
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
