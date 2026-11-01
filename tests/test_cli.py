from __future__ import annotations

import json
from pathlib import Path

import yaml
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

    def test_run_missing_target_does_not_create_a_run(self, tmp_path):
        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(
            "name: test\nstages:\n  - name: discover\n    processor: file_discovery\n"
        )
        work_root = tmp_path / "work"

        result = CliRunner().invoke(
            main,
            ["run", str(tmp_path / "missing"), "-p", str(pipeline_file), "-w", str(work_root)],
        )

        assert result.exit_code != 0
        assert "does not exist" in result.output
        assert not work_root.exists()

    def _run_with_processor(self, tmp_path, source):
        from deepzero.engine.pipeline import corpus_segment

        (tmp_path / "processor.py").write_text(source, encoding="utf-8")
        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(
            "name: failure_demo\nstages:\n"
            "  - name: discover\n    processor: file_discovery\n"
            "  - name: custom\n    processor: ./processor.py\n    parallel: 1\n",
            encoding="utf-8",
        )
        target = tmp_path / "input.bin"
        target.write_bytes(b"input")
        work_root = tmp_path / "work"
        result = CliRunner().invoke(
            main, ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root)]
        )
        run_dir = work_root / "failure_demo" / corpus_segment(target)
        return result, run_dir

    def test_run_setup_failure_returns_nonzero_and_keeps_report(self, tmp_path):
        from deepzero.engine.locking import RunLock

        result, run_dir = self._run_with_processor(
            tmp_path,
            "from deepzero.engine.stage import MapProcessor\n"
            "class Failing(MapProcessor):\n"
            "    def setup(self, config):\n"
            "        raise RuntimeError('setup exploded')\n"
            "    def process(self, ctx, entry):\n"
            "        raise AssertionError('setup should prevent processing')\n",
        )

        assert result.exit_code == 1, result.output
        state = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert state["status"] == "failed"
        assert state["stats"]["error"] == "setup exploded"
        assert (run_dir / "report" / "index.html").is_file()
        with RunLock(run_dir.parent / ".locks" / f"{run_dir.name}.lock"):
            pass

    def test_run_interrupted_returns_nonzero_and_keeps_report(self, tmp_path):
        result, run_dir = self._run_with_processor(
            tmp_path,
            "from deepzero.engine.stage import MapProcessor, ProcessorResult\n"
            "class Interrupted(MapProcessor):\n"
            "    def process(self, ctx, entry):\n"
            "        ctx.shutdown_event.set()\n"
            "        return ProcessorResult.ok()\n",
        )

        assert result.exit_code == 1, result.output
        state = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert state["status"] == "interrupted"
        assert (run_dir / "report" / "index.html").is_file()

    def test_refresh_updates_a_resumed_corpus_snapshot(self, tmp_path):
        from deepzero.engine.pipeline import corpus_segment
        from deepzero.engine.state import StateStore

        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(
            "name: refresh_demo\nstages:\n  - name: discover\n    processor: file_discovery\n"
        )
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "first.txt").write_text("first")
        work_root = tmp_path / "work"
        args = ["run", str(corpus), "-p", str(pipeline_file), "-w", str(work_root)]
        store = StateStore(work_root / "refresh_demo" / corpus_segment(corpus))

        result = CliRunner().invoke(main, args)
        assert result.exit_code == 0, result.output
        assert {state.filename for state in store.list_samples()} == {"first.txt"}

        (corpus / "second.txt").write_text("second")
        result = CliRunner().invoke(main, args)
        assert result.exit_code == 0, result.output
        assert {state.filename for state in store.list_samples()} == {"first.txt"}

        result = CliRunner().invoke(main, [*args, "--refresh"])
        assert result.exit_code == 0, result.output
        assert {state.filename for state in store.list_samples()} == {"first.txt", "second.txt"}

    def test_clean_is_refused_while_another_writer_holds_the_run(self, tmp_path):
        from deepzero.engine.locking import RunLock
        from deepzero.engine.pipeline import corpus_segment

        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(
            "name: locked_demo\nstages:\n  - name: discover\n    processor: file_discovery\n"
        )
        target = tmp_path / "input.bin"
        target.write_bytes(b"input")
        work_root = tmp_path / "work"
        corpus_key = corpus_segment(target)
        run_dir = work_root / "locked_demo" / corpus_key
        run_dir.mkdir(parents=True)
        marker = run_dir / "prior-results.txt"
        marker.write_text("keep until the writer finishes")
        args = ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root), "--clean"]

        with RunLock(run_dir.parent / ".locks" / f"{corpus_key}.lock"):
            result = CliRunner().invoke(main, args)
            assert result.exit_code == 1, result.output
            assert "another DeepZero process is writing this run" in result.output
            assert marker.read_text() == "keep until the writer finishes"
            assert not (run_dir / "pipeline.yaml").exists()

        result = CliRunner().invoke(main, args)
        assert result.exit_code == 0, result.output
        assert not marker.exists()

    def test_resume_updates_snapshot_without_expanding_secrets(self, tmp_path, monkeypatch):
        from deepzero.cli import _report_config_for_run
        from deepzero.engine.pipeline import corpus_segment

        monkeypatch.setenv("DEEPZERO_TEST_SECRET", "private-token-not-for-the-snapshot")
        monkeypatch.setattr("deepzero.engine.llm.LLMProvider", lambda model: None)
        pipeline_file = tmp_path / "pipeline.yaml"
        source = (
            "name: snapshot_demo\n"
            "model: original-model\n"
            "settings:\n  api_key: ${DEEPZERO_TEST_SECRET}\n"
            "report:\n  title: Initial report\n  entity_plural: artifacts\n"
            "stages:\n  - name: discover\n    processor: file_discovery\n"
        )
        pipeline_file.write_text(source, encoding="utf-8")
        target = tmp_path / "input.bin"
        target.write_bytes(b"input")
        work_root = tmp_path / "work"
        args = ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root)]
        run_dir = work_root / "snapshot_demo" / corpus_segment(target)

        result = CliRunner().invoke(main, [*args, "-m", "first-model"])
        assert result.exit_code == 0, result.output
        assert yaml.safe_load((run_dir / "pipeline.yaml").read_text())["model"] == "first-model"

        pipeline_file.write_text(
            source.replace("Initial report", "Updated report"), encoding="utf-8"
        )
        result = CliRunner().invoke(main, [*args, "-m", "second-model"])
        assert result.exit_code == 0, result.output
        snapshot_text = (run_dir / "pipeline.yaml").read_text(encoding="utf-8")
        snapshot = yaml.safe_load(snapshot_text)
        assert snapshot["model"] == "second-model"
        assert snapshot["report"]["title"] == "Updated report"
        assert snapshot["settings"]["api_key"] == "${DEEPZERO_TEST_SECRET}"
        assert "private-token-not-for-the-snapshot" not in snapshot_text

        pipeline_file.unlink()
        assert _report_config_for_run(run_dir)["title"] == "Updated report"
        result = CliRunner().invoke(main, ["report", "-w", str(run_dir)])
        assert result.exit_code == 0, result.output
        assert "Updated report" in (run_dir / "report" / "index.html").read_text(encoding="utf-8")

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


