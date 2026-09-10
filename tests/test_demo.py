from pathlib import Path

from click.testing import CliRunner

from deepzero.cli import main
from deepzero.engine.pipeline import corpus_segment
from deepzero.engine.state import StateStore


def test_shipped_demo_runs_resumes_and_reports(tmp_path):
    root = Path(__file__).resolve().parents[1]
    pipeline = root / "pipelines/demo/pipeline.yaml"
    samples = root / "pipelines/demo/samples"
    work = tmp_path / "work"
    cli = CliRunner()
    args = ["run", str(samples), "-p", str(pipeline), "-w", str(work)]

    first = cli.invoke(main, args)
    assert first.exit_code == 0, first.output
    run_dir = work / "demo" / corpus_segment(samples)
    store = StateStore(run_dir)
    run = store.load_run()
    assert run.status == "completed"
    states = {sample.filename: sample for sample in store.list_samples()}
    assert set(states) == {"hello.txt", "tiny.txt"}
    assert states["hello.txt"].history["keep_larger_files"].status == "completed"
    assert states["hello.txt"].history["keep_larger_files"].verdict == "continue"
    assert states["tiny.txt"].verdict == "filtered"
    assert (run_dir / "report/index.html").is_file()

    resumed = cli.invoke(main, args)
    assert resumed.exit_code == 0, resumed.output
    assert "resuming run" in resumed.output
    assert store.load_run().run_id == run.run_id
    assert len(store.list_samples()) == 2

    report = cli.invoke(main, ["report", "-w", str(run_dir)])
    assert report.exit_code == 0, report.output
    assert (run_dir / "report/report.json").is_file()
