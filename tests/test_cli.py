from __future__ import annotations

import json
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
    """validate exists to answer, before a long run, whether a pipeline holds
    together. That answer has to reach automation, so a pipeline that cannot
    start must not exit 0 while printing errors nobody is reading."""

    def test_a_pipeline_that_cannot_be_found_fails(self):
        runner = CliRunner()
        result = runner.invoke(main, ["validate", "nonexistent_pipeline_xyz"])
        assert result.exit_code == 1
        assert "ERROR" in result.output or "not found" in result.output

    def test_a_pipeline_naming_a_processor_that_does_not_exist_fails(self):
        """a bare name resolves against the built-ins only, so naming an
        external processor without its path is a real and easy mistake."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp:
            pipeline_yaml = Path(tmp) / "pipeline.yaml"
            pipeline_yaml.write_text(
                "name: test\nstages:\n  - name: discover\n    processor: pe_ingest\n",
                encoding="utf-8",
            )
            result = runner.invoke(main, ["validate", tmp])
        assert result.exit_code == 1
        assert "ERROR" in result.output

    def test_a_pipeline_that_holds_together_passes(self, tmp_path):
        yaml_content = """name: test
stages:
  - name: discover
    processor: file_discovery
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

        # trash dirs live beside the corpus run dirs under <work>/<pipeline>/, and
        # GC sweeps that directory on every run.
        work_root = tmp_path / "work"
        pipeline_work_dir = work_root / "test"
        pipeline_work_dir.mkdir(parents=True)
        trash_dir = pipeline_work_dir / "trash_test_123"
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

        target = tmp_path / "test.sys"
        target.write_bytes(b"MZ")

        # runs are scoped per corpus: <work>/<pipeline>/<corpus-key>/. --clean
        # purges this corpus's prior run dir, so pre-create it with a marker file.
        from deepzero.engine.pipeline import corpus_segment

        work_root = tmp_path / "work"
        corpus_dir = work_root / "test" / corpus_segment(target)
        corpus_dir.mkdir(parents=True)
        (corpus_dir / "dummy.txt").write_text("keep")

        runner = CliRunner()
        # Pass --clean flag to initiate force reset
        result = runner.invoke(
            main, ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root), "--clean"]
        )

        if result.exit_code != 0:
            print(result.output)
        assert result.exit_code == 0
        assert "purging" in result.output

        # The clean flag moves the corpus run dir to a trash directory which is then
        # recursively wiped; run synchronously via mock, so dummy.txt is gone.
        assert not (corpus_dir / "dummy.txt").exists()


class TestServeCommand:
    def test_serve_default_port(self):
        # just verify the command is registered and parses args
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output


class TestRunsCommand:
    """A run's results outlive its report, because the report is a projection of
    state that can be rebuilt at any time. That is only useful if there is a way
    to find the runs, which otherwise means remembering a pipeline name and a
    corpus key nobody chose by hand."""

    def _work(self, root, pipeline, corpus, status="completed"):
        d = root / pipeline / corpus
        d.mkdir(parents=True)
        (d / "run.json").write_text(
            json.dumps(
                {
                    "run_id": f"r_{corpus}",
                    "pipeline": pipeline,
                    "status": status,
                    "stats": {"discovered": 7},
                }
            ),
            encoding="utf-8",
        )
        return d

    def test_every_run_on_disk_is_listed_whatever_produced_it(self, tmp_path):
        root = tmp_path / "work"
        self._work(root, "loldrivers", "packA-1111")
        self._work(root, "source_audit", "orgB-2222", status="running")

        result = CliRunner().invoke(main, ["runs", "-w", str(root)])
        assert result.exit_code == 0
        assert "loldrivers" in result.output
        assert "source_audit" in result.output
        assert "packA" in result.output and "orgB" in result.output

    def test_a_missing_report_is_reported_rather_than_hidden(self, tmp_path):
        """deleting the report must read as a rebuildable state, not a lost run."""
        root = tmp_path / "work"
        d = self._work(root, "loldrivers", "packA-1111")
        result = CliRunner().invoke(main, ["runs", "-w", str(root)])
        assert "not built" in result.output

        (d / "report").mkdir()
        (d / "report" / "index.html").write_text("<html></html>", encoding="utf-8")
        result = CliRunner().invoke(main, ["runs", "-w", str(root)])
        assert "built" in result.output

    def test_an_empty_root_says_so_rather_than_printing_nothing(self, tmp_path):
        empty = tmp_path / "work"
        empty.mkdir()
        result = CliRunner().invoke(main, ["runs", "-w", str(empty)])
        assert result.exit_code == 1
        assert "no runs found" in result.output

    def test_a_path_that_is_not_a_directory_is_refused(self, tmp_path):
        f = tmp_path / "afile"
        f.write_text("", encoding="utf-8")
        result = CliRunner().invoke(main, ["runs", "-w", str(f)])
        assert result.exit_code == 1