class TestRedoDiscardsCachedOutput:
    """`--redo` has to take a stage's output with its state.

    Several processors treat their own file on disk as a cache and adopt it
    instead of doing the work again. Forgetting the state alone leaves the file
    behind, so the stage reads its previous answer back and records it as fresh:
    the command reports a redo that did not happen. The engine's own staleness
    check does not cover this, because `--redo` is for the case where nothing
    about the stage's inputs changed and the caller wants the work done anyway.
    """

    def _seed(self, tmp_path, artifact: str):
        from deepzero.engine.pipeline import corpus_segment
        from deepzero.engine.state import SampleState, StateStore

        pipeline_file = tmp_path / "pipeline.yaml"
        pipeline_file.write_text(
            "name: test\n"
            "stages:\n"
            "  - name: discover\n"
            "    processor: file_discovery\n"
            "  - name: mark\n"
            "    processor: sort\n"
            "    config:\n"
            "      by: discover.size\n"
        )

        target = tmp_path / "test.sys"
        target.write_bytes(b"MZ")

        work_root = tmp_path / "work"
        store = StateStore(work_root / "test" / corpus_segment(target))
        state = SampleState(sample_id="s0", filename="test.sys", source_path=str(target))
        state.mark_stage_completed("discover", data={"size": 2})
        state.mark_stage_completed("mark", data={}, artifacts={"out": artifact})
        store.save_sample(state)
        return pipeline_file, target, work_root, store.sample_dir("s0")

    def test_the_file_a_redone_stage_wrote_is_removed(self, tmp_path):
        pipeline_file, target, work_root, sample_dir = self._seed(tmp_path, "out.txt")
        cached = sample_dir / "out.txt"
        cached.write_text("an answer to the previous run")

        result = CliRunner().invoke(
            main,
            ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root), "--redo", "mark"],
        )

        assert result.exit_code == 0, result.output
        assert not cached.exists(), "the redone stage's output survived the redo"
        assert "discarded 1 output file" in result.output

    def test_an_artifact_outside_the_sample_directory_is_left_alone(self, tmp_path):
        """A path a processor recorded elsewhere is not this run's to delete.

        Nothing stops a processor writing outside the sample directory and
        recording where it put it, and a redo that followed such a path would be
        deleting a file it does not own.
        """
        outsider = tmp_path / "not-ours.txt"
        pipeline_file, target, work_root, _ = self._seed(tmp_path, str(outsider))
        outsider.write_text("belongs to someone else")

        result = CliRunner().invoke(
            main,
            ["run", str(target), "-p", str(pipeline_file), "-w", str(work_root), "--redo", "mark"],
        )

        assert result.exit_code == 0, result.output
        assert outsider.exists(), "a redo deleted a file outside the sample directory"
        assert "discarded" not in result.output


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


class TestReportWithNothingNamed:
    """Naming a run means remembering a pipeline and a corpus key nobody chose
    by hand. When there is one run the question has an obvious answer, and when
    there are several it is a question worth asking a person, but only a person:
    a prompt with nowhere to read from would hang whatever is running it."""

    def _work(self, root, pipeline, corpus):
        d = root / pipeline / corpus
        d.mkdir(parents=True)
        (d / "run.json").write_text(
            json.dumps({"run_id": corpus, "pipeline": pipeline, "status": "completed"}),
            encoding="utf-8",
        )
        return d

    def test_a_single_run_is_taken_rather_than_asked_about(self, tmp_path, monkeypatch):
        from deepzero.cli import _choose_run

        root = tmp_path / "work"
        only = self._work(root, "loldrivers", "packA-1111")

        def never(*a, **k):
            raise AssertionError("asked about a choice that does not exist")

        monkeypatch.setattr("click.prompt", never)
        assert _choose_run(root) == only

    def test_several_runs_with_no_terminal_are_listed_not_prompted(self, tmp_path, monkeypatch):
        from deepzero.cli import _choose_run

        root = tmp_path / "work"
        self._work(root, "loldrivers", "packA-1111")
        self._work(root, "source_audit", "orgB-2222")
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr(
            "click.prompt", lambda *a, **k: (_ for _ in ()).throw(AssertionError("prompted"))
        )
        assert _choose_run(root) is None

    def test_several_runs_at_a_terminal_take_the_answer(self, tmp_path, monkeypatch):
        from deepzero.cli import _choose_run

        root = tmp_path / "work"
        self._work(root, "loldrivers", "packA-1111")
        self._work(root, "source_audit", "orgB-2222")
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("click.prompt", lambda *a, **k: 2)
        chosen = _choose_run(root)
        assert chosen is not None
        # ordered newest first, so the second row is the older run
        assert chosen.name in {"packA-1111", "orgB-2222"}

    def test_a_terminal_that_turns_out_to_have_no_input_says_what_to_do(
        self, tmp_path, monkeypatch
    ):
        """isatty is not a promise: some shells call a redirected stdin a
        terminal, and reaching end of input there must not end the command
        without saying how to get the report."""
        import click as click_mod

        from deepzero.cli import _choose_run

        root = tmp_path / "work"
        self._work(root, "loldrivers", "packA-1111")
        self._work(root, "source_audit", "orgB-2222")
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        def eof(*a, **k):
            raise click_mod.Abort()

        monkeypatch.setattr("click.prompt", eof)
        assert _choose_run(root) is None

    def test_no_runs_at_all_explains_rather_than_traceback(self, tmp_path):
        from deepzero.cli import _choose_run

        empty = tmp_path / "work"
        empty.mkdir()
        assert _choose_run(empty) is None
